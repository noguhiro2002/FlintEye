# Community distribution

[日本語](DISTRIBUTION.ja.md)

## User installation

The desktop package includes Python, the compiled Web UI, FFmpeg and MediaMTX.
Users do not install Python, Node.js, npm, or Docker.

On Windows, run the matching `FlintEye-<version>-windows-<arch>-setup.exe`. Launch
FlintEye from the installer or Start menu.

On macOS, copy `FlintEye.app` from the DMG into Applications and open it. On Linux,
install the DEB/RPM with the desktop package installer and open FlintEye.
Developer ID signing/notarization and
Windows publisher signing are not included in this community release. macOS may
require the app-specific **Privacy & Security → Open Anyway** action. Do not disable
OS-wide security. macOS bundles use a local ad-hoc integrity signature for ARM64.

Starting with preview 6, the desktop launcher opens the browser and passes one-use
setup authorization. Choose the `admin` password (12–1024 characters, entered twice).
If the window closes before setup finishes, choose **Open FlintEye** in the desktop
app. Use **Address and setup assistance** for manual token entry. The password is
hashed locally and omitted from installer arguments and logs.

The English getting-started guide can be skipped and reopened. Configure USB/IP cameras in Settings. Configure the `viewer`
password in **Settings → Runtime & access → Viewer access**; viewers cannot sign in until
that password exists. Changing it invalidates existing sessions.

The Settings interface is shared by Windows, macOS, Linux, Docker and source installations. Recording location, quota and retention are in **Settings → Recording**; update checks are in **Settings → General**. Older installers retain their embedded interface until rebuilt and reinstalled. For a local Apple Silicon build, follow the [DMG build guide](LOCAL_MACOS_BUILD.md).

Closing the browser leaves monitoring running. Windows/macOS desktop menus provide Open FlintEye, Start/Stop/Restart monitoring, logs, login startup and Quit FlintEye. Linux has a compact control window and a tray icon where supported. Stop monitoring keeps settings and the API available; Quit exits everything. The stop preference is remembered unless Always resume monitoring on startup is enabled. See [monitoring controls](MONITORING.md).

Login autostart belongs to the current desktop user and installation. Automatic sleep is inhibited while monitoring/finalizing, and released when stopped. Manual sleep/logout/shutdown interrupts monitoring. Linux inhibition requires a working systemd/logind session. Docker/systemd/headless execution creates no desktop controls or login registration.

FlintEye accepts local connections at `http://127.0.0.1:18080` by default. For access
from other LAN devices, put an HTTPS reverse proxy in front of that loopback endpoint;
proxy `/api` and `/media` with WebSocket support. Keep MediaMTX HTTP, RTSP and
management listeners on loopback. Do not publish the plain HTTP port to the LAN.
The local proxy must set `X-Forwarded-Proto: https` and preserve the external Host
header; forwarded headers are trusted only from `127.0.0.1` and `::1`. Allow UDP
8189 for WebRTC media between the installation host and viewer devices.

## Recording lifecycle

The default retention is 7 days. Initial quota is the smaller of 50 GB (decimal)
and half the selected folder's available bytes. This suggestion is saved, not
continuously resized. Users may change the quota. Storage selection is native on
the installation PC; remote administrators enter an absolute server path.

Whichever limit is reached first causes oldest completed recordings to be
removed. Seven days is a maximum, not a guarantee. The completion hook registers
segments in a SQLite inventory. Only those registered files, whose size and
mtime still match, may be deleted by FlintEye. Active/unregistered/imported files
are not deleted. MediaMTX's independent age deletion is disabled in this mode.
Playback copies now use a private, bounded temporary cache outside the recording
folder. `recording.playback_cache_max_bytes` defaults to 2 GB and can be raised
in Advanced JSON for larger segments. Cache writes preserve the configured free
space reserve plus 256 MB. A segment that cannot fit is rejected for playback;
original recordings remain available to the administrator for download.
Before upgrading a development installation that used `.playback_cache`
inside the recording folder, stop FlintEye and remove that old cache directory.
If the active folder disappears or free space remains below 1 GB after cleanup,
recording is paused and a banner is shown. It resumes when the condition clears.
Quota enforcement runs every 30 seconds and allows temporary overshoot by active
segments. Leave sufficient disk headroom. Imported/unregistered files may require
manual cleanup; a crash before a completion hook may leave such a file.

Changing the recording folder does not move recordings. Old folders retain their
own previous retention/quota settings. They remain visible by default. Disabling
**Show recordings from previous locations** hides their playback endpoints and
list entries, but does not stop retention. The same filename in different roots
has a different recording ID. Removing a disk makes its recordings unavailable;
reconnect it to access them again.

Settings, inventory, logs and recordings are outside the installation directory:

* Windows: `%LOCALAPPDATA%\FlintEye`
* macOS: `~/Library/Application Support/FlintEye`
* Linux desktop: `${XDG_DATA_HOME:-~/.local/share}/flinteye`
* systemd: `/var/lib/flinteye`
* Docker: `/data`

Application uninstall preserves data by default. The Windows uninstaller offers
a separate, default-No confirmation to erase the default user data folder.
To explicitly erase data on other platforms, stop FlintEye,
remove its login-autostart entry, and delete the chosen data/recording folders.
Never use `docker compose down -v` unless the persisted data should be deleted.

## Administrator deployments

### Docker (Linux x86-64 / ARM64)

For published images without cloning, follow the [Docker guide](DOCKER.md).
The commands below build a private development checkout.

```sh
docker compose -f deploy/compose.dev.yaml up -d --build
docker compose -f deploy/compose.dev.yaml exec flinteye cat /data/setup-token
```

Use an SSH tunnel (`ssh -L 18080:127.0.0.1:18080 <server>`) and open
`http://127.0.0.1:18080` to enter the one-use setup token and choose the admin
password. The token is stored with owner-only permissions and removed after
setup. It is not written to logs. This is also the initial account flow for a
headless systemd installation. The Compose files use Linux host networking for LAN
ONVIF discovery and WebRTC. Optional USB device/video-group mappings are shown in
that file. Docker Desktop USB support is not included. Use the release workflow to distribute the already-tested amd64/arm64 archives; do not rebuild during publication.

The data volume belongs to UID/GID 10001. Bind mounts must be writable by that
identity. Container folder paths are the paths inside the container; mount any
additional recording disks explicitly. The built image includes the MediaMTX
binary so the orchestrator owns its startup and shutdown.

### systemd

Install the native Linux bundle at `/opt/flinteye` and create a `flinteye` system
user/group. Install `packaging/flinteye.service` under `/etc/systemd/system/`.
The host `video` group is required for USB capture; adapt this on hosts that use
another device group.

For LAN HTTPS on a new service profile, set the network in the [systemd environment](LAN_ACCESS.md#network-selection-and-external-players-next-development-build) before the first start. USB microphones additionally require the host audio group.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now flinteye
sudo cat /var/lib/flinteye/setup-token
```

On the next development build, get the actual URL with `sudo -u flinteye /opt/flinteye/FlintEye --headless --data-dir /var/lib/flinteye --connection-info`. Open that address and enter the owner’s one-use code.

Desktop and systemd instances must not share a running data directory or ports.
The service starts without login; the desktop application starts after login.

### Remove a server deployment

For systemd, first run `sudo systemctl disable --now flinteye`. Remove the manually installed unit and your deployment's drop-ins, run `sudo systemctl daemon-reload`, then remove the package or dedicated program bundle. Keep `/var/lib/flinteye`, custom data and external recordings unless you explicitly want to erase them. [Complete systemd removal](STOP_AND_UNINSTALL.md#systemd)

For Docker, use the same Compose file, deployment directory and project options that started it. `docker compose down` keeps data; the [Docker removal guide](STOP_AND_UNINSTALL.md#docker-compose) provides the Desktop/development variants and optional image cleanup. [Data erasure and LAN trust cleanup](STOP_AND_UNINSTALL.md#permanently-erase-data-optional) are separate steps.

## Building installers

For automated builds, source/license archives and GHCR publication, use the [release guide](RELEASING.md).

Build separately on each target OS and CPU, using Python 3.14.10 on Windows/macOS
and Node.js 22. The Linux Docker builder compiles pinned Python 3.13.18 sources.
The existing source workflow (`tools/start_orchestrator_stack.py`) remains available.

Run `bash packaging/build_vendor.sh` with the [documented build tools](RELEASING.md#local-native-build).
This prepares `vendor/bin/ffmpeg[.exe]`, `vendor/bin/ffprobe[.exe]` and `vendor/bin/mediamtx[.exe]` for the target CPU,
plus notices, corresponding sources and build configuration. FFmpeg
must support `drawtext` and `libx264`. Bundle any runtime libraries required by
the chosen binaries. Do not mix an x86-64 binary into an ARM64 package.
FFmpeg and FFprobe must include the concat demuxer and HTTP/HTTPS/RTSP support.
Camera URLs are delivered through a private, single-input manifest instead of
process arguments. The build checks authenticated HTTP and RTSP ingestion,
probing and snapshots with the actual vendor binaries before packaging them.
Source installations use the same private-input path. Custom publisher URLs
containing credentials or query tokens are rejected; use the bundled loopback
MediaMTX publisher endpoint. Runtime credentials and private manifests rely on
the installation user's private profile/temp-directory ACLs on Windows.
HTTPS ONVIF endpoints must present a trusted certificate;
administrators using a private camera CA can supply its bundle through
`REQUESTS_CA_BUNDLE`.

```sh
python -m pip install -c packaging/constraints.txt -r requirements.txt -r packaging/requirements-build.txt
python packaging/build_bundle.py --vendor vendor
```

The bundle is in `dist/FlintEye`; macOS additionally produces an app and DMG.
The script records vendor hashes in `dist/vendor-sha256.json`. For Windows, run
Inno Setup 6 against `packaging/windows.iss` with `/DAppVersion=X.Y.Z /DAppArch=amd64`
(or `arm64`). For Linux, install nFPM and run:

```sh
VERSION=$(python packaging/release.py version) ARCH=amd64 nfpm package --config packaging/nfpm.yaml --packager deb --target dist/
VERSION=$(python packaging/release.py version) ARCH=amd64 nfpm package --config packaging/nfpm.yaml --packager rpm --target dist/
```

Use `ARCH=arm64` for ARM builds. Build RPMs on Rocky Linux 9 to avoid introducing
a newer glibc requirement; build DEBs against their minimum target. Linux desktop
systems need a graphical session, Tk/X11 libraries. Native
ARM64 availability of the complete toolchain must be verified before publishing.

Preview installers check for newer published previews or stable releases in Settings; stable installers ignore previews. Source checkouts are updated with Git. FlintEye never downloads or installs updates automatically, and checking for updates never restarts recording. Choose **Quit FlintEye**,
back up configuration/inventory, install the replacement package and restart.
Keep the previous package for rollback. Preserve all data directories/volumes.
Existing configuration is preserved during an upgrade. If an earlier development
installation has `api.host` set to `0.0.0.0`, change it to `127.0.0.1` and restart;
use the HTTPS proxy described above for LAN access. Remove the old shared
`.playback_cache` while FlintEye is stopped before resuming recording.

## Release acceptance matrix (not a claim of completed certification)

* Windows 10 22H2 and Windows 11: x86-64, ARM64.
* Ubuntu 24.04 LTS and subsequent tested LTS releases: x86-64, ARM64.
* Rocky Linux latest 9.x and 10.x: x86-64, ARM64.
* macOS 14 and later tested releases: Intel, Apple Silicon.
* Raspberry Pi 4/5: 64-bit Raspberry Pi OS; verify exact OS image before release.

For each target, test clean install without Python/Node, password setup/cancel,
USB and IP input, live video from a second LAN device, recording/playback,
non-ASCII user/folder names, folder change, volume removal, disk limits, login
autostart, browser close versus quit, duplicate launch, and upgrade/uninstall data
retention. Verify all external media listeners reject unauthenticated access.
Test Pi performance with real cameras; do not promise a uniform camera count.

## Validation and development status

**UNDER DEVELOPMENT.** This repository starts from a current source snapshot. Public installers and GHCR images are being prepared; old private artifacts are not public releases. Follow [Releases](https://github.com/noguhiro2002/FlintEye/releases) and the [Docker guide](DOCKER.md) for availability.

Automated checks cover setup/authentication, storage retention, playback boundaries, worker loading, media process cleanup, installer/release integrity and preview-version comparison. The frontend is compiled from the shared source for every platform. Native build jobs test installed packages with synthetic media; they cannot certify real camera behavior or every minimum OS.

Before public preview distribution, complete the [acceptance checklist](ACCEPTANCE.md) on Windows x64, M1 Mac and Linux x64, and review the corresponding sources/licenses. Keep untested targets and [known UI issues](KNOWN_ISSUES.md) explicit. Closing the browser keeps monitoring active; explicit application quit must stop owned API and media processes.
