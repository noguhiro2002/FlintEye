#!/usr/bin/env bash
# Release assets replace this marker with a fixed version. Never run as root.
set -euo pipefail
version='@RELEASE_VERSION@'
start_app=1
fail() { printf 'FlintEye: %s\n' "$*" >&2; exit 1; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || fail '--version requires X.Y.Z'; version=$2; shift 2 ;;
    --no-start) start_app=0; shift ;;
    *) fail "Unknown option: $1" ;;
  esac
done
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-preview\.[1-9][0-9]{0,5})?$ ]] || fail 'Use a published release or pass --version X.Y.Z[-preview.N].'
application_version=${version%%-preview.*}
if [[ "$version" == *-preview.* ]]; then printf 'FlintEye %s — UNDER DEVELOPMENT; this is not a stable release.\n' "$version"; fi
[ "$(id -u)" -ne 0 ] || fail 'Run as your normal user. The Linux package manager will request sudo when needed.'
command -v curl >/dev/null || fail 'curl is required.'
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) fail 'Only 64-bit Intel/AMD and ARM computers are supported.' ;;
esac
os=$(uname -s)
if [ "$os" = Darwin ]; then
  # Detect Apple Silicon even when Terminal is running under Rosetta.
  if [ "$(sysctl -in hw.optional.arm64 2>/dev/null || true)" = 1 ]; then arch=arm64; fi
  major=$(sw_vers -productVersion | cut -d. -f1)
  [ "$major" -ge 14 ] || fail 'macOS 14 or newer is required.'
  asset="FlintEye-$application_version-macos-$arch.dmg"
elif [ "$os" = Linux ]; then
  [ -r /etc/os-release ] || fail 'Cannot identify Linux distribution.'
  . /etc/os-release
  major=${VERSION_ID%%.*}
  [[ "$major" =~ ^[0-9]+$ ]] || fail 'Cannot identify Linux version.'
  case "$ID" in
    ubuntu) [ "$major" -ge 24 ] || fail 'Ubuntu 24.04 or newer is required.'; kind=deb ;;
    debian|raspbian) [ "$major" -ge 12 ] || fail '64-bit Debian/Raspberry Pi OS Bookworm or newer is required.'; kind=deb ;;
    rocky|almalinux|rhel) [ "$major" -ge 9 ] || fail 'An Enterprise Linux 9 or newer system is required.'; kind=rpm ;;
    *) fail "Unsupported automatic installation target: $ID. See the manual installation guide." ;;
  esac
  asset="FlintEye-$application_version-linux-$arch.$kind"
  command -v sudo >/dev/null || fail 'sudo is required before downloading the package. Ask your administrator to install it, or download the package for administrator installation. See docs/MANUAL_INSTALL.md.'
  if [ "$kind" = deb ]; then command -v apt-get >/dev/null || fail 'apt-get is required.'; else command -v dnf >/dev/null || fail 'dnf is required.'; fi
else
  fail "Unsupported OS: $os"
fi
if command -v pgrep >/dev/null && pgrep -x FlintEye >/dev/null; then
  fail 'Quit FlintEye using Stop monitoring and quit, then run this installer again.'
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/flinteye-install.XXXXXXXX")
mount_dir=''
cleanup() {
  if [ -n "$mount_dir" ]; then hdiutil detach "$mount_dir" -quiet || true; fi
  rm -rf -- "$work"
}
trap cleanup EXIT
base="https://github.com/noguhiro2002/FlintEye/releases/download/v$version"
fetch() { curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --output "$2" "$1"; }
fetch "$base/SHA256SUMS" "$work/SHA256SUMS" || fail 'Release not available. Check the version and whether it has been published.'
expected=$(awk -v file="$asset" '$2 == file { print $1 }' "$work/SHA256SUMS")
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || fail 'Package checksum is missing or ambiguous.'
fetch "$base/$asset" "$work/$asset" || fail 'Package download failed.'
if command -v sha256sum >/dev/null; then
  actual=$(sha256sum "$work/$asset" | awk '{print $1}')
else
  actual=$(shasum -a 256 "$work/$asset" | awk '{print $1}')
fi
[ "$actual" = "$expected" ] || fail 'Checksum mismatch. Nothing was installed.'
if [ "$os" = Darwin ]; then
  destination="$HOME/Applications"
  mkdir -p "$destination"
  [ ! -L "$destination/FlintEye.app" ] || fail 'Destination app must not be a symbolic link.'
  [ ! -e "$destination/FlintEye.previous.app" ] || fail 'Move FlintEye.previous.app aside before another update.'
  mount_dir="$work/mounted"
  mkdir "$mount_dir"
  hdiutil attach "$work/$asset" -mountpoint "$mount_dir" -nobrowse -readonly -quiet
  stage=$(mktemp -d "$destination/.flinteye-install.XXXXXXXX")
  if ! ditto "$mount_dir/FlintEye.app" "$stage/FlintEye.app"; then
    rm -rf -- "$stage"; fail 'Could not copy the application. The existing app was preserved.'
  fi
  # curl does not add quarantine metadata like a browser download does.
  # Preserve the normal per-app Gatekeeper decision on first launch.
  quarantine_date=$(printf '%x' "$(date +%s)")
  if ! xattr -w com.apple.quarantine "0083;$quarantine_date;FlintEyeInstaller;" "$stage/FlintEye.app"; then
    rm -rf -- "$stage"; fail 'Could not mark the downloaded app for the normal macOS security check.'
  fi
  if [ -e "$destination/FlintEye.app" ]; then mv "$destination/FlintEye.app" "$destination/FlintEye.previous.app"; fi
  if ! mv "$stage/FlintEye.app" "$destination/FlintEye.app"; then
    if [ -e "$destination/FlintEye.previous.app" ]; then mv "$destination/FlintEye.previous.app" "$destination/FlintEye.app"; fi
    rm -rf -- "$stage"; fail 'Could not install the app; the previous app was restored.'
  fi
  rmdir "$stage"
  printf 'Installed FlintEye %s. macOS may ask you to allow this unsigned app in Privacy & Security.\n' "$version"
  if [ "$start_app" = 1 ]; then open "$destination/FlintEye.app"; fi
else
  if [ "$kind" = deb ]; then sudo apt-get install -y "$work/$asset"; else sudo dnf install -y "$work/$asset"; fi
  printf 'Installed FlintEye %s. Open FlintEye from your application menu.\n' "$version"
  if [ "$start_app" = 1 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    /opt/flinteye/FlintEye >/dev/null 2>&1 </dev/null &
  else
    printf 'For a headless server, follow docs/DISTRIBUTION.md (systemd).\n'
  fi
fi
