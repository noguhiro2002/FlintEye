# Advanced reference: Media Operations

[日本語](MEDIA_OPERATIONS.ja.md)

[Documentation](../README.md) · [Manual installation](../MANUAL_INSTALL.md)

> These are low-level source/development commands, run from the repository root.
> For the packaged application, use the [user guide](../USER_GUIDE.md).
> Standalone MediaMTX retention and service settings do not apply to FlintEye-managed storage.
> Keep listeners on loopback; LAN access uses the authenticated HTTPS proxy described in the [distribution guide](../DISTRIBUTION.md).

## 8. Multi Cam View (FFmpeg Compose)

Compose UVC and IP camera streams already published in MediaMTX into one or more tiled views.

Run:

```powershell
python -m flinteye_app.workers.multiview_to_rtsp --env-file ".env"
```

Key `.env` fields:

- `MV_SOURCE_MODE=hybrid|env|api`
- `MV_SOURCE_PATHS=uvc_cam1,uvc_cam2,ipcam1,...`
- `MV_AUTO_PLACEHOLDER_MISSING_SOURCES=true|false`
- `MV_MTX_API_URL=http://127.0.0.1:9997/v3/paths/list`
- `MV_INPUT_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MV_OUTPUT_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MV_OUTPUT_PREFIX=multiview`
- `MV_TILE_COUNT=4` (2..32)
- `MV_CANVAS_WIDTH`, `MV_CANVAS_HEIGHT`, `MV_GRID_COLUMNS`
- `MV_SLOT_POSITIONS` and optional per-view `MV_VIEW_1_SLOT_POSITIONS`
- `MV_FPS`, `MV_LATENCY_PRESET=low|normal`, `MV_QUALITY_PRESET`, `MV_BITRATE`, `MV_MAXRATE`, `MV_BUFSIZE`, `MV_GOP`, `MV_BFRAMES`
- `MV_INPUT_STALL_TIMEOUT_SEC=15` (set `0` to disable RTSP input stall timeout)
- `MV_INPUT_STALL_TIMEOUT_OPTION=auto|rw_timeout|stimeout|timeout|none`
- `MV_MAINTENANCE_ENABLED=true|false`
- `MV_MAINTENANCE_RESTART_INTERVAL_SEC=43200`
- `MV_MAINTENANCE_ALIGN_WITH_RECORD_SEGMENTS=true|false`
- `MV_MAINTENANCE_RESTART_OFFSET_SEC=2`

Split behavior:

- The script makes pages of `MV_TILE_COUNT` streams each.
- If total cameras are not divisible by tile count, the last view is partially filled.
- Example: `10` cameras with `MV_TILE_COUNT=4` -> `multiview_1` (4), `multiview_2` (4), `multiview_3` (2).

Loop prevention:

- Any source path matching `MV_OUTPUT_PREFIX` or `MV_OUTPUT_PREFIX_*` is excluded automatically.
- This prevents re-ingesting multi view outputs as inputs.

Operational recommendation:

- Keep event-driven restarts enabled through the orchestrator (camera restart -> multiview restart).
- Also enable periodic multiview maintenance restarts.
- Recommended default: restart every `12h`, aligned to recording segment boundaries, with `2s` offset after the boundary.

### 8.1 Multiview stutter / freeze troubleshooting

Symptoms:

- One tile stops for a few seconds, then jumps forward.
- The whole multiview output becomes choppy or "kaku-kaku".
- Some cameras look fine in single-camera Live View, but the same cameras stutter only inside multiview.

Most common causes:

- `MV_LATENCY_PRESET=low` is too aggressive for the source stability. It minimizes buffering, but unstable timestamps or short network stalls become visible as freezes and skips.
- An IP camera uses `MTX_IP_<TOKEN>_RELAY_MODE=copy`, so upstream GOP/timestamp irregularities are passed through directly into multiview.
- Encoder or CPU pressure is too high for the current `MV_FPS`, tile count, and total bitrate.

How to isolate the problem:

1. If the single-camera stream is smooth but only multiview is choppy, suspect multiview compose settings first.
2. If the single-camera stream is already unstable, fix the source publisher first (`flinteye_app/workers/uvc_to_rtsp.py` or the IP relay path).
3. If one tile freezes while others continue, suspect that specific source path.
4. If all tiles freeze together, suspect multiview framesync / encoder / output path.

Recommended mitigation order:

1. In Settings, enable **Raw wall-clock compositor** with `3s` delay, `5s` capacity, and `10fps`.
2. Use **Primary** as the default input when synchronized composition is enabled. Each source is already decoded independently into its raw ring; `normalized_primary` adds a redundant encode/internal-RTSP/decode stage.
3. Keep `64 MB` per input and `10s` maximum hold as initial values.
4. If sync buffering is disabled, change `MV_LATENCY_PRESET=normal` and lower `MV_FPS`.
5. For unstable source timestamps outside Multiview, use the main relay wall-clock mode. The public individual camera path remains unchanged by Multiview settings.

Raw wall-clock compositor behavior:

- Every selected input has an independent FFmpeg decoder and a bounded in-memory RGB frame ring.
- Frames are timestamped with the Orchestrator host clock. One worker selects the newest frame at or before `now - delay_sec` for every tile, then copies those frames into one canvas.
- One FFmpeg encoder per final view receives only completed raw canvases and publishes `multiview_*`; there are no intermediate `__mv_buffer/*` H.264 publishers, RTSP readers, second decodes, or `xstack` process.
- If one input disconnects, only that decoder reconnects. Its tile holds the last frame up to `max_hold_sec` and then becomes black while the other tiles and final output continue.
- The status file is written by the same worker that selects and composes frames, so source health cannot overwrite final-compositor health.
- Only final `multiview_*` outputs are recorded.
- The feature is opt-in for existing runtime files. Enabling or changing it restarts Multiview workers only, not MediaMTX or public camera relays.

Practical guidance:

- `copy` is efficient, but it is the least forgiving option for unstable IP cameras.
- `libx264` costs more CPU, but it usually produces more stable multiview inputs.
- If you are troubleshooting an unstable setup, prefer stability first: `MV_LATENCY_PRESET=normal`, shorter GOP, and moderate FPS.

Where to look:

- `logs/multiview.log`
- `logs/<camera>.log`
- `GET /api/v1/status/processes`

Typical log clues:

- `404 Not Found`: source path was not ready when multiview tried to open it.
- `Broken pipe`: downstream RTSP output or consumer disconnected.
- timestamp / DTS warnings: timestamps are unstable and low-latency settings may be too aggressive.

Dry-run (print FFmpeg commands only):

```powershell
python -m flinteye_app.workers.multiview_to_rtsp --env-file ".env" --dry-run
```


## 9. MediaMTX Loop Recording

This setup enables loop recording for multiple MediaMTX paths (UVC and IP cameras).
`flinteye_app/orchestrator_api.py` can now apply recording settings from `.env` / `runtime.json` directly to `mediamtx.yml` at startup (default enabled).
`tools/setup_mediamtx_recording.ps1` remains useful for standalone/manual Windows service workflows.

### 9.1 Configure recording (automated)

Recommended startup order:

1. Publish camera streams (`flinteye_app/workers/uvc_to_rtsp.py` and/or MediaMTX IP camera sources)
2. Start `flinteye_app/workers/multiview_to_rtsp.py` to publish `multiview_*` paths
3. Apply recording settings with `tools/setup_mediamtx_recording.ps1`

Run PowerShell as Administrator:

```powershell
cd C:\path\to\FlintEye
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env"
```

Override recording paths directly from CLI (optional):

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordPaths "uvc_cam1","uvc_cam2","ipcam1","ipcam2"
```

What this script does:

- Creates backup: `mediamtx.yml.bak` (same directory as `mediamtx.yml`)
- Adds/updates recording settings under each path in `MTX_RECORD_PATHS` (or `-RecordPaths`)
- Optionally auto-includes `multiview_1..multiview_N` recording targets
- Optionally adds/updates IP camera `source` for each path in `MTX_IP_PATHS`
- Creates `C:/recordings/mediamtx`
- Grants modify permission to current user (or `-MediaMTXUser`)
- Restarts MediaMTX service (unless `-NoRestart`)

Relevant `.env` keys:

- `MTX_CONFIG_PATH` (required if `-ConfigPath` is not passed)
- `MTX_RECORD_AUTO_APPLY` (default `true`; auto patch `mediamtx.yml` from orchestrator)
- `MTX_RECORD_ROOT`
- `MTX_RECORD_FORMAT` (default `fmp4`)
- `MTX_RECORD_PART_DURATION` (default `1s`)
- `MTX_RECORD_MAX_PART_SIZE` (default `50M`)
- `MTX_RECORD_SEGMENT_DURATION`
- `MTX_RECORD_DELETE_AFTER`
- `PLAYBACK_CACHE_DELETE_AFTER` (default `24h`; retention for internal playback-friendly MP4 files)
- `MTX_RECORD_PATHS` (example: `uvc_cam1,uvc_cam2,ipcam1,ipcam2`)
- `MTX_RECORD_INCLUDE_MULTIVIEW` (default `true`)
- `MTX_MULTI_VIEW_PREFIX` (default `multiview`)
- `MTX_MULTI_VIEW_MAX_COUNT` (default `16`)
- `MTX_IP_PATHS` (optional)
- `MTX_IP_<TOKEN>_SOURCE` (optional; example: `MTX_IP_IPCAM1_SOURCE`)
- `MTX_IP_<TOKEN>_RELAY_MODE` (`copy` or `libx264`; default `copy`)
- `MTX_IP_<TOKEN>_BITRATE` (optional; used when `RELAY_MODE=libx264`)
- `MTX_IP_<TOKEN>_MAXRATE` (optional; used when `RELAY_MODE=libx264`)
- `MTX_IP_<TOKEN>_BUFSIZE` (optional; used when `RELAY_MODE=libx264`)
- `MTX_IP_<TOKEN>_GOP` (default `40`)
- `MTX_IP_<TOKEN>_X264_PRESET` (default `veryfast`)
- `MTX_SERVICE_NAME`
- `MTX_SERVICE_USER`

### 9.2 Recording settings applied to each recording path

```yaml
paths:
  uvc_cam1:
    record: yes
    recordPath: C:/recordings/mediamtx/%path/%Y-%m-%d/%H-%M-%S-%f
    recordFormat: fmp4
    recordPartDuration: 1s
    recordMaxPartSize: 50M
    recordSegmentDuration: 10m
    recordDeleteAfter: 168h

  ipcam1:
    source: rtsp://username:password@192.168.1.101:554/stream1
    record: yes
    recordPath: C:/recordings/mediamtx/%path/%Y-%m-%d/%H-%M-%S-%f
    recordFormat: fmp4
    recordPartDuration: 1s
    recordMaxPartSize: 50M
    recordSegmentDuration: 10m
    recordDeleteAfter: 168h
```

### 9.3 Validate functionality

After stream starts, confirm files are created:

```powershell
Get-ChildItem "C:\recordings\mediamtx" -Recurse
```

Confirm segment rotation (~every 10 minutes):

```powershell
Get-ChildItem "C:\recordings\mediamtx" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName, LastWriteTime
```

### 9.4 Short retention test (before production)

Apply temporary 30-minute retention:

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordDeleteAfter "30m"
```

After deletion behavior is confirmed, restore 7-day retention:

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordDeleteAfter "168h"
```

### 9.5 Capacity planning and 24h monitoring

Sizing baseline (per stream):

- `2Mbps` -> about `21.6GB/day`
- `2Mbps` with `7 days` retention -> about `151GB`

Quick size check:

```powershell
$bytes = (Get-ChildItem "C:\recordings\mediamtx" -Recurse -File | Measure-Object Length -Sum).Sum
"{0:N2} GB" -f ($bytes / 1GB)
```

Disk free check:

```powershell
Get-PSDrive C
```

Operational policy:

- Keep free space above `20%`
- If approaching limit, lower bitrate (`--quality-preset low`) or shorten retention


## 10. Time Sync Check (NTP) Before Latency Measurement

If sender and receiver clocks are out of sync, measured "latency" can look much larger than actual transport delay.

### Windows (recommended check)

Check current sync status:

```powershell
w32tm /query /status
w32tm /query /source
Get-Date
```

Resync clock (run PowerShell as Administrator):

```powershell
w32tm /resync
```

If resync fails, restart Windows Time service and retry:

```powershell
Restart-Service w32time
w32tm /resync
```

### Linux

```bash
timedatectl status
sudo timedatectl set-ntp true
```

### macOS

```bash
sudo systemsetup -setusingnetworktime on
sudo sntp -sS time.apple.com
```

### Automatic latency measurement (OCR-based)

If your stream overlay contains sender time in `YYYY/MM/DD hh:mm:ss`, you can estimate latency automatically.

Requirements:

- `ffmpeg`
- `tesseract` OCR

Install example (macOS):

```bash
brew install tesseract
```

Measure camera stream latency:

```bash
python3 -m tools.measure_rtsp_latency \
  --rtsp-url rtsp://127.0.0.1:8554/uvc_cam1 \
  --samples 20 \
  --interval 0.5
```

Measure multiview latency:

```bash
python3 -m tools.measure_rtsp_latency \
  --rtsp-url rtsp://127.0.0.1:8554/multiview_1 \
  --samples 20 \
  --interval 0.5
```

For tiled multiview, adjust `--crop w:h:x:y` to target the timestamp area of each tile.

Notes:

- Since overlay time is second-based, measurement resolution is about `+/-1s`.
- Run NTP sync on sender and receiver before testing.
