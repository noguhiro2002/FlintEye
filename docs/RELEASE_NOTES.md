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

Windows/macOS packages are unsigned/not notarized. Follow the per-application OS confirmation in `documentation.zip`. Choose **Quit FlintEye** before upgrading; settings and recordings are retained. Camera access, recording, playback, tray/GUI behavior and minimum-OS support still need the applicable real-device acceptance checks.

The archives include English/Japanese installation and acceptance guides, the exact applicable LICENSE, third-party notices and corresponding sources. `SHA256SUMS` covers every attached file except itself; `build-manifest.json` records the original tested bundle. `distribution-manifest.json` identifies this release's selected files and GHCR image digests. Public one-command installation scripts are omitted from private testing releases.

## Container

Use `ghcr.io/noguhiro2002/flinteye:@IMAGE_VERSION@` for `linux/amd64` or `linux/arm64`. Public images allow anonymous pulls; private testing requires authorized GHCR login. Preview images have no container `latest` tag. Use the attached `compose.yaml` and the Docker guide in `documentation.zip`.

## Changes in this version

- The Windows, macOS and Linux desktop launchers open first-time setup in the browser and pass one-use authorization. Choose an administrator password to continue. The browser provides instructions for manual setup after expiry or on a server installation.
- **Runtime & access** explains how to enable access from other devices on a LAN or VPN. It shows the active HTTPS address, pending restarts, the last rejected source and a more specific message for an occupied port. The certificate guide covers browser trust and `ERR_SSL_PROTOCOL_ERROR`.
- USB camera startup probes FFmpeg encoders separately from capture on Windows. The supervisor logs worker failures. Camera settings show USB audio alongside the selected managed USB camera, and IP camera controls fit a narrower browser window.
- LAN administrators can add or remove IP cameras. Changes to MediaMTX server settings still require local administration.
- On macOS, Quit can finish after the operating system reports a signal error for a process group whose members have already exited. A still-running worker remains available for a shutdown retry.
- Installer QA registers two synthetic cameras, checks advancing frames in Live View and both camera images in Multiview, and verifies camera removal, re-addition and retained recordings. The Linux source check drives the USB worker with a synthetic input alongside a synthetic IP camera. See `QA-RESULTS.json` for the results of each build case. [Real-device checklist](RELEASE_CHECKLIST_1_2_0.md)

## License

Individuals and nonprofit or for-profit organizations, including universities, public research institutes and companies, may use and modify FlintEye for personal or internal purposes. Providers may charge for installation, configuration, modification, operation and maintenance on customer-owned or customer-controlled infrastructure, including the customer's contracted cloud environment, and provide necessary copies without charging for FlintEye itself. Selling FlintEye or a modified version, including a software fee in a bundle, or providing a paid hosted service requires a separate license. The English LICENSE is authoritative; third-party rights and grants for earlier versions remain unchanged.
