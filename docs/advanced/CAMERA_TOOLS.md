# Advanced reference: Camera Tools

[日本語](CAMERA_TOOLS.ja.md)

[Documentation](../README.md) · [Manual installation](../MANUAL_INSTALL.md)

> These are low-level source/development commands, run from the repository root.
> For the packaged application, use the [user guide](../USER_GUIDE.md).
> Standalone MediaMTX retention and service settings do not apply to FlintEye-managed storage.
> Keep listeners on loopback; LAN access uses the authenticated HTTPS proxy described in the [distribution guide](../DISTRIBUTION.md).

## 1. Prerequisites

- Python 3.13+
- `ffmpeg` installed
- MediaMTX RTSP endpoint already prepared (as you noted)

Check `ffmpeg`:

```bash
ffmpeg -version
```

Check that `drawtext` is available:

```bash
ffmpeg -hide_banner -filters | grep drawtext
```

If `drawtext` is missing, install/build ffmpeg with `libfreetype`.


## 2. Script Location

`flinteye_app/workers/uvc_to_rtsp.py`
`flinteye_app/workers/multiview_to_rtsp.py`

Examples below assume your shell is in the repository root.

Run:

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp --help
python3 -m flinteye_app.workers.multiview_to_rtsp --help
```

### Recommended: `.env` based parameter management

Create your runtime config from template:

```bash
# macOS
cp config/examples/.env.example.mac .env

# Linux
# cp config/examples/.env.example.linux .env

# Windows PowerShell
# Copy-Item config/examples/.env.example.windows .env
```

Edit `.env` values, then run with minimal arguments:

```powershell
python -m flinteye_app.workers.uvc_to_rtsp
```

For multi-UVC setups, use profile-based keys:

- Shared defaults: `UVC_*`
- Per-camera override: `UVC_<PROFILE>_*` (example: `UVC_CAM1_*`, `UVC_CAM2_*`)

Run each camera in its own process:

```powershell
python -m flinteye_app.workers.uvc_to_rtsp --profile cam1
python -m flinteye_app.workers.uvc_to_rtsp --profile cam2
```

Useful switches:

- `--env-file path/to/file.env`: use a specific env file
- `--no-env`: ignore `.env` and use CLI/defaults only
- `--profile cam1`: load `UVC_CAM1_*` first, then fallback to `UVC_*`

Priority order:

- CLI args > `.env` > built-in defaults


## 3. Linux (v4l2)

### Find camera device

```bash
ls /dev/video*
```

Optional (if `v4l2-ctl` is installed):

```bash
v4l2-ctl --list-devices
```

### Run

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --input-driver v4l2 \
  --device /dev/video0 \
  --camera-name "CAM-LINUX-01" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" \
  --width 1280 \
  --height 720 \
  --fps 30 \
  --input-format mjpeg
```


## 4. macOS (avfoundation)

### List camera devices

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

Use either index format (example: `0:none`) or device name format (example: `FaceTime HD Camera:none`).

### Run

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --input-driver avfoundation \
  --device "0:none" \
  --camera-name "CAM-MAC-01" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" \
  --width 1280 \
  --height 720 \
  --fps 30
```


## 5. Windows (dshow)

### List camera devices

```powershell
ffmpeg -list_devices true -f dshow -i dummy
```

Use the device name shown in the output.

### Run

```powershell
python -m flinteye_app.workers.uvc_to_rtsp `
  --input-driver dshow `
  --device "Integrated Camera" `
  --camera-name "CAM-WIN-01" `
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" `
  --fontfile "C:/Windows/Fonts/arial.ttf" `
  --rtbufsize 256M `
  --width 1280 `
  --height 720 `
  --fps 30
```

Notes for dshow:

- You can pass `--device "video=Integrated Camera"` explicitly.
- If `video=` is omitted, the script adds it automatically.
- If your ffmpeg prints a `Fontconfig` error, explicitly set `--fontfile`.
- On Windows, `--fontfile` with drive letters is normalized internally (for example `C:/Windows/Fonts/arial.ttf` -> `/Windows/Fonts/arial.ttf`).


## 6. Useful Options

- `--env-file PATH`: load runtime settings from env file (default `.env`)
- `--no-env`: ignore env file values
- `--profile NAME`: use profile-specific env keys (`UVC_<NAME>_*`)
- `--encoder auto` (default): pick available H.264 encoder automatically
- `--latency-preset low`: apply low-latency tuning (smaller buffers and low-delay flags)
- `--quality-preset high|standard|low`: apply bitrate preset (`high=4M`, `standard=2M`, `low=1M`)
- `--encoder libx264`: force software encode
- `--font-size 28`: change overlay text size
- `--fontfile /path/to/font.ttf`: specify a font file explicitly
- `--rtbufsize 256M`: increase realtime input buffer (effective for dshow)
- `--bframes 0`: keep B-frames disabled (required for MediaMTX WebRTC)
- `--dry-run`: print generated ffmpeg command and exit

When `--encoder auto` is used, the script tries platform-specific hardware encoders and falls back automatically.

- Windows order: `h264_qsv` -> `h264_amf` -> `h264_nvenc` -> `libx264`
- macOS order: `h264_videotoolbox` -> `libx264`
- Linux order: `h264_v4l2m2m` -> `h264_nvenc` -> `h264_qsv` -> `h264_amf` -> `libx264`

Preset guidance:

- `high`: `bitrate=4M`, `maxrate=4M`, `bufsize=8M` (recommended starting point for 1080p)
- `standard`: `bitrate=2M`, `maxrate=2M`, `bufsize=4M` (recommended starting point for 720p)
- `low`: `bitrate=1M`, `maxrate=1M`, `bufsize=2M` (bandwidth-saving profile)
- Manual options (`--bitrate`, `--maxrate`, `--bufsize`) override preset values.

Latency guidance:

- `--latency-preset low` reduces defaults (`thread_queue_size`, `gop`, `rtbufsize`) and enables low-delay ffmpeg flags.
- In `low` mode, `thread_queue_size` is reduced to `32` to limit queue-based delay growth.
- In `low` mode, wallclock timestamps and `genpts` are enabled, and RTSP mux delay is forced to `0`.
- This can reduce delay, but too small buffers may increase frame drops on slow machines.

Dry run example:

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-TEST" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" \
  --dry-run
```

Preset examples:

```bash
# 1080p / high quality
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-HIGH" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam_high" \
  --width 1920 --height 1080 \
  --quality-preset high
```

```bash
# 720p / standard quality
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-STD" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam_std" \
  --width 1280 --height 720 \
  --quality-preset standard
```

```bash
# 720p / standard quality + low latency
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-STD-LL" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam_std_ll" \
  --width 1280 --height 720 \
  --quality-preset standard \
  --latency-preset low
```


## 7. Troubleshooting

- `drawtext` error: install ffmpeg with `libfreetype` support.
- `Fontconfig error: Cannot load default config file` (mostly Windows): pass `--fontfile "C:/Windows/Fonts/arial.ttf"`.
- `Cannot load nvcuda.dll`: NVIDIA runtime is unavailable. Keep `--encoder auto` (script retries Intel/AMD/software encoders) or set `--encoder libx264`.
- `dshow ... real-time buffer ... too full`: increase `--rtbufsize` (for example `--rtbufsize 512M`) or lower `--fps`/resolution.
- Camera not found: re-check device listing commands in your OS section.
- High latency: reduce `--gop`, resolution, or bitrate.
- Apple Silicon note (GPU vs CPU): when running multiple UVC encoders plus multiview, `h264_videotoolbox` can show timestamp instability (`Non-monotonic DTS`) and become slower than software. In that case set `UVC_ENCODER=libx264` and `MV_ENCODER=libx264` (and optionally `UVC_LATENCY_PRESET=normal`, `MV_LATENCY_PRESET=normal`) for more stable low-latency behavior. Monitor CPU usage when using software encoding.
- Keep RTSP transport as TCP (already set in script).
- Live View thumbnail note: the UI already uses the API snapshot endpoint (`GET /api/v1/cameras/{camera_id}/snapshot`) for each camera. Manual one-by-one API calls can look more stable only because they reduce concurrent snapshot load.
- If `/snapshot` or Live View thumbnails fail sporadically, first increase `SNAPSHOT_TIMEOUT_SEC` (for example `3.0` -> `8.0`). Snapshot capture waits for a decodable frame; long GOP / slow keyframes / unstable IP cameras can exceed the timeout.
