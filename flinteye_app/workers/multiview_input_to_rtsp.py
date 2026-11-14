from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from flinteye_app.process_lifetime import popen_background
from flinteye_app.subprocess_utils import background_process_options
import sys
import threading
import time
from typing import Any
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse

from flinteye_app.orchestrator_ip_camera_probe import _hosts_match, probe_onvif
from flinteye_app.flinteye_runtime import load_worker_secrets, private_media_input_command
from flinteye_app.workers.multiview_to_rtsp import detect_input_stall_timeout_option, probe_input_stall_timeout_option


URL_CREDENTIALS_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)
QUALITY_CRF = {"high": 20, "standard": 23, "low": 28}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def select_onvif_profile(
    profiles: list[dict[str, Any]],
    *,
    target_width: int,
    target_height: int,
    target_fps: int,
    profile_token: str | None = None,
) -> dict[str, Any] | None:
    usable = [
        profile
        for profile in profiles
        if profile.get("stream_uri")
        and str(profile.get("encoding") or "").lower() not in {"jpeg", "mjpeg"}
    ]
    if profile_token:
        return next((item for item in usable if str(item.get("token")) == profile_token), None)
    if not usable:
        return None

    target_pixels = max(1, target_width * target_height)

    def rank(profile: dict[str, Any]) -> tuple[Any, ...]:
        width = int(_number(profile.get("width")))
        height = int(_number(profile.get("height")))
        pixels = max(1, width * height)
        fps = _number(profile.get("fps"))
        adequate_size = pixels >= target_pixels
        adequate_fps = fps >= target_fps
        encoding = str(profile.get("encoding") or "").lower()
        bitrate = _number(profile.get("bitrate_kbps"), float("inf"))
        return (
            0 if adequate_fps else 1,
            0 if adequate_size else 1,
            pixels if adequate_size else -pixels,
            bitrate,
            0 if encoding in {"h264", "avc"} else 1,
        )

    return min(usable, key=rank)


def _inject_source_credentials(uri: str, source_url: str) -> str:
    parsed = urlparse(uri)
    source = urlparse(source_url)
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname or not source.hostname:
        raise ValueError("ONVIF stream URL must use RTSP and include the configured camera host")
    if not _hosts_match(source.hostname, parsed.hostname):
        raise ValueError("ONVIF stream URL points to a different camera host")
    credential_source = parsed if parsed.username is not None else source
    credentials = ""
    if credential_source.username is not None:
        credentials = quote(unquote(credential_source.username), safe="")
        if credential_source.password is not None:
            credentials += ":" + quote(unquote(credential_source.password), safe="")
        credentials += "@"
    # Keep the trusted host at the use site, including when the advertised alias
    # passed a DNS-address comparison. This closes DNS rebinding after validation.
    host = source.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{credentials}{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def resolve_preferred_source(args: argparse.Namespace) -> tuple[str | None, str | None]:
    if args.mode == "manual":
        return args.manual_url, None if args.manual_url else "Manual URL is missing"
    if args.mode != "onvif":
        return args.primary_url, None
    result = probe_onvif(
        args.camera_source_url,
        mode=args.onvif_mode,
        address=args.onvif_address,
        username=args.onvif_username,
        password=args.onvif_password,
        timeout_sec=max(1.0, min(args.stall_timeout_sec, 5.0)),
    )
    profiles = list(result.get("profiles") or [])
    if not args.profile_token:
        main_path = urlparse(args.camera_source_url).path.rstrip("/").lower()
        profiles = [
            profile
            for profile in profiles
            if urlparse(str(profile.get("stream_uri") or "")).path.rstrip("/").lower() != main_path
        ]
    profile = select_onvif_profile(
        profiles,
        target_width=args.width,
        target_height=args.height,
        target_fps=args.fps,
        profile_token=args.profile_token,
    )
    if not profile:
        return None, str(result.get("message") or "No usable ONVIF video profile")
    try:
        return _inject_source_credentials(str(profile["stream_uri"]), args.camera_source_url), None
    except ValueError as error:
        return None, str(error)


def build_command(args: argparse.Namespace, source_url: str) -> list[str]:
    filter_parts = [
        f"fps={args.fps}:round=down",
        "settb=AVTB",
        f"setpts=N/({args.fps}*TB)",
    ]
    if args.width > 0 and args.height > 0:
        filter_parts.extend(
            [
                f"scale=w='min(iw,{args.width})':h='min(ih,{args.height})':force_original_aspect_ratio=decrease",
                f"pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2:color=black",
            ]
        )
    command = [
        args.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        args.loglevel,
    ]
    if args.stall_timeout_arg and args.stall_timeout_sec > 0:
        command += [f"-{args.stall_timeout_arg}", str(int(args.stall_timeout_sec * 1_000_000))]
    command += [
        "-thread_queue_size",
        str(args.thread_queue_size),
        "-rtsp_transport",
        "tcp",
        "-use_wallclock_as_timestamps",
        "1",
        "-i",
        source_url,
        "-an",
        "-vf",
        ",".join(filter_parts),
        "-c:v",
        args.encoder,
    ]
    if args.encoder in {"libx264", "libx265"}:
        command += [
            "-preset",
            args.x264_preset,
            "-crf",
            str(QUALITY_CRF[args.quality_preset]),
        ]
    command += [
        "-b:v",
        args.bitrate,
        "-maxrate",
        args.maxrate,
        "-bufsize",
        args.bufsize,
        "-g",
        str(max(args.fps * 2, 1)),
        "-bf",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        args.output_url,
    ]
    return command


def _redact_log_line(args: argparse.Namespace, line: str, source_url: str = "") -> str:
    if source_url:
        line = line.replace(source_url, "<camera-source>")
    redacted = URL_CREDENTIALS_RE.sub(lambda match: match.group("scheme") + "***@", line)
    secrets = [
        args.onvif_password,
        urlparse(args.camera_source_url).password,
        urlparse(args.manual_url or "").password,
        urlparse(args.primary_url).password,
        urlparse(source_url).password,
    ]
    for secret in secrets:
        if secret and len(secret) >= 3:
            redacted = redacted.replace(secret, "***")
    return redacted


def _run(args: argparse.Namespace, source_url: str, *, max_runtime: float | None = None) -> int:
    with private_media_input_command(build_command(args, source_url), source_url, force=source_url != args.primary_url) as safe_command:
        proc = popen_background(
            safe_command, **background_process_options(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return _wait_for_input_process(args, proc, source_url, max_runtime=max_runtime)


def _wait_for_input_process(
    args: argparse.Namespace, proc: subprocess.Popen[str], source_url: str, *, max_runtime: float | None
) -> int:
    if proc.stderr is not None:
        stderr = proc.stderr

        def forward_stderr() -> None:
            for line in stderr:
                print(_redact_log_line(args, line.rstrip(), source_url), file=sys.stderr)

        threading.Thread(target=forward_stderr, name="multiview-input-stderr", daemon=True).start()
    started = time.monotonic()
    try:
        while proc.poll() is None:
            if max_runtime is not None and time.monotonic() - started >= max_runtime:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        proc.terminate()
        return 130
    return int(proc.returncode or 0)


def write_status(args: argparse.Namespace, state: str, reason: str | None = None) -> None:
    if not args.status_file:
        return
    path = Path(args.status_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps({"updated_at": time.time(), "state": state, "mode": args.mode, "reason": reason}),
        encoding="utf-8",
    )
    os.replace(temp, path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Normalize one Multiview input without changing its public camera path.")
    p.add_argument("--secret-stdin", action="store_true")
    p.add_argument("--mode", choices=["normalized_primary", "onvif", "manual"], required=True)
    p.add_argument("--primary-url", required=True)
    p.add_argument("--camera-source-url", default="")
    p.add_argument("--manual-url")
    p.add_argument("--profile-token")
    p.add_argument("--onvif-mode", choices=["auto", "manual", "disabled"], default="auto")
    p.add_argument("--onvif-address")
    p.add_argument("--onvif-username")
    p.add_argument("--onvif-password")
    p.add_argument("--output-url", required=True)
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=360)
    p.add_argument("--encoder", default="libx264")
    p.add_argument("--quality-preset", choices=["high", "standard", "low"], default="standard")
    p.add_argument("--bitrate", default="800k")
    p.add_argument("--maxrate", default="1M")
    p.add_argument("--bufsize", default="2M")
    p.add_argument("--x264-preset", default="veryfast")
    p.add_argument("--thread-queue-size", type=int, default=128)
    p.add_argument("--stall-timeout-sec", type=float, default=15.0)
    p.add_argument("--stall-timeout-option", choices=["auto", "rw_timeout", "stimeout", "timeout", "none"], default="auto")
    p.add_argument("--preferred-retry-sec", type=float, default=300.0)
    p.add_argument("--fallback-to-primary", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--ffmpeg-bin", default="ffmpeg")
    p.add_argument("--loglevel", default="error")
    p.add_argument("--status-file")
    return load_worker_secrets(p.parse_args())


def main() -> int:
    args = parse_args()
    if args.stall_timeout_option == "auto":
        args.stall_timeout_arg = detect_input_stall_timeout_option(args.ffmpeg_bin)
    elif args.stall_timeout_option == "none":
        args.stall_timeout_arg = None
    else:
        args.stall_timeout_arg = (
            args.stall_timeout_option
            if probe_input_stall_timeout_option(args.ffmpeg_bin, args.stall_timeout_option)
            else None
        )
    while True:
        preferred, error = resolve_preferred_source(args)
        if preferred:
            write_status(args, "preferred")
            print(f"[info] multiview input mode={args.mode} preferred source selected", file=sys.stderr)
            code = _run(args, preferred)
            if code == 130:
                return code
            print(f"[warn] preferred multiview input exited with code {code}", file=sys.stderr)
        elif error:
            write_status(args, "degraded", error)
            print(f"[warn] preferred multiview input unavailable: {error}", file=sys.stderr)

        if not args.fallback_to_primary or args.mode == "normalized_primary":
            time.sleep(3)
            continue
        print("[warn] using the existing MediaMTX main path as Multiview fallback", file=sys.stderr)
        write_status(args, "fallback", error or "Preferred input exited")
        code = _run(args, args.primary_url, max_runtime=args.preferred_retry_sec)
        if code == 130:
            return code
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
