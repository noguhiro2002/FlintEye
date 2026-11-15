# Follow-up to the 2026-11-15 device review

[日本語](DEVICE_QA_FOLLOWUP.ja.md) · [Acceptance checklist](ACCEPTANCE.md)

The supplied review tested commit `fc95bea3732f84c38e1c7a5d8a806e9fb0824548` (application 1.1.2). The shared WebApp fixes in `778a334` came afterward. Neither that update nor this follow-up changes installers already downloaded from the earlier Actions run. Rebuild from this source before repeating acceptance checks.

The review confirmed short USB capture, recording and UI playback on one Windows x64 machine, and synthetic recording/download on Mac ARM64 and Linux source installations. It did not certify all platforms, long-running recording, IP cameras or all installation routes. Those results remain useful evidence for that exact earlier build, not a blanket pass for a replacement build.

## Findings and changes

| Finding | Change and remaining verification |
| --- | --- |
| Mac signature fails on a `copying...dSYM` test binary | The runtime license collector now selects text notices and excludes object code/debug bundles. Rebuilding clears generated runtime notices and stale DMG staging, while retaining vendor sources/licenses. Final DMG and installed-copy signature checks are mandatory; a tampered copy must fail. Repeat quarantine-aware first launch on the Mac. |
| Gatekeeper rejection | Current preview policy remains ad-hoc signing without Developer ID/notarization. Integrity and trust are separate results in the signature report. Gatekeeper rejection is not a successful trust check. Automatic trusted distribution would require a separate Developer ID signing/notarization setup and acceptance. No OS protection is disabled. |
| Shell one-command returns success on download failure | The README command downloads into a temporary file and executes only after a successful download. Download/script exit status is propagated and the temporary file is cleaned up. Synthetic success, HTTP failure, connection failure, incomplete transfer and script failure are tested. Public `v1.1.3-preview.1` downloads are now available. The README command passed installation, setup, synthetic recording/playback and complete shutdown on Ubuntu 24.04 amd64. Windows/macOS one-command installation still needs real-device acceptance. |
| API port differs from Settings | **API listening now** uses the running server's address. Editable host/port fields are explicitly saved next-launch values. CLI overrides remain temporary; without `--port`, the launcher now honors the saved port. Reopening a running instance uses its actual listener, even after a pending saved-port change. |
| Mac LaunchAgent remains after Trash | The tray action **Disable start at login and quit** and CLI `--disable-autostart` remove the registration and preserve data. New registrations name the specific app copy and profile; automatic setup does not overwrite another installation’s registration. Manual Trash removal cannot invoke cleanup by itself. Follow [Stop and uninstall](STOP_AND_UNINSTALL.md) and check the next login. |
| Windows shutdown result is ambiguous | The helper discovers explicit profile paths, supports `-DataDir`, validates the current process identity, and writes `last-stop-result.json`. Normal requests, timeout, forced termination and incomplete stops are distinguished. Profile discovery uses the running instance’s resolved data directory; scoped shutdown tracks owned descendants even when the launcher exits or a child starts during shutdown. Uninstall still allows a bounded fallback for its own installation. Parent-process shutdown completion is not proof of graceful media finalization; verify a recording that was active at shutdown. |
| Camera exit `4294967264` on configuration apply | The value represents `-32`; its precise cause is not established by the supplied log. Planned media changes now stop publishers before reconfiguring/restarting MediaMTX, and shutdown orders publishers before the recorder. Settings changes that do not alter the media configuration leave streams running. Whole-stack restart starts publishers once. Unexpected nonzero exits remain errors. Recheck the original USB scenario and retain child logs if it recurs. |
| Old product names | Browser title, remaining help text and default labels use **FlintEye**. Exact historical default labels are normalized when configuration is read; custom titles, internal identifiers, paths and API routes are retained. |
| Settings briefly shows defaults | Already addressed in `778a334`: loading/unavailable state is shown until configuration is loaded. |
| Windows package has no publisher signature | Still the intentional preview policy, documented in [Install](INSTALL.md). No certificate was purchased or signing identity configured as part of this change. |
| Old tutorial video | The GIF/MP4 now show the current five-step guide, with the source version/date and scope stated in the README. It is a UI tour with synthetic responses and zero cameras, not an installation/recording/uninstall demonstration. The original WebM is retained. |
| Missing Linux venv/ensurepip package | [Source setup](MANUAL_INSTALL.md) now explains the distribution's version-matched venv and Tk prerequisites. |

## Additional local USB check

At the owner's request, the two connected USB cameras were tested on the Linux development host using isolated profiles. The README's main video shows Live View, switching between the two cameras, a healthy two-input Multiview, and actual recording playback. Camera streams are 640×480; Multiview is 1280×480. All 48 recorded files from that main capture session passed FFprobe, matching 48 recording-index entries. A separate developer video executes `GET /api/v1/viewer/cameras` in Swagger (HTTP 200) and opens the returned `addresses.webrtc_url`, with real 640×480 WebRTC playback.

Normal stop requests removed the instance control files, closed the API/MediaMTX listeners and released both cameras. The earlier single-camera check also validated all 9 recorded files and their index entries. Demo capture used 15 fps, a one-second camera keyframe interval and an eight-second thumbnail timeout. These short Linux source tests do not establish Windows media finalization, long-run reliability or native package acceptance. The first-run guide remains a separate synthetic UI tour.

## Recheck on the new artifacts

- Verify the same source commit across the artifacts. Check the macOS `-signature.json` report and repeat first launch from a quarantined download, without disabling Gatekeeper.
- Start with `--port 18765`, compare the real listener and **API listening now**, then restart without that override to check the saved port.
- On Windows, test both default and custom data directories, inspect `last-stop-result.json`, and test quit/uninstall while a recording is active. Check the file with FFprobe, its UI playback and recording-index entry, and verify unrelated processes remain running.
- On Mac, test the removal-preparation menu, preserved recordings/settings, and the next login. Test normal Dock Quit separately from Force Quit.
- Repeat Linux DEB/RPM installation/removal on target distributions and desktops. Container-based package checks do not establish native desktop acceptance.
- Continue the camera, sleep/resume, long-run, quota and upgrade checks in [Acceptance](ACCEPTANCE.md). This work does not publish a release or certify all those scenarios.
