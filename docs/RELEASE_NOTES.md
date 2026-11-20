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

Preview 5 updates MediaMTX to 1.21.4 and builds it with Go 1.27.4. The container also installs Debian's patched zlib and removes the build-time pip tool and bootstrap wheel. Installation checks follow the active WebRTC player across reloads and still require advancing video, the correct camera image and audio reception.

On Linux, the command installer replaces an older preview even when the package manager shows the same numeric version. Quit FlintEye before updating and rerun the command for this release.

The amd64 and arm64 container scans passed the gate for High and Critical findings with fixes available in the image's package sources. The build's `container-advisories-*` artifacts record the findings still awaiting fixes in Debian 13.

Distribution checks now require an observed HTTP response for all 87 registered API operations, including access-denial checks. The suite also verifies that the recording index recovers after a full volume and that a Compose upgrade and rollback preserve the original clip. The audit records which successful responses and error paths were exercised. [Distribution checks](https://github.com/noguhiro2002/FlintEye/actions/runs/44712702586)

Installation QA now runs the real installed API and browser through setup, two synthetic cameras, audio/video, recording playback/download, viewer access, Stop, Quit, uninstall and retained-data reinstall. The 32-case build matrix and subsequent 10 anonymous online-install/GHCR cases record missing/failed steps explicitly. macOS first launch uses Launch Services and reports confirmed OS approval refusals as manual-required with API/GUI untested. Installer output distinguishes copied files, launch requests and first-launch permission. The real-backend checks also cover configurable local media ports and stereo Opus preview conversion while preserving the selected recording-audio format. See `QA-RESULTS.json` and the installation QA guide for the exact tested build and remaining limits.

Native control windows now load their PNG icon directly, so a missing Pillow/Tk extension cannot terminate the application. OS service stop requests finish ownership cleanup, and multiview detects the DejaVu font installed by Rocky Linux.

This development preview includes the macOS camera, setup and icon fixes in the matching online installers. Screen inputs are excluded from camera discovery and checked before capture, preventing an old camera index from selecting a display. Administrator setup uses the browser; native setup assistance shows the connection address and one-use code. Bundle and running-application icon settings use the FlintEye symbol.

Other 1.2.0 changes include trusted-LAN HTTPS setup, authenticated RTSPS camera addresses, corrected USB capture modes, optional per-camera audio (off by default), and consistent uninstall instructions. Settings and recordings remain outside the application. Shared monitoring status, Stop versus Quit, recording completion and owned-process cleanup remain included.

Of the 32 required build-time cases, 24 passed all seven stages. The eight macOS DMG and script cases passed installation, integrity and removal. macOS required first-launch approval, so the installed API, browser, Quit and retained-data reinstall checks were not run. The per-stage results are in `QA-RESULTS.json`. All eight real-device acceptance checks remain pending. The public download and GHCR checks run after publication. [Build results](https://github.com/noguhiro2002/FlintEye/actions/runs/44712701442)

## License

Individuals and nonprofit or for-profit organizations, including universities, public research institutes and companies, may use and modify FlintEye for personal or internal purposes. Providers may charge for installation, configuration, modification, operation and maintenance on customer-owned or customer-controlled infrastructure, including the customer's contracted cloud environment, and provide necessary copies without charging for FlintEye itself. Selling FlintEye or a modified version, including a software fee in a bundle, or providing a paid hosted service requires a separate license. The English LICENSE is authoritative; third-party rights and grants for earlier versions remain unchanged.
