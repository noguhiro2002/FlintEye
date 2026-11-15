#!/usr/bin/env bash
# Run inside a disposable package-test container, with curl available.
set -euo pipefail
app=${1:-/opt/flinteye/FlintEye}
profile=$(mktemp -d /tmp/flinteye-bundle-check.XXXXXXXX)
pid=''
cleanup() {
  if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  rm -rf -- "$profile"
}
trap cleanup EXIT
trap 'code=$?; printf "FAIL: bundle smoke test at line %s (exit %s)\n" "$LINENO" "$code"; cat "$profile/startup.log"; exit "$code"' ERR
cd "$profile"
: > "$profile/startup.log"
for worker in uvc_to_rtsp ip_camera_to_rtsp multiview_input_to_rtsp multiview_buffer_to_rtsp multiview_raw_compositor multiview_to_rtsp; do
  timeout 30 "$app" --worker "$worker" --help < /dev/null > /dev/null
done
libraries="$(dirname "$app")/_internal"
# Run as an ordinary user: licenses must remain readable after package install.
find "$libraries/licenses" -type f -exec cat {} + > /dev/null
LD_LIBRARY_PATH="$libraries" "$libraries/bin/ffmpeg" -nostdin -v error -f lavfi -i testsrc2=s=160x120:r=2 -t 1 -c:v libx264 "$profile/test.mp4"
LD_LIBRARY_PATH="$libraries" "$libraries/bin/ffprobe" -v error -show_entries stream=codec_name -of csv=p=0 "$profile/test.mp4" < /dev/null | grep -q h264
"$app" --headless --data-dir "$profile" --port 18481 < /dev/null >"$profile/startup.log" 2>&1 &
pid=$!
base=http://127.0.0.1:18481
ready=0
for attempt in $(seq 1 60); do
  if curl --silent --fail "$base/api/v1/health" > /dev/null; then ready=1; break; fi
  if ! kill -0 "$pid" 2>/dev/null; then cat "$profile/startup.log"; exit 1; fi
  sleep 1
done
[ "$ready" = 1 ] || { cat "$profile/startup.log"; exit 1; }
test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$base/api/v1/config/runtime")" = 503
token=$(cat "$profile/setup-token")
printf '{"token":"%s","password":"synthetic-bundle-password"}' "$token" |
  curl --silent --show-error --fail -H "Origin: $base" -H 'Content-Type: application/json' --data-binary @- "$base/api/v1/setup" > /dev/null
test ! -e "$profile/setup-token"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$base/api/v1/config/runtime")" = 401
printf '%s' '{"username":"admin","password":"synthetic-bundle-password"}' |
  curl --silent --show-error --fail -H "Origin: $base" -H 'Content-Type: application/json' --data-binary @- --cookie-jar "$profile/cookies" "$base/api/v1/auth/login" > /dev/null
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/config/runtime" > /dev/null
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/" | grep -q '<div id="root">'
printf 'PASS: installed media tools encode/probe; bundle serves UI, requires authentication and completes first-run setup.\n'

# Exercise an actual MediaMTX recording with the packaged encoder and hooks.
# The publisher is a test-owned process, so it exits before monitoring is stopped.
printf '%s' '{"recording":{"record_all_cameras":false,"record_paths":["bundle-smoke"],"include_multiview":false}}' |
  curl --silent --show-error --fail --cookie "$profile/cookies" -H "Origin: $base" -H 'Content-Type: application/json' -X PATCH --data-binary @- "$base/api/v1/config/runtime" > /dev/null
media_ready=0
for attempt in $(seq 1 60); do
  if curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/mediamtx" | grep -Eq '"running"[[:space:]]*:[[:space:]]*true'; then media_ready=1; break; fi
  sleep 1
done
[ "$media_ready" = 1 ] || { printf 'MediaMTX did not start\n' >&2; exit 1; }
LD_LIBRARY_PATH="$libraries" "$libraries/bin/ffmpeg" -nostdin -hide_banner -loglevel error -re -f lavfi -i testsrc2=s=160x120:r=5 -t 4 -c:v libx264 -pix_fmt yuv420p -g 5 -f rtsp rtsp://127.0.0.1:8554/bundle-smoke

curl --silent --show-error --fail --max-time 45 --cookie "$profile/cookies" -H "Origin: $base" -X POST "$base/api/v1/control/stop" > /dev/null
curl --silent --show-error --fail "$base/api/v1/health" > /dev/null
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/config/runtime" > /dev/null
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/monitoring" | grep -Eq '"desired_running"[[:space:]]*:[[:space:]]*false'
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/mediamtx" | grep -Eq '"running"[[:space:]]*:[[:space:]]*false'

# Confirm that at least one completed segment exists and decode every segment.
segments=0
while IFS= read -r -d '' segment; do
  LD_LIBRARY_PATH="$libraries" "$libraries/bin/ffmpeg" -nostdin -v error -xerror -i "$segment" -f null -
  segments=$((segments + 1))
done < <(find "$profile/recordings/bundle-smoke" -type f \( -name '*.mp4' -o -name '*.ts' \) -print0)
[ "$segments" -gt 0 ] || { printf 'No completed synthetic recording found\n' >&2; exit 1; }

# Applying a camera configuration while stopped must not restart any worker.
printf '%s' '{"cameras":[{"id":"bundle-camera","path":"bundle-camera","type":"ip","enabled":true,"ip":{"source_url":"rtsp://127.0.0.1:18554/no-source"}}]}' |
  curl --silent --show-error --fail --cookie "$profile/cookies" -H "Origin: $base" -H 'Content-Type: application/json' -X PATCH --data-binary @- "$base/api/v1/config/runtime" > /dev/null
sleep 2
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/monitoring" | grep -Eq '"desired_running"[[:space:]]*:[[:space:]]*false'
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/mediamtx" | grep -Eq '"running"[[:space:]]*:[[:space:]]*false'
processes=$(curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/processes")
if printf '%s' "$processes" | grep -Eq '"(status|desired)"[[:space:]]*:[[:space:]]*("running"|true)'; then
  printf 'A media process restarted while monitoring was stopped: %s\n' "$processes" >&2
  exit 1
fi
test "$(curl --silent --output /dev/null --write-out '%{http_code}' --cookie "$profile/cookies" -H "Origin: $base" -X POST "$base/api/v1/control/restart")" = 409

curl --silent --show-error --fail --max-time 45 --cookie "$profile/cookies" -H "Origin: $base" -X POST "$base/api/v1/control/start" > /dev/null
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/monitoring" | grep -Eq '"desired_running"[[:space:]]*:[[:space:]]*true'
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/mediamtx" | grep -Eq '"running"[[:space:]]*:[[:space:]]*true'
curl --silent --show-error --fail --max-time 45 --cookie "$profile/cookies" -H "Origin: $base" -X POST "$base/api/v1/control/stop" > /dev/null
# Ask the owning instance to quit without delivering a signal to Uvicorn.
control=$(<"$profile/instance-control.json")
if [[ ! $control =~ \"token\"[[:space:]]*:[[:space:]]*\"([0-9a-f]{64})\" ]]; then
  printf 'Could not read instance shutdown token\n' >&2
  exit 1
fi
printf '{"token":"%s"}\n' "${BASH_REMATCH[1]}" > "$profile/stop-request.json"
unset control
for attempt in $(seq 1 45); do
  if ! kill -0 "$pid" 2>/dev/null; then break; fi
  sleep 1
done
if kill -0 "$pid" 2>/dev/null; then
  printf 'Application did not exit within 45 seconds\n' >&2
  exit 1
fi
wait "$pid"
pid=''
"$app" --headless --data-dir "$profile" --port 18481 < /dev/null >>"$profile/startup.log" 2>&1 &
pid=$!
ready=0
for attempt in $(seq 1 60); do
  if curl --silent --fail "$base/api/v1/health" > /dev/null; then ready=1; break; fi
  if ! kill -0 "$pid" 2>/dev/null; then cat "$profile/startup.log"; exit 1; fi
  sleep 1
done
[ "$ready" = 1 ] || { cat "$profile/startup.log"; exit 1; }
printf '%s' '{"username":"admin","password":"synthetic-bundle-password"}' |
  curl --silent --show-error --fail -H "Origin: $base" -H 'Content-Type: application/json' --data-binary @- --cookie-jar "$profile/cookies" "$base/api/v1/auth/login" > /dev/null
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/monitoring" | grep -Eq '"desired_running"[[:space:]]*:[[:space:]]*false'
curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/mediamtx" | grep -Eq '"running"[[:space:]]*:[[:space:]]*false'
processes=$(curl --silent --show-error --fail --cookie "$profile/cookies" "$base/api/v1/status/processes")
if printf '%s' "$processes" | grep -Eq '"(status|desired)"[[:space:]]*:[[:space:]]*("running"|true)'; then
  printf 'A media process started after restarting the stopped app: %s\n' "$processes" >&2
  exit 1
fi
printf 'PASS: synthetic recording decodes completely; monitoring stop, configuration, restart rejection, explicit start and stopped persistence work.\n'
