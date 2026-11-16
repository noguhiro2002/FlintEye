# Install FlintEye

[日本語](INSTALL.ja.md)

[Documentation](README.md)

**UNDER DEVELOPMENT.** Install the [1.1.3 development preview](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.1.3-preview.1) using a package or the [Quick Install command](../README.md#quick-install). Downloads are ready when the linked release lists its assets. They are provided for installation-path and physical-device testing, not as a stable release. Automated checks passed; real-device acceptance is still in progress. [Source setup](MANUAL_INSTALL.md), [local M1 DMG builds](LOCAL_MACOS_BUILD.md) and [development Docker](DOCKER.md#build-the-development-image) remain available. See [acceptance checks](ACCEPTANCE.md) and [known issues](KNOWN_ISSUES.md).

## Choose a package

| System | Package | Minimum target |
| --- | --- | --- |
| Windows x64 / ARM64 | `FlintEye-VERSION-windows-ARCH-setup.exe` | Windows 10 22H2; Windows 11 |
| macOS Intel / Apple Silicon | `FlintEye-VERSION-macos-ARCH.dmg` | macOS 14 |
| Ubuntu x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.deb` | Ubuntu 24.04 |
| Rocky Linux x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.rpm` | Rocky Linux 9 / 10 |
| Raspberry Pi 4 / 5 | ARM64 DEB | 64-bit Raspberry Pi OS Bookworm or newer tested release |

ARCH is `amd64` or `arm64`. These are acceptance targets, not a claim that all have been tested.
32-bit systems are unsupported. Camera count and performance depend on the hardware and streams.

## Desktop installation

- **Windows:** open the EXE, follow setup, and choose your admin password. Installation is per-user and creates a Start menu entry.
- **macOS:** open the DMG, drag FlintEye into Applications, and open it. The one-command installer uses your personal `~/Applications` folder.
- **Linux:** open the DEB/RPM with your package manager, then launch FlintEye from the application menu. Package installation needs administrator privileges.

The command installers select the CPU, download the package for one fixed release, and verify its SHA-256.
They do not compile software on your computer. Quit a running FlintEye instance before upgrading.
For an unattended Linux server, install without launching the desktop UI and follow the [systemd guide](DISTRIBUTION.md#systemd).

## Included media tools and macOS recovery

Desktop packages include **MediaMTX, FFmpeg and FFprobe**. No separate Homebrew or MediaMTX installation is required. In the macOS app, the executables are in `FlintEye.app/Contents/Frameworks/bin/`. Earlier private ARM64 builds were inspected and contained all three.

Earlier private 1.1.0/1.1.1 macOS installers (not public downloads) can retain a temporary `AppTranslocation` path in saved settings. After that directory disappears, MediaMTX cannot start even though it is bundled. The UI may show **Media server is unavailable**, and camera publishers may repeatedly restart, switching a USB camera on and off. This matches an `orchestrator.log` entry containing `failed to start mediamtx:direct`, `FileNotFoundError`, and an old `AppTranslocation` path. An absent `mediamtx.log` is possible because the process never started.

For these existing installers:

1. Quit FlintEye using its menu-bar icon. Place the complete `FlintEye.app` in `/Applications`, eject the DMG, and open the installed app. Closing the browser alone does not stop FlintEye.
2. Sign in as administrator and open **Settings → Advanced**. In the runtime JSON, change only the first item of `mediamtx.direct.command` to `/Applications/FlintEye.app/Contents/Frameworks/bin/mediamtx`. Keep the second item (your `mediamtx.yml` path) and all other settings unchanged. For a personal Applications folder, use the full `/Users/YOUR_NAME/Applications/...` path, not `~`.
3. Click **Replace Runtime & Restart**. Check the MediaMTX status and retry Live View, recording and playback. Keep the app at that location while using this workaround.

Do not delete `runtime.json` or the data directory to recover: they contain your accounts and settings. Logs are under `~/Library/Application Support/FlintEye/logs/` unless you chose another data directory. If startup still fails, inspect `orchestrator.log` and, if present, `mediamtx.log` for the new error.

The source fix resolves the bundled executable from the current app location on every launch and preserves user settings. It also stops saving a temporary executable path for login autostart. These fixes are included in the 1.1.3 preview installers. Native automated package checks passed; physical-camera and quarantined first-launch acceptance remain separate checks. Old private installer files are unchanged.

To test the updated source on your own M1 Mac without GitHub Actions, follow the [local DMG build guide](LOCAL_MACOS_BUILD.md). It includes the startup repair and consolidated Settings interface, and keeps existing release downloads unchanged.

## Unsigned packages

Initial Windows packages have no publisher signature. Check that you downloaded the expected package from this repository.
If Windows permits it, use the per-application confirmation presented by SmartScreen.

macOS preview packages use an ad-hoc integrity signature, without Developer ID notarization. The build now rejects invalid bundle signatures, including the test/debug binaries accidentally copied into older license bundles. A valid ad-hoc signature still does not establish a trusted publisher: a Gatekeeper rejection is expected on a clean machine. A downloaded app's first launch remains an explicit acceptance check. See [Apple's explanation of app checks](https://support.apple.com/102445) and [signature verification](https://developer.apple.com/library/archive/technotes/tn2206/).
After attempting to open the app, macOS may require **System Settings → Privacy & Security → Open Anyway**.
Do not disable Gatekeeper globally or remove quarantine attributes in an installer script.
Managed computers may require help from their administrator.

## Install a specific version

Download the installer or command script directly from the exact preview release. Preview releases are not returned by GitHub’s `releases/latest` URL.

Download `install.sh` or `install.ps1` from that release and run it locally.
Each generated script pins its own release version. Optional `--version 1.1.3-preview.1` (shell) or `-Version 1.1.3-preview.1` (PowerShell) selects that exact development release; `X.Y.Z` selects a stable release when available. The tag includes the preview suffix, while installer filenames use the numeric application version (`1.1.3`). `--no-start` / `-NoStart` installs without launching the application.

Packages include the application runtime and media tools. Linux desktop packages also ask the system package manager to install any required desktop libraries.

## Update and remove

See [Stop and uninstall FlintEye](STOP_AND_UNINSTALL.md) for complete shutdown, Windows uninstall behavior, program/data locations and recovery from older installers that leave processes running.

Choose **Quit FlintEye** before updating. Back up configuration/inventory and keep the previous installer for rollback.
Install the replacement package and restart. User data is outside the installation directory.
The macOS command installer retains the previous app as `FlintEye.previous.app`; move that backup aside before a subsequent upgrade.

Normal removal keeps recordings and settings. The Windows uninstaller offers a separate default-No data deletion prompt.
See [data locations](DISTRIBUTION.md#recording-lifecycle) before manually removing data.


## 1.2.0 development installer checks

The next development build uses the browser for the administrator password form. The native setup window provides the local URL and a one-use token with copy actions. It does not reset an existing account after reinstalling. Compare one-command and standalone installers using clean, retained and unfinished profiles. Linux automatic installation checks sudo and the package manager before downloading. Windows removal first finishes recordings and checks the uninstall-data lock; a reported lock is not permission to delete unins000.dat. See [1.2.0 acceptance](DEVELOPMENT_1_2_0.md) and [LAN setup](LAN_ACCESS.md). The published 1.1.3 installers remain unchanged.
