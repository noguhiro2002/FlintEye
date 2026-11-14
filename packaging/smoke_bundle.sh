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
  timeout 30 "$app" --worker "$worker" --help > /dev/null
done
libraries="$(dirname "$app")/_internal"
# Run as an ordinary user: licenses must remain readable after package install.
find "$libraries/licenses" -type f -exec cat {} + > /dev/null
LD_LIBRARY_PATH="$libraries" "$libraries/bin/ffmpeg" -v error -f lavfi -i testsrc2=s=160x120:r=2 -t 1 -c:v libx264 "$profile/test.mp4"
LD_LIBRARY_PATH="$libraries" "$libraries/bin/ffprobe" -v error -show_entries stream=codec_name -of csv=p=0 "$profile/test.mp4" | grep -q h264
"$app" --headless --data-dir "$profile" --port 18481 >"$profile/startup.log" 2>&1 &
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
