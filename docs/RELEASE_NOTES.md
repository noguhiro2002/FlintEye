# FlintEye @TAG@ — @STATUS@

[日本語](RELEASE_NOTES.ja.md)

Application version: `@VERSION@` · Source commit: `@COMMIT@` · Build run: `@RUN_ID@`

@VALIDATION@

## Downloads

Download the installer for your system from this release's Assets:

| Computer | Installer |
| --- | --- |
| Windows x64 / ARM64 | `FlintEye-@VERSION@-windows-amd64-setup.exe` / `FlintEye-@VERSION@-windows-arm64-setup.exe` |
| macOS Intel / Apple Silicon | `FlintEye-@VERSION@-macos-amd64.dmg` / `FlintEye-@VERSION@-macos-arm64.dmg` |
| Ubuntu / Raspberry Pi OS (64-bit) | `FlintEye-@VERSION@-linux-amd64.deb` / `FlintEye-@VERSION@-linux-arm64.deb` |
| Rocky Linux | `FlintEye-@VERSION@-linux-amd64.rpm` / `FlintEye-@VERSION@-linux-arm64.rpm` |

Windows packages have no publisher signature. macOS apps have an ad-hoc integrity signature, without Developer ID signing or notarization. Follow the per-application OS confirmation in `documentation.zip`. Choose **Quit FlintEye** before upgrading; settings and recordings are retained. Camera access, recording, playback, tray/GUI behavior and minimum-OS support still need the applicable real-device acceptance checks.

The archives include English/Japanese installation and acceptance guides, the exact applicable LICENSE, third-party notices and corresponding sources. `SHA256SUMS` covers every attached file except itself; `build-manifest.json` records the original tested bundle. `distribution-manifest.json` identifies this release's selected files and GHCR image digests. Public one-command installation scripts are omitted from private testing releases.

`documentation.zip` includes the [Windows and macOS runtime notices](licenses/README.md).

## Container

Use `ghcr.io/noguhiro2002/flinteye:@IMAGE_VERSION@` for `linux/amd64` or `linux/arm64`. Public images allow anonymous pulls; private testing requires authorized GHCR login. Preview images have no container `latest` tag. Use the attached `compose.yaml` and the Docker guide in `documentation.zip`.

## Changes in this version

- Settings opens in **Basic** for cameras, recording, Multiview and access. **Advanced** holds detailed options and shares the same unsaved changes. The theme menu offers System, Light and Dark. Reopen Getting started from **Information** after the first run. [Illustrated first-run guide (Japanese)](PREVIEW_10_FIRST_RUN.ja.md)
- LAN and VPN setup shows when a restart is pending and displays the active HTTPS address once it is ready. The connection guide covers installing the FlintEye CA on viewing devices and connecting through Tailscale. [LAN and VPN guide](LAN_ACCESS.md)
- On Linux, USB discovery identifies capture devices and explains when access is denied, a device is busy or no capture modes are available. Reassign a replacement device while keeping the saved camera and its recording history.
- Live video and controls are easier to reach on narrow screens. Recording filters collapse on phones, long names wrap, and playback controls fit in landscape. Multiview includes a font for Japanese camera labels.
- Saved event recordings play while the loop recording index is being updated.
- The Linux quick-install command downloads and runs the pinned installer for the current user. The Actions checks and the local verification command share the same test definitions. [Installation guide](INSTALL.md) [Test inventory](testing/CI_ACCEPTANCE.md)

## Earlier previews

The paths below describe the corresponding earlier previews. For current settings locations, use the [Preview 10 user guide](USER_GUIDE.md).

- Multiview uses the same sources for its video and camera list. Automatic layouts place two cameras side by side. Set positions for the live and recorded composite in **Settings → Multiview → Camera layout**.
- Live audio waits for the camera stream to publish an audio track and keeps the main video available. ONVIF checks candidate endpoints and reports connection, trust and authentication failures.
- Camera audio controls take less space, the active recording tab is highlighted, and the MediaMTX RTSP URL fields align.
- Slow thumbnails leave room for recording playback requests. Event recordings remain available during brief recording index updates.
- Issue and revoke REST API keys in **Runtime & access**. The same section guides iPhone users through LAN certificate trust. The Linux and macOS script explains how to retry a download when staging writes fail. [Preview 8 findings and Preview 9 regressions (Japanese)](testing/PREVIEW_8_FINDINGS.ja.md)

- Equipment can preserve the footage leading up to an event by sending a timestamp, lookback and camera IDs to the new API. FlintEye saves the requested interval in a separate folder and shows it in **Recordings → Event recordings**. [Setup and API guide](USER_GUIDE.md#event-recordings)
- On macOS, stopping the recorder gives MediaMTX time to finalize open segments. **Retry Stop** can index a segment whose completion hook was lost after validating the finished video. Recordings can be filtered by capture time or file update time.
- Camera settings identify recording and ONVIF controls during setup. Settings saves complete before navigation, and Live View reports a rejected camera operation. On first launch the network picker defaults to this computer only.

- **Inspect camera** checks Media1 and Media2 profiles for PTZ capabilities. Auto discovery checks TCP 2020 for Tapo cameras when discovery over the network fails. The inspection result distinguishes unreachable endpoints, rejected credentials and TLS certificate failures.
- The desktop menu and Dashboard share monitoring status and available actions. **Retry Stop** can index completed recordings after storage recovers. On macOS, the **Force quit** confirmation appears after the menu closes, and confirmed force quit interrupts an outstanding stop.
- USB and IP camera display names can be edited in Settings. Changes to a MediaMTX path update explicit recording and Multiview source selections while previously recorded clips remain at their original paths.
- On Windows, the recording hooks use UTF-8 settings. Recording completion and shutdown work when camera names contain Japanese or other Unicode text.
- Linux users can install and remove FlintEye in their own account using `install.sh --user`. The removal command retains settings and recordings. [Installation and removal](INSTALL.md)
- The API suite checks access and permitted behavior for every registered operation. A Settings inventory records inputs, limits and choices. Installed tests use synthetic streams and ONVIF endpoints to verify camera changes, Live View, Multiview, recordings and PTZ operations. [Reading the Actions results](testing/CI_ACCEPTANCE.md)
- The Windows, macOS and Linux desktop launchers open first-time setup in the browser and pass one-use authorization. Choose an administrator password to continue. The browser provides instructions for manual setup after expiry or on a server installation.
- **Runtime & access** explains how to enable access from other devices on a LAN or VPN. It shows the active HTTPS address, pending restarts, the last rejected source and a more specific message for an occupied port. The certificate guide covers browser trust and `ERR_SSL_PROTOCOL_ERROR`.
- USB camera startup probes FFmpeg encoders separately from capture on Windows. The supervisor logs worker failures. Camera settings show USB audio alongside the selected managed USB camera, and IP camera controls fit a narrower browser window.
- LAN administrators can add or remove IP cameras. Changes to MediaMTX server settings still require local administration.
- On macOS, Quit can finish after the operating system reports a signal error for a process group whose members have already exited. A still-running worker remains available for a shutdown retry.
- On Windows, saving settings retries a brief file-sharing conflict with the recording service. A failed save preserves the previous settings.
- Installer QA registers two synthetic cameras, checks advancing frames in Live View and both camera images in Multiview, and verifies camera removal, re-addition and retained recordings. The Linux source check drives the USB worker with a synthetic input alongside a synthetic IP camera. See `QA-RESULTS.json` for the results of each build case. [Real-device checklist](RELEASE_CHECKLIST_1_2_0.md)

## License

Individuals and nonprofit or for-profit organizations, including universities, public research institutes and companies, may use and modify FlintEye for personal or internal purposes. Providers may charge for installation, configuration, modification, operation and maintenance on customer-owned or customer-controlled infrastructure, including the customer's contracted cloud environment, and provide necessary copies without charging for FlintEye itself. Selling FlintEye or a modified version, including a software fee in a bundle, or providing a paid hosted service requires a separate license. The English LICENSE is authoritative; third-party rights and grants for earlier versions remain unchanged.
