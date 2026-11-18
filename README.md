# 🚧 UNDER DEVELOPMENT

**FlintEye is under active development. This is a development preview, not a stable release. Use development previews for testing.**

The current development build is **1.2.0-preview.3**. Get its test installers from [GitHub Actions](https://github.com/noguhiro2002/FlintEye/actions/workflows/build-release.yml) after the build succeeds. **The published 1.1.3-preview.1 scripts install the older app; they do not include the 1.2.0 setup, icon or network-stream changes.**

[Known issues](docs/KNOWN_ISSUES.md) · [Report a bug](https://github.com/noguhiro2002/FlintEye/issues) · [Questions and ideas](https://github.com/noguhiro2002/FlintEye/discussions)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/FlintEyeLogo-white.png">
    <source media="(prefers-color-scheme: light)" srcset="images/FlintEyeLogo.png">
    <img src="images/FlintEyeLogo-white.png" alt="FlintEye" width="520">
  </picture>
</p>
<p align="center"><strong>Your cameras. Your recordings. Your computer.</strong><br>
Monitor USB and IP cameras, watch live video, and find recordings in your browser.</p>
<p align="center">
  <a href="docs/RELEASING.md"><img src="https://img.shields.io/badge/status-UNDER_DEVELOPMENT-orange" alt="Development preview"></a>
  <a href="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml"><img src="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml/badge.svg" alt="Checks"></a>
  <a href="docs/INSTALL.md"><img src="https://img.shields.io/badge/targets-Windows_%7C_macOS_%7C_Linux-blue" alt="Platform targets"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-SUL_%2B_permission-green" alt="Sustainable Use License plus additional permission"></a>
</p>
<p align="center"><a href="README.ja.md">日本語</a> · <a href="docs/README.md">Documentation</a> · <a href="https://github.com/noguhiro2002/FlintEye/releases">Downloads</a></p>

![Live View, two-camera Multiview, and recording playback](images/camera-workflow.gif)

*Two real USB cameras: **Live View → Multiview → Recordings**. Captured on Linux from the current development build. [Watch/download the MP4](images/camera-workflow.mp4?raw=true).*

## Quick Install

### Test the current fixes: 1.2.0-preview.3

1. Open a successful **Build release** run for **1.2.0-preview.3** in [GitHub Actions](https://github.com/noguhiro2002/FlintEye/actions/workflows/build-release.yml). Download and extract the artifact for your computer: `build-macos-arm64` for an Apple Silicon Mac, `build-macos-amd64` for an Intel Mac, or `build-windows-ARCH` / `build-linux-ARCH`. GitHub requires sign-in to download Actions artifacts.
2. Quit your existing FlintEye, open a terminal in the extracted folder, and run the command below. These scripts use the downloaded package and its checksum; they do not download the older public release.

| Computer | Command in the extracted folder |
| --- | --- |
| macOS / Linux | `bash ./install.sh --package-directory .` |
| Windows PowerShell | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PackageDirectory .` |

Alternatively, open the EXE, DMG, DEB or RPM from that same folder. In the app, check **Information → System** for `1.2.0-preview.3`. Then follow [Quick Usage](#quick-usage). [Removal instructions](#uninstall) apply to either route.

<details>
<summary><strong>Older public preview: 1.1.3-preview.1 — online one-command installation</strong></summary>

**Development preview: [v1.1.3-preview.1](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.1.3-preview.1).** The commands below work once that release lists its download assets. Real-device acceptance is still in progress. Run the command for your computer and follow setup. Python, FFmpeg, FFprobe and MediaMTX are included; no Git checkout or compilation is needed.

**Windows — PowerShell**

```powershell
irm https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.ps1 | iex
```

**macOS — Terminal**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.sh
```

**Linux — Terminal**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.sh
```

You can also download the script from the selected release, inspect it, and run it locally. Packaged builds include Python, FFmpeg, FFprobe and MediaMTX. No separate copies are required. Windows/macOS packages are unsigned/not notarized; see [OS confirmation screens](docs/INSTALL.md#unsigned-packages).

</details>

<details>
<summary><strong>Other Install Options</strong> — binary packages, Docker, manual installation</summary>

- **Binary packages:** Windows EXE, macOS DMG, Linux DEB/RPM. [Installation guide →](docs/INSTALL.md)
- **Docker Compose:** use the versioned GHCR image for Linux x86-64 and ARM64. [Docker guide →](docs/DOCKER.md)
- **systemd:** run continuously on a Linux server, without desktop login. [Server guide →](docs/DISTRIBUTION.md#systemd)
- **Manual install:** run from source for development or customization. [Developer setup →](docs/MANUAL_INSTALL.md)

A pip application package is not part of the first release.

</details>

### After installing

| Method | Where to start |
| --- | --- |
| One-command install | Follow the installer's prompt. If FlintEye did not open, launch it as shown below. |
| Binary installer | Windows: Start → FlintEye. macOS: drag FlintEye into Applications, then open it. Linux desktop: Applications → FlintEye. |
| Docker Compose | Start the container and retrieve its browser address and setup instructions. [Docker setup →](docs/DOCKER.md#install-without-cloning) |
| Linux server | Start the systemd service and retrieve the address printed at startup. [Server setup →](docs/DISTRIBUTION.md#systemd) |

Then continue with [Quick Usage](#quick-usage).

## Quick Usage

1. **Open the address shown by FlintEye.** On the computer running FlintEye, open the local browser address. A new build from this branch also offers a choice of trusted network and shows the HTTPS address when it is ready. On another device, [trust the installation's certificate](docs/LAN_ACCESS.md) before opening that address. Public v1.1.3 uses the local setup flow.
2. **Create your administrator account.** Enter the one-use code from the setup window or the server's private token file, and set the password in your browser. Sign in as `admin`.
3. **Add a camera in Settings.** Follow the getting-started tour for USB and IP cameras.
4. **Open Live View.** Enable recording if needed, then open **Recordings** to play saved footage.

<details>
<summary>Five-step first-run guide</summary>

![FlintEye's five-step English first-run guide](images/getting-started.gif)

*UI tour: FlintEye 1.1.3 source with the 2026-11-15 QA fixes, using a demo profile with no cameras. This illustrates the five-step guide, not installation, real recording, shutdown or uninstall. [Download the full-resolution MP4](images/getting-started.mp4?raw=true).*

</details>

Recordings stay on your computer. Initial limits are **7 days** and **up to 50 GB** (or half the available disk space, whichever is smaller). Reaching either limit removes the oldest completed recordings. Change the folder and limits in Settings.

Closing the browser keeps monitoring running. Use **Stop monitoring** to pause cameras while keeping settings open, or **Quit FlintEye** in the desktop menu to exit completely. [Status colors and startup preferences →](docs/MONITORING.md)

<details>
<summary>Linux server / SSH — after package installation</summary>

Start as your normal server user:

```sh
/opt/flinteye/FlintEye --headless
```

Read `setup-token` in the data directory printed at startup, using another SSH session. On your own computer open a tunnel:

```sh
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 your-server
```

Open `http://127.0.0.1:18080` locally and enter the token to create the administrator account. If that local port is in use, change the left-hand forwarding port and the browser URL. This tunnel carries the HTTP management connection; it does not forward WebRTC UDP video. Stop the foreground server with Ctrl+C and wait for recordings to finish. For operation after SSH disconnect, follow [systemd setup](docs/DISTRIBUTION.md#systemd), which uses its own service user and `/var/lib/flinteye`. Do not run manual and service instances on the same port or profile.

</details>

<details>
<summary>1.2.0 development: other PCs and phones on your LAN</summary>

The source for the next development version adds opt-in HTTPS at `https://SERVER-IP:18080`, with one-time certificate trust on each viewing PC/iPhone/iPad/Android device. **Public 1.1.3 does not include this feature.** See [LAN connection and trust](docs/LAN_ACCESS.md) and [1.2.0 changes and acceptance status](docs/DEVELOPMENT_1_2_0.md) before testing a rebuilt package.

</details>

[Full user guide →](docs/USER_GUIDE.md)

## Uninstall

Settings and recordings are kept by default. Quit FlintEye completely before removing it; closing the browser leaves monitoring running.

| Installation | Remove the application |
| --- | --- |
| Windows script or EXE | **Settings → Apps → Installed apps → FlintEye → Uninstall**. |
| macOS script | Menu-bar icon → **Disable start at login and quit**, then move `~/Applications/FlintEye.app` to Trash. Remove `FlintEye.previous.app` there too if you no longer need the rollback copy. |
| macOS DMG | Same quit action, then move `/Applications/FlintEye.app` to Trash (or the location you chose). |
| Linux script or DEB/RPM | Disable login startup, quit, then `sudo apt-get remove flinteye` or `sudo dnf remove flinteye`. |
| Docker Compose | From the deployment folder, `docker compose down`. For Docker Desktop, `docker compose -f deploy/compose.desktop.yaml down`. Keep the data volume. |
| systemd / source | Stop and disable the service first; then remove the package or dedicated source environment after preserving any data inside it. |

[Complete removal commands, data locations and old-installation recovery →](docs/STOP_AND_UNINSTALL.md)


## Documentation

Visit our **[documentation](docs/README.md)** to learn more about how to use FlintEye.

| Get started | Operate a server | Build and contribute |
| --- | --- | --- |
| [Install](docs/INSTALL.md) | [Docker Compose](docs/DOCKER.md) | [Source setup](docs/MANUAL_INSTALL.md) |
| [Cameras and recordings](docs/USER_GUIDE.md) | [LAN access and systemd](docs/DISTRIBUTION.md) | [Build and release](docs/RELEASING.md) |

<details>
<summary><strong>Developer demo: Swagger API → WebRTC</strong></summary>

![Calling the camera API in Swagger, then opening its WebRTC view](images/api-webrtc.gif)

Open `/docs` after signing in, try `GET /api/v1/viewer/cameras`, then open the returned `addresses.webrtc_url` on the same FlintEye server. The demo uses a real USB camera and an authenticated local session. [Watch/download the developer MP4](images/api-webrtc.mp4?raw=true).

</details>

## License

FlintEye is **source available**, under the [Sustainable Use License with additional permission](LICENSE). Individuals and nonprofit or for-profit organizations, including universities, public research institutes and companies, may use and modify it for personal or internal purposes. Service providers may charge for installation, configuration, modification, operation and maintenance on customer-owned or customer-controlled infrastructure, including the customer's contracted cloud environment, and supply necessary copies without charging for FlintEye itself. Selling FlintEye or a modified version, or offering it as a paid hosted service, requires a separate license. [Examples and third-party licenses →](docs/LICENSING.md)

## Acknowledgements

- **[FFmpeg](https://ffmpeg.org/)** — camera capture, video processing, and playback conversion. Our libx264-enabled builds are GPL-licensed; release assets include corresponding source and build instructions.
- **[MediaMTX](https://github.com/bluenviron/mediamtx)** — media transport and recording, under the MIT license.

Third-party components retain their original licenses and are excluded from FlintEye's commercial restrictions. See [third-party notices](THIRD_PARTY_NOTICES.md).
