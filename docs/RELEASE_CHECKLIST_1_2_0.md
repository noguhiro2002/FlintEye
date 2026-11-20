# Required device checks before stable distribution of 1.2.0

[日本語](RELEASE_CHECKLIST_1_2_0.ja.md) · [Development QA](DEVELOPMENT_1_2_0.md) · [LAN trust guide](LAN_ACCESS.md)

**Stable distribution of 1.2.0 requires all eight device gates below and a passing build for every OS and CPU on the same commit.** A failed or untested gate blocks stable promotion. A public UNDER DEVELOPMENT preview may distribute the passing build for testing while physical cases are pending; it must disclose those pending results and must not become Latest.

Of the 32 required build-time cases, 24 passed all seven stages. The eight macOS DMG and script cases passed installation, integrity and removal. macOS required first-launch approval, so the installed API, browser, Quit and retained-data reinstall checks were not run. The per-stage results are in `QA-RESULTS.json`. All eight real-device acceptance checks remain pending. [Build results](https://github.com/noguhiro2002/FlintEye/actions/runs/44712701442) · [Public installation results](https://github.com/noguhiro2002/FlintEye/actions/runs/44729094734)

## Use the exact QA build

| Field | Required value or record |
| --- | --- |
| Release / application | `v1.2.0-preview.5` / `1.2.0` |
| Tested application commit | `26421ce87ab9f882d342279a9204efe2942dee94` |
| Build | [Actions run 44712701442](https://github.com/noguhiro2002/FlintEye/actions/runs/44712701442), OS-specific test artifacts or `release-bundle` |
| Package identity | Record the package filename and its matching `SHA256SUMS` value; confirm `build-manifest.json` and Information agree |
| Environment | Date, tester, device, OS/build, CPU, browser/version, install method, install/data paths, actual API address/port, camera model/resolution/fps |
| Results | For each operation, record expected behavior, observed behavior, Pass / Fail / Not tested, and an evidence reference |

Use dedicated test profiles, recording folders and container volumes. Retained-profile tests use a backed-up test profile. Do not attach passwords, setup tokens, private keys, private configuration backups or personal footage to public evidence. Disk-full, deletion, abrupt-stop and power-loss tests use disposable data; simulate power loss in a VM rather than switching off a computer containing user data.

The required desktop device coverage includes Windows x64, an M1 Mac and Linux x64. Run the listed PC/mobile browser combinations below as well. Record other OS/CPU targets separately; a successful ARM64/Intel build alone does not establish device acceptance for that target. Follow the documented OS approval for these community packages; Developer ID signing/notarization remains deferred.

Test both the standalone package and the [local-artifact one-command mode](DEVELOPMENT_1_2_0.md) using these same files. Before GHCR publication, load the matching verified `containers/container-amd64.tar.gz` or `containers/container-arm64.tar.gz` and use the local image tag described in that guide. A public 1.2.0 download URL or GHCR tag is not needed to complete these tests.

## Gate summary

Fill in Pass / Fail / Not tested and evidence only after performing the checks. A checked subitem does not pass the whole gate if another required subitem remains untested.

| Gate in the acceptance record | Coverage | Result | Evidence |
| --- | --- | --- | --- |
| `windows-owner-startup` | Original Windows startup failure and both install routes | Not tested | |
| `windows-owner-removal` | Original Windows removal failure and cleanup | Not tested | |
| `native-menus-and-accessibility` | Physical Windows/M1/Linux controls and accessibility | Not tested | |
| `lan-pc` | Separate Windows/macOS/Linux PCs over HTTPS | Not tested | |
| `lan-mobile` | iPhone, iPad and Android | Not tested | |
| `physical-cameras-and-long-run` | Two USB cameras, recovery and 24 hours | Not tested | |
| `linux-native-and-docker` | Linux packages, SSH/systemd and Docker Engine | Not tested | |
| `docker-desktop-host-video` | Actual Windows/macOS host browsers | Not tested | |

## 1. Windows startup — `windows-owner-startup`

- [ ] On the Windows computer that reported WinError 2, compare the EXE installer and local-artifact one-command installation from the exact same build. No separate Python, Node.js, Git, FFmpeg or MediaMTX installation is required.
- [ ] Repeat with a fresh profile, retained configured profile, and interrupted initial setup. Initial setup versus normal login is correct, and existing passwords/settings/recordings survive the retained-profile case.
- [ ] Check a changed installation directory, paths with spaces/non-ASCII characters, and launch from a different working directory. Duplicate launch does not create a second server.
- [ ] Select a real USB camera. Bundled MediaMTX starts, Live View shows video, a completed recording plays/downloads, and Quit closes the owned API/media processes. No repeating blank console windows appear.
- [ ] Reproduce the original operation and record the outcome: no WinError 2. A different capture error, including 4294967291, is recorded and investigated separately; a page loading without camera video does not pass this gate.

## 2. Windows removal — `windows-owner-removal`

- [ ] Use Windows Settings → Apps to remove FlintEye while running, while recording, and after monitoring has stopped. Recheck the original Error 32 on the reporting computer.
- [ ] Normal removal finalizes the last recording, stops all running profiles and their owned processes/listeners, and removes the bundled application, FastAPI runtime, FFmpeg/FFprobe and MediaMTX. Another application's processes remain untouched.
- [ ] Login startup entries and this installation's LAN firewall rules are removed, including rules for stopped/custom profiles. Another installation's rules remain intact. Rejecting required firewall approval cancels removal and permits retry.
- [ ] Settings and recordings remain by default and are usable after reinstalling. Explicit data deletion applies only when deliberately selected. No duplicate or broken Apps removal entry remains after successful removal.
- [ ] In a disposable environment, test simultaneous/duplicate removal, a held uninstall-data handle, and denied permissions. Failure identifies the blocker, preserves data and allows retry after the blocker is removed; it does not silently force unrelated processes to stop.

## 3. Desktop controls and accessibility — `native-menus-and-accessibility`

- [ ] On Windows x64, M1 Mac and Linux x64, physically click Open, Start, Stop, Restart and Quit in the available tray/menu/control window. On macOS test Dock Quit as well; on Linux test the tray and the compact fallback window.
- [ ] While recording, Stop pauses cameras/thumbnails/players and completes the last recording while leaving API/settings available. Saving settings and reopening the application preserve the stopped preference unless Always resume was explicitly enabled.
- [ ] Quit, including Quit after Stop, exits the app and its owned media processes; camera indicators turn off in a test environment where no other app uses them. Reopening uses the retained configuration. Browser-window close alone keeps monitoring running.
- [ ] Login startup and monitoring resume work as separate preferences. Icons, visible state/progress, high-DPI and light/dark appearance remain understandable. Native and Web status agree; an intentional Stop is distinct from no cameras or an unhealthy stream.
- [ ] Keyboard operation and Narrator/VoiceOver reach initial password fields, validation feedback and actions in the browser. English onboarding can be skipped/reopened; storage and viewer-password controls can be found and used.

## 4. LAN PCs — `lan-pc`

- [ ] From separate physical clients, test Windows Edge/Chrome, macOS Safari/Chrome and Linux Firefox/Chrome. Install/trust the exported CA using the guide, compare its fingerprint and use the selected HTTPS URL.
- [ ] Initial setup requires the owner token; expired/reused tokens and excess attempts are rejected. Sign in as admin and viewer. Viewer cannot change settings; anonymous clients cannot bypass authentication through the API or internal media endpoints.
- [ ] Live View, Multiview, recording listing/playback/download work through HTTPS with real camera video. A successful login or reachable page alone is insufficient. Repeat after app/server/client restart; the URL stays usable when the server IP is unchanged.
- [ ] Check certificate renewal/expiry recovery, an IP change and multiple network interfaces. Only the selected interface is exposed. With a changed IP, recover through local settings and the updated connection guide; do not expect the old IP URL to remain valid.
- [ ] Check firewall refusal/retry and rejected source networks. Windows permission is limited to the intended Private-network sources; local recovery still works when approval is refused. Remove/reinstall the client CA trust and confirm the expected trust state.

## 5. Mobile LAN — `lan-mobile`

- [ ] Test actual iPhone Safari, iPad Safari and Android Chrome separately; record each device/OS/browser version. Linux WebKit or a mobile-sized desktop window does not pass this gate.
- [ ] Follow the certificate guide, including full trust on iPhone/iPad. HTTPS works after deliberate trust and shows the expected failure when that FlintEye trust is removed.
- [ ] Admin/viewer login and restrictions, Live View, Multiview, recording listing/playback/download work with real camera video and usable touch controls. Recheck after app/device restart at the same unchanged-IP URL; sign in again if the session has expired.

## 6. Cameras, storage and long run — `physical-cameras-and-long-run`

- [ ] Use both real USB cameras concurrently for live view, Multiview and recording. Record camera models/resolution/fps. Compare thumbnail timestamps with real video and distinguish stale images from camera health. Also check long-GOP input with concurrent Live View/Multiview.
- [ ] Unplug/replug cameras and test sleep/resume. Record interruption and recovery times, useful errors and any unintended camera on/off loop. After Quit, the owned capture processes and camera indicators stop.
- [ ] Run a separate 24-hour two-camera test. Record start/end times, intended stops, unexpected gaps/restarts, recording counts, CPU/memory and storage behavior. A short test does not pass this item.
- [ ] Play/download completed clips near the beginning, middle and end, including the complete final segment after Stop/Quit. Check displayed duration/end time/time zone. Abrupt-stop tests must not mark incomplete files as successfully finalized.
- [ ] Confirm the initial 7-day retention and free-space-based capacity suggestion. On disposable test recordings, exercise age and capacity limits separately: the first limit triggers deletion of eligible old completed recordings, not unrelated or active files.
- [ ] Change the recording folder: old recordings remain visible/playable by default and can be hidden with the option; existing files are not silently moved. Hiding a previous location does not disable its scheduled cleanup. Check full, disconnected and unwritable storage with test data.

## 7. Linux packages and Docker Engine — `linux-native-and-docker`

- [ ] On dedicated Linux OS environments, test DEB/APT and RPM/DNF install, update and removal, including preserved data and normal shutdown. Record host versus VM; a container-only package smoke does not establish OS/service integration.
- [ ] Over SSH, complete private-token setup, find the correct address and stop normally. Verify systemd start/stop/reboot without desktop login. Record WebRTC routing separately: an HTTP-only SSH tunnel is not proof of video connectivity.
- [ ] On Linux Docker Engine, use the matching loaded image and versioned Compose configuration, UID/GID 10001 and a dedicated persistent volume. Initial setup, real input/live/record/playback and container recreation retain accounts/certificates/settings/recordings/stopped preference.
- [ ] Normal Compose stop/SIGTERM completes and indexes the final recording, closes owned processes and permits restart. Decode the final clip; exit 143 or an internal health check alone is insufficient. Check pinned-version update/rollback with the documented compatible backup; keep desktop/server data directories and ports separate.

## 8. Docker Desktop — `docker-desktop-host-video`

- [ ] On actual Windows and macOS hosts, use the matching loaded image and `compose.desktop.yaml`. Open `http://127.0.0.1:18080` in the host browser and complete setup/login.
- [ ] Manually register reachable IP/RTSP cameras and confirm real WebRTC video, Multiview, recording/playback/download in the host browser. A curl/health check inside the VM is insufficient. This configuration does not provide USB forwarding, ONVIF multicast discovery or LAN-server access.
- [ ] Stop/recreate/restart using the same project and volume. Confirm final recording completion, retained accounts/settings/recordings and the stopped preference; the container starts without a desktop GUI/tray requirement.

## Record the result and authorize distribution

For every gate, attach the environment record, operation/expected/observed result and an evidence reference. Keep Fail and Not tested visible. Do not mark a whole gate passed using only a build log, an older release, generated footage or an incomplete device matrix.

| Gate / subitem | Environment / date / tester | Operation | Expected | Observed | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | Not tested | |

Record each result and the matching tested application commit in the [acceptance record](../packaging/acceptance-1.2.0.json). Only after all eight gates pass may the [release procedure](RELEASING.md) promote the software to stable distribution. Keep pending cases unchanged when publishing a development preview for these tests. App-code or package changes require a matching new build and appropriate rechecks. Documentation/evidence-only updates do not turn an untested application into a tested one. This checklist does not publish anything or promote a stable/latest tag.

## Verify distribution after approved publication

These checks happen after the selected preview or stable publication; they are not prerequisites requiring an already-public 1.2.0 image during the device tests above.

- [ ] From clean computers, the real public one-command URLs download/install the intended OS/CPU/version without Git clone or separate runtimes, and their package hashes match the tested files.
- [ ] GitHub Release downloads, sources/licenses, guides, Compose and checksums are accessible. The exact GHCR version pulls on amd64/arm64 and matches the recorded image identities; repeat the documented update/rollback route.
- [ ] Preview status is explicit, no stable/latest promotion occurred, and the older version's assets/tags remain unchanged.

## Additional checks for the next development build

Record the actual candidate commit and package checksums above before applying these checks. The earlier 1.2.0 build does not attest to these changes.

- [ ] Start from a clean profile using the one-command installer, native package, Docker Compose and systemd. Confirm that the printed address works after certificate trust on another device and that the browser setup accepts the owner’s one-use code. Confirm local recovery when there is no eligible LAN or firewall permission is refused.
- [ ] Use a separate physical client and an RTSPS-capable player. Confirm a verified certificate and authenticated read for the intended camera. Try a wrong password, an unapproved source and publish access. Confirm the relay closes when disabled.
- [ ] On Windows, macOS and Linux, compare reported 720p/1080p capture formats and rates with the actual video. Include 29.97 fps where supported and verify that refreshing devices keeps existing settings.
- [ ] On each OS, test a USB camera with a microphone, a video-only USB camera and an IP camera with an audio track. Verify the audio-off default, unavailable-input feedback, audio-only failure with video continuing, initially muted Live View and audible, synchronized recording playback. Use ffprobe to confirm the actual PCM format and verify playback of a previous video-only recording.
- [ ] Open a freshly built DMG in Finder and verify the icon there and after running from Applications. Check Windows installer, executable, shortcuts and Linux launcher icons.
- [ ] On the M1 Mac that reported the preview.3 issue, compare the downloaded DMG and that same artifact's `install.sh --package-directory .`. Information → System must show `1.2.0-preview.5`. Initial password entry is in the browser; an address/token assistance window may appear, but the old native password form must not. Test retained and unfinished profiles without deleting data.
- [ ] Open and refresh camera discovery repeatedly with Screen Recording permission disabled. `Capture screen` must not be offered or opened, no Screen Recording prompt should recur, and the physical camera must still work. Disconnect/reconnect a camera saved by index and confirm the old index never opens a display. Test an OBS virtual camera separately.
- [ ] Check the running Dock icon as well as the DMG/Finder icon and native setup/connection/folder dialogs. Test removal of the script's `~/Applications/FlintEye.app` separately from `/Applications/FlintEye.app`; retained accounts and recordings survive reinstallation. Confirm camera-table RTSPS addresses use the selected server address, never an internal loopback publishing URL.
