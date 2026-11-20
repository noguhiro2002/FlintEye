#!/usr/bin/env bash
# Release assets replace this marker with a fixed version. Never run as root.
set -euo pipefail
version='@RELEASE_VERSION@'
start_app=1
package_directory=''
install_directory=''
fail() { printf 'FlintEye: %s\n' "$*" >&2; exit 1; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || fail '--version requires X.Y.Z'; version=$2; shift 2 ;;
    --no-start) start_app=0; shift ;;
    --package-directory) [ "$#" -ge 2 ] || fail '--package-directory requires an artifact folder'; package_directory=$2; shift 2 ;;
    --install-directory) [ "$#" -ge 2 ] || fail '--install-directory requires a macOS application folder'; install_directory=$2; shift 2 ;;
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
  [ -z "$install_directory" ] || fail '--install-directory is available only on macOS.'
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
  if [ "$kind" = deb ]; then manager=apt-get; else manager=dnf; fi
  command -v "$manager" >/dev/null || fail "$manager is required."
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
if [ -n "$package_directory" ]; then
  [ -d "$package_directory" ] || fail 'The selected artifact folder does not exist.'
  printf 'Installing from explicitly selected validation artifacts; no release download will occur.\n'
  cp -- "$package_directory/SHA256SUMS" "$work/SHA256SUMS" || fail 'The artifact checksum file is missing.'
else
  fetch "$base/SHA256SUMS" "$work/SHA256SUMS" || fail 'Release not available. Check the version and whether it has been published.'
fi
expected=$(awk -v file="$asset" '$2 == file { print $1 }' "$work/SHA256SUMS")
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || fail 'Package checksum is missing or ambiguous.'
if [ -n "$package_directory" ]; then
  cp -- "$package_directory/$asset" "$work/$asset" || fail 'The selected package is missing.'
else
  fetch "$base/$asset" "$work/$asset" || fail 'Package download failed.'
fi
if command -v sha256sum >/dev/null; then
  actual=$(sha256sum "$work/$asset" | awk '{print $1}')
else
  actual=$(shasum -a 256 "$work/$asset" | awk '{print $1}')
fi
[ "$actual" = "$expected" ] || fail 'Checksum mismatch. Nothing was installed.'
if [ "$os" = Darwin ]; then
  destination=${install_directory:-"$HOME/Applications"}
  mkdir -p "$destination"
  [ ! -L "$destination/FlintEye.app" ] || fail 'Destination app must not be a symbolic link.'
  [ ! -e "$destination/FlintEye.previous.app" ] || fail 'Move FlintEye.previous.app aside before another update.'
  mount_dir="$work/mounted"
  mkdir "$mount_dir"
  hdiutil attach "$work/$asset" -mountpoint "$mount_dir" -nobrowse -readonly -quiet
  info="$mount_dir/FlintEye.app/Contents/Info.plist"
  bundled_executable=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$info")
  [ "$bundled_executable" = FlintEye ] || fail 'The DMG does not declare the FlintEye executable. Nothing was installed.'
  [ -x "$mount_dir/FlintEye.app/Contents/MacOS/FlintEye" ] || fail 'The app executable is missing or is not executable. Nothing was installed.'
  codesign --verify --deep --strict "$mount_dir/FlintEye.app" || fail 'The app signature is damaged. Nothing was installed.'
  bundled_version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$info")
  [ "$bundled_version" = "$application_version" ] || fail 'The app inside the DMG has a different version. Nothing was installed.'
  bundled_release=$(/usr/libexec/PlistBuddy -c 'Print :FlintEyeReleaseVersion' "$info" 2>/dev/null || true)
  if [ -n "$bundled_release" ] || [[ "$application_version" = 1.2.* ]]; then
    [ "$bundled_release" = "$version" ] || fail 'The app inside the DMG is a different preview. Nothing was installed.'
  fi
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
  if ! codesign --verify --deep --strict "$stage/FlintEye.app"; then
    rm -rf -- "$stage"; fail 'The copied app failed its integrity check. The existing app was preserved.'
  fi
  if [ -e "$destination/FlintEye.app" ]; then mv "$destination/FlintEye.app" "$destination/FlintEye.previous.app"; fi
  if ! mv "$stage/FlintEye.app" "$destination/FlintEye.app"; then
    if [ -e "$destination/FlintEye.previous.app" ]; then mv "$destination/FlintEye.previous.app" "$destination/FlintEye.app"; fi
    rm -rf -- "$stage"; fail 'Could not install the app; the previous app was restored.'
  fi
  rmdir "$stage"
  # Register this exact installed copy, rather than asking Launch Services to
  # choose an older app with the same bundle identifier.
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$destination/FlintEye.app" || true
  printf 'FlintEye %s files installed at: %s\n' "$version" "$destination/FlintEye.app"
  printf 'FIRST LAUNCH: this development preview has an ad-hoc signature and is not notarized.\n'
  printf 'After trying to open FlintEye, use System Settings > Privacy & Security > Open Anyway, then Open.\n'
  printf 'An integrity check does not grant macOS permission to run the app. Managed Macs may require your administrator.\n'
  printf 'Guide: https://github.com/noguhiro2002/FlintEye/blob/main/docs/INSTALL.md#unsigned-packages\n'
  printf 'To remove: choose Disable start at login and quit, then move %s to Trash. Settings and recordings are kept.\n' "$destination/FlintEye.app"
  if [ "$start_app" = 1 ]; then
    if launch_output=$(open "$destination/FlintEye.app" 2>&1); then
      printf 'Application launch requested. If no window appears, complete the macOS permission step above.\n'
    else
      launch_status=$?
      printf 'FlintEye: application launch request failed (exit %s):\n%s\n' "$launch_status" "$launch_output" >&2
      printf 'Files remain installed at %s; application startup has not been confirmed.\n' "$destination/FlintEye.app" >&2
      printf 'For this unnotarized preview, check Privacy & Security > Open Anyway. Other launch errors may need investigation.\n' >&2
      exit "$launch_status"
    fi
  else
    printf 'Application was not started (--no-start). First-launch permission and operation remain unverified.\n'
  fi
  printf 'On first launch, choose a trusted network and follow the setup address shown by FlintEye.\n'
else
  if [ "$kind" = deb ]; then
    # Multiple previews share the numeric package version. Apply the selected
    # archive even when apt already has a package with that version installed.
    sudo apt-get install --reinstall -y "$work/$asset"
  else
    rpm_identity='%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}'
    selected=$(rpm -qp --qf "$rpm_identity" "$work/$asset")
    if installed=$(rpm -q --qf "$rpm_identity" flinteye) && [ "$installed" = "$selected" ]; then
      sudo dnf reinstall -y "$work/$asset"
    else
      sudo dnf install -y "$work/$asset"
    fi
  fi
  printf 'Installed FlintEye %s. Open FlintEye from your application menu.\n' "$version"
  printf 'To remove after quitting: sudo %s remove flinteye. Settings and recordings are kept.\n' "$manager"
  if [ "$start_app" = 1 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    /opt/flinteye/FlintEye </dev/null &
    /opt/flinteye/FlintEye --headless --connection-info ||
      printf 'After choosing a network in FlintEye, use the address shown in its setup window.\n'
  else
    printf 'Open FlintEye and follow its connection instructions. On a server, see docs/DISTRIBUTION.md (systemd).\n'
  fi
fi
