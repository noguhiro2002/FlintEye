#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import signal
import subprocess
from flinteye_app.process_lifetime import popen_background
from flinteye_app.subprocess_utils import background_process_options
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit

from flinteye_app.workers.multiview_to_rtsp import detect_input_stall_timeout_option


@dataclass(frozen=True)
class BufferedFrame:
    captured_at: float
    data: bytes


class WallClockFrameBuffer:
    def __init__(self, *, max_frames: int, retention_sec: float) -> None:
        self.max_frames = max(2, max_frames)
        self.retention_sec = max(0.5, retention_sec)
        self._frames: collections.deque[BufferedFrame] = collections.deque()
        self._lock = threading.Lock()

    def append(self, captured_at: float, data: bytes) -> None:
        with self._lock:
            self._frames.append(BufferedFrame(captured_at, data))
            cutoff = captured_at - self.retention_sec
            while len(self._frames) > 1 and self._frames[1].captured_at < cutoff:
                self._frames.popleft()
            while len(self._frames) > self.max_frames:
                self._frames.popleft()

    def select(self, target_at: float) -> BufferedFrame | None:
        with self._lock:
            selected: BufferedFrame | None = None
            for frame in self._frames:
                if frame.captured_at > target_at:
                    break
                selected = frame
            return selected

    def stats(self) -> tuple[int, float | None, float | None]:
        with self._lock:
            if not self._frames:
                return 0, None, None
            return len(self._frames), self._frames[0].captured_at, self._frames[-1].captured_at


class WorkerState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.source_state = "starting"
        self.reason: str | None = None
        self.reader_restarts = 0
        self.publisher_restarts = 0
        self.frames_received = 0
        self.frames_published = 0
        self.last_received_at: float | None = None
        self.last_selected_at: float | None = None
        self.output_state = "starting"

    def update(self, **values: object) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "source_state": self.source_state,
                "reason": self.reason,
                "reader_restarts": self.reader_restarts,
                "publisher_restarts": self.publisher_restarts,
                "frames_received": self.frames_received,
                "frames_published": self.frames_published,
                "last_received_at": self.last_received_at,
                "last_selected_at": self.last_selected_at,
                "output_state": self.output_state,
            }


class ChildProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: set[subprocess.Popen[bytes]] = set()

    def add(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes.add(process)

    def discard(self, process: subprocess.Popen[bytes] | None) -> None:
        if process is None:
            return
        with self._lock:
            self._processes.discard(process)

    def terminate_all(self) -> None:
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            terminate_process(process)


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.username:
        return value
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, f"***@{host}", parsed.path, parsed.query, parsed.fragment))


def read_exact(stream: BinaryIO, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def memory_limited_frame_count(args: argparse.Namespace) -> int:
    frame_bytes = args.width * args.height * 3
    time_limit = math.ceil(args.buffer_sec * args.fps) + 2
    memory_limit = max(2, int(args.memory_limit_mb * 1024 * 1024 // frame_bytes))
    return max(2, min(time_limit, memory_limit))


def synchronized_target_at(now: float, delay_sec: float, fps: int) -> float:
    return math.floor((now - delay_sec) * fps) / fps


def choose_output_frame(
    frame_buffer: WallClockFrameBuffer,
    *,
    target_at: float,
    last_selected: BufferedFrame | None,
    late_frame_policy: str,
    max_hold_sec: float,
    fps: int,
) -> tuple[BufferedFrame | None, BufferedFrame | None, str]:
    candidate = frame_buffer.select(target_at)
    if candidate is not None:
        last_selected = candidate
    usable = candidate or last_selected
    if usable is None:
        return None, last_selected, "missing"
    age = max(0.0, target_at - usable.captured_at)
    freshness_sec = max(0.5, 2.0 / fps)
    if age <= freshness_sec:
        return usable, last_selected, "healthy"
    if late_frame_policy == "hold" and age <= max_hold_sec:
        return usable, last_selected, "holding"
    return None, last_selected, "no_stream"


def build_reader_command(args: argparse.Namespace) -> list[str]:
    filter_graph = (
        f"fps={args.fps}:round=down,"
        f"scale=w='min(iw,{args.width})':h='min(ih,{args.height})':force_original_aspect_ratio=decrease,"
        f"pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2:color=black,format=rgb24"
    )
    command = [args.ffmpeg_bin, "-hide_banner", "-loglevel", args.loglevel]
    if args.stall_timeout_option != "none" and args.stall_timeout_sec > 0:
        command += [f"-{args.stall_timeout_option}", str(int(args.stall_timeout_sec * 1_000_000))]
    command += [
        "-thread_queue_size", str(args.thread_queue_size),
        "-rtsp_transport", "tcp",
        "-use_wallclock_as_timestamps", "1",
        "-i", args.source_url,
        "-an", "-vf", filter_graph,
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]
    return command


def build_publisher_command(args: argparse.Namespace) -> list[str]:
    command = [
        args.ffmpeg_bin, "-hide_banner", "-loglevel", args.loglevel,
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{args.width}x{args.height}",
        "-framerate", str(args.fps), "-i", "pipe:0",
        "-an", "-c:v", args.encoder,
    ]
    if args.encoder == "libx264":
        command += ["-preset", args.x264_preset, "-tune", "zerolatency"]
    elif args.encoder == "libx265":
        command += ["-preset", args.x264_preset]
    command += [
        "-b:v", args.bitrate, "-maxrate", args.maxrate, "-bufsize", args.bufsize,
        "-g", str(max(1, args.fps * 2)), "-bf", "0", "-pix_fmt", "yuv420p",
        "-f", "rtsp", "-rtsp_transport", "tcp", args.output_url,
    ]
    return command


def drain_stderr(stream: BinaryIO | None, prefix: str, stop_event: threading.Event) -> None:
    if stream is None:
        return
    while not stop_event.is_set():
        line = stream.readline()
        if not line:
            return
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            print(f"[{prefix}] {text}", file=sys.stderr)


def terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def reader_loop(
    args: argparse.Namespace,
    frame_buffer: WallClockFrameBuffer,
    state: WorkerState,
    stop_event: threading.Event,
    children: ChildProcessRegistry,
) -> None:
    frame_size = args.width * args.height * 3
    while not stop_event.is_set():
        command = build_reader_command(args)
        print(f"[info] buffer reader connecting to {redact_url(args.source_url)}", file=sys.stderr)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = popen_background(
                command, **background_process_options(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            children.add(process)
            threading.Thread(
                target=drain_stderr,
                args=(process.stderr, "buffer-reader", stop_event),
                daemon=True,
            ).start()
            state.update(source_state="buffering", reason=None)
            if process.stdout is None:
                raise RuntimeError("reader stdout is unavailable")
            while not stop_event.is_set():
                data = read_exact(process.stdout, frame_size)
                if data is None:
                    raise RuntimeError("source reader ended")
                captured_at = time.time()
                frame_buffer.append(captured_at, data)
                with state.lock:
                    state.frames_received += 1
                    state.last_received_at = captured_at
                    state.source_state = "healthy"
                    state.reason = None
        except (BrokenPipeError, OSError, RuntimeError) as exc:
            with state.lock:
                state.reader_restarts += 1
                state.source_state = "reconnecting"
                state.reason = str(exc)[:300]
        finally:
            terminate_process(process)
            children.discard(process)
        if stop_event.wait(args.reconnect_sec):
            break


def write_status(
    args: argparse.Namespace,
    frame_buffer: WallClockFrameBuffer,
    state: WorkerState,
    *,
    target_at: float,
    selected: BufferedFrame | None,
) -> None:
    if not args.status_file:
        return
    count, oldest_at, newest_at = frame_buffer.stats()
    snapshot = state.snapshot()
    payload = {
        "updated_at": time.time(),
        "source_path": args.source_path,
        "buffer_path": args.buffer_path,
        "state": snapshot["output_state"],
        "source_state": snapshot["source_state"],
        "reason": snapshot["reason"],
        "buffer_delay_sec": args.delay_sec,
        "buffer_capacity_sec": args.buffer_sec,
        "buffered_frames": count,
        "oldest_frame_at": oldest_at,
        "newest_frame_at": newest_at,
        "target_at": target_at,
        "selected_frame_at": selected.captured_at if selected else None,
        "selected_age_sec": target_at - selected.captured_at if selected else None,
        "late_frame_policy": args.late_frame_policy,
        "max_hold_sec": args.max_hold_sec,
        "reader_restarts": snapshot["reader_restarts"],
        "publisher_restarts": snapshot["publisher_restarts"],
        "frames_received": snapshot["frames_received"],
        "frames_published": snapshot["frames_published"],
        "memory_limit_mb": args.memory_limit_mb,
    }
    path = Path(args.status_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> int:
    stop_event = threading.Event()

    def stop_handler(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    frame_buffer = WallClockFrameBuffer(
        max_frames=memory_limited_frame_count(args),
        retention_sec=args.buffer_sec,
    )
    state = WorkerState()
    children = ChildProcessRegistry()
    reader = threading.Thread(
        target=reader_loop,
        args=(args, frame_buffer, state, stop_event, children),
        name=f"multiview-buffer-reader-{args.source_path}",
        daemon=True,
    )
    reader.start()
    black_frame = bytes(args.width * args.height * 3)
    last_selected: BufferedFrame | None = None
    publisher: subprocess.Popen[bytes] | None = None
    frame_interval = 1.0 / args.fps
    next_frame_at = math.ceil(time.time() * args.fps) / args.fps
    next_status_at = 0.0
    run_started_at = time.monotonic()

    try:
        while not stop_event.is_set():
            if args.run_sec > 0 and time.monotonic() - run_started_at >= args.run_sec:
                break
            wait_sec = next_frame_at - time.time()
            if wait_sec > 0 and stop_event.wait(wait_sec):
                break
            if time.time() - next_frame_at > 1.0:
                next_frame_at = math.ceil(time.time() * args.fps) / args.fps
            if publisher is None or publisher.poll() is not None:
                terminate_process(publisher)
                children.discard(publisher)
                publisher = popen_background(
                    build_publisher_command(args), **background_process_options(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                children.add(publisher)
                threading.Thread(
                    target=drain_stderr,
                    args=(publisher.stderr, "buffer-publisher", stop_event),
                    daemon=True,
                ).start()
                with state.lock:
                    state.publisher_restarts += 1
                    state.output_state = "buffering"

            now = time.time()
            target_at = synchronized_target_at(next_frame_at, args.delay_sec, args.fps)
            usable, last_selected, selection_state = choose_output_frame(
                frame_buffer,
                target_at=target_at,
                last_selected=last_selected,
                late_frame_policy=args.late_frame_policy,
                max_hold_sec=args.max_hold_sec,
                fps=args.fps,
            )
            if usable is None:
                frame = black_frame
                received = int(state.snapshot()["frames_received"])
                startup_elapsed = time.monotonic() - run_started_at
                output_state = "buffering" if received == 0 and startup_elapsed < args.buffer_sec else "no_stream"
            else:
                frame = usable.data
                output_state = selection_state

            try:
                if publisher.stdin is None:
                    raise BrokenPipeError("publisher stdin is unavailable")
                publisher.stdin.write(frame)
                publisher.stdin.flush()
                with state.lock:
                    state.frames_published += 1
                    state.last_selected_at = usable.captured_at if usable else None
                    state.output_state = output_state
            except (BrokenPipeError, OSError):
                with state.lock:
                    state.publisher_restarts += 1
                    state.output_state = "reconnecting"
                terminate_process(publisher)
                children.discard(publisher)
                publisher = None

            if now >= next_status_at:
                write_status(args, frame_buffer, state, target_at=target_at, selected=usable)
                next_status_at = now + 1.0
            next_frame_at += frame_interval
    finally:
        stop_event.set()
        children.terminate_all()
        reader.join(timeout=3)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wall-clock delayed Multiview input buffer")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--output-url", required=True)
    parser.add_argument("--buffer-path", required=True)
    parser.add_argument("--delay-sec", type=float, default=3.0)
    parser.add_argument("--buffer-sec", type=float, default=5.0)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--late-frame-policy", choices=["hold", "no_stream"], default="hold")
    parser.add_argument("--max-hold-sec", type=float, default=10.0)
    parser.add_argument("--memory-limit-mb", type=float, default=64.0)
    parser.add_argument("--reconnect-sec", type=float, default=2.0)
    parser.add_argument("--thread-queue-size", type=int, default=128)
    parser.add_argument("--stall-timeout-sec", type=float, default=15.0)
    parser.add_argument("--stall-timeout-option", choices=["auto", "rw_timeout", "stimeout", "timeout", "none"], default="auto")
    parser.add_argument("--encoder", default="libx264")
    parser.add_argument("--bitrate", default="800k")
    parser.add_argument("--maxrate", default="1M")
    parser.add_argument("--bufsize", default="2M")
    parser.add_argument("--x264-preset", default="veryfast")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--loglevel", default="error")
    parser.add_argument("--status-file", default="")
    parser.add_argument("--run-sec", type=float, default=0.0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.delay_sec < 0 or args.buffer_sec <= 0 or args.delay_sec > args.buffer_sec:
        parser.error("buffer timing must satisfy 0 <= delay-sec <= buffer-sec")
    if args.fps <= 0 or args.width <= 0 or args.height <= 0:
        parser.error("fps, width, and height must be positive")
    if args.width % 2 or args.height % 2:
        parser.error("width and height must be even")
    if args.max_hold_sec < 0 or args.memory_limit_mb <= 0 or args.reconnect_sec <= 0 or args.run_sec < 0:
        parser.error("hold, memory, and reconnect settings are invalid")
    if args.stall_timeout_option == "auto":
        args.stall_timeout_option = detect_input_stall_timeout_option(args.ffmpeg_bin) or "none"
    return args


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
