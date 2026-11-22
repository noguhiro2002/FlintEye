# 🚧 UNDER DEVELOPMENT

**FlintEye is under active development. This is a development preview, not a stable release. Use development previews for testing.**

The current development preview is **1.2.0-preview.8**. Install it with the Quick Install commands below. On macOS, follow the first-launch approval instructions. The [development preview validation checklist](docs/RELEASE_CHECKLIST_1_2_0.md) records completed automated checks and remaining real-device tests.

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

[Installing without administrator privileges?](#install-without-administrator-privileges)

**Development preview: [v1.2.0-preview.8](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.2.0-preview.8).** Real-device acceptance is still in progress. Run the command for your computer and follow setup. Python, FFmpeg, FFprobe and MediaMTX are included; no Git checkout or compilation is needed.

**Windows — PowerShell**

```powershell
irm https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.8/install.ps1 | iex
```

**macOS — Terminal**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.8/install.sh
```

**Linux — Terminal**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.8/install.sh
```

You can also download the script from the selected release, inspect it, and run it locally. Packaged builds include Python, FFmpeg, FFprobe and MediaMTX. No separate copies are required. Windows/macOS packages are unsigned/not notarized; see [OS confirmation screens](docs/INSTALL.md#unsigned-packages).

**macOS first launch:** after trying to open this community preview, use **System Settings → Privacy & Security → Open Anyway → Open** if offered. The app is ad-hoc signed and not notarized; installation alone does not grant permission to run it. [If macOS says the file cannot be found →](docs/INSTALL.md#unsigned-packages)

<a id="install-without-administrator-privileges"></a>
### Install without administrator privileges

- **Windows** — Run the EXE or PowerShell installer from your normal account. FlintEye goes into `%LOCALAPPDATA%\Programs\FlintEye`. Open it from Start. To remove it, quit FlintEye, then use **Settings → Apps → FlintEye → Uninstall** and keep the default choice to retain data.
- **macOS** — Run the shell installer from your normal account or copy `FlintEye.app` from the DMG into your personal `~/Applications` folder. Open that copy and follow the first-launch instructions if prompted. To remove it, choose **Disable start at login and quit** in the menu bar, then move that copy to Trash. Managed Macs may require IT approval for launch. [First-launch instructions](docs/INSTALL.md#unsigned-packages)
- **Linux** — Download the script and run the command below. For a matching Actions artifact, extract the ZIP and add `--package-directory .` from the extracted folder. [Download install.sh](https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.8/install.sh)

```sh
bash ./install.sh --user
```

On supported Ubuntu, Debian and 64-bit Raspberry Pi OS systems the script uses `dpkg-deb`. On supported Rocky, AlmaLinux and RHEL systems it uses `rpm2cpio` and `cpio`. The host needs the package's [runtime libraries](packaging/nfpm.yaml) already installed. The script puts the app in `~/.local/opt/flinteye-user`. Start it with `"$HOME/.local/opt/flinteye-user/FlintEye"` and open the address it shows. On a server add `--headless` and stop it with Ctrl+C.

After quitting, run `bash ./install.sh --user --uninstall` with the same script. Keep data outside the program folder. The default profile is `$XDG_DATA_HOME/flinteye`, or `~/.local/share/flinteye` if `XDG_DATA_HOME` is unset. If you use a custom profile, disable its start-at-login entry before removing the app.

For local use choose **This computer only**. USB cameras and microphones need permission for your OS account. Access from other devices can require administrator-managed firewall and certificate settings. [LAN and VPN guide](docs/LAN_ACCESS.md)


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
| Linux `--user` | Run `"$HOME/.local/opt/flinteye-user/FlintEye"` and open its browser address. |
| Binary installer | Windows: Start → FlintEye. macOS: drag FlintEye into Applications, then open it. Linux desktop: Applications → FlintEye. |
| Docker Compose | Start the container and retrieve its browser address and setup instructions. [Docker setup →](docs/DOCKER.md#install-without-cloning) |
| Linux server | Start the systemd service and retrieve the address printed at startup. [Server setup →](docs/DISTRIBUTION.md#systemd) |

Then continue with [Quick Usage](#quick-usage). To remove an installation later, see [Uninstall](#uninstall).

## Quick Usage

1. **Open the address shown by FlintEye.** On the computer running FlintEye, open the local browser address. Choose a trusted network at first launch; FlintEye shows the HTTPS address when it is ready. On another device, [trust the installation's certificate](docs/LAN_ACCESS.md) before opening that address.
2. **Create your administrator account.** With a desktop installation, set your password in the browser opened by FlintEye. If you closed it, choose **Open FlintEye** in the app menu to resume. With Docker or a headless server, enter the one-use code from the server's private `setup-token` file. Sign in as `admin`.
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

This development preview includes opt-in HTTPS at `https://SERVER-IP:18080`, with one-time certificate trust on each viewing PC/iPhone/iPad/Android device.  See [LAN connection and trust](docs/LAN_ACCESS.md) and [1.2.0 changes and acceptance status](docs/DEVELOPMENT_1_2_0.md) when testing the preview package.

</details>

[Full user guide →](docs/USER_GUIDE.md)

## Uninstall

**Accounts, settings and recordings are kept by default.** Quit FlintEye completely before removing it. Closing the browser or choosing **Stop monitoring** leaves the application running.

| Installation | Remove the application |
| --- | --- |
| Windows script / EXE / Actions package | Windows 11: **Settings → Apps → Installed apps**. Windows 10: **Settings → Apps → Apps & features**. Select **FlintEye → Uninstall**; keep the default data-retention choice. |
| macOS script | Menu-bar icon → **Disable start at login and quit**, then move `~/Applications/FlintEye.app` to Trash (or use your custom install folder). Remove `FlintEye.previous.app` too if you no longer need the rollback copy. |
| macOS DMG / locally built DMG | Choose **Disable start at login and quit**, then move `/Applications/FlintEye.app` to Trash, or remove it from the folder you chose. |
| Linux `--user` | Run `bash ./install.sh --user --uninstall` with the installer you downloaded. |
| Linux script / DEB | Disable login startup, quit, then run `sudo apt-get remove flinteye`. |
| Linux script / RPM | Disable login startup, quit, then run `sudo dnf remove flinteye`. |
| Docker Engine, downloaded `compose.yaml` | In the original deployment folder, run `docker compose down`. |
| Docker Desktop, downloaded `compose.desktop.yaml` | In the original deployment folder, run `docker compose -f compose.desktop.yaml down`. For a source checkout use `-f deploy/compose.desktop.yaml` instead. |
| Development Docker | From the checkout root, run `docker compose -f deploy/compose.dev.yaml down`. |
| systemd | Run `sudo systemctl disable --now flinteye`, then [remove the manually installed service and application](docs/STOP_AND_UNINSTALL.md#systemd). |
| Manual source / virtual environment | Disable any login startup, stop the launcher/terminal processes or service, then preserve data before removing the dedicated checkout and virtual environment. [Source removal →](docs/STOP_AND_UNINSTALL.md#manual-source-and-virtual-environment) |

Native app removal also removes its bundled Python/FastAPI, FFmpeg, FFprobe and MediaMTX. Docker keeps its data volume and cached image after `down`; see [Docker removal](docs/STOP_AND_UNINSTALL.md#docker-compose). Data erasure is a separate, explicit choice.

[Full removal guide: data locations, optional data erasure, startup recovery and LAN certificate removal →](docs/STOP_AND_UNINSTALL.md)


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
