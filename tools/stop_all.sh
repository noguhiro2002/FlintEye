#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf '[info] %s\n' "$*"
}

warn() {
  printf '[warn] %s\n' "$*" >&2
}

kill_pattern() {
  local pattern="$1"
  local label="$2"
  if pkill -f "$pattern" >/dev/null 2>&1; then
    log "stopped $label"
  else
    log "no running $label found"
  fi
}

log "stopping orchestrator stack from $WORKSPACE_DIR"

# Stop parents first, otherwise ffmpeg workers are respawned immediately.
kill_pattern "tools.start_orchestrator_stack|start_orchestrator_stack.py" "development launcher"
kill_pattern "flinteye_app.orchestrator_api|orchestrator_api.py" "API"

sleep 1

# Stop managed workers and remaining media processes.
kill_pattern "flinteye.py --worker (uvc_to_rtsp|ip_camera_to_rtsp|multiview_to_rtsp|multiview_input_to_rtsp|multiview_buffer_to_rtsp|multiview_raw_compositor)" "camera workers"
kill_pattern "multiview_to_rtsp.py" "multiview_to_rtsp.py"
kill_pattern "/mediamtx/mediamtx" "mediamtx"
kill_pattern "ffmpeg" "ffmpeg"

log "remaining related processes:"
ps -ax -o pid,ppid,command | grep -E "orchestrator_api.py|start_orchestrator_stack.py|uvc_to_rtsp.py|multiview_to_rtsp.py|/mediamtx/mediamtx|ffmpeg" | grep -v grep || true

log "done"
