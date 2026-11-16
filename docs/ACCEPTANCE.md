# Final checks on your computers

[日本語](ACCEPTANCE.ja.md)

[Documentation](README.md) · [Build/release procedure](RELEASING.md)

## Obtain the exact build

1. Push the reviewed changes to the repository's default branch.
2. Run **Actions → Build release → Run workflow**.
3. Download the successful run's **release-bundle** artifact.
4. Record its run ID, commit SHA and version from `build-manifest.json`.
5. On each computer, install the matching package from its `public` directory.

Build artifacts in this public repository are visible to repository readers; downloading them requires GitHub sign-in. They are unapproved development builds, not published releases.
Artifacts expire after 30 days; keep a local copy while testing.
The install scripts in a build point to release URLs that do not work until that version is published. Test the downloaded EXE/DMG/DEB/RPM directly during this phase.

Use a clean account/VM with no Python, Node.js, Git, FFmpeg or MediaMTX installed.
Use test cameras and a disposable recording folder; capacity/retention checks intentionally remove eligible test recordings.

## Target matrix

Record **pass**, **fail**, or **not tested** separately. A successful build does not certify the OS.

| OS | CPU | Install/setup | Live/record/playback | Update/data retention |
| --- | --- | --- | --- | --- |
| Windows 10 22H2 / Windows 11 | x64 | | | |
| Windows 10 22H2 / Windows 11 | ARM64 | | | |
| macOS 14+ | Intel | | | |
| macOS 14+ | Apple Silicon | | | |
| Ubuntu 24.04 | x64 / ARM64 | | | |
| Rocky Linux 9 / 10 | x64 / ARM64 | | | |
| Raspberry Pi OS Bookworm, 64-bit, Pi 4/5 | ARM64 | | | |
| Docker Engine on Linux | amd64 / arm64 | | | |

If some targets are not tested, keep the build as a development preview rather than advertising the full matrix as validated.
Record real Raspberry Pi camera count/resolution/fps; do not extrapolate a universal camera limit.

## Desktop checklist

- [ ] Installer works without developer tools; unsigned-app confirmation follows the documented OS flow.
- [ ] Admin password creation, cancellation and resumption work; no default password grants access.
- [ ] First-run English tour opens; skipping and reopening work.
- [ ] USB permission and discovery work; an IP camera can connect using its credentials.
- [ ] Live View, camera recording, recording listing, download and playback work.
- [ ] On macOS, copy the app from the DMG, eject the DMG, quit/relaunch, and verify MediaMTX and a USB camera stay running. Move the stopped app, relaunch with the same profile, and confirm recordings/settings remain available. Repeat login autostart after installing the replacement app.
- [ ] Viewer access requires a configured viewer password and cannot change settings.
- [ ] Initial storage suggestion is min(50 GB, half the free space); retention is 7 days.
- [ ] Both age-based and capacity-based cleanup remove only completed eligible test recordings.
- [ ] Folder change keeps old recordings visible by default; turning the option off hides them.
- [ ] Removed/reconnected disks and low free space produce understandable behavior.
- [ ] Non-ASCII usernames, paths with spaces, and custom recording folders work.
- [ ] Browser close keeps monitoring running; explicit quit stops it; duplicate launch does not create two servers.
- [ ] Login autostart works; manual sleep/logout/shutdown behavior is understood.
- [ ] Upgrade preserves configuration and recordings; normal uninstall preserves data. On Windows, uninstall while the API is active: verify that API/media processes stop and bundled executables are removed. On macOS, quit from the tray/control window and Dock separately: verify that the camera turns off and owned media processes exit.
- [ ] LAN viewing uses HTTPS and requires authentication; internal media endpoints cannot be used anonymously.

## Server checklist

- [ ] Docker starts as UID/GID 10001 and persists data across container recreation.
- [ ] Headless first-run token is private, single-use, and absent from logs.
- [ ] Compose pull/update and rollback work using pinned versions.
- [ ] systemd starts without desktop login using its own account/data directory.
- [ ] Neither deployment shares ports or a live data directory with a desktop instance.

## Publication sign-off

Review the source/license archives, installer inventory and checksums.
Confirm that the source commit and build run ID are exactly those you tested.
Do not edit/rebuild the packages after sign-off. A code change requires a new build and appropriate rechecks.

The source repository is public already. Only after this review, enable the matching public-preview flag and use both phases of **Publish tested release**. The first public preview requires Windows x64, M1 Mac and Linux x64 device acceptance, including camera recording/playback, complete GUI quit, and Windows uninstall with data retention. Mark other platforms as not tested where applicable. Public previews use GitHub Pre-release and never Latest.
After public launch, verify the README one-command install routes from clean computers and confirm that all advertised release assets are accessible.

## Follow-up to the November device review

Use the [device QA follow-up](DEVICE_QA_FOLLOWUP.md) alongside this checklist. Its reported passes apply to the reviewed commit only. Recheck macOS signature integrity versus Gatekeeper trust, actual versus saved API ports, custom-profile shutdown results, active recording finalization and removal of login startup registrations on the new build.

## Monitoring controls in 1.1.3

- [ ] Test one commit across all installers; record the version, channel and commit from Information.
- [ ] Compare native and Web status: no cameras, receiving, recording, one/all disconnected, MediaMTX down, unavailable health, starting, stopping and stopped. Confirm the 15-second stall threshold and distinct configured/target/receiving/recording counts.
- [ ] Stop while recording: API/settings remain available, camera indicators turn off, MediaMTX stops after the final segment is indexed. Decode the complete last segment and replay it after restarting.
- [ ] Save configuration while stopped, wait for maintenance/recovery, and restart the application. Monitoring stays stopped by default; the Always resume preference explicitly changes that behavior.
- [ ] Verify login startup separately from monitoring resume; preserve another installation/profile's login registration.
- [ ] Retry a pending stop with low space, disconnected storage or delayed completion hooks. Force quit must warn and retain an unverified receipt, never claim a valid recording.
- [ ] On Windows/macOS, physically click every tray/menu action; inspect high-DPI, light/dark mode and keyboard operation. On Linux, test both a tray-enabled desktop and the compact fallback window.
- [ ] Docker/headless starts without Tk/tray/login registration; Compose recreation preserves accounts, recording inventory and stopped-state preference.
- [ ] Repeat physical USB disconnect/reconnect and manual sleep/resume. Record a separate 24-hour soak result; a short test does not pass this item.

Signing contracts, notarization and public Release promotion are outside this development-build test cycle.


## 1.2.0 development acceptance

The additional [1.2.0 test matrix](DEVELOPMENT_1_2_0.md) and [LAN trust procedure](LAN_ACCESS.md) apply to rebuilt 1.2.0 artifacts. Separate tests are required for the owner’s Windows startup and removal failures, native menu clicks/accessibility, PC and mobile LAN clients, two real USB cameras/24 hours, Linux OS packages, Docker Desktop host video and all native CPU builds. These are pending until actual evidence exists. Update `packaging/acceptance-1.2.0.json` with the tested app commit and passing evidence before publication.
