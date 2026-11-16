from __future__ import annotations

import subprocess
import threading
import time
from concurrent.futures import Future
from flinteye_app.process_lifetime import run_background
from flinteye_app.subprocess_utils import background_process_options
from flinteye_app.flinteye_runtime import private_media_input_command


class SnapshotError(RuntimeError):
    pass


class SnapshotPool:
    """Coalesce one camera's requests and bound competing FFmpeg processes."""
    def __init__(self):
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.pending = {}
        self.cache = {}

    def capture(self, **arguments):
        key = (arguments['ffmpeg_bin'], arguments['rtsp_url'])
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 2:
                return cached[1]
            future = self.pending.get(key)
            owner = future is None
            if owner:
                future = self.pending[key] = Future()
        if not owner:
            try: return future.result(timeout=arguments['timeout_sec'] + 3)
            except TimeoutError as error: raise SnapshotError('Thumbnail is busy; retry shortly') from error
        try:
            if not self.slots.acquire(timeout=2):
                raise SnapshotError('Thumbnail queue is busy; live video is unaffected. Retry shortly.')
            try: image = capture_snapshot_jpeg(**arguments)
            finally: self.slots.release()
            with self.lock:
                self.cache[key] = (time.monotonic(), image)
                if len(self.cache) > 128: self.cache.pop(next(iter(self.cache)))
            future.set_result(image)
            return image
        except Exception as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock: self.pending.pop(key, None)


def capture_snapshot_jpeg(
    *,
    ffmpeg_bin: str,
    rtsp_url: str,
    timeout_sec: float = 3.0,
) -> bytes:
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        # A single JPEG does not need seconds of frame-rate analysis. Apply this
        # budget to both the private input manifest and the outer demuxer.
        "-analyzeduration",
        "100000",
        "-i",
        rtsp_url,
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    try:
        with private_media_input_command(cmd, rtsp_url) as safe_command:
            proc = run_background(
                safe_command, **background_process_options(),
                check=False,
                capture_output=True,
                timeout=timeout_sec,
            )
    except FileNotFoundError as e:
        raise SnapshotError(f"ffmpeg not found: {ffmpeg_bin}") from e
    except subprocess.TimeoutExpired as e:
        raise SnapshotError(f"snapshot timeout after {timeout_sec:.1f}s") from e

    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
        stderr = stderr.replace(rtsp_url, '<camera-source>')
        raise SnapshotError(
            f"snapshot capture failed (exit={proc.returncode}): {stderr or 'unknown ffmpeg error'}"
        )

    if not proc.stdout:
        raise SnapshotError("snapshot capture returned empty output")
    return proc.stdout
