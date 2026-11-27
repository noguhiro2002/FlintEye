# Advanced reference: Development

[日本語](DEVELOPMENT.ja.md)

[Documentation](../README.md) · [Manual installation](../MANUAL_INSTALL.md)

> These are low-level source/development commands, run from the repository root.
> For the packaged application, use the [user guide](../USER_GUIDE.md).
> Standalone MediaMTX retention and service settings do not apply to FlintEye-managed storage.
> Keep listeners on loopback; LAN access uses the authenticated HTTPS proxy described in the [distribution guide](../DISTRIBUTION.md).

## 12. Web UI (Developer reference)

Frontend source is located at:

- `frontend`

Main structure:

- `frontend/src/App.tsx`: shell layout and page routing
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/pages/LiveViewPage.tsx`
- `frontend/src/pages/MultiviewPage.tsx`
- `frontend/src/pages/RecordingsPage.tsx`
- `frontend/src/api/client.ts`: API client

### 12.1 Start

Recommended (start API + MediaMTX + camera workers + frontend together):

```bash
python3 -m tools.start_orchestrator_stack --env-file .env --runtime-file runtime.json
```

After pulling changes that update `frontend/package.json` or `frontend/package-lock.json`,
refresh the frontend dependencies once before starting the stack. Existing
`frontend/node_modules` is local to each machine and is not updated by Git.

```bash
cd frontend
npm ci
cd ..
```

On PowerShell:

```powershell
Set-Location .\frontend
npm ci
Set-Location ..
python -m tools.start_orchestrator_stack --env-file .env --runtime-file runtime.json
```

If Vite reports that an imported package "could not be resolved", run the same
`npm ci` command and restart the stack.

### 12.1.1 Full stop / cleanup

Do not kill `ffmpeg` alone when the orchestrator is running.

Reason:

- `flinteye_app/orchestrator_api.py` supervises camera and multiview worker processes
- if you kill only `ffmpeg`, the supervisor treats it as a crashed worker and starts it again

Correct shutdown order:

1. stop `tools/start_orchestrator_stack.py` or `flinteye_app/orchestrator_api.py`
2. then stop remaining worker processes
3. then stop leftover `mediamtx` / `ffmpeg` if needed

Convenience script:

```bash
./tools/stop_all.sh
```

Manual commands:

Stop the foreground development stack with Ctrl+C. Inspect any remaining process before stopping its exact PID; do not kill unrelated FFmpeg or MediaMTX processes.

Verify nothing is left:

```bash
ps -ax -o pid,ppid,command | rg "flinteye_app/orchestrator_api.py|tools/start_orchestrator_stack.py|flinteye_app/workers/uvc_to_rtsp.py|flinteye_app/workers/multiview_to_rtsp.py|mediamtx|ffmpeg"
```

Optional flags:

- `--api-host 127.0.0.1 --api-port 18080`
- `--ui-host 127.0.0.1 --ui-port 5173`
- `--skip-npm-install` (skip dependency auto-install check)
- `--npm-command npm` (when `npm` command name differs)

Legacy/manual frontend start:

```bash
cd frontend
npm ci
npm run dev
```

Default URL:

- `http://127.0.0.1:5173`

The Vite dev server proxies:

- `/api/*` -> `http://127.0.0.1:18080`

### 12.1.2 Access from other devices on the same LAN

Keep the API and Vite development server on `127.0.0.1`. For another device, use the packaged UI with built-in LAN HTTPS or an existing HTTPS reverse proxy, as described in the [LAN access guide](../LAN_ACCESS.md). An SSH tunnel to `127.0.0.1:18080` is suitable for temporary administration; its TCP forwarding does not carry WebRTC UDP.

### 12.2 UI features

- Sidebar navigation: Dashboard / Information / Settings / Live View / Multiview / Recordings
- Dashboard: orchestrator and process status
- Information:
  - camera RTSP/WebRTC endpoints
  - simple camera settings (resolution/fps/bitrate/encoder where available)
  - multiview settings summary
- Settings:
  - UVC discovery from `/api/v1/uvc/devices`
  - UVC suggestion/apply workflow
  - IP camera draft table
  - Basic tab: Cameras, Recording, Multiview, Runtime & access
  - Advanced tab: additional camera/media controls, General, MediaMTX, Logging, Integrations & API, and Runtime JSON
  - Available to signed-in administrators; issued REST API keys have a separate, limited scope
- Live View:
  - Snapshot thumbnail grid for all cameras
  - Click thumbnail to open single-camera WebRTC using `WebRtcPlayer` and a `<video>` element
- Multiview:
  - View list from API
  - Selected multiview WebRTC using the same `WebRtcPlayer`
- Recordings:
  - Stream filter + recorded file list from API
  - Built-in player for saved video files
  - Browser playback creates temporary remuxed MP4 files in a private playback cache outside the recording folder.
    They expire after `recording.playback_cache_delete_after` (default `24h`, checked every 30 seconds) or on shutdown.
- Footer text is configurable via runtime/UI settings (`ui.footer_text` or `WEBAPP_FOOTER_TEXT`)

## Repository layout

`flinteye.py` is the source and frozen-bundle entry point. The application lives in `flinteye_app/`, its six worker modules in `flinteye_app/workers/`, and development commands in `tools/`. Run tools from the checkout root with `python -m tools.manage_auth --help` or `python -m tools.start_orchestrator_stack --help`.

Resource lookup uses the checkout root for source runs and PyInstaller's extracted resource directory for installed builds. User settings and recordings remain in the existing data directory. Launching an absolute path to `flinteye.py` from another directory does not change resource discovery.

Environment examples are in `config/examples/`, the environment reference is [ENV_OPTIONS.md](ENV_OPTIONS.md), and development Compose is in `deploy/`. Generated TypeScript build information and emitted Vite configuration are ignored; edit `frontend/vite.config.ts` instead.
