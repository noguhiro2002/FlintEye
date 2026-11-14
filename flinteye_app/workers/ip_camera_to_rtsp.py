from __future__ import annotations

import argparse
import subprocess
from flinteye_app.process_lifetime import popen_background
from flinteye_app.subprocess_utils import background_process_options
import sys
from typing import Any

from flinteye_app.orchestrator_ip_camera_probe import IpCameraProbeError, probe_rtsp_timing
from flinteye_app.flinteye_runtime import load_worker_secrets, private_media_input_command


TIMESTAMP_MODES = {"auto", "source", "wallclock", "cfr"}
RELAY_MODES = {"copy", "libx264"}


def _fps_text(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 0.0001:
        return str(rounded)
    return f"{value:.3f}".rstrip("0").rstrip(".")


def resolve_timestamp_mode(args: argparse.Namespace) -> tuple[str, float, dict[str, Any] | None]:
    if args.timestamp_mode != "auto":
        return args.timestamp_mode, args.cfr_fps, None
    try:
        result = probe_rtsp_timing(
            args.source_url,
            ffprobe_bin=args.ffprobe_bin,
            duration_sec=args.probe_duration_sec,
        )
    except IpCameraProbeError as exc:
        print(f"[warn] automatic timestamp probe failed; using wallclock: {exc}", file=sys.stderr)
        return "wallclock", args.cfr_fps, None
    mode = str(result.get("recommended_timestamp_mode") or "wallclock")
    detected_fps = float(result.get("recommended_cfr_fps") or args.cfr_fps)
    print(
        "[info] timestamp probe: "
        f"mode={mode}, fps={detected_fps:g}, nonpositive={result.get('nonpositive_delta_count')}, "
        f"large_gaps={result.get('large_gap_count')}, decode_errors={result.get('decode_error_count')}",
        file=sys.stderr,
    )
    return mode, detected_fps, result


def build_ffmpeg_command(args: argparse.Namespace, *, timestamp_mode: str, cfr_fps: float) -> list[str]:
    cmd = [
        args.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        args.loglevel,
        "-rtsp_transport",
        "tcp",
    ]
    if timestamp_mode in {"wallclock", "cfr"}:
        cmd += ["-use_wallclock_as_timestamps", "1", "-fflags", "+genpts"]
    else:
        cmd += ["-fflags", "+genpts+nobuffer"]
    cmd += ["-i", args.source_url, "-an"]

    must_encode = args.relay_mode == "libx264" or timestamp_mode == "cfr"
    if timestamp_mode == "cfr":
        fps = _fps_text(cfr_fps)
        cmd += [
            "-vf",
            f"fps={fps},settb=AVTB,setpts=N/({fps}*TB)",
            "-fps_mode",
            "cfr",
        ]
    if must_encode:
        cmd += [
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-bf",
            "0",
            "-preset",
            args.x264_preset,
            "-tune",
            "zerolatency",
            "-b:v",
            args.bitrate,
            "-maxrate",
            args.maxrate,
            "-bufsize",
            args.bufsize,
            "-g",
            str(args.gop),
        ]
    else:
        cmd += ["-c:v", "copy"]

    cmd += [
        "-avoid_negative_ts",
        "make_zero",
        "-flush_packets",
        "1",
        "-muxdelay",
        "0",
        "-rtsp_transport",
        "tcp",
        "-f",
        "rtsp",
        args.rtsp_url,
    ]
    return cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize an IP camera stream and publish it to RTSP")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--secret-stdin", action="store_true")
    parser.add_argument("--rtsp-url", required=True)
    parser.add_argument("--relay-mode", choices=sorted(RELAY_MODES), default="copy")
    parser.add_argument("--timestamp-mode", choices=sorted(TIMESTAMP_MODES), default="auto")
    parser.add_argument("--cfr-fps", type=float, default=20.0)
    parser.add_argument("--probe-duration-sec", type=float, default=4.0)
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--ffprobe-bin", default="ffprobe")
    parser.add_argument("--loglevel", default="error")
    parser.add_argument("--bitrate", default="2M")
    parser.add_argument("--maxrate", default="2M")
    parser.add_argument("--bufsize", default="4M")
    parser.add_argument("--gop", type=int, default=40)
    parser.add_argument("--x264-preset", default="veryfast")
    return parser


def main() -> int:
    parser = build_parser()
    args = load_worker_secrets(parser.parse_args())
    if args.cfr_fps <= 0 or args.cfr_fps > 240:
        parser.error("--cfr-fps must be in range 0..240")
    if args.probe_duration_sec <= 0 or args.probe_duration_sec > 30:
        parser.error("--probe-duration-sec must be in range 0..30")
    timestamp_mode, cfr_fps, _ = resolve_timestamp_mode(args)
    command = build_ffmpeg_command(args, timestamp_mode=timestamp_mode, cfr_fps=cfr_fps)
    print(
        f"[info] IP relay: timestamp_mode={timestamp_mode}, relay_mode={args.relay_mode}, cfr_fps={cfr_fps:g}",
        file=sys.stderr,
    )
    try:
        with private_media_input_command(command, args.source_url, force=True) as safe_command:
            with popen_background(safe_command, **background_process_options(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8", errors="replace") as process:
                if process.stderr is not None:
                    for line in process.stderr:
                        print(line.rstrip().replace(args.source_url, "<camera-source>"), file=sys.stderr, flush=True)
                return process.wait()
    except FileNotFoundError:
        print(f"[error] ffmpeg was not found: {args.ffmpeg_bin}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
