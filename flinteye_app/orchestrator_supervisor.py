from __future__ import annotations
from contextlib import contextmanager

from flinteye_app.flinteye_runtime import worker_command

import logging
import json
import os
import signal
import shlex
import socket
import subprocess
from flinteye_app.process_lifetime import popen_background, run_background
from flinteye_app.subprocess_utils import background_process_options
import sys
import threading
import time
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flinteye_app.orchestrator_logging import LogManager, infer_line_level, parse_duration_to_seconds
from flinteye_app.orchestrator_models import CameraConfig, RuntimeConfig
from flinteye_app.orchestrator_snapshot import SnapshotError, capture_snapshot_jpeg


logger = logging.getLogger("orchestrator.supervisor")


@dataclass
class ManagedProcess:
    key: str
    kind: str
    command: list[str] = field(default_factory=list)
    command_display: str = ""
    env: dict[str, str] | None = None
    cwd: str | None = None
    desired: bool = False
    process: subprocess.Popen[str] | None = None
    started_at: float | None = None
    restart_count: int = 0
    last_exit_code: int | None = None
    last_error: str | None = None
    next_restart_at: float = 0.0
    maintenance_enabled: bool = False
    maintenance_interval_sec: float | None = None
    maintenance_align_sec: float | None = None
    maintenance_offset_sec: float = 0.0
    maintenance_next_at: float | None = None
    restart_pending_at: float | None = None
    restart_pending_reason: str | None = None
    healthcheck_enabled: bool = False
    healthcheck_interval_sec: float | None = None
    healthcheck_timeout_sec: float = 0.0
    healthcheck_failure_threshold: int = 1
    healthcheck_next_at: float | None = None
    healthcheck_failures: int = 0
    last_healthcheck_at: float | None = None
    last_healthcheck_error: str | None = None
    healthcheck_rtsp_url: str | None = None
    healthcheck_ffmpeg_bin: str = "ffmpeg"
    manual_excluded: bool = False
    manual_excluded_since: float | None = None
    quarantined: bool = False
    quarantine_since: float | None = None
    quarantine_reason: str | None = None
    output_thread: threading.Thread | None = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def health_state(self) -> str:
        if self.manual_excluded:
            return "excluded"
        if self.quarantined:
            return "quarantined"
        if not self.desired:
            return "disabled"
        if self.is_running():
            if self.healthcheck_failures > 0 or self.last_healthcheck_error:
                return "degraded"
            return "healthy"
        if self.last_error or self.last_exit_code not in (None, 0):
            return "unhealthy"
        return "starting"


def _format_cmd(cmd: list[str]) -> str:
    safe: list[str] = []
    hide_next = False
    for part in cmd:
        if hide_next:
            safe.append("***")
            hide_next = False
            continue
        if part in {"--onvif-password", "--source-url", "--camera-source-url", "--manual-url"}:
            safe.append(part)
            hide_next = True
            continue
        parsed = urlparse(part) if "://" in part else None
        if parsed and (parsed.username is not None or parsed.password is not None or parsed.query):
            part = "<redacted-url>"
        safe.append(part)
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(safe)
    return " ".join(shlex.quote(part) for part in safe)


def _protected_worker_command(command: list[str]) -> tuple[list[str], dict[str, str]]:
    supported = any("ip_camera_to_rtsp" in part or "multiview_input_to_rtsp" in part for part in command[:4])
    safe = list(command)
    secrets: dict[str, str] = {}
    for index, value in enumerate(command):
        flag = command[index - 1] if index else ""
        parsed = urlparse(value) if "://" in value else None
        sensitive = supported and flag in {"--onvif-password", "--source-url", "--camera-source-url", "--manual-url"} and bool(value)
        sensitive = sensitive or bool(parsed and (parsed.username is not None or parsed.password is not None or parsed.query))
        if not sensitive:
            continue
        if flag in {"--rtsp-url", "--output-url"}:
            raise ValueError("Authenticated RTSP publisher URLs are not supported securely")
        if not supported or not flag.startswith("--"):
            raise ValueError("Credential-bearing URL is not supported in this worker")
        secrets[flag[2:].replace("-", "_")] = value
        safe[index] = ""
    if secrets:
        safe.append("--secret-stdin")
    return safe, secrets


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _publisher_rtsp_base_url(config: RuntimeConfig) -> str:
    return config.mediamtx.internal_rtsp_base_url or config.mediamtx.rtsp_base_url


def _camera_label(camera: CameraConfig) -> str:
    if camera.display_name:
        return camera.display_name
    if camera.type == "uvc" and camera.uvc and camera.uvc.env:
        camera_name = camera.uvc.env.get("CAMERA_NAME")
        if isinstance(camera_name, str) and camera_name.strip():
            return camera_name.strip()
    return camera.path or camera.id


def _configured_multiview_sources(config: RuntimeConfig) -> list[str]:
    raw_paths = config.multiview.source_paths or [
        camera.path for camera in config.cameras if camera.enabled and camera.path
    ]
    out: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        normalized = raw_path.strip().strip("/")
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        camera = next((item for item in config.cameras if item.path.lower() == key), None)
        if camera and camera.type == "ip" and camera.ip:
            mode = camera.ip.multiview_input.mode
            if mode == "inherit":
                mode = config.multiview.input_defaults.mode
            if mode != "primary":
                normalized = f"__mv_input/{camera.path}"
        out.append(normalized)
    return out


def _multiview_input_mode(config: RuntimeConfig, camera: CameraConfig) -> str:
    if camera.type != "ip" or not camera.ip:
        return "primary"
    mode = camera.ip.multiview_input.mode
    return config.multiview.input_defaults.mode if mode == "inherit" else mode


def _multiview_tile_size(config: RuntimeConfig) -> tuple[int, int]:
    layout = config.multiview.layout
    columns = layout.grid_columns or max(1, math.ceil(math.sqrt(config.multiview.tile_count)))
    rows = max(1, math.ceil(config.multiview.tile_count / columns))
    return max(2, (layout.canvas_width // columns) // 2 * 2), max(2, (layout.canvas_height // rows) // 2 * 2)


def _multiview_buffer_path(source_path: str) -> str:
    return f"__mv_buffer/{source_path.strip().strip('/')}"


def _multiview_effective_sources(config: RuntimeConfig) -> list[str]:
    # The synchronized compositor consumes the selected source directly. It
    # keeps decoded frames in memory and never publishes/reads the former
    # __mv_buffer/* intermediary paths.
    return _configured_multiview_sources(config)


def _value_to_cli(value: Any) -> str:
    return str(value)


def _append_arg(cmd: list[str], flag: str, value: Any | None) -> None:
    if value is None:
        return
    if isinstance(value, str) and value == "":
        return
    cmd.extend([flag, _value_to_cli(value)])


def _probe_rtsp_listener(rtsp_base_url: str, timeout_sec: float = 0.7) -> tuple[bool, str]:
    parsed = urlparse(rtsp_base_url)
    host = parsed.hostname
    if not host:
        return False, "invalid rtsp_base_url (missing host)"
    port = parsed.port or 8554
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True, f"tcp {host}:{port} reachable"
    except OSError as e:
        return False, f"tcp {host}:{port} unreachable ({e})"


def _default_ffmpeg_loglevel(level: str) -> str:
    normalized = (level or "").strip().upper()
    if normalized == "DEBUG":
        return "debug"
    if normalized == "INFO":
        return "info"
    if normalized == "WARNING":
        return "warning"
    return "error"


def _kill_process_tree_windows(pid: int, *, timeout: float = 10) -> bool:
    try:
        result = run_background(
            ["taskkill", "/PID", str(pid), "/T", "/F"], **background_process_options(),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class OrchestratorSupervisor:
    def __init__(
        self,
        *,
        workspace_dir: str,
        env_file: str,
        log_manager: LogManager,
        python_bin: str | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.env_file = env_file
        self.log_manager = log_manager
        self.python_bin = python_bin or sys.executable or "python3"
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitoring_enabled = True
        self.media_environment: dict[str, str] = {}
        self._processes: dict[str, ManagedProcess] = {}
        self._last_config: RuntimeConfig | None = None
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._monitor_thread.join(timeout=2.0)
        with self._lock:
            # Keep the recorder alive until its publishers have disconnected.
            for proc in sorted(self._processes.values(), key=lambda item: item.key.startswith('mediamtx:')):
                self._stop_process(proc)

    def set_monitoring_enabled(self, enabled: bool) -> None:
        """Gate every launch/retry without stopping the recorder prematurely."""
        with self._lock:
            self._monitoring_enabled = enabled and not self._stop_event.is_set()
            if not self._monitoring_enabled:
                for proc in self._processes.values():
                    proc.desired = False
                    proc.restart_pending_at = None
                    proc.maintenance_next_at = None
                    proc.healthcheck_next_at = None

    @contextmanager
    def media_update(self, *, pause=True):
        """Pause publishers before changing their media server, under its monitor lock."""
        with self._lock:
            if pause:
                self.pause_media_publishers()
            yield

    def pause_media_publishers(self, *, deadline: float | None = None):
        with self._lock:
            for proc in self._processes.values():
                if not proc.key.startswith('mediamtx:'):
                    self._stop_process(proc, deadline=deadline) if deadline is not None else self._stop_process(proc)
            logger.info('publishers stopped for a planned media configuration change')

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            due_healthchecks: list[str] = []
            with self._lock:
                now = time.time()
                for proc in self._processes.values():
                    if proc.process is None:
                        if proc.desired and now >= proc.next_restart_at and proc.command:
                            self._start_process(proc, is_restart=True)
                        continue

                    exit_code = proc.process.poll()
                    if exit_code is None:
                        if proc.restart_pending_at is not None and now >= proc.restart_pending_at:
                            self._request_managed_restart(
                                proc,
                                now=now,
                                reason=proc.restart_pending_reason or f"deferred {proc.kind} restart",
                                delay_sec=0.5,
                            )
                            continue
                        if (
                            proc.maintenance_enabled
                            and proc.maintenance_next_at is not None
                            and now >= proc.maintenance_next_at
                        ):
                            self._request_managed_restart(
                                proc,
                                now=now,
                                reason=f"scheduled {proc.kind} maintenance restart",
                                delay_sec=0.5,
                            )
                            continue
                        if (
                            proc.healthcheck_enabled
                            and proc.healthcheck_next_at is not None
                            and now >= proc.healthcheck_next_at
                        ):
                            interval = proc.healthcheck_interval_sec or 60.0
                            proc.healthcheck_next_at = now + interval
                            due_healthchecks.append(proc.key)
                        continue

                    desired = proc.desired
                    # A worker can exit while its FFmpeg descendants still run.
                    self._stop_process(proc)
                    proc.desired = desired
                    proc.last_exit_code = exit_code
                    if proc.desired:
                        proc.next_restart_at = now + (5.0 if proc.key == "multiview" else 1.0)
                    if exit_code != 0:
                        logger.error("%s exited with code %s", proc.key, exit_code)
                    if proc.key.startswith("camera:"):
                        self._schedule_multiview_restart(
                            source_key=proc.key,
                            exit_code=exit_code,
                            now=now,
                        )
            for process_key in due_healthchecks:
                self._run_process_healthcheck(process_key)
            time.sleep(0.5)

    def _request_managed_restart(
        self,
        proc: ManagedProcess,
        *,
        now: float,
        reason: str,
        delay_sec: float,
    ) -> None:
        if not self._monitoring_enabled or not proc.desired:
            return
        saved_desired = proc.desired
        self._stop_process(proc)
        proc.desired = saved_desired
        proc.last_error = reason
        proc.next_restart_at = now + delay_sec
        proc.restart_pending_at = None
        proc.restart_pending_reason = None
        proc.maintenance_next_at = None
        proc.healthcheck_next_at = None
        proc.healthcheck_failures = 0
        if proc.key.startswith("camera:"):
            self._schedule_multiview_restart(source_key=proc.key, exit_code=None, now=now)

    def _schedule_multiview_restart(
        self,
        *,
        source_key: str,
        exit_code: int | None,
        now: float,
    ) -> None:
        if self._last_config is not None and self._last_config.multiview.sync_buffer.enabled:
            return
        mv_proc = self._processes.get("multiview")
        if mv_proc is None or not mv_proc.desired:
            return
        if self._last_config is not None and self._last_config.multiview.enabled:
            mv_proc.command = self._multiview_command(self._last_config)
            mv_proc.command_display = _format_cmd(mv_proc.command)
        delay_sec = 8.0
        reason = (
            f"restarting multiview after source change: {source_key} exited"
            + (f" ({exit_code})" if exit_code is not None else "")
        )
        if mv_proc.process is None or mv_proc.process.poll() is not None:
            mv_proc.next_restart_at = max(mv_proc.next_restart_at, now + delay_sec)
            mv_proc.last_error = reason
            return

        # Multiple IP relays can reconnect together. Debounce multiview restarts so
        # the compose process reopens inputs after the MediaMTX paths are published.
        mv_proc.restart_pending_at = now + delay_sec
        mv_proc.restart_pending_reason = reason
        mv_proc.last_error = reason

    def _refresh_maintenance_schedule(
        self,
        proc: ManagedProcess,
        *,
        reference_time: float,
    ) -> None:
        if not proc.maintenance_enabled or not proc.maintenance_interval_sec:
            proc.maintenance_next_at = None
            return

        candidate = reference_time + proc.maintenance_interval_sec
        if proc.maintenance_align_sec and proc.maintenance_align_sec > 0:
            aligned = math.floor(candidate / proc.maintenance_align_sec) * proc.maintenance_align_sec
            aligned += proc.maintenance_offset_sec
            if aligned <= candidate:
                aligned += proc.maintenance_align_sec
            candidate = aligned
        else:
            candidate += proc.maintenance_offset_sec
        proc.maintenance_next_at = candidate

    def _refresh_healthcheck_schedule(
        self,
        proc: ManagedProcess,
        *,
        reference_time: float,
    ) -> None:
        if not proc.healthcheck_enabled or not proc.healthcheck_interval_sec:
            proc.healthcheck_next_at = None
            return
        proc.healthcheck_next_at = reference_time + proc.healthcheck_interval_sec

    def _run_process_healthcheck(self, process_key: str) -> None:
        with self._lock:
            proc = self._processes.get(process_key)
            if (
                proc is None
                or proc.process is None
                or proc.process.poll() is not None
                or not proc.healthcheck_enabled
                or not proc.healthcheck_rtsp_url
            ):
                return
            pid = proc.process.pid
            ffmpeg_bin = proc.healthcheck_ffmpeg_bin
            rtsp_url = proc.healthcheck_rtsp_url
            timeout_sec = proc.healthcheck_timeout_sec
            threshold = proc.healthcheck_failure_threshold

        try:
            capture_snapshot_jpeg(
                ffmpeg_bin=ffmpeg_bin,
                rtsp_url=rtsp_url,
                timeout_sec=timeout_sec,
            )
        except SnapshotError as e:
            now = time.time()
            with self._lock:
                proc = self._processes.get(process_key)
                if proc is None or proc.process is None or proc.process.poll() is not None or proc.process.pid != pid:
                    return
                proc.last_healthcheck_at = now
                proc.healthcheck_failures += 1
                proc.last_healthcheck_error = str(e)
                logger.warning(
                    "%s watchdog failed (%s/%s): %s",
                    process_key,
                    proc.healthcheck_failures,
                    threshold,
                    e,
                )
                if proc.healthcheck_failures >= threshold:
                    if not proc.quarantined:
                        proc.quarantined = True
                        proc.quarantine_since = now
                    proc.quarantine_reason = (
                        f"watchdog quarantine after {proc.healthcheck_failures} consecutive "
                        f"snapshot failures: {e}"
                    )
                    self._request_managed_restart(
                        proc,
                        now=now,
                        reason=(
                            f"watchdog restart after {proc.healthcheck_failures} consecutive "
                            f"snapshot failures: {e}"
                        ),
                        delay_sec=1.0,
                    )
            return

        with self._lock:
            proc = self._processes.get(process_key)
            if proc is None or proc.process is None or proc.process.poll() is not None or proc.process.pid != pid:
                return
            was_degraded = proc.quarantined or proc.healthcheck_failures > 0 or bool(proc.last_healthcheck_error)
            proc.last_healthcheck_at = time.time()
            proc.healthcheck_failures = 0
            proc.last_healthcheck_error = None
            proc.quarantined = False
            proc.quarantine_since = None
            proc.quarantine_reason = None
            if was_degraded and proc.key.startswith("camera:"):
                self._schedule_multiview_restart(source_key=proc.key, exit_code=None, now=proc.last_healthcheck_at)

    def _start_process(self, proc: ManagedProcess, *, is_restart: bool = False) -> None:
        if self._stop_event.is_set() or not self._monitoring_enabled:
            proc.desired = False
            return
        try:
            safe_command, secret_input = _protected_worker_command(proc.command)
            if proc.key == 'mediamtx:direct':
                import shutil
                executable = safe_command[0]
                working_dir = proc.cwd or self.workspace_dir
                if not Path(working_dir).is_dir():
                    raise FileNotFoundError(2, 'MediaMTX working directory does not exist', working_dir)
                resolved = str(Path(executable).resolve()) if Path(executable).is_absolute() else shutil.which(executable)
                if not resolved or not Path(resolved).is_file():
                    raise FileNotFoundError(2, 'MediaMTX executable does not exist; select the bundled version or reinstall FlintEye', executable)
                if len(safe_command) >= 2 and not Path(safe_command[1]).is_file():
                    raise FileNotFoundError(2, 'MediaMTX configuration file does not exist', safe_command[1])
                safe_command[0] = resolved
                logger.info('Starting MediaMTX executable=%s cwd=%s', resolved, working_dir)
            popen_env = os.environ.copy()
            if proc.env:
                popen_env.update(proc.env)
            if proc.key == 'mediamtx:direct':
                popen_env.update(self.media_environment)
            popen_kwargs: dict[str, Any] = {
                "cwd": proc.cwd or self.workspace_dir,
                "env": popen_env,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "bufsize": 1,
            }
            if secret_input:
                popen_kwargs["stdin"] = subprocess.PIPE
            popen_kwargs.update(background_process_options(new_process_group=True))
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True
            proc.process = popen_background(
                safe_command,
                **popen_kwargs,
            )
            if secret_input and proc.process.stdin is not None:
                try:
                    proc.process.stdin.write(json.dumps(secret_input))
                    proc.process.stdin.close()
                except (BrokenPipeError, OSError):
                    proc.process.kill()
                    raise
            proc.started_at = time.time()
            proc.command_display = _format_cmd(proc.command)
            proc.last_error = None
            proc.restart_pending_at = None
            proc.restart_pending_reason = None
            self._refresh_maintenance_schedule(proc, reference_time=proc.started_at)
            self._refresh_healthcheck_schedule(proc, reference_time=proc.started_at)
            proc.healthcheck_failures = 0
            proc.last_healthcheck_error = None
            if proc.process.stdout is not None:
                proc.output_thread = threading.Thread(
                    target=self._pump_process_output,
                    args=(proc.key, proc.process.stdout),
                    daemon=True,
                )
                proc.output_thread.start()
            if is_restart:
                proc.restart_count += 1
                logger.info("restarted %s", proc.key)
                if proc.key.startswith("camera:"):
                    self._schedule_multiview_restart(source_key=proc.key, exit_code=None, now=proc.started_at)
            else:
                logger.info("started %s", proc.key)
        except Exception as e:  # noqa: BLE001
            if proc.process is not None:
                desired = proc.desired
                self._stop_process(proc)
                proc.desired = desired and not self._stop_event.is_set()
            proc.process = None
            proc.started_at = None
            proc.last_error = str(e)
            proc.next_restart_at = time.time() + 2.0
            proc.maintenance_next_at = None
            logger.exception("failed to start %s", proc.key)

    def _pump_process_output(self, process_key: str, stream: Any) -> None:
        process_logger = self.log_manager.get_process_logger(process_key)
        try:
            for raw_line in stream:
                line = raw_line.rstrip()
                if not line:
                    continue
                process_logger.log(infer_line_level(line), line)
        except Exception:
            logger.exception("failed while reading child output for %s", process_key)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _stop_process(self, proc: ManagedProcess, *, deadline: float | None = None) -> None:
        proc.desired = False
        if proc.process is None:
            return
        try:
            if os.name != "nt":
                # terminate process group so child ffmpeg processes are not orphaned
                try:
                    os.killpg(proc.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                proc.process.wait(timeout=5 if deadline is None else max(0, min(5, deadline - time.monotonic())))
            elif proc.process.poll() is None:
                if not _kill_process_tree_windows(proc.process.pid, timeout=10 if deadline is None else max(.1, min(10, deadline - time.monotonic()))):
                    proc.process.terminate()
                proc.process.wait(timeout=5 if deadline is None else max(0, min(5, deadline - time.monotonic())))
        except Exception:  # noqa: BLE001
            try:
                if proc.process and proc.process.poll() is None and os.name != "nt":
                    os.killpg(proc.process.pid, signal.SIGKILL)
                elif proc.process and not _kill_process_tree_windows(proc.process.pid, timeout=1 if deadline is not None else 10):
                    proc.process.kill()
            except Exception:  # noqa: BLE001
                pass
        finally:
            if proc.process is not None and os.name != "nt":
                # The leader exiting does not prove its process group is empty.
                # Escalate for descendants that ignored TERM or outlived it.
                try:
                    os.killpg(proc.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.process.wait(timeout=5 if deadline is None else max(.1, min(5, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    logger.error("process group did not stop: %s", proc.key)
            if proc.process is not None:
                proc.last_exit_code = proc.process.poll()
            proc.process = None
            proc.started_at = None
            proc.maintenance_next_at = None
            proc.restart_pending_at = None
            proc.restart_pending_reason = None
            proc.healthcheck_next_at = None
            proc.healthcheck_failures = 0
            proc.output_thread = None

    def _ensure_process(
        self,
        *,
        key: str,
        kind: str,
        command: list[str],
        desired: bool,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        force_restart: bool = False,
    ) -> ManagedProcess:
        desired = desired and self._monitoring_enabled
        proc = self._processes.get(key)
        if proc is None:
            proc = ManagedProcess(key=key, kind=kind)
            self._processes[key] = proc

        command_changed = proc.command != command or proc.cwd != (cwd or self.workspace_dir) or proc.env != env
        proc.command = command
        proc.cwd = cwd or self.workspace_dir
        proc.env = env
        proc.desired = desired

        if not desired:
            self._stop_process(proc)
            return proc

        if force_restart and proc.is_running():
            self._stop_process(proc)
            proc.desired = desired

        if command_changed and proc.is_running():
            self._stop_process(proc)
            proc.desired = desired

        if proc.process is None:
            proc.desired = desired
            self._start_process(proc, is_restart=proc.restart_count > 0 or force_restart)
        return proc

    def _camera_command(self, config: RuntimeConfig, camera: CameraConfig) -> list[str]:
        rtsp_url = _join_url(_publisher_rtsp_base_url(config), camera.path)
        default_loglevel = _default_ffmpeg_loglevel(config.logging.level)
        if camera.type == "uvc":
            cmd = [
                *worker_command("uvc_to_rtsp", self.python_bin),
                "--no-env",
            ]
            if camera.uvc and camera.uvc.profile:
                _append_arg(cmd, "--profile", camera.uvc.profile)

            uvc_env = camera.uvc.env if camera.uvc else {}
            _append_arg(cmd, "--input-driver", uvc_env.get("INPUT_DRIVER"))
            _append_arg(cmd, "--device", uvc_env.get("DEVICE"))
            _append_arg(cmd, "--ffmpeg-bin", uvc_env.get("FFMPEG_BIN"))
            _append_arg(cmd, "--loglevel", uvc_env.get("LOGLEVEL") or default_loglevel)
            _append_arg(cmd, "--encoder", uvc_env.get("ENCODER"))
            _append_arg(cmd, "--latency-preset", uvc_env.get("LATENCY_PRESET"))
            _append_arg(cmd, "--quality-preset", uvc_env.get("QUALITY_PRESET"))
            _append_arg(cmd, "--width", uvc_env.get("WIDTH"))
            _append_arg(cmd, "--height", uvc_env.get("HEIGHT"))
            _append_arg(cmd, "--fps", uvc_env.get("FPS"))
            _append_arg(cmd, "--input-format", uvc_env.get("INPUT_FORMAT"))
            _append_arg(cmd, "--rtbufsize", uvc_env.get("RTBUFSIZE"))
            _append_arg(cmd, "--bitrate", uvc_env.get("BITRATE"))
            _append_arg(cmd, "--maxrate", uvc_env.get("MAXRATE"))
            _append_arg(cmd, "--bufsize", uvc_env.get("BUFSIZE"))
            _append_arg(cmd, "--gop", uvc_env.get("GOP"))
            _append_arg(cmd, "--thread-queue-size", uvc_env.get("THREAD_QUEUE_SIZE"))
            _append_arg(cmd, "--bframes", uvc_env.get("BFRAMES"))
            _append_arg(cmd, "--font-size", uvc_env.get("FONT_SIZE"))
            _append_arg(cmd, "--fontfile", uvc_env.get("FONTFILE"))
            _append_arg(cmd, "--x264-preset", uvc_env.get("X264_PRESET"))

            camera_name = (uvc_env.get("CAMERA_NAME") if uvc_env else None) or camera.id
            _append_arg(cmd, "--camera-name", camera_name)
            _append_arg(cmd, "--rtsp-url", rtsp_url)
            if camera.uvc and camera.uvc.extra_args:
                cmd.extend(camera.uvc.extra_args)
            return cmd

        ip_cfg = camera.ip
        if ip_cfg and ip_cfg.source_url:
            source_url = ip_cfg.source_url
        else:
            source_url = ""
        relay_mode = ip_cfg.relay_mode if ip_cfg else "copy"
        cmd = [
            *worker_command("ip_camera_to_rtsp", self.python_bin),
            "--source-url",
            source_url,
            "--rtsp-url",
            rtsp_url,
            "--relay-mode",
            relay_mode,
            "--timestamp-mode",
            ip_cfg.timestamp_mode if ip_cfg else "auto",
            "--cfr-fps",
            str(ip_cfg.cfr_fps if ip_cfg else 20.0),
            "--loglevel",
            default_loglevel,
        ]
        bitrate = (ip_cfg.bitrate if ip_cfg else None) or "2M"
        maxrate = (ip_cfg.maxrate if ip_cfg else None) or bitrate
        _append_arg(cmd, "--bitrate", bitrate)
        _append_arg(cmd, "--maxrate", maxrate)
        _append_arg(cmd, "--bufsize", (ip_cfg.bufsize if ip_cfg else None) or "4M")
        _append_arg(cmd, "--gop", ip_cfg.gop if ip_cfg else 40)
        _append_arg(cmd, "--x264-preset", (ip_cfg.x264_preset if ip_cfg else None) or "veryfast")
        return cmd

    def _multiview_input_command(self, config: RuntimeConfig, camera: CameraConfig) -> list[str]:
        assert camera.ip is not None
        mv = config.multiview
        defaults = mv.input_defaults
        override = camera.ip.multiview_input
        mode = _multiview_input_mode(config, camera)
        width, height = _multiview_tile_size(config)
        resolution = override.resolution or defaults.resolution
        if resolution != "auto" and "x" in resolution.lower():
            try:
                raw_width, raw_height = resolution.lower().split("x", 1)
                width = max(2, int(raw_width) // 2 * 2)
                height = max(2, int(raw_height) // 2 * 2)
            except ValueError:
                pass
        primary_url = _join_url(mv.input_rtsp_base_url, camera.path)
        output_url = _join_url(mv.output_rtsp_base_url, f"__mv_input/{camera.path}")
        cmd = [
            *worker_command("multiview_input_to_rtsp", self.python_bin),
            "--mode",
            mode,
            "--primary-url",
            primary_url,
            "--camera-source-url",
            camera.ip.source_url or "",
            "--output-url",
            output_url,
            "--fps",
            str(override.target_fps or defaults.target_fps),
            "--width",
            str(width),
            "--height",
            str(height),
            "--encoder",
            override.encoder or defaults.encoder,
            "--quality-preset",
            override.quality_preset or defaults.quality_preset,
            "--bitrate",
            override.bitrate or defaults.bitrate,
            "--maxrate",
            override.maxrate or defaults.maxrate,
            "--bufsize",
            override.bufsize or defaults.bufsize,
            "--x264-preset",
            override.x264_preset or defaults.x264_preset,
            "--thread-queue-size",
            str(override.thread_queue_size or mv.input_thread_queue_size),
            "--stall-timeout-sec",
            str(override.stall_timeout_sec if override.stall_timeout_sec is not None else mv.input_stall_timeout_sec),
            "--stall-timeout-option",
            mv.input_stall_timeout_option,
            "--preferred-retry-sec",
            "300",
            "--ffmpeg-bin",
            mv.ffmpeg_bin,
            "--loglevel",
            mv.loglevel,
            "--status-file",
            str(Path(mv.status_file).with_name(f"multiview_input_{camera.id}.json")),
        ]
        _append_arg(cmd, "--manual-url", override.manual_url)
        _append_arg(cmd, "--profile-token", override.profile_token)
        _append_arg(cmd, "--onvif-mode", camera.ip.onvif_mode)
        _append_arg(cmd, "--onvif-address", camera.ip.onvif_address)
        _append_arg(cmd, "--onvif-username", camera.ip.onvif_username)
        _append_arg(cmd, "--onvif-password", camera.ip.onvif_password)
        cmd.append("--fallback-to-primary" if defaults.fallback_to_primary else "--no-fallback-to-primary")
        return cmd

    def _multiview_buffer_command(
        self,
        config: RuntimeConfig,
        source_path: str,
        index: int,
    ) -> list[str]:
        mv = config.multiview
        sync = mv.sync_buffer
        defaults = mv.input_defaults
        buffer_path = _multiview_buffer_path(source_path)
        timeout_option = mv.input_stall_timeout_option
        return [
            *worker_command("multiview_buffer_to_rtsp", self.python_bin),
            "--source-url", _join_url(mv.input_rtsp_base_url, source_path),
            "--source-path", source_path,
            "--output-url", _join_url(mv.output_rtsp_base_url, buffer_path),
            "--buffer-path", buffer_path,
            "--delay-sec", str(sync.delay_sec),
            "--buffer-sec", str(sync.buffer_sec),
            "--fps", str(sync.fps),
            "--width", str(sync.width),
            "--height", str(sync.height),
            "--late-frame-policy", sync.late_frame_policy,
            "--max-hold-sec", str(sync.max_hold_sec),
            "--memory-limit-mb", str(sync.memory_limit_mb_per_input),
            "--reconnect-sec", str(sync.reconnect_sec),
            "--thread-queue-size", str(mv.input_thread_queue_size),
            "--stall-timeout-sec", str(mv.input_stall_timeout_sec),
            "--stall-timeout-option", timeout_option,
            "--encoder", defaults.encoder,
            "--bitrate", defaults.bitrate,
            "--maxrate", defaults.maxrate,
            "--bufsize", defaults.bufsize,
            "--x264-preset", defaults.x264_preset,
            "--ffmpeg-bin", mv.ffmpeg_bin,
            "--loglevel", mv.loglevel,
            "--status-file",
            str(Path(mv.status_file).with_name(f"multiview_buffer_{index}.json")),
        ]

    def _multiview_command(self, config: RuntimeConfig) -> list[str]:
        mv = config.multiview
        q = mv.quality
        layout = mv.layout
        if mv.sync_buffer.enabled:
            sync = mv.sync_buffer
            configured_sources = _multiview_effective_sources(config)
            source_label_map: dict[str, str] = {}
            for camera in config.cameras:
                effective_path = (
                    f"__mv_input/{camera.path}"
                    if _multiview_input_mode(config, camera) != "primary"
                    else camera.path
                )
                label = _camera_label(camera).strip()
                if label:
                    source_label_map[effective_path] = label
            cmd = [
                *worker_command("multiview_raw_compositor", self.python_bin),
                "--source-paths", ",".join(configured_sources),
                "--input-rtsp-base-url", mv.input_rtsp_base_url,
                "--output-rtsp-base-url", mv.output_rtsp_base_url,
                "--output-prefix", mv.output_prefix,
                "--max-sources", str(mv.max_sources),
                "--tile-count", str(mv.tile_count),
                "--canvas-width", str(layout.canvas_width),
                "--canvas-height", str(layout.canvas_height),
                "--fps", str(sync.fps),
                "--delay-sec", str(sync.delay_sec),
                "--buffer-sec", str(sync.buffer_sec),
                "--late-frame-policy", sync.late_frame_policy,
                "--max-hold-sec", str(sync.max_hold_sec),
                "--memory-limit-mb", str(sync.memory_limit_mb_per_input),
                "--reconnect-sec", str(sync.reconnect_sec),
                "--thread-queue-size", str(mv.input_thread_queue_size),
                "--stall-timeout-sec", str(mv.input_stall_timeout_sec),
                "--stall-timeout-option", mv.input_stall_timeout_option,
                "--encoder", q.encoder,
                "--quality-preset", q.quality_preset,
                "--gop", str(q.gop),
                "--bframes", str(q.bframes),
                "--x264-preset", q.x264_preset,
                "--ffmpeg-bin", mv.ffmpeg_bin,
                "--loglevel", mv.loglevel,
                "--status-file", mv.status_file,
            ]
            if layout.grid_columns:
                _append_arg(cmd, "--grid-columns", layout.grid_columns)
            if layout.global_slots:
                _append_arg(cmd, "--slot-positions", layout.global_slots)
            if layout.per_view_slots:
                _append_arg(cmd, "--per-view-slots-json", json.dumps(layout.per_view_slots, ensure_ascii=False, separators=(",", ":")))
            if q.bitrate:
                _append_arg(cmd, "--bitrate", q.bitrate)
            if q.maxrate:
                _append_arg(cmd, "--maxrate", q.maxrate)
            if q.bufsize:
                _append_arg(cmd, "--bufsize", q.bufsize)
            if source_label_map:
                _append_arg(cmd, "--source-label-map-json", json.dumps(source_label_map, ensure_ascii=False, separators=(",", ":")))
            return cmd

        # A delayed wall-clock buffer deliberately trades latency for
        # continuity. The compositor's low-latency RTSP flags (nobuffer,
        # zero probe/analyze budget and max_delay=0) work against that goal and
        # can discard leading packets when an internal publisher reconnects.
        effective_latency_preset = "normal" if mv.sync_buffer.enabled else mv.latency_preset
        source_label_map: dict[str, str] = {}
        source_placeholder_map: dict[str, str] = {}
        configured_sources = _multiview_effective_sources(config)
        shadowed_sources = [
            camera.path
            for camera in config.cameras
            if camera.type == "ip" and camera.ip and _multiview_input_mode(config, camera) != "primary"
        ]
        source_mode = "hybrid" if shadowed_sources and mv.source_mode == "api" else mv.source_mode
        for camera in config.cameras:
            effective_path = (
                f"__mv_input/{camera.path}"
                if _multiview_input_mode(config, camera) != "primary"
                else camera.path
            )
            if mv.sync_buffer.enabled:
                effective_path = _multiview_buffer_path(effective_path)
            label = _camera_label(camera).strip()
            if label:
                source_label_map[effective_path] = label

            proc = self._processes.get(f"camera:{camera.id.lower()}")
            placeholder_reason = None if mv.sync_buffer.enabled else self._multiview_placeholder_reason(camera, proc)
            if placeholder_reason:
                source_placeholder_map[effective_path] = placeholder_reason
        if mv.sync_buffer.enabled:
            source_mode = "env"
        cmd = [
            *worker_command("multiview_to_rtsp", self.python_bin),
            "--env-file",
            self.env_file,
            "--source-mode",
            "hybrid" if source_placeholder_map and source_mode == "api" else source_mode,
            "--auto-placeholder-missing-sources"
            if mv.auto_placeholder_missing_sources and not mv.sync_buffer.enabled
            else "--no-auto-placeholder-missing-sources",
            "--mtx-api-url",
            mv.mtx_api_url,
            "--input-rtsp-base-url",
            mv.input_rtsp_base_url,
            "--output-rtsp-base-url",
            mv.output_rtsp_base_url,
            "--output-prefix",
            mv.output_prefix,
            "--max-sources",
            str(mv.max_sources),
            "--tile-count",
            str(mv.tile_count),
            "--latency-preset",
            effective_latency_preset,
            "--canvas-width",
            str(layout.canvas_width),
            "--canvas-height",
            str(layout.canvas_height),
            "--fps",
            str(q.fps),
            "--encoder",
            q.encoder,
            "--quality-preset",
            q.quality_preset,
            "--gop",
            str(q.gop),
            "--bframes",
            str(q.bframes),
            "--x264-preset",
            q.x264_preset,
            "--restart-backoff-sec",
            str(mv.restart_backoff_sec),
            "--input-stall-timeout-sec",
            str(mv.input_stall_timeout_sec),
            "--input-stall-timeout-option",
            mv.input_stall_timeout_option,
            "--input-thread-queue-size",
            str(mv.input_thread_queue_size),
            "--input-healthcheck-interval-sec",
            str(mv.input_healthcheck_interval_sec),
            "--input-isolation-threshold",
            str(mv.input_isolation_threshold),
            "--input-retry-interval-sec",
            str(mv.input_retry_interval_sec),
            "--status-file",
            mv.status_file,
            "--ffmpeg-bin",
            mv.ffmpeg_bin,
            "--loglevel",
            mv.loglevel,
        ]
        healthcheck_enabled = mv.input_healthcheck_enabled and not mv.sync_buffer.enabled
        cmd.append("--input-healthcheck-enabled" if healthcheck_enabled else "--no-input-healthcheck-enabled")
        if mv.sync_buffer.enabled or mv.source_paths or source_placeholder_map or shadowed_sources:
            _append_arg(cmd, "--source-paths", ",".join(configured_sources))
        if shadowed_sources and not mv.sync_buffer.enabled:
            _append_arg(cmd, "--shadowed-source-paths", ",".join(shadowed_sources))
        if layout.grid_columns:
            _append_arg(cmd, "--grid-columns", layout.grid_columns)
        if layout.global_slots:
            _append_arg(cmd, "--slot-positions", layout.global_slots)
        if q.bitrate:
            _append_arg(cmd, "--bitrate", q.bitrate)
        if q.maxrate:
            _append_arg(cmd, "--maxrate", q.maxrate)
        if q.bufsize:
            _append_arg(cmd, "--bufsize", q.bufsize)
        if source_label_map:
            _append_arg(
                cmd,
                "--source-label-map-json",
                json.dumps(source_label_map, ensure_ascii=False, separators=(",", ":")),
            )
        if source_placeholder_map:
            _append_arg(
                cmd,
                "--source-placeholder-map-json",
                json.dumps(source_placeholder_map, ensure_ascii=False, separators=(",", ":")),
            )
        if mv.verbose:
            cmd.append("--verbose")
        return cmd

    def _multiview_placeholder_reason(self, camera: CameraConfig, proc: ManagedProcess | None) -> str | None:
        if not camera.enabled:
            return "Camera disabled"
        if proc is None:
            return "Camera process not registered"
        if proc.manual_excluded:
            return "Temporarily excluded"
        if proc.quarantined:
            return proc.quarantine_reason or "Quarantined by watchdog"
        if not proc.is_running():
            if proc.last_error:
                return proc.last_error
            if proc.last_exit_code not in (None, 0):
                return f"Process exited with code {proc.last_exit_code}"
            if proc.desired:
                return "Camera process is not running"
        return None

    def reconcile(self, config: RuntimeConfig, *, force_restart: bool = False) -> None:
        with self._lock:
            self._last_config = config
            if not self._monitoring_enabled:
                return
            desired_camera_keys: set[str] = set()
            for camera in config.cameras:
                key = f"camera:{camera.id.lower()}"
                desired_camera_keys.add(key)
                command = self._camera_command(config, camera)
                enabled = bool(camera.enabled)
                proc = self._ensure_process(
                    key=key,
                    kind=f"camera/{camera.type}",
                    command=command,
                    desired=enabled,
                    force_restart=force_restart and enabled,
                )
                if camera.type == "ip" and camera.ip:
                    proc.maintenance_enabled = camera.ip.periodic_restart_enabled
                    proc.maintenance_interval_sec = camera.ip.periodic_restart_interval_sec
                    proc.maintenance_align_sec = None
                    proc.maintenance_offset_sec = 0.0
                    proc.healthcheck_enabled = camera.ip.watchdog_enabled
                    proc.healthcheck_interval_sec = camera.ip.watchdog_interval_sec
                    proc.healthcheck_timeout_sec = camera.ip.watchdog_timeout_sec
                    proc.healthcheck_failure_threshold = camera.ip.watchdog_failure_threshold
                    proc.healthcheck_rtsp_url = _join_url(_publisher_rtsp_base_url(config), camera.path)
                    proc.healthcheck_ffmpeg_bin = "ffmpeg"
                    if proc.started_at is not None:
                        self._refresh_maintenance_schedule(proc, reference_time=proc.started_at)
                        self._refresh_healthcheck_schedule(proc, reference_time=proc.started_at)
                elif camera.type == "uvc":
                    proc.maintenance_enabled = False
                    proc.maintenance_interval_sec = None
                    proc.maintenance_align_sec = None
                    proc.maintenance_offset_sec = 0.0
                    proc.maintenance_next_at = None
                    proc.healthcheck_enabled = True
                    proc.healthcheck_interval_sec = 300.0
                    proc.healthcheck_timeout_sec = max(config.snapshot.timeout_sec, 5.0)
                    proc.healthcheck_failure_threshold = 3
                    proc.healthcheck_rtsp_url = _join_url(_publisher_rtsp_base_url(config), camera.path)
                    uvc_env = camera.uvc.env if camera.uvc else {}
                    proc.healthcheck_ffmpeg_bin = uvc_env.get("FFMPEG_BIN") or "ffmpeg"
                    if proc.started_at is not None:
                        self._refresh_healthcheck_schedule(proc, reference_time=proc.started_at)
                else:
                    proc.maintenance_enabled = False
                    proc.maintenance_interval_sec = None
                    proc.maintenance_align_sec = None
                    proc.maintenance_offset_sec = 0.0
                    proc.maintenance_next_at = None
                    proc.healthcheck_enabled = False
                    proc.healthcheck_interval_sec = None
                    proc.healthcheck_timeout_sec = 0.0
                    proc.healthcheck_failure_threshold = 1
                    proc.healthcheck_next_at = None
                    proc.healthcheck_rtsp_url = None

            for key, proc in list(self._processes.items()):
                if key.startswith("camera:") and key not in desired_camera_keys:
                    self._stop_process(proc)

            desired_mv_input_keys: set[str] = set()
            selected_paths = {
                path.strip().strip("/").lower()
                for path in (
                    config.multiview.source_paths
                    or [item.path for item in config.cameras if item.enabled]
                )
            }
            for camera in config.cameras:
                mode = _multiview_input_mode(config, camera)
                if (
                    not config.multiview.enabled
                    or not camera.enabled
                    or camera.type != "ip"
                    or not camera.ip
                    or mode == "primary"
                    or camera.path.lower() not in selected_paths
                ):
                    continue
                key = f"multiview-input:{camera.id.lower()}"
                desired_mv_input_keys.add(key)
                self._ensure_process(
                    key=key,
                    kind="multiview/input",
                    command=self._multiview_input_command(config, camera),
                    desired=True,
                    force_restart=force_restart,
                )
            for key, proc in list(self._processes.items()):
                if key.startswith("multiview-input:") and key not in desired_mv_input_keys:
                    self._stop_process(proc)

            desired_buffer_keys: set[str] = set()
            # Raw synchronized mode owns independent decoder children inside
            # the one Multiview service. Legacy H.264/RTSP buffer workers are
            # deliberately left undesired and stopped below.
            for key, proc in list(self._processes.items()):
                if key.startswith("multiview-buffer:") and key not in desired_buffer_keys:
                    self._stop_process(proc)

            mv_key = "multiview"
            if config.multiview.enabled:
                mv_command = self._multiview_command(config)
                mv_proc = self._ensure_process(
                    key=mv_key,
                    kind="multiview",
                    command=mv_command,
                    desired=True,
                    force_restart=force_restart,
                )
                align_sec = None
                if config.multiview.maintenance.align_with_record_segments:
                    align_sec = parse_duration_to_seconds(config.recording.record_segment_duration)
                mv_proc.maintenance_enabled = config.multiview.maintenance.enabled
                mv_proc.maintenance_interval_sec = config.multiview.maintenance.restart_interval_sec
                mv_proc.maintenance_align_sec = align_sec
                mv_proc.maintenance_offset_sec = config.multiview.maintenance.restart_offset_sec
                if mv_proc.started_at is not None:
                    self._refresh_maintenance_schedule(mv_proc, reference_time=mv_proc.started_at)
            elif mv_key in self._processes:
                self._stop_process(self._processes[mv_key])

    def _run_control_command(self, cmd: list[str]) -> tuple[int, str, str]:
        try:
            result = run_background(cmd, **background_process_options(), check=False, capture_output=True, text=True)
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError as e:
            return 127, "", str(e)
        except Exception as e:  # noqa: BLE001
            return 1, "", str(e)

    def mediamtx_status(self, config: RuntimeConfig) -> dict[str, Any]:
        mode = config.mediamtx.control_mode
        service_name = config.mediamtx.service_name
        if mode == "systemd":
            code, out, err = self._run_control_command(["systemctl", "is-active", service_name])
            status = out or err or ("active" if code == 0 else "inactive")
            return {"mode": mode, "service_name": service_name, "status": status, "running": code == 0}
        if mode == "launchd":
            target = f"system/{service_name}"
            code, out, err = self._run_control_command(["launchctl", "print", target])
            running = code == 0
            status = "running" if running else (err or "not_running")
            return {"mode": mode, "service_name": service_name, "status": status, "running": running}
        if mode == "windows_service":
            ps_cmd = (
                f"$s=Get-Service -Name '{service_name}' -ErrorAction SilentlyContinue; "
                "if ($null -eq $s) { exit 3 } ; "
                'Write-Output $s.Status'
            )
            code, out, err = self._run_control_command(["powershell", "-NoProfile", "-Command", ps_cmd])
            running = out.strip().lower() == "running"
            status = out or err or ("running" if running else "stopped")
            return {"mode": mode, "service_name": service_name, "status": status, "running": running}
        if mode == "direct":
            key = "mediamtx:direct"
            with self._lock:
                proc = self._processes.get(key)
                running = proc.is_running() if proc else False
                return {
                    "mode": mode,
                    "service_name": service_name,
                    "status": "running" if running else "stopped",
                    "running": running,
                    "pid": proc.process.pid if proc and proc.process else None,
                    "detail": proc.last_error if proc else None,
                    "last_exit_code": proc.last_exit_code if proc else None,
                }
        if mode == "external":
            running, detail = _probe_rtsp_listener(config.mediamtx.rtsp_base_url)
            return {
                "mode": mode,
                "service_name": service_name,
                "status": "running" if running else "stopped",
                "running": running,
                "detail": detail,
            }
        return {"mode": mode, "service_name": service_name, "status": "unsupported", "running": False}

    def mediamtx_start(self, config: RuntimeConfig) -> dict[str, Any]:
        if not self._monitoring_enabled:
            return {'ok': False, 'stderr': 'Monitoring is stopped', 'stdout': ''}
        mode = config.mediamtx.control_mode
        service_name = config.mediamtx.service_name
        if mode == "systemd":
            code, out, err = self._run_control_command(["systemctl", "start", service_name])
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "launchd":
            code, out, err = self._run_control_command(["launchctl", "kickstart", "-k", f"system/{service_name}"])
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "windows_service":
            code, out, err = self._run_control_command(
                ["powershell", "-NoProfile", "-Command", f"Start-Service -Name '{service_name}'"]
            )
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "direct":
            cmd = list(config.mediamtx.direct.command)
            if not cmd:
                return {"ok": False, "stdout": "", "stderr": "mediamtx.direct.command is empty"}
            with self._lock:
                self._ensure_process(
                    key="mediamtx:direct",
                    kind="mediamtx/direct",
                    command=cmd,
                    desired=True,
                    cwd=config.mediamtx.direct.working_dir or self.workspace_dir,
                )
                proc = self._processes["mediamtx:direct"]
                running = proc.is_running()
                error = proc.last_error or ("MediaMTX exited before startup completed" if not running else "")
            return {"ok": running, "stdout": "", "stderr": error}
        if mode == "external":
            running, detail = _probe_rtsp_listener(config.mediamtx.rtsp_base_url)
            if running:
                return {"ok": True, "stdout": "", "stderr": "external mode: already running"}
            return {"ok": False, "stdout": "", "stderr": f"external mode: start manually ({detail})"}
        return {"ok": False, "stdout": "", "stderr": f"unsupported control_mode: {mode}"}

    def mediamtx_stop(self, config: RuntimeConfig) -> dict[str, Any]:
        mode = config.mediamtx.control_mode
        service_name = config.mediamtx.service_name
        if mode == "systemd":
            code, out, err = self._run_control_command(["systemctl", "stop", service_name])
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "launchd":
            code, out, err = self._run_control_command(["launchctl", "bootout", f"system/{service_name}"])
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "windows_service":
            code, out, err = self._run_control_command(
                ["powershell", "-NoProfile", "-Command", f"Stop-Service -Name '{service_name}'"]
            )
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "direct":
            with self._lock:
                proc = self._processes.get("mediamtx:direct")
                if proc:
                    self._stop_process(proc)
            return {"ok": True, "stdout": "", "stderr": ""}
        if mode == "external":
            return {"ok": True, "stdout": "", "stderr": "external mode: stop manually (no-op)"}
        return {"ok": False, "stdout": "", "stderr": f"unsupported control_mode: {mode}"}

    def mediamtx_restart(self, config: RuntimeConfig) -> dict[str, Any]:
        if not self._monitoring_enabled:
            return {'ok': False, 'stderr': 'Monitoring is stopped', 'stdout': ''}
        if config.mediamtx.control_mode == 'external':
            return self._restart_mediamtx(config)
        with self.media_update():
            try:
                return self._restart_mediamtx(config)
            finally:
                self.reconcile(config)

    def _restart_mediamtx(self, config: RuntimeConfig) -> dict[str, Any]:
        mode = config.mediamtx.control_mode
        service_name = config.mediamtx.service_name
        if mode == "systemd":
            code, out, err = self._run_control_command(["systemctl", "restart", service_name])
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "launchd":
            code, out, err = self._run_control_command(["launchctl", "kickstart", "-k", f"system/{service_name}"])
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "windows_service":
            code, out, err = self._run_control_command(
                ["powershell", "-NoProfile", "-Command", f"Restart-Service -Name '{service_name}' -Force"]
            )
            return {"ok": code == 0, "stdout": out, "stderr": err}
        if mode == "direct":
            stop_result = self.mediamtx_stop(config)
            start_result = self.mediamtx_start(config)
            return {
                "ok": bool(stop_result.get("ok")) and bool(start_result.get("ok")),
                "stdout": "\n".join(filter(None, [stop_result.get("stdout", ""), start_result.get("stdout", "")])),
                "stderr": "\n".join(filter(None, [stop_result.get("stderr", ""), start_result.get("stderr", "")])),
            }
        if mode == "external":
            running, detail = _probe_rtsp_listener(config.mediamtx.rtsp_base_url)
            if running:
                return {"ok": True, "stdout": "", "stderr": "external mode: restart manually if needed (no-op)"}
            return {"ok": False, "stdout": "", "stderr": f"external mode: not reachable ({detail})"}
        return {"ok": False, "stdout": "", "stderr": f"unsupported control_mode: {mode}"}

    def start_all(self, config: RuntimeConfig) -> dict[str, Any]:
        mtx = self.mediamtx_start(config)
        self.reconcile(config)
        return {"mediamtx": mtx}

    def stop_all(self, config: RuntimeConfig) -> dict[str, Any]:
        with self._lock:
            for proc in sorted(self._processes.values(), key=lambda item: item.key.startswith('mediamtx:')):
                self._stop_process(proc)
        mtx = self.mediamtx_stop(config)
        return {"mediamtx": mtx}

    def restart_all(self, config: RuntimeConfig) -> dict[str, Any]:
        mtx = self.mediamtx_restart(config)
        if config.mediamtx.control_mode == 'external':
            self.reconcile(config, force_restart=True)
        return {"mediamtx": mtx}

    def restart_camera(self, config: RuntimeConfig, camera_id: str) -> bool:
        with self._lock:
            if not self._monitoring_enabled:
                return False
            for camera in config.cameras:
                if camera.id.lower() != camera_id.lower():
                    continue
                key = f"camera:{camera.id.lower()}"
                command = self._camera_command(config, camera)
                self._ensure_process(
                    key=key,
                    kind=f"camera/{camera.type}",
                    command=command,
                    desired=bool(camera.enabled),
                    force_restart=True,
                )
                return True
        return False

    def restart_multiview(self, config: RuntimeConfig) -> bool:
        with self._lock:
            if not self._monitoring_enabled:
                return False
            self._last_config = config
            if not config.multiview.enabled:
                proc = self._processes.get("multiview")
                if proc:
                    self._stop_process(proc)
                return True
            command = self._multiview_command(config)
            self._ensure_process(
                key="multiview",
                kind="multiview",
                command=command,
                desired=True,
                force_restart=True,
            )
            return True

    def exclude_camera_from_multiview(self, camera_id: str, reason: str | None = None) -> bool:
        key = f"camera:{camera_id.strip().lower()}"
        now = time.time()
        with self._lock:
            proc = self._processes.get(key)
            if proc is None:
                return False
            proc.manual_excluded = True
            proc.manual_excluded_since = now
            proc.last_error = reason or "temporarily excluded from multiview"
            self._schedule_multiview_restart(source_key=key, exit_code=None, now=now)
            return True

    def restore_camera_to_multiview(self, camera_id: str) -> bool:
        key = f"camera:{camera_id.strip().lower()}"
        now = time.time()
        with self._lock:
            proc = self._processes.get(key)
            if proc is None:
                return False
            proc.manual_excluded = False
            proc.manual_excluded_since = None
            proc.quarantined = False
            proc.quarantine_since = None
            proc.quarantine_reason = None
            proc.healthcheck_failures = 0
            proc.last_healthcheck_error = None
            if proc.desired and not proc.is_running():
                proc.next_restart_at = min(proc.next_restart_at or now, now + 0.5)
            self._schedule_multiview_restart(source_key=key, exit_code=None, now=now)
            return True

    def process_status(self) -> dict[str, Any]:
        with self._lock:
            items: list[dict[str, Any]] = []
            for key, proc in sorted(self._processes.items(), key=lambda x: x[0]):
                running = proc.is_running()
                pid = proc.process.pid if proc.process else None
                items.append(
                    {
                        "id": key,
                        "kind": proc.kind,
                        "status": "running" if running else ("error" if proc.last_error else "stopped"),
                        "desired": proc.desired,
                        "pid": pid,
                        "started_at": proc.started_at,
                        "restart_count": proc.restart_count,
                        "last_exit_code": proc.last_exit_code,
                        "last_error": proc.last_error,
                        "health_state": proc.health_state(),
                        "healthcheck_failures": proc.healthcheck_failures,
                        "last_healthcheck_at": proc.last_healthcheck_at,
                        "last_healthcheck_error": proc.last_healthcheck_error,
                        "manual_excluded": proc.manual_excluded,
                        "manual_excluded_since": proc.manual_excluded_since,
                        "quarantined": proc.quarantined,
                        "quarantine_since": proc.quarantine_since,
                        "quarantine_reason": proc.quarantine_reason,
                        "command": proc.command_display,
                    }
                )
            return {"items": items}

    def stream_addresses(self, config: RuntimeConfig, path: str) -> dict[str, str]:
        clean_path = path.strip().strip("/")
        return {
            "rtsp_url": _join_url(config.mediamtx.rtsp_base_url, clean_path),
            "webrtc_url": _join_url(config.mediamtx.webrtc_base_url, clean_path),
        }
