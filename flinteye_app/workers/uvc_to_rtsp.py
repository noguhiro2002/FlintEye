#!/usr/bin/env python3
"""UVC webcam to RTSP (MediaMTX) sender with drawtext overlays."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
from flinteye_app.process_lifetime import run_background
from flinteye_app.subprocess_utils import background_process_options
import sys


WINDOWS_ENCODERS = [
    "h264_qsv",
    "h264_amf",
    "h264_nvenc",
    "libx264",
]

MACOS_ENCODERS = [
    "h264_videotoolbox",
    "libx264",
]

LINUX_ENCODERS = [
    "h264_v4l2m2m",
    "h264_nvenc",
    "h264_qsv",
    "h264_amf",
    "libx264",
]

DEFAULT_GOP = 60
DEFAULT_THREAD_QUEUE_SIZE = 1024
DEFAULT_RTBUFSIZE = "256M"

DEFAULT_RATE_CONTROL = {
    "bitrate": "4M",
    "maxrate": "4M",
    "bufsize": "8M",
}

QUALITY_PRESETS = {
    "high": {
        "bitrate": "4M",
        "maxrate": "4M",
        "bufsize": "8M",
    },
    "standard": {
        "bitrate": "2M",
        "maxrate": "2M",
        "bufsize": "4M",
    },
    "low": {
        "bitrate": "1M",
        "maxrate": "1M",
        "bufsize": "2M",
    },
}

TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}


def profile_to_env_token(profile: str | None) -> str | None:
    if not profile:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", profile.strip()).strip("_").upper()
    if not normalized:
        raise ValueError(f"Invalid profile name: '{profile}'")
    return normalized


def load_env_file(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return env

    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue

            if len(value) >= 2 and (
                (value[0] == "'" and value[-1] == "'")
                or (value[0] == '"' and value[-1] == '"')
            ):
                value = value[1:-1]
            env[key] = value
    return env


def parse_env_int(value: str, key: str) -> int:
    try:
        return int(value)
    except ValueError as e:
        raise ValueError(f"{key} must be an integer: '{value}'") from e


def parse_env_bool(value: str, key: str) -> bool:
    lowered = value.strip().lower()
    if lowered in TRUTHY_VALUES:
        return True
    if lowered in FALSY_VALUES:
        return False
    raise ValueError(f"{key} must be one of {sorted(TRUTHY_VALUES | FALSY_VALUES)}: '{value}'")


def run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return run_background(cmd, **background_process_options(), capture_output=True, text=True, check=False)


def get_available_encoders(ffmpeg_bin: str) -> set[str]:
    result = run_capture([ffmpeg_bin, "-hide_banner", "-encoders"])
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    encoders: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        m = re.match(r"^[A-Z\.]{6}\s+([^\s]+)\s+", line)
        if m:
            encoders.add(m.group(1))
    return encoders


def has_drawtext_filter(ffmpeg_bin: str) -> bool:
    result = run_capture([ffmpeg_bin, "-hide_banner", "-filters"])
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    return re.search(r"\bdrawtext\b", text) is not None


def preferred_encoders_for_platform() -> list[str]:
    if sys.platform.startswith("win"):
        return WINDOWS_ENCODERS
    if sys.platform == "darwin":
        return MACOS_ENCODERS
    if sys.platform.startswith("linux"):
        return LINUX_ENCODERS
    return LINUX_ENCODERS


def build_encoder_candidates(available: set[str], requested: str) -> list[str]:
    if requested != "auto":
        if requested not in available:
            raise ValueError(
                f"Requested encoder '{requested}' is not available in this ffmpeg build."
            )
        return [requested]

    candidates = [enc for enc in preferred_encoders_for_platform() if enc in available]
    if not candidates:
        raise ValueError("No supported H.264 encoder found in this ffmpeg build.")
    return candidates


def resolve_rate_control(args: argparse.Namespace) -> None:
    if args.quality_preset:
        values = QUALITY_PRESETS[args.quality_preset].copy()
    else:
        values = DEFAULT_RATE_CONTROL.copy()

    if args.bitrate is not None:
        values["bitrate"] = args.bitrate
    if args.maxrate is not None:
        values["maxrate"] = args.maxrate
    if args.bufsize is not None:
        values["bufsize"] = args.bufsize

    args.bitrate = values["bitrate"]
    args.maxrate = values["maxrate"]
    args.bufsize = values["bufsize"]


def apply_latency_preset(args: argparse.Namespace) -> None:
    if args.latency_preset != "low":
        return

    # Only override common defaults; explicit user values still win.
    if args.thread_queue_size == DEFAULT_THREAD_QUEUE_SIZE:
        args.thread_queue_size = 32
    if args.gop == DEFAULT_GOP:
        args.gop = max(10, min(args.fps, 30))
    if args.rtbufsize == DEFAULT_RTBUFSIZE:
        args.rtbufsize = "8M"

    # Keep VBV tighter for latency when default quality profiles are used.
    if args.bufsize == "8M" and args.maxrate == "4M":
        args.bufsize = "4M"
    elif args.bufsize == "4M" and args.maxrate == "2M":
        args.bufsize = "2M"
    elif args.bufsize == "2M" and args.maxrate == "1M":
        args.bufsize = "1M"


def pick_input_driver(requested: str) -> str:
    if requested != "auto":
        return requested
    if sys.platform.startswith("linux"):
        return "v4l2"
    if sys.platform == "darwin":
        return "avfoundation"
    if sys.platform.startswith("win"):
        return "dshow"
    raise ValueError(f"Unsupported platform for auto input driver: {sys.platform}")


def default_device_for_driver(driver: str) -> str:
    if driver == "v4l2":
        return "/dev/video0"
    if driver == "avfoundation":
        # avfoundation format: "<video_index_or_name>:<audio_index_or_name>"
        return "0:none"
    if driver == "dshow":
        # dshow input string: video="device name"
        return "Integrated Camera"
    raise ValueError(f"Unsupported input driver: {driver}")


def find_default_fontfile() -> str | None:
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        win_root = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
        candidates = [
            os.path.join(win_root, "Fonts", "arial.ttf"),
            os.path.join(win_root, "Fonts", "segoeui.ttf"),
            os.path.join(win_root, "Fonts", "msgothic.ttc"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ]
    elif sys.platform.startswith("linux"):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def normalize_fontfile_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if not sys.platform.startswith("win"):
        return normalized

    # Avoid drive-letter syntax in drawtext (e.g. C:/...), which is fragile in
    # filter option parsing on Windows builds. Convert to /... on system drive.
    m = re.match(r"^([A-Za-z]):/(.*)$", normalized)
    if not m:
        return normalized

    sys_root = (os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows").replace("\\", "/")
    sys_drive = re.match(r"^([A-Za-z]):/", sys_root)
    if sys_drive and m.group(1).lower() == sys_drive.group(1).lower():
        return "/" + m.group(2)
    return normalized


def escape_drawtext_text(value: str) -> str:
    # drawtext's text= value parser treats these chars specially.
    return (
        value.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def escape_filter_value(value: str) -> str:
    value = normalize_fontfile_path(value)
    # drawtext treats ':' as option delimiters even inside quoted values.
    # Keep fontfile single-quoted and escape delimiters explicitly.
    return (
        value.replace("\\", r"\\")
        .replace(":", r"\\:")
        .replace(",", r"\\,")
        .replace("'", r"\'")
    )


def format_cmd_for_display(cmd: list[str]) -> str:
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(cmd)
    return " ".join(shlex.quote(part) for part in cmd)


def build_filter(camera_name: str, font_size: int, fontfile: str | None) -> str:
    common = [f"fontsize={font_size}", "fontcolor=white", "shadowcolor=black", "shadowx=2", "shadowy=2"]
    fontopt: list[str] = []
    if fontfile:
        fontopt.append(f"fontfile='{escape_filter_value(fontfile)}'")

    # Use localtime() without %T for better Windows compatibility.
    # Build HH:MM:SS with three expansions to avoid formatter differences.
    time_text = r"%{localtime\:%Y/%m/%d %H}\:%{localtime\:%M}\:%{localtime\:%S}"

    dt_time = "drawtext=" + ":".join(
        fontopt + [f"text='{time_text}'", "x=20", "y=20"] + common
    )
    cam_name = escape_drawtext_text(camera_name)
    dt_cam = "drawtext=" + ":".join(
        fontopt
        + [f"text='{cam_name}'", "expansion=none", "x=w-tw-20", "y=20"]
        + common
    )
    return f"{dt_time},{dt_cam}"


def preferred_pix_fmt_for_encoder(encoder: str) -> str:
    if encoder in {"h264_qsv", "h264_amf"}:
        return "nv12"
    return "yuv420p"


def build_input_args(args: argparse.Namespace, driver: str) -> list[str]:
    device = args.device or default_device_for_driver(driver)

    input_args = [
        "-f",
        driver,
        "-thread_queue_size",
        str(args.thread_queue_size),
    ]
    if args.latency_preset == "low":
        input_args += ["-use_wallclock_as_timestamps", "1"]

    if args.width and args.height:
        input_args += ["-video_size", f"{args.width}x{args.height}"]
    if args.fps:
        input_args += ["-framerate", str(args.fps)]

    if args.input_format:
        if driver == "v4l2":
            input_args += ["-input_format", args.input_format]
        else:
            input_args += ["-pixel_format", args.input_format]
    if driver == "dshow" and args.rtbufsize:
        input_args += ["-rtbufsize", args.rtbufsize]

    if driver == "dshow":
        lowered = device.lower()
        if not lowered.startswith("video=") and not lowered.startswith("audio="):
            device = f"video={device}"

    input_args += ["-i", device]
    return input_args


def build_cmd(args: argparse.Namespace, encoder: str, input_driver: str) -> list[str]:
    vf = build_filter(args.camera_name, args.font_size, args.fontfile)
    pix_fmt = preferred_pix_fmt_for_encoder(encoder)

    cmd = [
        args.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        args.loglevel,
    ]
    if args.latency_preset == "low":
        cmd += ["-fflags", "+genpts+nobuffer", "-flags", "low_delay"]

    cmd += build_input_args(args, input_driver)
    cmd += ["-an", "-vf", vf, "-pix_fmt", pix_fmt, "-c:v", encoder]
    cmd += ["-bf", str(args.bframes)]

    if encoder == "libx264":
        cmd += ["-preset", args.x264_preset, "-tune", "zerolatency"]

    cmd += [
        "-b:v",
        args.bitrate,
        "-maxrate",
        args.maxrate,
        "-bufsize",
        args.bufsize,
        "-g",
        str(args.gop),
        "-flush_packets",
        "1",
        "-muxdelay",
        "0",
        "-muxpreload",
        "0",
        "-rtsp_transport",
        "tcp",
        "-f",
        "rtsp",
        args.rtsp_url,
    ]
    return cmd


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", default=".env")
    pre.add_argument("--no-env", action="store_true")
    pre.add_argument("--profile")
    pre_args, _ = pre.parse_known_args(argv)

    env_values: dict[str, str] = {}
    env_path = pre_args.env_file
    env_loaded_path: str | None = None
    if not pre_args.no_env and env_path:
        if os.path.isfile(env_path):
            env_values = load_env_file(env_path)
            env_loaded_path = env_path
        elif env_path != ".env":
            raise SystemExit(f"env file not found: {env_path}")

    selected_profile = pre_args.profile
    if not selected_profile and env_values.get("UVC_PROFILE"):
        selected_profile = env_values["UVC_PROFILE"].strip()
    try:
        selected_profile_token = profile_to_env_token(selected_profile)
    except ValueError as e:
        raise SystemExit(str(e)) from e

    p = argparse.ArgumentParser(
        description="Capture UVC webcam, overlay timestamp/camera name, and publish RTSP."
    )
    p.add_argument("--env-file", default=env_path, help="Path to .env file (default: .env)")
    p.add_argument("--no-env", action="store_true", help="Ignore .env values")
    p.add_argument(
        "--profile",
        default=selected_profile,
        help="Camera profile name for .env keys (uses UVC_<PROFILE>_* before UVC_*)",
    )
    p.add_argument(
        "--input-driver",
        choices=["auto", "v4l2", "avfoundation", "dshow"],
        default="auto",
        help="Input backend: auto, v4l2 (Linux), avfoundation (macOS), dshow (Windows)",
    )
    p.add_argument(
        "--device",
        help=(
            "Input device identifier. Examples: /dev/video0 (v4l2), "
            "0:none or CameraName:none (avfoundation), "
            "Integrated Camera or video=Integrated Camera (dshow)"
        ),
    )
    p.add_argument("--camera-name", help="Label shown at top-right (or UVC_CAMERA_NAME in .env)")
    p.add_argument("--rtsp-url", help="RTSP URL served by MediaMTX (or UVC_RTSP_URL in .env)")
    p.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg binary path/name")
    p.add_argument("--loglevel", default="error", help="ffmpeg loglevel (error, warning, info, debug, ...)")
    p.add_argument("--encoder", default="auto", help="H.264 encoder name or 'auto'")
    p.add_argument(
        "--latency-preset",
        choices=["low"],
        help="Latency preset: low (smaller buffers and low-delay flags)",
    )
    p.add_argument(
        "--quality-preset",
        choices=["high", "standard", "low"],
        help="Rate-control preset: high (4M), standard (2M), low (1M)",
    )
    p.add_argument("--width", type=int, help="Capture width")
    p.add_argument("--height", type=int, help="Capture height")
    p.add_argument("--fps", type=int, default=30, help="Capture framerate")
    p.add_argument(
        "--input-format",
        help="Input pixel format (v4l2: input_format, avfoundation/dshow: pixel_format)",
    )
    p.add_argument(
        "--rtbufsize",
        default=DEFAULT_RTBUFSIZE,
        help="Input realtime buffer size (mainly for dshow, e.g. 128M, 256M)",
    )
    p.add_argument("--bitrate", help="Target video bitrate")
    p.add_argument("--maxrate", help="Rate control maxrate")
    p.add_argument("--bufsize", help="Rate control buffer size")
    p.add_argument("--gop", type=int, default=DEFAULT_GOP, help="GOP size")
    p.add_argument("--thread-queue-size", type=int, default=DEFAULT_THREAD_QUEUE_SIZE, help="Input queue size")
    p.add_argument(
        "--bframes",
        type=int,
        default=0,
        help="Number of B-frames (default 0 for WebRTC compatibility)",
    )
    p.add_argument("--font-size", type=int, default=28, help="Overlay font size")
    p.add_argument("--fontfile", help="Optional font file path for drawtext")
    p.add_argument("--x264-preset", default="veryfast", help="Preset when using libx264")
    p.add_argument("--dry-run", action="store_true", help="Print command and exit")

    env_defaults: dict[str, object] = {}
    env_errors: list[str] = []

    def env_value(suffix: str) -> str | None:
        keys: list[str] = []
        if selected_profile_token:
            keys.append(f"UVC_{selected_profile_token}_{suffix}")
        keys.append(f"UVC_{suffix}")
        for key in keys:
            if key in env_values:
                return env_values[key]
        return None

    def env_str(dest: str, suffix: str) -> None:
        value = env_value(suffix)
        if value is not None:
            env_defaults[dest] = value

    def env_int(dest: str, suffix: str) -> None:
        value = env_value(suffix)
        if value is not None:
            key = f"UVC_{suffix}" if not selected_profile_token else f"UVC_{selected_profile_token}_{suffix} / UVC_{suffix}"
            try:
                env_defaults[dest] = parse_env_int(value, key)
            except ValueError as e:
                env_errors.append(str(e))

    def env_bool(dest: str, suffix: str) -> None:
        value = env_value(suffix)
        if value is not None:
            key = f"UVC_{suffix}" if not selected_profile_token else f"UVC_{selected_profile_token}_{suffix} / UVC_{suffix}"
            try:
                env_defaults[dest] = parse_env_bool(value, key)
            except ValueError as e:
                env_errors.append(str(e))

    env_str("input_driver", "INPUT_DRIVER")
    env_str("device", "DEVICE")
    env_str("camera_name", "CAMERA_NAME")
    env_str("rtsp_url", "RTSP_URL")
    env_str("ffmpeg_bin", "FFMPEG_BIN")
    env_str("loglevel", "LOGLEVEL")
    env_str("encoder", "ENCODER")
    env_str("latency_preset", "LATENCY_PRESET")
    env_str("quality_preset", "QUALITY_PRESET")
    env_int("width", "WIDTH")
    env_int("height", "HEIGHT")
    env_int("fps", "FPS")
    env_str("input_format", "INPUT_FORMAT")
    env_str("rtbufsize", "RTBUFSIZE")
    env_str("bitrate", "BITRATE")
    env_str("maxrate", "MAXRATE")
    env_str("bufsize", "BUFSIZE")
    env_int("gop", "GOP")
    env_int("thread_queue_size", "THREAD_QUEUE_SIZE")
    env_int("bframes", "BFRAMES")
    env_int("font_size", "FONT_SIZE")
    env_str("fontfile", "FONTFILE")
    env_str("x264_preset", "X264_PRESET")
    env_bool("dry_run", "DRY_RUN")

    if env_errors:
        p.error("; ".join(env_errors))
    if env_defaults:
        p.set_defaults(**env_defaults)

    args = p.parse_args(argv)
    args.env_loaded_path = None if args.no_env else env_loaded_path
    try:
        args.profile_env_token = profile_to_env_token(args.profile)
    except ValueError as e:
        p.error(str(e))

    if not args.camera_name:
        p.error(
            "argument --camera-name is required "
            "(or set UVC_CAMERA_NAME / UVC_<PROFILE>_CAMERA_NAME in .env)"
        )
    if not args.rtsp_url:
        p.error(
            "argument --rtsp-url is required "
            "(or set UVC_RTSP_URL / UVC_<PROFILE>_RTSP_URL in .env)"
        )
    return args


def main() -> int:
    args = parse_args()
    resolve_rate_control(args)
    apply_latency_preset(args)

    try:
        available = get_available_encoders(args.ffmpeg_bin)
    except FileNotFoundError:
        print(f"ffmpeg binary not found: {args.ffmpeg_bin}", file=sys.stderr)
        return 127

    if not has_drawtext_filter(args.ffmpeg_bin):
        msg = (
            "Your ffmpeg build does not include drawtext. Rebuild/install ffmpeg with "
            "libfreetype (and optionally fontconfig)."
        )
        if args.dry_run:
            print(f"[warn] {msg}", file=sys.stderr)
        else:
            print(msg, file=sys.stderr)
            return 2

    try:
        input_driver = pick_input_driver(args.input_driver)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not args.fontfile:
        auto_font = find_default_fontfile()
        if auto_font:
            args.fontfile = auto_font
            print(f"[info] using fontfile: {auto_font}", file=sys.stderr)
        elif sys.platform.startswith("win"):
            print(
                "[warn] No default font found. If drawtext fails, pass "
                "--fontfile C:\\Windows\\Fonts\\arial.ttf",
                file=sys.stderr,
            )

    try:
        encoder_candidates = build_encoder_candidates(available, args.encoder)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    initial_encoder = encoder_candidates[0]
    initial_cmd = build_cmd(args, initial_encoder, input_driver)

    if args.env_loaded_path:
        print(f"[info] loaded env file: {args.env_loaded_path}", file=sys.stderr)
    if args.profile:
        print(f"[info] profile: {args.profile}", file=sys.stderr)
    print(f"[info] input driver: {input_driver}", file=sys.stderr)
    if args.quality_preset:
        print(f"[info] quality preset: {args.quality_preset}", file=sys.stderr)
    if args.latency_preset:
        print(f"[info] latency preset: {args.latency_preset}", file=sys.stderr)
    print(
        f"[info] rate control: bitrate={args.bitrate} maxrate={args.maxrate} bufsize={args.bufsize}",
        file=sys.stderr,
    )
    print(f"[info] selected encoder: {initial_encoder}", file=sys.stderr)
    if args.encoder == "auto":
        print(f"[info] auto candidates: {', '.join(encoder_candidates)}", file=sys.stderr)
    print("[info] ffmpeg command:", file=sys.stderr)
    print(format_cmd_for_display(initial_cmd), file=sys.stderr)

    if args.dry_run:
        return 0

    try:
        for idx, encoder in enumerate(encoder_candidates):
            cmd = initial_cmd if idx == 0 else build_cmd(args, encoder, input_driver)
            if idx > 0:
                print(f"[warn] retrying with encoder '{encoder}'", file=sys.stderr)
                print("[info] fallback ffmpeg command:", file=sys.stderr)
                print(format_cmd_for_display(cmd), file=sys.stderr)

            result = run_background(cmd, **background_process_options(), check=False)
            if result.returncode == 0:
                return 0

            if args.encoder != "auto":
                return result.returncode

            print(
                f"[warn] encoder '{encoder}' failed (exit={result.returncode})",
                file=sys.stderr,
            )

        return result.returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
