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

This development preview includes the macOS camera, setup and icon fixes in the matching online installers. Screen inputs are excluded from camera discovery and checked before capture, preventing an old camera index from selecting a display. Administrator setup uses the browser; native setup assistance shows the connection address and one-use code. Bundle and running-application icon settings use the FlintEye symbol.

Other 1.2.0 changes include trusted-LAN HTTPS setup, authenticated RTSPS camera addresses, corrected USB capture modes, optional per-camera audio (off by default), and consistent uninstall instructions. Settings and recordings remain outside the application. Shared monitoring status, Stop versus Quit, recording completion and owned-process cleanup remain included.

All eight installers and both container archives passed their automated checks for the recorded source commit. Physical-device acceptance remains in progress. See the acceptance record and guides in `documentation.zip`; this preview is UNDER DEVELOPMENT and is not a stable release.

## License

Individuals and nonprofit or for-profit organizations, including universities, public research institutes and companies, may use and modify FlintEye for personal or internal purposes. Providers may charge for installation, configuration, modification, operation and maintenance on customer-owned or customer-controlled infrastructure, including the customer's contracted cloud environment, and provide necessary copies without charging for FlintEye itself. Selling FlintEye or a modified version, including a software fee in a bundle, or providing a paid hosted service requires a separate license. The English LICENSE is authoritative; third-party rights and grants for earlier versions remain unchanged.
