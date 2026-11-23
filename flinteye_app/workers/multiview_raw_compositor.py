#!/usr/bin/env python3
"""Wall-clock synchronized Multiview compositor.

Each source is decoded by its own FFmpeg child into a bounded RGB frame ring.
The Python worker selects every tile at one server-wall-clock target, copies the
selected RGB frames into a canvas, and gives that completed canvas to one
encoder FFmpeg per Multiview output.  No intermediate RTSP paths are involved.
"""

from __future__ import annotations

import argparse
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from flinteye_app.multiview_layout import parse_placements, source_pages
from flinteye_app.workers.multiview_buffer_to_rtsp import (
    BufferedFrame,
    ChildProcessRegistry,
    WallClockFrameBuffer,
    choose_output_frame,
    read_exact,
    synchronized_target_at,
    terminate_process,
)
from flinteye_app.workers.multiview_to_rtsp import (
    FFMPEG_DECODE_ERROR_PATTERNS,
    QUALITY_PRESETS,
    auto_default_font_path,
    build_auto_slots,
    build_encoder_candidates,
    detect_input_stall_timeout_option,
    escape_drawtext_text,
    escape_filter_value,
    get_available_encoders,
    join_rtsp_url,
    parse_slot_positions,
    preferred_pix_fmt_for_encoder,
)


Slot = tuple[int, int, int, int]


def parse_path_list(value: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in value.replace("\n", ",").replace(";", ",").split(","):
        path = raw.strip().strip("/")
        if not path or path.lower() in seen:
            continue
        seen.add(path.lower())
        result.append(path)
    return result


def parse_label_map(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("source label map must be a JSON object")
    return {
        str(key).strip().strip("/"): str(label).strip()
        for key, label in payload.items()
        if str(key).strip().strip("/") and str(label).strip()
    }


def frame_limit(*, width: int, height: int, buffer_sec: float, fps: int, memory_limit_mb: float) -> int:
    frame_bytes = width * height * 3
    time_limit = math.ceil(buffer_sec * fps) + 2
    memory_limit = max(2, int(memory_limit_mb * 1024 * 1024 // frame_bytes))
    return max(2, min(time_limit, memory_limit))


def frame_filter(slot: Slot, *, fps: int, label: str, font_size: int, fontfile: str | None) -> str:
    _x, _y, width, height = slot
    chain = (
        f"fps={fps}:round=down,"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,format=rgb24"
    )
    if not label:
        return chain
    band_height = max(28, font_size + 14)
    font_option = f"fontfile='{escape_filter_value(fontfile)}':" if fontfile else ""
    return (
        chain
        + f",drawbox=x=0:y=ih-{band_height}:w=iw:h={band_height}:color=black@0.45:t=fill"
        + ",drawtext="
        + font_option
        + f"text='{escape_drawtext_text(label)}':expansion=none:x=12:y=h-th-8:"
        + f"fontsize={font_size}:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2"
    )


def build_reader_command(args: argparse.Namespace, source: str, slot: Slot, label: str) -> list[str]:
    command = [args.ffmpeg_bin, "-hide_banner", "-loglevel", args.loglevel]
    if args.stall_timeout_arg and args.stall_timeout_sec > 0:
        command += [f"-{args.stall_timeout_arg}", str(int(args.stall_timeout_sec * 1_000_000))]
    command += [
        "-thread_queue_size", str(args.thread_queue_size),
        "-rtsp_transport", "tcp",
        "-use_wallclock_as_timestamps", "1",
        "-i", join_rtsp_url(args.input_rtsp_base_url, source),
        "-an", "-vf", frame_filter(
            slot,
            fps=args.fps,
            label=label,
            font_size=args.label_font_size,
            fontfile=args.label_fontfile,
        ),
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]
    return command


def build_encoder_command(args: argparse.Namespace, view_index: int, encoder: str) -> list[str]:
    output_url = join_rtsp_url(args.output_rtsp_base_url, f"{args.output_prefix}_{view_index}")
    command = [
        args.ffmpeg_bin, "-hide_banner", "-loglevel", args.loglevel,
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{args.canvas_width}x{args.canvas_height}",
        "-framerate", str(args.fps), "-i", "pipe:0",
        "-an", "-pix_fmt", preferred_pix_fmt_for_encoder(encoder),
        "-c:v", encoder, "-bf", str(args.bframes),
    ]
    if encoder == "libx264":
        command += ["-preset", args.x264_preset, "-tune", "zerolatency"]
    elif encoder == "libx265":
        command += ["-preset", args.x264_preset]
    command += [
        "-b:v", args.bitrate, "-maxrate", args.maxrate, "-bufsize", args.bufsize,
        "-g", str(args.gop), "-flush_packets", "1", "-muxdelay", "0", "-muxpreload", "0",
        "-rtsp_transport", "tcp", "-f", "rtsp", output_url,
    ]
    return command


def copy_tile(canvas: bytearray, frame: bytes, slot: Slot, canvas_width: int) -> None:
    x, y, width, height = slot
    source_stride = width * 3
    canvas_stride = canvas_width * 3
    first = (y * canvas_width + x) * 3
    for row in range(height):
        source_start = row * source_stride
        target_start = first + row * canvas_stride
        canvas[target_start : target_start + source_stride] = frame[source_start : source_start + source_stride]


@dataclass
class InputRuntime:
    source: str
    label: str
    slot: Slot
    frame_buffer: WallClockFrameBuffer
    slot_index: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: str = "starting"
    reason: str | None = None
    failures: int = 0
    decode_error_count: int = 0
    frames_received: int = 0
    last_received_at: float | None = None
    selected: BufferedFrame | None = None
    selected_state: str = "starting"
    selected_target_at: float | None = None
    started_at: float = field(default_factory=time.time)

    def snapshot(self) -> dict[str, object]:
        count, _oldest, _newest = self.frame_buffer.stats()
        with self.lock:
            return {
                "path": self.source,
                "state": self.selected_state,
                "last_progress_at": self.last_received_at,
                "failures": self.failures,
                "isolated": False,
                "reason": self.reason,
                "buffered_frames": count,
                "frames_received": self.frames_received,
                "selected_frame_at": self.selected.captured_at if self.selected else None,
                "target_at": self.selected_target_at,
                "decode_error_count": self.decode_error_count,
            }


@dataclass
class ViewSpec:
    index: int
    inputs: list[InputRuntime]


class EncoderWorker:
    def __init__(
        self,
        *,
        args: argparse.Namespace,
        view_index: int,
        encoders: list[str],
        stop_event: threading.Event,
        children: ChildProcessRegistry,
    ) -> None:
        self.args = args
        self.view_index = view_index
        self.encoders = encoders
        self.stop_event = stop_event
        self.children = children
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.pending: bytes | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.encoder_index = 0
        self.start_count = 0
        self.restart_count = 0
        self.frames_published = 0
        self.last_published_at: float | None = None
        self.reason: str | None = None
        self.thread = threading.Thread(target=self._run, name=f"multiview-encoder-{view_index}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def submit(self, frame: bytes) -> None:
        with self.condition:
            self.pending = frame
            self.condition.notify()

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return {
                "running": running,
                "restart_count": self.restart_count,
                "frames_published": self.frames_published,
                "last_published_at": self.last_published_at,
                "reason": self.reason,
            }

    def stop(self) -> None:
        with self.condition:
            self.condition.notify_all()
        terminate_process(self.process)
        self.children.discard(self.process)
        self.thread.join(timeout=3)

    def _stderr(self, stream: BinaryIO | None) -> None:
        if stream is None:
            return
        while not self.stop_event.is_set():
            line = stream.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                print(f"[multiview-encoder-{self.view_index}] {text}", file=sys.stderr)

    def _start_process(self) -> None:
        encoder = self.encoders[self.encoder_index]
        self.process = popen_background(
            build_encoder_command(self.args, self.view_index, encoder), **background_process_options(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.children.add(self.process)
        threading.Thread(target=self._stderr, args=(self.process.stderr,), daemon=True).start()
        with self.lock:
            if self.start_count > 0:
                self.restart_count += 1
            self.start_count += 1
            self.reason = None

    def _restart(self, reason: str) -> None:
        failed = self.process
        terminate_process(failed)
        self.children.discard(failed)
        self.process = None
        with self.lock:
            self.reason = reason[:300]
        if self.encoder_index + 1 < len(self.encoders):
            self.encoder_index += 1

    def _run(self) -> None:
        while not self.stop_event.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.stop_event.is_set(), timeout=1)
                if self.stop_event.is_set():
                    return
                frame = self.pending
                self.pending = None
            if frame is None:
                continue
            if self.process is None:
                try:
                    self._start_process()
                except OSError as exc:
                    with self.lock:
                        self.reason = str(exc)[:300]
                    self.stop_event.wait(self.args.reconnect_sec)
                    continue
            elif self.process.poll() is not None:
                self._restart("encoder stopped")
                try:
                    self._start_process()
                except OSError as exc:
                    with self.lock:
                        self.reason = str(exc)[:300]
                    self.stop_event.wait(self.args.reconnect_sec)
                    continue
            try:
                if self.process is None or self.process.stdin is None:
                    raise BrokenPipeError("encoder stdin is unavailable")
                self.process.stdin.write(frame)
                self.process.stdin.flush()
                with self.lock:
                    self.frames_published += 1
                    self.last_published_at = time.time()
                    self.reason = None
            except (BrokenPipeError, OSError) as exc:
                self._restart(str(exc))


def drain_reader_stderr(stream: BinaryIO | None, runtime: InputRuntime, stop_event: threading.Event) -> None:
    if stream is None:
        return
    while not stop_event.is_set():
        line = stream.readline()
        if not line:
            return
        text = line.decode("utf-8", errors="replace").rstrip()
        if any(pattern in text.lower() for pattern in FFMPEG_DECODE_ERROR_PATTERNS):
            with runtime.lock:
                runtime.decode_error_count += 1
        if text:
            print(f"[multiview-reader:{runtime.source}] {text}", file=sys.stderr)


def reader_loop(
    args: argparse.Namespace,
    runtime: InputRuntime,
    stop_event: threading.Event,
    children: ChildProcessRegistry,
) -> None:
    frame_size = runtime.slot[2] * runtime.slot[3] * 3
    while not stop_event.is_set():
        process: subprocess.Popen[bytes] | None = None
        try:
            process = popen_background(
                build_reader_command(args, runtime.source, runtime.slot, runtime.label), **background_process_options(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            children.add(process)
            threading.Thread(
                target=drain_reader_stderr,
                args=(process.stderr, runtime, stop_event),
                daemon=True,
            ).start()
            with runtime.lock:
                runtime.state = "buffering"
                runtime.reason = None
            if process.stdout is None:
                raise RuntimeError("reader stdout is unavailable")
            while not stop_event.is_set():
                frame = read_exact(process.stdout, frame_size)
                if frame is None:
                    raise RuntimeError("source decoder ended")
                captured_at = time.time()
                runtime.frame_buffer.append(captured_at, frame)
                with runtime.lock:
                    runtime.frames_received += 1
                    runtime.last_received_at = captured_at
                    runtime.state = "healthy"
                    runtime.reason = None
        except (BrokenPipeError, OSError, RuntimeError) as exc:
            with runtime.lock:
                runtime.failures += 1
                runtime.state = "reconnecting"
                runtime.reason = str(exc)[:300]
        finally:
            terminate_process(process)
            children.discard(process)
        if stop_event.wait(args.reconnect_sec):
            return


def build_views(args: argparse.Namespace, sources: list[str]) -> list[ViewSpec]:
    labels = parse_label_map(args.source_label_map_json)
    views: list[ViewSpec] = []
    for view_index, page in enumerate(source_pages(sources, args.tile_count, args.source_slots), start=1):
        if not any(page):
            continue
        slot_text = args.per_view_slots.get(str(view_index)) or args.slot_positions
        compact = not slot_text and args.source_slots is None and len(page) == 2
        count = 2 if compact else args.tile_count
        auto_slots = build_auto_slots(count, args.canvas_width, args.canvas_height, 2 if compact else args.grid_columns)
        slots = parse_slot_positions(slot_text, f"view {view_index} slots") if slot_text else auto_slots
        if len(slots) < count:
            raise ValueError(f"view {view_index} has fewer slots than tile_count")
        inputs: list[InputRuntime] = []
        for source_index, source in enumerate(page):
            if not source:
                continue
            slot = slots[source_index]
            x, y, width, height = slot
            if x + width > args.canvas_width or y + height > args.canvas_height:
                raise ValueError(f"slot for {source} exceeds the canvas")
            buffer = WallClockFrameBuffer(
                max_frames=frame_limit(
                    width=width,
                    height=height,
                    buffer_sec=args.buffer_sec,
                    fps=args.fps,
                    memory_limit_mb=args.memory_limit_mb,
                ),
                retention_sec=args.buffer_sec,
            )
            inputs.append(InputRuntime(source=source, label=labels.get(source, source), slot=slot,
                                       frame_buffer=buffer, slot_index=source_index))
        views.append(ViewSpec(index=view_index, inputs=inputs))
    return views


def compose_view(args: argparse.Namespace, view: ViewSpec, target_at: float) -> tuple[bytes, list[str]]:
    canvas = bytearray(args.canvas_width * args.canvas_height * 3)
    states: list[str] = []
    for runtime in view.inputs:
        with runtime.lock:
            last_selected = runtime.selected
        selected, next_last, state = choose_output_frame(
            runtime.frame_buffer,
            target_at=target_at,
            last_selected=last_selected,
            late_frame_policy=args.late_frame_policy,
            max_hold_sec=args.max_hold_sec,
            fps=args.fps,
        )
        received = runtime.frame_buffer.stats()[0]
        if selected is None and state == "missing":
            startup_grace = args.delay_sec + args.buffer_sec
            state = "buffering" if received == 0 and time.time() - runtime.started_at < startup_grace else "no_stream"
        if selected is not None:
            copy_tile(canvas, selected.data, runtime.slot, args.canvas_width)
        with runtime.lock:
            runtime.selected = next_last
            runtime.selected_state = state
            runtime.selected_target_at = target_at
            if state in {"healthy", "holding"}:
                runtime.reason = None if state == "healthy" else "Holding the last frame while this input reconnects"
            elif state == "buffering":
                runtime.reason = "Filling the wall-clock frame buffer"
            elif state == "no_stream":
                runtime.reason = "No frame is available for the shared wall-clock target"
        states.append(state)
    return bytes(canvas), states


def write_status(args: argparse.Namespace, views: list[ViewSpec], encoders: list[EncoderWorker]) -> None:
    now = time.time()
    payload_views: list[dict[str, object]] = []
    for view, encoder in zip(views, encoders):
        inputs = [{**runtime.snapshot(), "slot": runtime.slot_index + 1} for runtime in view.inputs]
        states = [str(item["state"]) for item in inputs]
        encoder_status = encoder.snapshot()
        output_fresh = bool(
            encoder_status["running"]
            and encoder_status["last_published_at"]
            and now - float(encoder_status["last_published_at"]) <= max(3.0, 3.0 / args.fps)
        )
        if states and all(state == "healthy" for state in states) and output_fresh:
            view_state = "healthy"
        elif states and all(state in {"starting", "buffering"} for state in states) and not encoder_status["reason"]:
            view_state = "starting"
        else:
            view_state = "degraded"
        payload_views.append(
            {
                "id": f"{args.output_prefix}_{view.index}",
                "state": view_state,
                "restart_count": int(encoder_status["restart_count"]),
                "decode_error_count": sum(int(item["decode_error_count"]) for item in inputs),
                "frames_published": int(encoder_status["frames_published"]),
                "last_published_at": encoder_status["last_published_at"],
                "output_reason": encoder_status["reason"],
                "inputs": [
                    {
                        **item,
                        "buffer_delay_sec": args.delay_sec,
                    }
                    for item in inputs
                ],
            }
        )
    payload = {"updated_at": now, "architecture": "raw_ring_compositor", "views": payload_views}
    path = Path(args.status_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"[warn] unable to write Multiview status temporary file: {exc}", file=sys.stderr)
        return
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            # On Windows a reader can briefly prevent replacement of the
            # destination. Status telemetry must never terminate video output.
            if attempt < 4:
                time.sleep(0.02 * (attempt + 1))
                continue
            print(f"[warn] unable to replace Multiview status file: {exc}", file=sys.stderr)
        except OSError as exc:
            print(f"[warn] unable to replace Multiview status file: {exc}", file=sys.stderr)
            break
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass


def run(args: argparse.Namespace) -> int:
    sources = parse_path_list(args.source_paths)
    if not sources:
        raise ValueError("at least one source path is required")
    if len(sources) > args.max_sources:
        sources = sources[: args.max_sources]
    views = build_views(args, sources)
    stop_event = threading.Event()
    children = ChildProcessRegistry()

    def stop_handler(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    reader_threads: list[threading.Thread] = []
    for view in views:
        for runtime in view.inputs:
            thread = threading.Thread(
                target=reader_loop,
                args=(args, runtime, stop_event, children),
                name=f"multiview-reader-{runtime.source}",
                daemon=True,
            )
            reader_threads.append(thread)
            thread.start()

    available = get_available_encoders(args.ffmpeg_bin)
    candidates = build_encoder_candidates(available, args.encoder)
    encoder_workers = [
        EncoderWorker(
            args=args,
            view_index=view.index,
            encoders=candidates,
            stop_event=stop_event,
            children=children,
        )
        for view in views
    ]
    for worker in encoder_workers:
        worker.start()

    interval = 1.0 / args.fps
    next_frame_at = math.ceil(time.time() * args.fps) / args.fps
    next_status_at = 0.0
    started = time.monotonic()
    try:
        while not stop_event.is_set():
            if args.run_sec > 0 and time.monotonic() - started >= args.run_sec:
                break
            delay = next_frame_at - time.time()
            if delay > 0 and stop_event.wait(delay):
                break
            now = time.time()
            if now - next_frame_at > 1.0:
                next_frame_at = math.ceil(now * args.fps) / args.fps
            target_at = synchronized_target_at(next_frame_at, args.delay_sec, args.fps)
            for view, encoder in zip(views, encoder_workers):
                canvas, _states = compose_view(args, view, target_at)
                encoder.submit(canvas)
            if now >= next_status_at:
                write_status(args, views, encoder_workers)
                next_status_at = now + 1.0
            next_frame_at += interval
    finally:
        stop_event.set()
        for worker in encoder_workers:
            worker.stop()
        children.terminate_all()
        for thread in reader_threads:
            thread.join(timeout=2)
        write_status(args, views, encoder_workers)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronized raw-frame Multiview compositor")
    parser.add_argument("--source-paths", required=True)
    parser.add_argument("--source-slots-json")
    parser.add_argument("--source-label-map-json")
    parser.add_argument("--input-rtsp-base-url", default="rtsp://127.0.0.1:8554")
    parser.add_argument("--output-rtsp-base-url", default="rtsp://127.0.0.1:8554")
    parser.add_argument("--output-prefix", default="multiview")
    parser.add_argument("--max-sources", type=int, default=32)
    parser.add_argument("--tile-count", type=int, default=4)
    parser.add_argument("--canvas-width", type=int, default=1920)
    parser.add_argument("--canvas-height", type=int, default=1080)
    parser.add_argument("--grid-columns", type=int)
    parser.add_argument("--slot-positions")
    parser.add_argument("--per-view-slots-json")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--delay-sec", type=float, default=3.0)
    parser.add_argument("--buffer-sec", type=float, default=5.0)
    parser.add_argument("--late-frame-policy", choices=["hold", "no_stream"], default="hold")
    parser.add_argument("--max-hold-sec", type=float, default=10.0)
    parser.add_argument("--memory-limit-mb", type=float, default=64.0)
    parser.add_argument("--reconnect-sec", type=float, default=2.0)
    parser.add_argument("--thread-queue-size", type=int, default=128)
    parser.add_argument("--stall-timeout-sec", type=float, default=15.0)
    parser.add_argument("--stall-timeout-option", choices=["auto", "rw_timeout", "stimeout", "timeout", "none"], default="auto")
    parser.add_argument("--encoder", default="auto")
    parser.add_argument("--quality-preset", choices=["high", "standard", "low"], default="standard")
    parser.add_argument("--bitrate")
    parser.add_argument("--maxrate")
    parser.add_argument("--bufsize")
    parser.add_argument("--gop", type=int, default=40)
    parser.add_argument("--bframes", type=int, default=0)
    parser.add_argument("--x264-preset", default="veryfast")
    parser.add_argument("--label-font-size", type=int, default=20)
    parser.add_argument("--label-fontfile")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--loglevel", default="error")
    parser.add_argument("--status-file", default="./logs/runtime/multiview_status.json")
    parser.add_argument("--run-sec", type=float, default=0.0)
    args = parser.parse_args(argv)
    if not 1 <= args.fps <= 60:
        parser.error("--fps must be in range 1..60")
    if not 1 <= args.tile_count <= 32 or not 1 <= args.max_sources <= 32:
        parser.error("tile_count and max_sources must be in range 1..32")
    if args.canvas_width <= 0 or args.canvas_height <= 0:
        parser.error("canvas dimensions must be positive")
    if not 0 <= args.delay_sec <= args.buffer_sec <= 120:
        parser.error("must satisfy 0 <= delay_sec <= buffer_sec <= 120")
    if args.memory_limit_mb <= 0 or args.reconnect_sec <= 0 or args.thread_queue_size <= 0:
        parser.error("memory, reconnect, and queue values must be positive")
    try:
        args.source_slots = parse_placements(args.source_slots_json, args.tile_count)
        parsed_slots = json.loads(args.per_view_slots_json) if args.per_view_slots_json else {}
        if not isinstance(parsed_slots, dict):
            raise ValueError("per-view slots must be an object")
        args.per_view_slots = {str(key): str(value) for key, value in parsed_slots.items() if value}
        parse_label_map(args.source_label_map_json)
    except (ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    rate = QUALITY_PRESETS[args.quality_preset]
    args.bitrate = args.bitrate or rate["bitrate"]
    args.maxrate = args.maxrate or rate["maxrate"]
    args.bufsize = args.bufsize or rate["bufsize"]
    args.label_fontfile = args.label_fontfile or auto_default_font_path()
    if args.stall_timeout_option == "none" or args.stall_timeout_sec <= 0:
        args.stall_timeout_arg = None
    elif args.stall_timeout_option == "auto":
        args.stall_timeout_arg = detect_input_stall_timeout_option(args.ffmpeg_bin)
    else:
        args.stall_timeout_arg = args.stall_timeout_option
    return args


def main() -> None:
    try:
        raise SystemExit(run(parse_args()))
    except (ValueError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
