# Install FlintEye

[日本語](INSTALL.ja.md)

[Documentation](README.md)

**UNDER DEVELOPMENT.** Install **1.2.0-preview.5** from the [Quick Install commands](../README.md#quick-install) or [the matching release](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.2.0-preview.5). Both routes use the same tested application. Check **Information → System** for the exact preview and source commit. Automated package checks passed; physical-device acceptance is still in progress. Older downloaded 1.1.3 installers and scripts remain pinned to that older version. [Source setup](MANUAL_INSTALL.md), [local M1 DMG builds](LOCAL_MACOS_BUILD.md) and [development Docker](DOCKER.md#build-the-development-image) remain available.

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

- **Windows:** open the EXE and follow setup. The current build opens the browser for your admin password. Installation is per-user and creates a Start menu entry.
- **macOS:** open the DMG, drag FlintEye into Applications, and open it. The one-command installer uses your personal `~/Applications` folder.
- **Linux:** open the DEB/RPM with your package manager, then launch FlintEye from the application menu. Package installation needs administrator privileges.

The command installers select the CPU, download the package for one fixed release, and verify its SHA-256.
They do not compile software on your computer. Quit a running FlintEye instance before upgrading.
For an unattended Linux server, install without launching the desktop UI and follow the [systemd guide](DISTRIBUTION.md#systemd).

## Included media tools and macOS recovery

### Screen Recording requests in older previews

FlintEye does not record your desktop. Older camera discovery included FFmpeg's `Capture screen` inputs and opened them while querying camera modes, causing repeated **Screen Recording** permission dialogs. In **1.2.0-preview.3**, screen inputs are excluded before probing. Saved camera indices are checked before capture too, so a removed camera cannot make its old index select the screen. OBS virtual cameras remain supported as camera inputs. You do not need to grant Screen Recording permission to FlintEye; microphone access is separate and is used only when camera audio is enabled. Confirm absence of repeated prompts on your Mac as part of physical-device QA.

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

If Finder reports **The file can't be found** but `Contents/MacOS/FlintEye` exists, an OS trust rejection is also possible. In the reported M1 case, the executable and bundle signature were valid, while `amfid` rejected the ad-hoc signature and direct execution ended with exit 137. Try the per-app approval above. Missing notarization is not repaired by reinstalling MediaMTX or deleting accounts/settings. Installer messages distinguish file installation, the launch request and first-launch permission. The build-time tests confirm the same OS refusal on macOS CI and leave the installed API/GUI checks not run until approval. See [installation lifecycle checks](INSTALLATION_QA.md).

## Install a specific version

Download the installer or command script directly from the exact preview release. Preview releases are not returned by GitHub’s `releases/latest` URL.

Download `install.sh` or `install.ps1` from that release and run it locally.
Each generated script pins its own release version. Optional `--version 1.2.0-preview.5` (shell) or `-Version 1.2.0-preview.5` (PowerShell) selects that exact development release; `X.Y.Z` selects a stable release when available. The tag includes the preview suffix, while installer filenames use the numeric application version (`1.2.0`). `--no-start` / `-NoStart` installs without launching the application.

Packages include the application runtime and media tools. Linux desktop packages also ask the system package manager to install any required desktop libraries.

## Update and remove

The same removal method applies whether a one-command script, an Actions artifact or a binary installer installed the native package. Start with the [README removal table](../README.md#uninstall), then follow [your installation method](STOP_AND_UNINSTALL.md#remove-by-installation-method) for the full steps. macOS script installs normally go to `~/Applications`; dragging from the DMG normally installs to `/Applications`. A custom install folder must be removed at its actual location.

The guide covers Windows 10/11, Linux DEB/RPM, Docker, systemd and source environments. Normal removal retains accounts, settings and recordings; [permanent data erasure](STOP_AND_UNINSTALL.md#permanently-erase-data-optional) is a separate choice.

See [Stop and uninstall FlintEye](STOP_AND_UNINSTALL.md) for complete shutdown, Windows uninstall behavior, program/data locations and recovery from older installers that leave processes running.

Choose **Quit FlintEye** before updating. Back up configuration/inventory and keep the previous installer for rollback.
Install the replacement package and restart. User data is outside the installation directory.
If you are moving between Linux previews with the same package version, run the command installer from the new release. It asks the package manager to reinstall from the downloaded archive.
The macOS command installer retains the previous app as `FlintEye.previous.app`; move that backup aside before a subsequent upgrade.

Normal removal keeps recordings and settings. The Windows uninstaller offers a separate default-No data deletion prompt.
See [data locations](DISTRIBUTION.md#recording-lifecycle) before manually removing data.


## 1.2.0 development installer checks

On first launch, choose a trusted network. Starting with 1.2.0-preview.6, the desktop app passes setup authorization to the local browser so you can set the administrator password directly. Use **Open FlintEye** to resume setup. **Address and setup assistance** shows the manual token, the local address and, when available, the active HTTPS address and certificate guide. With a retained profile, sign in with the existing account. Use the matching artifact for both one-command and standalone installation. [1.2.0 acceptance checklist](RELEASE_CHECKLIST_1_2_0.md) · [LAN setup](LAN_ACCESS.md)
