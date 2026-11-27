# Installation lifecycle checks

[日本語](INSTALLATION_QA.ja.md) · [Documentation](README.md)

GitHub Actions checks **install → API and browser operation → Quit → uninstall → reinstall with retained data**. Preview 10 uses commit `6508296ff967bbb5505dc51936fe0c85d144a8c7`. **28 of 36 build-time cases** passed all seven stages. The eight macOS installer cases passed installation, integrity and removal and require first-launch approval before API/GUI, Quit and retained-data reinstall can be exercised. [Preview 10 build results](https://github.com/noguhiro2002/FlintEye/actions/runs/45609459603)

**12 of 14 public-installation cases** passed all seven stages, including both Windows scripts, Linux DEB/RPM in system and user modes, and both GHCR architectures. The two macOS script cases require first-launch approval. Physical-device acceptance is pending. [Preview 10 public-installation results](https://github.com/noguhiro2002/FlintEye/actions/runs/45624057667)

## What the browser checks

`frontend/tests/installed.mjs` connects to the installed application's HTTP server without substituting API responses. It creates an administrator through the browser, checks the embedded release/commit, registers two synthetic RTSP cameras and saves settings. It opens Dashboard, Information, Settings, Live View, Multiview and Recordings; checks advancing WebRTC video and incoming audio; plays/downloads an actual recording; and verifies viewer login and denied writes.

Audio starts off for both cameras. The test enables one camera and verifies Standard recording audio: 16-bit PCM, 16 kHz, mono. The second camera must remain silent. FFmpeg reads every generated recording to the end with decoding errors treated as failures. No physical camera, microphone, real password or personal footage is needed.

**Stop monitoring** must stop media processes while leaving the API available. Saving settings must not restart them. The ordinary Quit request must close the API and owned media listeners before removal. Uninstall must remove the program while preserving accounts, configuration and recordings. Reinstall must reuse the administrator password and retain both cameras, audio settings and recording inventory. Cleanup after failure cannot make normal Quit pass.

Existing synthetic frontend tests still cover errors, slow responses, responsive layout and accessibility alongside these real-backend tests.

Synthetic camera publishers use isolated copies of the media tools outside the application installation. The test must not keep installed executables open or make the uninstaller treat its own test cameras as application processes.

## Build-time matrix

Every case uses the build's source commit. Installer cases reuse its existing artifacts; they do not compile another application for each method.

| Host / target | CPUs | Installation methods |
| --- | --- | --- |
| Windows Server 2022 / Windows 11 ARM | x64 / ARM64 | EXE; one-script installer |
| macOS 15 and 26 | Intel / Apple Silicon | DMG; one-script installer |
| Ubuntu 24.04 desktop in a disposable Xvfb container | x64 / ARM64 | DEB, system-wide script, user script (`--user`); actual desktop entry for DEB |
| Rocky Linux 9 desktop in a disposable Xvfb container | x64 / ARM64 | RPM, system-wide script, user script (`--user`); actual desktop entry for RPM |
| Ubuntu 24.04 hosted VM | x64 / ARM64 | Shipped systemd unit with a separate QA service/state directory |
| Linux Docker Engine | x64 / ARM64 | Distribution Compose; development Compose using the already-built image |
| Windows, macOS 15, Ubuntu 24.04 | x64 / ARM64 | Source snapshot in a dedicated Python environment |

There are **36 required cases**. macOS runners are pinned to 15/26 and Intel/Apple Silicon rather than `latest`; see [GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners). Windows Server CI does not establish Windows 10 compatibility. A Linux container is not a physical Linux desktop; Docker Engine is not Docker Desktop.

The four Linux `--user` cases run in containers without sudo or privilege escalation. They check the real API and Web UI, reject removal while FlintEye is running, hash the saved settings and recordings before and after removal, and reopen them after reinstall.

Windows script QA uses the supported `-Silent -NoStart` options, then starts the installed executable. Internet-origin metadata is retained. Interactive shell warnings, SmartScreen and native permission dialogs remain physical-device checks. macOS script QA observes its normal open request asynchronously so an OS approval dialog cannot prevent diagnostic collection.

## macOS installation, integrity and permission are separate

Both DMG and one-script installs must produce the declared executable, valid internal links, the FlintEye icon and a valid ad-hoc integrity signature. The test then calls Launch Services with `open FlintEye.app`, retaining normal download quarantine. A headless subprocess or successful `codesign --verify` alone is not a normal first launch.

Community previews have no Developer ID/notarization. If macOS explicitly refuses an ad-hoc first launch, the receipt records `os_launch: manual-required`, API/GUI/Quit/reinstall as `not-run`, and still checks removal. This is **not a passed application test**. It may accompany an UNDER DEVELOPMENT preview with that limitation disclosed. Missing executables, damaged signatures, unrecognized launch failures or executed test failures block assembly. The suite never removes quarantine, disables Gatekeeper or simulates approval.

If macOS reports an internal XProtect error, QA assesses a freshly compiled harmless control app on the same runner. The internal-error text must match after substituting the app name; an extra app-specific finding or a threat verdict blocks acceptance. This comparison does not grant execution permission or verify FlintEye operation. A confirmed first-launch denial still leaves API/GUI tests not run.

On the actual Mac, try opening FlintEye, then use **System Settings → Privacy & Security → Open Anyway → Open**, if offered. Managed Macs may need administrator assistance. Record first launch and repeat the API/GUI/removal checks after approval. An `amfid` rejection can produce “The file can't be found” even when the executable exists; do not erase accounts/settings to address it. See [installation and OS confirmation](INSTALL.md#unsigned-packages).

## Evidence and publication

Open **Actions → Build release → Artifacts**. Each `lifecycle-*` artifact contains `lifecycle.json`, browser screenshots/video, Playwright traces, real API/build identity, recording decode/audio checks, fixture logs and available app/OS logs. Failure evidence uploads even if the job fails. All credentials and media are synthetic. Never reuse the harness with personal profiles.

Assembly requires the complete matrix and matching commit/release evidence. Missing cases, failed stages, modified artifacts or missing real-browser evidence block `release-bundle`. Attached `QA-RESULTS.json` distinguishes completed CI cases from macOS approval requirements and pending physical acceptance. Existing releases/files are never overwritten.

Diagnose existing installers reuses archived EXE, DMG or Linux packages while the harness or installer scripts are corrected. It verifies that compiled application and native compiler inputs have not changed and records any diagnostic script overlay. These receipts are explicitly rejected by publication validation. A fresh complete Build release run is still required before publication.

After an authorized public publication, **Published installation lifecycle** runs another **14 cases**. It downloads scripts/packages anonymously from real Release URLs, verifies checksums, tag and commit, and runs scripts without a local package override. It also anonymously pulls both GHCR CPU images, checks their published digest/commit and runs the Compose lifecycle. Recommend new Quick Install URLs only after reviewing these results; successful upload alone is not an online install pass. The workflow can also be dispatched for a published release matching the selected checkout.

## Earlier Preview 5 results

GitHub Actions checks **install → API and browser operation → Quit → uninstall → reinstall with retained data**. For **1.2.0-preview.5**, 24 of 32 build-time cases passed all seven stages. The other eight macOS installer cases passed installation, integrity and removal. First-launch approval is required to test the installed API, browser, Quit and retained-data reinstall. Physical-device checks are pending. [Build results](https://github.com/noguhiro2002/FlintEye/actions/runs/44712701442)

In the first Windows ARM64 EXE case, recording completion could not be verified during Stop. The repeat with the same installer passed all seven stages. [Windows ARM64 recheck](https://github.com/noguhiro2002/FlintEye/actions/runs/44712701442/job/136250360304)

The public-installation recheck used the published one-command scripts and GHCR images for **1.2.0-preview.5**. Eight of ten cases passed the full lifecycle. The macOS Intel and Apple Silicon script cases passed install, integrity and removal. They require OS approval before the installed API, browser, Quit and retained-data reinstall can be tested. [Public installation results](https://github.com/noguhiro2002/FlintEye/actions/runs/44729094734)

The first public run reached a shared GitHub anonymous REST API limit before testing the Linux x64 GHCR and macOS ARM64 script cases. The tag check now uses anonymous Git over HTTPS. The recheck used the same published installers and images. [Initial public run](https://github.com/noguhiro2002/FlintEye/actions/runs/44727482801)

## Run the harness locally

Native tests remove an installation. Use only a disposable VM or fresh dedicated QA account: existing default installations, startup registrations and data directories are refused. Do not pass `--disposable` for your normal account. The source test creates a temporary snapshot and separate profile/ports without stopping an existing FlintEye instance.

Prepare Python and Node, install the frontend's dependencies, build it and run `npx playwright install chromium` from `frontend/`. Install the harness's HTTP client with `python -m pip install httpx==0.28.1` in a QA environment. With the matching Actions artifact extracted into `installer-input` on a fresh QA Mac:

```sh
python packaging/lifecycle.py --method macos-dmg --artifact-directory installer-input --output lifecycle-results/macos-dmg --disposable
```

Other methods: `windows-exe`, `windows-script`, `macos-script`, `linux-deb`, `linux-deb-script`, `linux-rpm`, `linux-rpm-script`, `linux-deb-user-script`, `linux-rpm-user-script`, `linux-systemd`. Linux package cases require Docker Engine. Source uses `--method source --media-directory vendor/bin` with vetted native media binaries. Compose uses `--method compose` or `--method compose-development` and `--image YOUR_ALREADY_BUILT_IMAGE`; each creates its own project/volume without rebuilding that image. Leave the default release unchanged unless testing a matching published build.

## Checks still required on real machines

The [eight device gates](RELEASE_CHECKLIST_1_2_0.md) remain mandatory before stable promotion: native menus/windows and accessibility; macOS first-launch/camera/microphone permissions; removal on the originally affected Windows PC; USB cameras/reconnect; sleep; separate LAN clients/certificate trust; actual Docker Desktop host video; minimum supported OS versions; and a 24-hour run. CI cannot approve these on the user's computer. Record Pass, Fail or Not tested with evidence rather than inferring a pass from builds or browser-only tests.
