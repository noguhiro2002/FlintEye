#!/usr/bin/env bash
# Release assets replace this marker with a fixed version. Run as a normal user.
set -euo pipefail
version='@RELEASE_VERSION@'
start_app=1
package_directory=''
install_directory=''
user_install=0
uninstall=0
fail() { printf 'FlintEye: %s\n' "$*" >&2; exit 1; }

user_install_running() {
  local process image
  for process in /proc/[0-9]*/exe; do
    [ -O "${process%/exe}" ] || continue
    image=$(readlink -- "$process" 2>/dev/null) || continue
    case "$image" in
      "$1/"*) return 0 ;;
    esac
  done
  return 1
}

check_user_destination() {
  local installed profile
  installed=$(realpath -m -- "$user_destination")
  profile=$(realpath -m -- "${FLINTEYE_DATA_DIR:-${XDG_DATA_HOME:-"$HOME/.local/share"}/flinteye}")
  case "$profile/" in
    "$installed/"*) fail 'Move the FlintEye data directory outside the program directory before installing or removing the app.' ;;
  esac
  if [ -e "$user_destination" ] || [ -L "$user_destination" ]; then
    [ -d "$user_destination" ] && [ -O "$user_destination" ] && [ ! -L "$user_destination" ] &&
      [ -f "$user_destination/.flinteye-user-install" ] && [ ! -L "$user_destination/.flinteye-user-install" ] ||
      fail "This directory is not a FlintEye user installation: $user_destination"
    # The API can close just before the executable exits.
    local deadline=$((SECONDS + 5))
    while user_install_running "$installed"; do
      [ "$SECONDS" -lt "$deadline" ] ||
        fail 'Quit this FlintEye installation and wait for recordings to finish, then retry.'
      sleep 0.2
    done
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || fail '--version requires X.Y.Z'; version=$2; shift 2 ;;
    --no-start) start_app=0; shift ;;
    --package-directory) [ "$#" -ge 2 ] || fail '--package-directory requires an artifact folder'; package_directory=$2; shift 2 ;;
    --install-directory) [ "$#" -ge 2 ] || fail '--install-directory requires a macOS application folder'; install_directory=$2; shift 2 ;;
    --user) user_install=1; shift ;;
    --uninstall) uninstall=1; shift ;;
    --help|-h)
      printf '%s\n' 'Usage: bash install.sh [--version RELEASE] [--no-start]' \
        '       bash install.sh --user [--version RELEASE] [--no-start]  (Linux, no sudo)' \
        '       bash install.sh --user --uninstall                     (keeps settings and recordings)'
      exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done
[ "$(id -u)" -ne 0 ] || fail 'Run as your normal user. A system-wide Linux installation will request sudo when needed.'
os=$(uname -s)
[ "$uninstall" = 0 ] || [ "$user_install" = 1 ] || fail '--uninstall requires --user.'
if [ "$uninstall" = 0 ]; then
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-preview\.[1-9][0-9]{0,5})?$ ]] || fail 'Use a published release or pass --version X.Y.Z[-preview.N].'
fi
if [ "$user_install" = 1 ]; then
  [ "$os" = Linux ] || fail '--user is available only on Linux. The macOS installer already uses ~/Applications.'
  [ -z "$install_directory" ] || fail '--install-directory is available only on macOS.'
  user_parent="$HOME/.local/opt"
  user_destination="$user_parent/flinteye-user"
  if [ "$uninstall" = 1 ] && [ ! -e "$user_destination" ] && [ ! -L "$user_destination" ]; then
    printf 'FlintEye is already removed from %s. Settings and recordings are kept.\n' "$user_destination"
    exit 0
  fi
  command -v flock >/dev/null || fail 'flock (util-linux) is required for user installation and removal.'
  mkdir -p -- "$user_parent"
  exec 9>>"$user_parent/.flinteye-user.lock"
  flock -n 9 || fail 'Another FlintEye user installation or removal is in progress.'
  check_user_destination
  if [ "$uninstall" = 1 ]; then
    "$user_destination/FlintEye" --disable-autostart
    rm -rf -- "$user_destination"
    printf 'Removed %s. Settings and recordings are kept.\n' "$user_destination"
    exit 0
  fi
fi
application_version=${version%%-preview.*}
if [[ "$version" == *-preview.* ]]; then printf 'FlintEye %s — UNDER DEVELOPMENT; this is not a stable release.\n' "$version"; fi
command -v curl >/dev/null || fail 'curl is required.'
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) fail 'Only 64-bit Intel/AMD and ARM computers are supported.' ;;
esac
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
  if [ "$user_install" = 1 ]; then
    if [ "$kind" = deb ]; then
      command -v dpkg-deb >/dev/null || fail 'dpkg-deb is required to unpack the DEB.'
    else
      command -v rpm2cpio >/dev/null && command -v cpio >/dev/null ||
        fail 'rpm2cpio and cpio are required to unpack the RPM. Ask your administrator if they are missing.'
    fi
  else
    command -v sudo >/dev/null || fail 'sudo is required for system-wide installation. Use --user to install in your home directory.'
    if [ "$kind" = deb ]; then manager=apt-get; else manager=dnf; fi
    command -v "$manager" >/dev/null || fail "$manager is required."
  fi
else
  fail "Unsupported OS: $os"
fi
if [ "$user_install" = 0 ] && command -v pgrep >/dev/null && pgrep -x FlintEye >/dev/null; then
  fail 'Quit FlintEye using Stop monitoring and quit, then run this installer again.'
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/flinteye-install.XXXXXXXX")
mount_dir=''
user_stage=''
cleanup() {
  if [ -n "$mount_dir" ]; then hdiutil detach "$mount_dir" -quiet || true; fi
  rm -rf -- "$work"
  if [ -n "$user_stage" ]; then
    if [ -d "$user_stage/previous" ] && [ ! -e "$user_destination" ] && [ ! -L "$user_destination" ]; then
      if ! mv -T -- "$user_stage/previous" "$user_destination"; then
        printf 'Previous installation is available at %s\n' "$user_stage/previous" >&2
        return
      fi
    fi
    rm -rf -- "$user_stage"
  fi
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
elif [ "$user_install" = 1 ]; then
  user_stage=$(mktemp -d "$user_parent/.flinteye-stage.XXXXXXXX")
  unpacked="$user_stage/unpacked"
  mkdir -- "$unpacked"
  if [ "$kind" = deb ]; then
    dpkg-deb -x "$work/$asset" "$unpacked"
  else
    rpm2cpio "$work/$asset" | (cd "$unpacked" && cpio -idm --quiet --no-absolute-filenames)
  fi
  bundle="$unpacked/opt/flinteye"
  [ -d "$bundle" ] && [ ! -L "$bundle" ] && [ -x "$bundle/FlintEye" ] ||
    fail 'The package does not contain the Linux application.'
  if ! bundled_release=$("$bundle/FlintEye" --version); then
    fail 'The bundled app could not run. Check that the required Linux runtime libraries are installed.'
  fi
  [ "$bundled_release" = "$version" ] || fail 'The package contains a different FlintEye release.'
  printf '%s\n' "$version" > "$bundle/.flinteye-user-install"
  check_user_destination
  if [ -d "$user_destination" ]; then mv -T -- "$user_destination" "$user_stage/previous"; fi
  mv -T -- "$bundle" "$user_destination"
  printf 'Installed FlintEye %s for the current user at %s\n' "$version" "$user_destination"
  printf 'To remove after quitting: bash install.sh --user --uninstall\n'
  if [ "$start_app" = 1 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    "$user_destination/FlintEye" </dev/null 9>&- &
    "$user_destination/FlintEye" --headless --connection-info 9>&- ||
      printf 'After choosing a network in FlintEye, use the address shown in its setup window.\n'
  else
    printf 'Start FlintEye with: %q\n' "$user_destination/FlintEye"
    printf 'On a server, add --headless and open the address it prints.\n'
  fi
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
