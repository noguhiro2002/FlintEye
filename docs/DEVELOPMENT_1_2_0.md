# 1.2.0-preview.1 development and QA follow-up

[日本語](DEVELOPMENT_1_2_0.ja.md) · [Acceptance](ACCEPTANCE.md) · [Required device checklist](RELEASE_CHECKLIST_1_2_0.md) · [LAN access](LAN_ACCESS.md)

**UNDER DEVELOPMENT. Public 1.1.3-preview.1 is unchanged. This source is not a claim that the reported Windows failures have recovered on the owner's machine.**

Baseline: application build `25718ed3f06833a1f291992753b4f0538d7dc939`, published tag `v1.1.3-preview.1`; implementation starts from main `8e13378`. Input: the owner's QA rev11 dated 2026-11-15. Findings below preserve the distinction between observed defects, new product requests and unperformed tests. Application 1.2.0 and release v1.2.0-preview.1 are the next target, not the stable channel.

| QA chapters | Implementation and evidence status |
| --- | --- |
| 1–8, 11 | Previous package/OBS/synthetic tests remain evidence for that exact version and environment only. They do not establish physical-camera, mobile, native menu, OS-install or long-run success for this version. |
| 9, 18 | Dashboard-only monitoring panel; shared monitoring information keeps players and thumbnails paused after intentional Stop. Operation-specific progress replaces the misleading Start message. Automated regression tests are required. |
| 12–13, 16–17 | Media executable/config/cwd preflight, bundled path repair and protected upgrade backups. Compare the same installer and one-command path with clean, retained and incomplete profiles. Owner WinError 2 is **unresolved pending reproduction and retest**. Camera exit 4294967291 remains a separate input-device investigation. |
| 14–15 | Windows removal entry adds per-installation exclusion, graceful stop and file-lock diagnostics before Inno opens its uninstall data. No forced process termination by default. Owner Error 32 is **unresolved pending Windows retest**. |
| 19 | Coalesced thumbnails and a bounded capture pool; stale-image timestamp/error remains separate from camera health. Long-GOP and concurrent live/multiview tests are required. |
| 20–23, 28–30 | Opt-in built-in LAN HTTPS, source restrictions, private CA export, token ownership and explicit firewall action. Desktop/mobile trust, daily operations and restart must pass on separate physical clients before public 1.2.0 distribution. |
| 24 | Inline viewer password feedback and backend bounds. No real user password is collected. |
| 25 | Symbol-only icon assets across native packages, tray, launchers and favicon. OS icon-cache/high-DPI/theme checks are pending. |
| 26–27 | Linux preflight before download, desktop versus SSH Quick Usage, token location, tunnel limits, normal shutdown and systemd instructions. OS install/remove acceptance remains separate. |
| 10 | Browser-based initial password entry; address/copy fallback; compact Linux controls; sanitized allowlisted diagnostics; recording completion metadata. Signing/notarization deferred by the owner's decision. UI remains English; documentation and installation instructions are bilingual. |

## Acceptance required before publication

Use dedicated profiles, recording folders and container volumes. Preserve existing user recordings and configuration. Record exact release, checksum, commit, OS/CPU, browser, installation path, profile and steps, excluding secrets and personal footage.

1. Windows x64: one-command and EXE, each with a fresh profile, a retained configured profile, unfinished setup, changed install directory, spaces/non-ASCII paths and stale cwd. Confirm expected setup versus login, bundled MediaMTX, actual video, completed recording decode and owned Quit.
2. Windows removal: running, recording, stopped, duplicate entry, a deliberately held uninstall-data handle, denied permissions and retry. Identify the lock holder without terminating unrelated processes. Confirm no program/process/startup/owned firewall remnants and retained recordings. Test the original owner symptoms; synthetic reproduction is not proof of owner recovery.
3. Native Mac M1, Windows x64 and Linux: real tray/menu clicks for Open/Start/Stop/Restart/Quit, login startup, correct icons and visible state text. VoiceOver/Narrator and keyboard must reach password inputs and actions in the browser. Run builds and smoke tests for x64/ARM64 on all three OS families.
4. Physical LAN: Windows Edge/Chrome, Mac Safari/Chrome, Linux Firefox/Chrome, iPhone and iPad Safari, Android Chrome. Trust installation/removal, admin/viewer roles, initial ownership, live/multiview, record/playback, app/OS restart at the same URL. Test certificate rotation/expiry, IP changes, multiple NICs, firewall refusal, unauthorized ranges, token expiry/reuse and rate limits. Record actual device/OS/browser versions.
5. Real USB cameras: both attached devices, concurrent recording, unplug/replug, sleep/resume, 24 hours, full/unavailable storage. Abrupt-stop/power-loss simulations use disposable test data and a VM. Verify completed files remain playable and incomplete files are not falsely finalized.
6. Linux dedicated host: actual apt/rpm install, update and removal, SSH setup/normal exit and systemd start/stop. Docker Engine: use the matching loaded build archive before publication to test persistence, SIGTERM recording flush and process cleanup; verify GHCR pull after approved publication. Docker Desktop: host-browser authentication and real WebRTC playback; VM-internal health alone is insufficient.

## Build, review and rollback

Run the Python suite, frontend build/browser suites, documentation checks and exact native-package/container smoke tests. Keep secrets and footage outside committed evidence. A source-only unit test or an emulator does not replace required hardware acceptance. Terra reviews the changed authentication and lifecycle boundaries.

Before migration, runtime/monitoring backups are stored privately under `backup-before-1.2.0` in the profile. They contain sensitive configuration: never attach them to issues. Stop the new application before restoring a matching old backup and reinstalling the pinned 1.1.3 package. Preserve existing recordings and inventory. Remove the new Windows firewall rules and obsolete client trust if rolling back LAN access. No automatic downgrade or data erasure is performed.

**Publication is blocked while any 1.2.0 P1 acceptance gate is pending or failed.** Build artifacts may be delivered for testing. Do not overwrite the existing 1.1.3 tag/assets. After acceptance, publish matching tested source, installers, version-pinned scripts, both Compose routes, licenses/sources and checksums together, as a prerelease with no image `latest` tag.

## Validate the one-command installer before publication

Download and extract the successful Build release run's `release-bundle` artifact. Its `public` folder contains the exact installers, install scripts and `SHA256SUMS`. Confirm the workflow commit and build manifest before using it. The following explicit local-artifact mode uses the same installer and checksum checks without requiring a public 1.2.0 Release; it does not clone the repository or bypass OS execution approval. Run as the normal user, quit existing FlintEye instances first, and use a dedicated clean/retained QA profile as appropriate.

Windows PowerShell, from the extracted bundle directory:

```powershell
.\public\install.ps1 -Version 1.2.0-preview.1 -PackageDirectory .\public
```

macOS or Linux, from the extracted bundle directory:

```sh
bash public/install.sh --version 1.2.0-preview.1 --package-directory public
```

Compare this installation with the standalone installer from the same folder and verify both SHA-256 values match. Keep the version and source commit fixed. Public download commands remain pinned to the currently published 1.1.3 release until 1.2.0 acceptance passes. To test the container before GHCR publication, load the matching `containers/container-amd64.tar.gz` or `container-arm64.tar.gz`, then set `FLINTEYE_IMAGE=flinteye:release-amd64` or `flinteye:release-arm64` before using Compose. Do not mistake a downloaded Compose file's future GHCR tag for an already published image.

## Recorded automated verification

Application commit: `a0aa7592195a6b52cd732014603ea2fbc3ff4b22`. [Successful build and QA artifacts](https://github.com/noguhiro2002/FlintEye/actions/runs/43800923694). All six native OS/CPU targets passed: Windows x64/ARM64, macOS Intel/Apple Silicon and Linux amd64/arm64. This produced eight installers (EXE, DMG, DEB and RPM) and two container archives. Installed/frozen application checks covered setup, authentication, bundled media, generated-video recording/playback and normal Quit. Windows checks also used the registered uninstall command and confirmed retained data; Linux checked actual DEB/RPM installation.

The Python suite ran 190 cases without failures: 2 platform-dependent skips locally and 3 in Linux CI. Chromium passed the full 18-group interface suite; Firefox and WebKit passed monitoring, setup and recording flows. LAN settings/setup were additionally checked at 320/1440 pixels on all three engines. Isolated LAN integration verified TLS trust, ownership, Secure cookies, roles, generated media, retained certificates/authentication/recordings and normal owned Quit. Linux-hosted browser engines and generated video do not count as physical Safari, mobile or camera acceptance.

The downloaded Actions artifacts were checked against GitHub's stored sizes and SHA-256 values, safely extracted with ZIP CRC verification and assembled using this commit's release recipe. The manifest, complete file checksums, container architectures/source revisions and macOS ad-hoc integrity reports were verified. Intel Mac required a same-commit retry after macOS returned `Resource busy` while creating its first DMG; successful artifacts from the other targets were retained.

Only the automated native-architecture acceptance case is marked passed. The eight physical/owner acceptance cases above remain pending, including the reported Windows WinError 2 and Error 32. No new Release, GHCR image or stable/latest promotion was made.
