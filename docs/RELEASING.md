# Build and release FlintEye

[日本語](RELEASING.ja.md)

[Documentation](README.md) · [Acceptance checklist](ACCEPTANCE.md)

## Source-first public development

The public history begins with a single **1.1.1 source snapshot**. The current development preview is **`v1.2.0-preview.4`**. Public development previews require a successful complete build and reviewed licenses/sources. Stable distribution additionally requires the physical-device acceptance checks below. Keep old private installers and locally emulated builds outside public releases. Clone the public repository into a new directory if you still have a checkout with the old private history.

Normal pushes run **Distribution checks**. A push to `main` that changes `flinteye_app/_version.py`, the frontend dependency manifests, frontend install/audit scripts, the Linux package smoke test, or the build workflow also starts **Build release**, which creates desktop installers, tested container archives, and an assembled `release-bundle` in Actions. Run it manually for other rebuilds of the same version. On a public repository readers can access the logs and download artifacts after signing in to GitHub. Only **Publish tested release** uploads approved assets to Releases and GHCR. Keep camera credentials, recordings and personal profiles out of CI inputs and logs.

**Publish tested release** supports these channels:

| Requirement | `private-test` | `public-preview` | `stable` |
| --- | --- | --- | --- |
| Repository | Private | Public | Public |
| Successful complete build from the default branch, unchanged application/build inputs | Required | Required | Required |
| Repository variable | None | `PUBLIC_PREVIEW_ENABLED=true` | `PUBLIC_RELEASE_ENABLED=true` |
| License/source review | May be pending | Required | Required |
| Complete real-device acceptance | May be pending | May be pending; disclose it | Required |
| Embedded channel | Internal test | `preview` | `stable` |
| GitHub release | Normal testing release | **Pre-release**, not Latest | Normal release, Latest |
| Image tags | Exact preview only | Exact preview only | Version and `latest` |
| Command installers | Excluded | Included, pinned preview | Included, pinned stable version |

Public flags default to `false`; enable only the requested distribution channel. A public preview can be published so users can test its installation routes and physical devices. Leave `device_tests_confirmed` false while acceptance is pending: the release notes and distribution manifest must say so. Never describe CI checks as completed physical-device acceptance. Stable publication still requires Windows x64, an M1 Mac and Linux x64: camera capture, recording/playback, GUI quit stopping owned processes, and Windows uninstall removing bundled programs while retaining data. See [acceptance checks](ACCEPTANCE.md).

## GHCR setup

Images use `ghcr.io/noguhiro2002/flinteye`. Only the distribution job receives `packages: write`; it uses `GITHUB_TOKEN`. Docker Hub credentials and personal publication tokens are unnecessary. OCI source/documentation labels associate the package with this repository.

GitHub initially creates packages as private; repository visibility and package visibility are separate. Publication is therefore split into two explicit phases:

1. **prepare:** upload tested image archives without rebuilding and create a draft release. Verify its checksums, source commit, architecture and image digests. The first GHCR package may still be private at this stage.
2. In the package settings, verify the repository association and change the intended public package to **Public**. This exposes the verified container, so license/source review and the selected channel’s acceptance requirements apply before the prepare phase too. Leave private-test packages private.
3. **publish:** rerun with the same build run ID, source commit, channel and preview number. Recheck the uploaded assets and container receipt, then publish the draft. This phase refuses a private package for public channels and never rebuilds or replaces artifacts.

The workflow does not change visibility automatically. Public images allow anonymous pulls; private testing needs authorized `read:packages` credentials. Standard GitHub-hosted runners are used; no larger paid runner is configured. Check current storage limits and runner availability before building.

Official reference: [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Version and source of truth

`flinteye_app/_version.py` holds `VERSION` (numeric `X.Y.Z`), `RELEASE_VERSION` (for example `1.1.3-preview.1`) and `RELEASE_CHANNEL` (`source`, `preview` or `stable`). Installer filenames, Inno Setup and DEB/RPM metadata use the numeric version; download URLs, update comparison and image tags use the complete release version. These values must match the tested build manifest. Source snapshots use the `source` channel and do not advertise installer updates.
Do not overwrite an existing release or image version.

`packaging/vendor-lock.json` fixes source URLs and SHA-256 hashes.
FFmpeg, x264, FreeType, HarfBuzz and MediaMTX are built from these verified sources.
The MediaMTX build excludes its precompiled Raspberry Pi CSI helper; FlintEye's USB/IP inputs remain available.
Its embedded HLS asset is verified against the hash in the pinned upstream source.
Go modules use the upstream go.sum and are vendored into the retained source tree.

The Python dependency set is constrained in `packaging/constraints.txt`; npm uses its package lock.
Refresh dependencies deliberately, then run tests and a new release build.

The build applies a local fix to picomatch 4.0.7 for GHSA-fc5q-39xc-vjpf during `npm ci`. Repeated extglobs containing wildcard stars use the parser's existing literal fallback. The install hook verifies the upstream source hash and the applied change. `npm run audit` checks all dependencies and accounts for this specific advisory only when every reported copy has the verified fix. Other high/critical findings and audit service failures stop the build. Review and remove the local fix when upgrading picomatch. The regression tests cover malicious patterns, normal build globs, and rejected advisory exceptions. [Upstream advisory](https://github.com/advisories/GHSA-fc5q-39xc-vjpf).

## Build and test

1. Set the numeric version, release version and channel in `flinteye_app/_version.py`. For another preview of the same application version, increment the preview number.
2. Push the version change to `main` and follow **Build release** in GitHub Actions. To rebuild the same version from the default branch, start it manually with the diagnostic options off.
3. Download **release-bundle**, review the licenses/corresponding sources, and record the completed and pending [acceptance checks](ACCEPTANCE.md).
4. Keep the build run ID and commit SHA. Publication uses those archived artifacts; it does not rebuild.

The native matrix builds Windows x64/ARM64 and macOS Intel/ARM64 on matching runners. Windows runs the actual EXE installer and uninstaller with an active API, verifying shutdown, bundled-file removal and default data retention. This automated check does not replace physical-camera acceptance.
Windows and macOS use Python 3.14.10, which has installer builds for both CPUs.
Linux packages build inside updated Rocky Linux 9 for Ubuntu, Enterprise Linux and 64-bit Raspberry Pi OS. The bundled runtime requires GLIBC_2.35 symbols: DEBs require libc6 2.35 or newer, while RPMs require the libc.so.6(GLIBC_2.35)(64bit) capability so dnf upgrades older Rocky 9 installations to the backported runtime when needed.
The Linux builder and server image use the pinned Python 3.13 runtime.
GitHub runner availability and minimum-OS hardware checks are separate concerns; a newer runner does not prove an older OS works.

Leave **desktop_only** unchecked for a complete release bundle. Select it only to
diagnose Windows/macOS packaging; that run produces individual desktop artifacts
and cannot be used for publication.

Source builds can take considerable time, especially the first run. Build artifacts are retained for 30 days.
If a runner is unavailable on your GitHub plan, run the equivalent native build on your own machine and resolve runner availability before claiming a complete release matrix.

### Local native build

For an M1 / Apple Silicon Mac, use the [local DMG guide](LOCAL_MACOS_BUILD.md). It prepares an isolated build, rebuilds the shared Settings interface, and tests the installed DMG and MediaMTX path recovery without GitHub Actions. This produces a local test artifact and does not publish it.

On Windows/macOS, install Python 3.14.10, Node.js 22.12+, Go 1.27, a C/C++ compiler, make, CMake, Ninja, pkg-config, Meson and NASM (x64).
Windows uses MSYS2 UCRT64 or CLANGARM64. macOS builds with `MACOSX_DEPLOYMENT_TARGET=14.0`.
Use the Docker builder below for native Linux packages; it compiles the pinned Python 3.13.18 source.

For Windows ARM64, also install Visual Studio C++ ARM64 tools, Rust and native Strawberry Perl. Before the dependency command below, run `python packaging/build_windows_crypto.py` with native ARM64 Python. The constrained cryptography release has no Windows ARM64 wheel: this helper builds and installs its native wheel against statically linked OpenSSL 3.5.9, whose official source hash is pinned in `packaging/vendor-lock.json`. Sources, licenses and build information are retained with the bundle. Use a fresh checkout for a retry. See the [cryptography build instructions](https://cryptography.io/en/stable/installation/#building-cryptography-on-windows) and [OpenSSL Windows instructions](https://github.com/openssl/openssl/blob/openssl-3.5.9/NOTES-WINDOWS.md).

```sh
python -m pip install -c packaging/constraints.txt -r requirements.txt -r packaging/requirements-build.txt meson==1.9.1 ninja==1.13.0
bash packaging/build_vendor.sh
python packaging/build_bundle.py --vendor vendor
python packaging/smoke_desktop_bundle.py
```

Compile Windows installers with Inno Setup using `/DAppVersion=X.Y.Z /DAppArch=amd64` (or `arm64`).
The macOS bundle builder creates a DMG with an Applications shortcut.

For Linux, build the complete package set on the target CPU:

```sh
docker buildx build -f packaging/LinuxBuilder.Dockerfile --target artifacts --output type=local,dest=dist .
```

### Redistribution material

Every native target includes corresponding sources and a license ZIP.
Linux packages also retain signed, exact-version Rocky source RPMs and notices for
the system libraries copied into the bundle, including LGPL libraries. The desktop
bundle excludes the unused interactive `readline` module.
The Docker build captures the exact source versions of its FFmpeg/FFprobe dependency closure and exports their Debian source packages.
MediaMTX's modified source tree and vendored dependencies are exported separately.
Never substitute an upstream homepage link for required corresponding source.

Review the generated inventories for the Python interpreter, Tcl/Tk, OS libraries and any additional binary dependencies before distribution.
Keep source/license archives downloadable for old releases too. Builds enabling FFmpeg `--enable-nonfree` fail.

### Source-cache option

Docker can use a BuildKit named context `vendor-downloads` containing only already-downloaded public MediaMTX/HLS archives.
The build still verifies their pinned hashes. This permits testing where direct source downloads inside Docker are unavailable:

```sh
docker build --build-context vendor-downloads=/path/to/verified-public-source-cache -t flinteye:development .
```

Do not put credentials, runtime configuration or recordings in that cache.

## Publish the tested build

Run **Publish tested release** from the current default branch after the complete build passes. Select the successful complete build run, `public-preview`, and the number from its embedded version (`4` for `1.2.0-preview.4`). Keep the build run ID and publication commit fixed across both phases. License/source review and the matching enable flag are required. Report device acceptance accurately when selecting the checkbox.

The build commit remains the source of truth for installers, container labels and the release tag. A newer publication commit may only change README files, Markdown under `docs/`, Compose, the release-publishing scripts/workflow, or their focused tests. Changes to application code, dependencies, native build inputs, command installer scripts, images or LICENSE require a new complete build. Both commit identities are recorded in the distribution manifest. Updated documentation is packaged reproducibly so the prepare and publish checksums agree. Stable publication also requires a stable embedded identity and a complete build; a preview is not renamed into a stable release.

The attached `documentation.zip` pins active installation examples to the preview being published. Historical fix notes and the original source archive keep their original versions. The main README recommendation changes only after the anonymous public-installation checks have been reviewed. Keep the publication commit fixed across prepare and publish so the documentation checksums remain identical.

GitHub's `GITHUB_TOKEN` cannot create a release for a tested commit whose workflow files differ from the current default branch. The guard rejects that case before uploading images. Prefer a complete build after workflow changes. If images were already uploaded by an interrupted publication, a maintainer can complete the release using their authorized account: reconstruct the files from the original build and publication commit, require every checksum to match the saved `distribution-receipt`, verify the existing container digests, and publish the release against the original build commit. Do not overwrite versioned images or add a broader personal token to CI. Look up drafts through the authenticated release list or release ID; the tag endpoint returns published releases only. [GitHub release API and permissions](https://docs.github.com/en/rest/releases/releases).

The workflow verifies every archived file, loads the tested amd64/arm64 container archives, checks CPU and source identity, creates a multi-platform manifest and records registry digests. Release assets include installers, corresponding source/licenses, bilingual guides/notes, Compose, original build information, distribution metadata, checksums and (for public channels) pinned command installers.

Existing tags, installer contents and versioned image tags are never overwritten. A failed prepare operation may leave uploaded images or a draft: inspect and preserve that provenance before recovery. A draft successfully prepared for the same build can be published by the second phase. Only stable publication updates the container `latest` tag.

## User updates

Preview desktop builds check published previews and stable releases using their full version; stable builds ignore previews. An update link points to the exact tag. Source snapshots are updated from Git. Users install manually after stopping monitoring.
Docker administrators change the image version and run `docker compose pull` followed by `docker compose up -d`.
Retain previous release artifacts and document any configuration migration/rollback requirements.


## 1.2.0 publication gate

For the next 1.2.0-preview.4 build, [installation lifecycle checks](INSTALLATION_QA.md) add 32 install/API/GUI/quit/uninstall/reinstall cases before assembly, using the same-commit installers and images. Missing or failed required evidence blocks the release bundle. A confirmed macOS first-launch policy refusal is explicitly manual-required, with API/GUI untested. Public publication starts another workflow that tests real anonymous Release downloads and GHCR pulls; review that workflow before recommending a new Quick Install version. Native permission, camera and other device gates remain separate.

The 1.2.0 cycle records automated and physical-device results separately in `packaging/acceptance-1.2.0.json`, tied to the exact tested application commit. A public development preview requires `all-native-architectures` to pass; physical cases may remain pending and must be disclosed. Failed cases or missing evidence block publication. Keep `device_tests_confirmed=false` while any physical case is pending; confirming it without complete evidence is rejected. Stable distribution requires all nine recorded cases to pass and explicit device confirmation. Neither path can replace tested app/build inputs, skip license/source review, or overwrite an existing version. Previews remain UNDER DEVELOPMENT, are GitHub Pre-releases, and do not update Latest or the container `latest` tag. [Full 1.2.0 acceptance](DEVELOPMENT_1_2_0.md)
