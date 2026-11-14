# Known issues — under development

[日本語](KNOWN_ISSUES.ja.md) · [Documentation](README.md)

This source-first preview is not a stable release. A browser review reproduced 26 groups of interface issues using synthetic data. These are pending work, not fixes included in this snapshot. The review did not exercise physical cameras and does not establish that every issue has been found.

| Area | Known limitation and current precaution |
| --- | --- |
| Settings drafts | Refresh, navigation, conflict recovery and some camera removal actions can discard unsaved edits. Save one task at a time before changing pages or devices. Advanced JSON has separate save behavior and incomplete unsaved indicators. |
| Camera inspection and PTZ | Delayed responses may apply stale information after switching or removing cameras. Finish an inspection before editing the camera list; verify the selected camera and capabilities before operating PTZ. |
| Camera identities | Removing and then adding an IP camera can generate a duplicate default path. Check that every camera path is unique before saving. |
| Connection and loading errors | Some pages confuse loading, empty results, partial failure or unknown authentication state. “Public viewer” during a service failure is not evidence of an authorization bypass; retry and check server status. |
| Recordings | Invalid date ranges may appear as no results; partial filter failures can hide available recordings. Check the date order and retry. Playback dialogs have keyboard-focus problems. |
| Narrow displays and accessibility | Some layouts overflow on phones/tablets. Selection labels, keyboard focus, contrast and first-run form spacing need further work. A desktop-width window is currently the most practical test environment. |
| Guidance and search | Settings search misses some labels, first-run guidance can highlight a different page, and some empty-state actions are misleading. |

Automated builds check startup, initial authentication, bundled media tools, synthetic recording and playback. Windows installer checks also exercise uninstall with an active API and retained data. They do **not** replace USB/IP camera, microphone/privacy permission, sleep/resume, minimum-OS, autostart or desktop quit checks on real machines.

Public installers and GHCR images are being prepared. Before publishing the first preview, the maintainer must confirm Windows x64, M1 Mac and Linux x64 acceptance and review corresponding sources/licenses. Other CPU/OS combinations remain explicitly subject to device testing. See the [acceptance checklist](ACCEPTANCE.md).

Report reproducible problems through [Issues](https://github.com/noguhiro2002/FlintEye/issues). Remove credentials, setup tokens, private camera URLs and personal footage from reports. Report security vulnerabilities using the [private security channel](../.github/SECURITY.md).
