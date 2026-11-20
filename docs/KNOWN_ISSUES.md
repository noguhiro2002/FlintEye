# Known issues and WebApp review status

[日本語](KNOWN_ISSUES.ja.md) · [Documentation](README.md)

FlintEye is **UNDER DEVELOPMENT**, not a stable release. The 2026-11-15 Terra browser review identified 26 groups of interface defects. The changes below address those groups in the current source. Installer artifacts built before these changes still contain the earlier interface; rebuild from the updated source before testing on Windows or macOS.

## Changes from the review

| Review findings | Behavior in the updated source |
| --- | --- |
| 1, 2, 13, 25 — Settings drafts and loading | Navigation, Refresh and both Discard actions confirm before dropping unsaved form or JSON edits. Separate device/account operations require existing changes to be saved or discarded. Advanced JSON has an accessible label and its own dirty state; replacing it warns about unsaved form changes. Status no longer understates changes with an incomplete count. Failed USB discovery leaves other settings available. Missing configuration is shown as unavailable rather than populated with default status claims. |
| 19, 21, 22, 23, 24 — Camera identity and inspection | Switching cameras isolates PTZ state. Removed or edited drafts reject stale inspection responses. New camera paths are unique and duplicate/empty paths are rejected before saving. A failed inspection clears the previous success. Inspection presents an explicit **Apply recommended FPS** action instead of changing settings automatically. |
| 3 — Authentication | An unavailable authentication endpoint shows an error and **Retry connection**, rather than claiming public access. Requests have bounded waits, except for the native folder picker, which waits for the user. |
| 16, 18 — Recording player | Opening the player moves focus inside, keeps keyboard navigation inside, makes background controls inert, and restores focus on close. Play controls identify their recording. |
| 17, 20 — Recording queries | Reversed date ranges show an inline error without sending an invalid query. Recordings and stream filters load independently; a failed filter request does not hide available footage. Retained results are identified as previous results while filters change or a refresh fails. |
| 6, 7, 26 — Live View and Multiview | Polls run sequentially and outdated responses are ignored. A removed selection falls back to an available source. Loading, service failure and genuinely empty configuration have distinct messages. |
| 4, 5 — Small screens | Headers, controls, camera cards and tables wrap or shrink at narrow widths. Long names and URLs no longer force the page wider. Mobile navigation takes only the height its content needs. |
| 8 — Settings search | Encoder is included. Search describes its scope as settings categories and common keywords, rather than promising every field. |
| 9, 10 — Setup and sign-in | Setup fields use a spaced vertical layout, FlintEye branding and visible password requirements. Mandatory sign-in does not show a Back action with no destination. |
| 11, 12 — Accessible state and contrast | Navigation exposes its current page; camera and Multiview selectors expose their selected state. Camera controls are separate from the selection button. Small PTZ explanatory text has stronger contrast. |
| 14, 15 — Guidance and empty states | Opening the guide no longer decorates a different page as if it were active. Empty camera/output/recording states explain the situation; empty recording lists omit pagination. |

## Physical-device follow-up

The later Windows/Mac/Linux review adds packaging, startup and shutdown findings. See the [device QA follow-up](DEVICE_QA_FOLLOWUP.md) for fixes, evidence boundaries and the remaining acceptance checks. Windows media-child termination and macOS Developer ID/notarization remain explicit limits.

## Validation and remaining limits

The 1.2.0-preview.5 [installed API/browser lifecycle suite](INSTALLATION_QA.md) completed 24 cases through all seven stages in its [32-case Actions run](https://github.com/noguhiro2002/FlintEye/actions/runs/44712701442). The 8 macOS installer cases require first-launch OS approval; their API/GUI checks are not run. macOS ad-hoc integrity does not establish OS permission: the reported M1 launch refusal came from `amfid`, despite a valid executable/signature. Approved first launch and physical-device gates remain pending. Earlier published installers are unchanged.

The regression suite uses a built frontend, Chromium and synthetic API responses. It exercises delayed and failed requests, draft protection, camera switching, keyboard interaction and narrow layouts. It blocks requests to external hosts and does not connect to physical cameras. See [Contributing](../.github/CONTRIBUTING.md) for the test commands.

- **Real-device acceptance remains required:** Windows and macOS desktop behavior, physical USB/IP cameras, PTZ movement/stop, microphone/privacy permissions, sleep/resume, minimum-OS support and actual video decoding must be checked on the intended machines. Linux browser tests do not establish compatibility with every browser or screen reader.
- **Conflicting settings are not merged automatically:** the draft stays on screen after a conflict. Copy the changes you need before explicitly discarding the draft and reloading the latest settings.
- **Deployment guidance differs:** closing the browser keeps monitoring running. Desktop users pause cameras through **Stop monitoring** or exit the application through **Quit FlintEye**; Docker/systemd users stop their server service.
- **Release status:** public development previews require a complete successful build and corresponding source/license review, with incomplete macOS first-launch and physical-device checks disclosed. Stable promotion also requires the [physical-device acceptance checklist](ACCEPTANCE.md). CI success does not complete those device checks.

Report new reproducible problems through [Issues](https://github.com/noguhiro2002/FlintEye/issues). Remove credentials, setup tokens, private camera URLs and personal footage from reports. Use the [private security channel](../.github/SECURITY.md) for vulnerabilities.

## Monitoring controls in 1.1.3

The tray and WebApp share monitoring state. See [monitoring controls](MONITORING.md) and the [acceptance checklist](ACCEPTANCE.md). Native menu clicks, sleep/resume, physical USB reconnects and 24-hour operation must be recorded separately for each target computer. Automated process tests do not certify those behaviors. Timeline, bulk export, diagnostic ZIP and a fully Japanese UI remain deferred.


## 1.2.0 source follow-up

The [rev11 follow-up matrix](DEVELOPMENT_1_2_0.md) describes this source’s next development changes and pending acceptance. It supersedes the older statement that no diagnostic ZIP exists: the new export is allowlisted and excludes raw logs/configuration, camera URLs, footage and secrets. The Web UI remains English. Signing/notarization, a recording timeline and bulk export remain deferred. The owner’s WinError 2 and Error 32 are not declared recovered by source changes. Built-in LAN access and Docker Desktop require the new build and dedicated real-device acceptance; public 1.1.3 packages do not acquire these changes automatically.
