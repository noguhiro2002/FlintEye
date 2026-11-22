# Advanced reference: Api

[日本語](API.ja.md)

[Documentation](../README.md) · [Manual installation](../MANUAL_INSTALL.md)

> These are low-level source/development commands, run from the repository root.
> For the packaged application, use the [user guide](../USER_GUIDE.md).
> Standalone MediaMTX retention and service settings do not apply to FlintEye-managed storage.
> Keep listeners on loopback; LAN access uses the authenticated HTTPS proxy described in the [distribution guide](../DISTRIBUTION.md).

<a id="11-unified-camera-orchestrator-api-uvc--multiview--mediamtx"></a>

## 11. FlintEye API (UVC / MultiView / MediaMTX)

`flinteye_app/orchestrator_api.py` provides a single REST API to control:

- UVC ingest processes (`flinteye_app/workers/uvc_to_rtsp.py`) per camera
- IP camera ingest processes per camera
- Multi view compose process (`flinteye_app/workers/multiview_to_rtsp.py`)
- MediaMTX service (Windows service / systemd / launchd / direct / external mode)
- Runtime config persistence (`runtime.json`)
- Snapshot capture and stream address discovery

<a id="equipment-recording-events"></a>
### Equipment recording events

Enable event recordings and obtain the dedicated token in [Settings → Recording](../USER_GUIDE.md#event-recordings). Use local HTTP on the FlintEye server or the trusted LAN HTTPS address from another device.

```bash
curl --fail-with-body http://127.0.0.1:18080/api/v1/recording-events \
  -H "Authorization: Bearer ${FLINTEYE_EVENT_TOKEN}" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: press-03-alarm-42' \
  --data '{"camera_ids":["press-03","workbench"],"occurred_at":"2026-11-22T10:35:23+09:00","lookback_sec":45,"label":"Press 03 alarm"}'
```

Use the camera IDs from `GET /api/v1/cameras` as an administrator. Supply one or more IDs. `occurred_at` accepts an ISO 8601 timestamp with an offset or `Z`. Omit it to use receipt time. For the example above, the requested interval is 10:34:38 to 10:35:23. Retrying the same request with the same idempotency key returns the original event. Reusing that key with different fields returns HTTP 409.

`202 Accepted` returns an event ID. Poll `GET /api/v1/recording-events/{event_id}` with the event token, or use **Recordings → Event recordings** with a viewer or administrator session. `ready` means the requested interval was saved, `partial` means some footage was missing, and `unavailable` means no completed footage matched. `waiting_recording` can last until the current segment closes. `waiting_storage` resumes after the original destination is reconnected or space is freed. An administrator can cancel a waiting event.

The event token can submit events and read their status. Sign in to play or download the media. The archive contains independent clips at video frame boundaries. The queue and archive index are kept in the FlintEye profile. Back up the profile and event folder together to retain playback from the list.

### 11.1 Install dependencies

```bash
python3 -m pip install fastapi uvicorn
# or
python3 -m pip install -r requirements.txt
```

### 11.2 Required `.env` keys

See OS-specific templates for full list:

- `config/examples/.env.example.mac`
- `config/examples/.env.example.windows`
- `config/examples/.env.example.linux`

Minimum recommended keys:

- `API_HOST=127.0.0.1`
- `API_PORT=18080`
- `AUTH_PROVIDER=local`
- `AUTH_VIEWER_AUTH_REQUIRED=true`
- `AUTH_SESSION_COOKIE_NAME=orch_session`
- `AUTH_SESSION_TTL_SEC=43200`
- `AUTH_LOCAL_ADMIN_USERNAME=admin`
- `AUTH_LOCAL_VIEWER_USERNAME=viewer`
- `AUTH_SESSION_SECRET=` (recommended: initialize with `tools/manage_auth.py`, not by hand)
- `AUTH_LOCAL_ADMIN_PASSWORD_HASH=` (recommended: initialize with `tools/manage_auth.py`, not by hand)
- `AUTH_LOCAL_VIEWER_PASSWORD_HASH=` (recommended: initialize with `tools/manage_auth.py`, not by hand)
- `API_ADMIN_TOKEN=` / `API_VIEWER_TOKEN=` / `API_BEARER_TOKEN=` only when using `AUTH_PROVIDER=legacy_token`
- `SNAPSHOT_TIMEOUT_SEC=3.0` (increase when `/snapshot` returns timeout)
- `LOG_DIR=./logs`
- `LOG_LEVEL=ERROR`
- `LOG_RETENTION=` (blank = follow `MTX_RECORD_DELETE_AFTER`)
- `WEBAPP_TITLE=FlintEye`
- `WEBAPP_SIDEBAR_TITLE=FlintEye`
- `WEBAPP_FOOTER_TEXT=© 2026 Noguhiro. Sustainable Use License + additional permission.`
- `MTX_CONTROL_MODE=windows_service|systemd|launchd|direct|external`
- `MTX_SERVICE_NAME=mediamtx`
- `MTX_AUTOSTART_ON_API_START=true` (default)
- `MTX_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MTX_INTERNAL_RTSP_BASE_URL=rtsp://127.0.0.1:8554` for local publisher processes on the same host (optional; defaults to `MTX_RTSP_BASE_URL`)
- `MTX_WEBRTC_BASE_URL=http://127.0.0.1:8889`
- `MTX_MANAGED_ENABLED=false` (set `true` when editing mediamtx.yml global/path via REST)
- `MTX_CONFIG_PATH=<path-to-mediamtx.yml>`
- `MTX_RECORD_AUTO_APPLY=true` (default)

Config priority:

- `runtime.json` (API-updated values) > `.env` > built-in defaults

When MediaMTX is started manually (outside this API), set:

- `MTX_CONTROL_MODE=external`
- `MTX_AUTOSTART_ON_API_START=false` (recommended)

In `external` mode, `/control/start|stop|restart` don't manage the process and return manual-operation guidance.

### 11.3 Start API server

```bash
python3 -m flinteye_app.orchestrator_api --env-file .env --runtime-file runtime.json
```

### 11.4 Authentication

Recommended local-auth bootstrap:

```bash
python3 -m tools.manage_auth init-local --runtime-file runtime.json
```

This command:

- generates password hashes
- generates a session secret when missing
- writes the auth block into `runtime.json`

Local auth keys:

- `AUTH_PROVIDER=local`
- `AUTH_VIEWER_AUTH_REQUIRED=true|false`
- `AUTH_SESSION_COOKIE_NAME`
- `AUTH_SESSION_TTL_SEC`
- `AUTH_SESSION_SECRET`
- `AUTH_LOCAL_ADMIN_USERNAME`
- `AUTH_LOCAL_ADMIN_PASSWORD_HASH`
- `AUTH_LOCAL_VIEWER_USERNAME`
- `AUTH_LOCAL_VIEWER_PASSWORD_HASH`

Legacy token mode is still supported:

- `AUTH_PROVIDER=legacy_token`
- `API_ADMIN_TOKEN`
- `API_VIEWER_TOKEN`
- `API_VIEWER_AUTH_REQUIRED=true|false`
- `API_BEARER_TOKEN` (legacy fallback)

### 11.5 Logging

Current implementation writes:

- `logs/orchestrator.log`: orchestrator/API runtime log
- `logs/uvc_cam1.log`, `logs/uvc_cam2.log`, ...: per-camera worker logs
- `logs/multiview.log`: multiview worker log
- `logs/mediamtx.log`: MediaMTX direct-mode log

Rotation is enabled daily. Old rotated logs are deleted by retention period.

Main logging keys:

- `LOG_DIR=./logs`
- `LOG_LEVEL=ERROR`
- `LOG_RETENTION=`: blank means use `recording.record_delete_after` / `MTX_RECORD_DELETE_AFTER`
- `UVC_LOGLEVEL=error`
- `MV_LOGLEVEL=error`

Public (no token required) endpoints:

- `GET /api/v1/health`
- `GET /api/v1/status`

Viewer endpoints:

- monitor/view/snapshot/recording APIs
- token is optional only when `API_VIEWER_AUTH_REQUIRED=false`

Admin endpoints:

- configuration/control/write APIs
- always require `API_ADMIN_TOKEN` when it is set

### 11.5 API documents (Swagger / ReDoc)

When the API server is running:

- Swagger UI: `http://127.0.0.1:18080/docs`
- ReDoc: `http://127.0.0.1:18080/redoc`
- OpenAPI JSON: `http://127.0.0.1:18080/openapi.json`

If auth is enabled, click `Authorize` in Swagger UI and enter:

- `Bearer <API_ADMIN_TOKEN>` (or viewer token for viewer-only endpoints)

### 11.6 Main endpoints

- `camera_id` is exactly the MediaMTX path name (for example `uvc_cam1`, `ipcam2`)
- `GET /api/v1/health`
- `GET /api/v1/status`
- `GET /api/v1/status/processes`
- `GET /api/v1/status/mediamtx`
- `POST /api/v1/control/start`
- `POST /api/v1/control/stop`
- `POST /api/v1/control/restart`
- `GET /api/v1/config/effective`
- `GET /api/v1/config/runtime`
- `PUT /api/v1/config/runtime`
- `PATCH /api/v1/config/runtime`
- `POST /api/v1/config/apply`
- `GET /api/v1/uvc/devices`
- `GET /api/v1/uvc/devices/{device_id}`
- `POST /api/v1/uvc/devices/{device_id}/suggest`
- `POST /api/v1/uvc/devices/{device_id}/apply`
- `GET /api/v1/mediamtx/config`
- `PATCH /api/v1/mediamtx/config`
- `POST /api/v1/mediamtx/config/apply`
- `GET /api/v1/cameras`
- `POST /api/v1/cameras`
- `GET /api/v1/cameras/{camera_id}`
- `PATCH /api/v1/cameras/{camera_id}`
- `DELETE /api/v1/cameras/{camera_id}`
- `POST /api/v1/cameras/{camera_id}/enable`
- `POST /api/v1/cameras/{camera_id}/disable`
- `GET /api/v1/viewer/cameras`
- `GET /api/v1/viewer/info`
- `GET /api/v1/cameras/{camera_id}/addresses`
- `GET /api/v1/cameras/{camera_id}/snapshot`
- `GET /api/v1/multiview`
- `PATCH /api/v1/multiview`
- `POST /api/v1/multiview/enable`
- `POST /api/v1/multiview/disable`
- `GET /api/v1/multiview/views`
- `GET /api/v1/multiview/views/{view_id}/addresses`
- `GET /api/v1/multiview/views/{view_id}/snapshot`
- `GET /api/v1/streams/{stream_id}/addresses`
- `GET /api/v1/recordings/streams`
- `GET /api/v1/recordings`
- `GET /api/v1/recordings/files/{file_id}`

### 11.7 Quick API examples

```bash
ADMIN_TOKEN="change-this-token"
VIEWER_TOKEN="change-this-viewer-token"
BASE="http://127.0.0.1:18080"
ADMIN_AUTH="Authorization: Bearer ${ADMIN_TOKEN}"
VIEWER_AUTH="Authorization: Bearer ${VIEWER_TOKEN}"
```

Health/status:

```bash
curl "$BASE/api/v1/health"
curl "$BASE/api/v1/status"
```

List detected UVC cameras:

```bash
curl -H "$ADMIN_AUTH" "$BASE/api/v1/uvc/devices"
```

Get suggestion for one UVC device:

```bash
curl -X POST "$BASE/api/v1/uvc/devices/<device_id>/suggest" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"profile":"cam3","path":"uvc_cam3","camera_name":"UVC-CAM-03","use_device_index":false}'
```

Apply detected UVC device directly to runtime + process:

```bash
curl -X POST "$BASE/api/v1/uvc/devices/<device_id>/apply" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"profile":"cam3","path":"uvc_cam3","camera_name":"UVC-CAM-03"}'
```

Disable/enable one camera:

```bash
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/cameras/uvc_cam1/disable"
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/cameras/uvc_cam1/enable"
```

Disable/enable multiview:

```bash
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/multiview/disable"
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/multiview/enable"
```

Patch runtime config (example: change multiview bitrate):

```bash
curl -X PATCH "$BASE/api/v1/config/runtime" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"multiview":{"quality":{"bitrate":"2M","maxrate":"2M","bufsize":"2M"}}}'
```

Patch MediaMTX managed settings (example: enable API listener and set per-path source):

```bash
curl -X PATCH "$BASE/api/v1/mediamtx/config" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "managed": {
      "enabled": true,
      "global": {
        "api": true,
        "apiAddress": ":9997"
      },
      "paths": {
        "ipcam1": {
          "source": "rtsp://username:password@192.168.1.101:554/stream1",
          "sourceOnDemand": true
        }
      }
    },
    "recording": {
      "record_segment_duration": "1m",
      "record_delete_after": "5m",
      "playback_cache_delete_after": "24h"
    }
  }'
```

Get/apply current MediaMTX config state:

```bash
curl -H "$ADMIN_AUTH" "$BASE/api/v1/mediamtx/config"
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/mediamtx/config/apply"
```

Take snapshots:

```bash
curl -H "$VIEWER_AUTH" "$BASE/api/v1/cameras/uvc_cam1/snapshot" --output cam1.jpg
curl -H "$VIEWER_AUTH" "$BASE/api/v1/multiview/views/multiview_1/snapshot" --output mv1.jpg
```

Increase snapshot timeout at runtime (example: 8 seconds):

```bash
curl -X PATCH "$BASE/api/v1/config/runtime" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"snapshot":{"timeout_sec":8.0}}'
```

Get RTSP/WebRTC addresses:

```bash
curl -H "$VIEWER_AUTH" "$BASE/api/v1/cameras/uvc_cam1/addresses"
curl -H "$VIEWER_AUTH" "$BASE/api/v1/streams/multiview_1/addresses"
```

Recordings list/playback:

```bash
curl -H "$VIEWER_AUTH" "$BASE/api/v1/recordings/streams"
curl -H "$VIEWER_AUTH" "$BASE/api/v1/recordings?stream_id=uvc_cam1&limit=20"
```
