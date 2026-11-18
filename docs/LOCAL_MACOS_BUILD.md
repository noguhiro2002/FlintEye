# Build a test DMG on your M1 Mac

[日本語](LOCAL_MACOS_BUILD.ja.md) · [Documentation](README.md) · [Build and release](RELEASING.md)

This procedure builds the current committed source on an Apple Silicon Mac without using GitHub Actions minutes. It includes the MediaMTX path repair, the consolidated Settings screen, and the **FlintEye API** documentation title. FFmpeg, FFprobe and MediaMTX are built and bundled automatically; do not install separate copies for FlintEye.

The result is a local test build. Nothing is uploaded, published, installed into Applications, or changed in your existing FlintEye data. Existing GitHub installers remain unchanged. This procedure targets your own Mac; it does not establish compatibility with every supported macOS version.

Build 1.2.0-preview.3 from `main`. Record the source commit printed by the build and use an isolated test profile.

## 1. Prepare the Mac once

Use Terminal on the Mac itself, with **Open using Rosetta** disabled. Connect power and leave enough free space for source archives, media compilation, Python packages and the DMG; allow roughly 15–20 GB of working space initially. Build time depends on the Mac and network, so the first run can take a while.

Install Apple's command-line developer tools and wait for their installation to finish:

```sh
xcode-select --install
```

If they are already installed, continue. Install native Apple Silicon Homebrew using its [official instructions](https://docs.brew.sh/Installation) if `/opt/homebrew/bin/brew` does not exist. Then install the build tools:

```sh
/opt/homebrew/bin/brew install python@3.14 python-tk@3.14 node@22 go cmake pkgconf ninja gh
```

Use Python 3.14.10 or a newer 3.14 patch, Node.js 22.12 or newer 22.x, and Go 1.27 or newer. The script selects native Homebrew tools explicitly, even if your shell has an active Conda environment. It creates its own Python environment. Homebrew provides [Tk separately for Python 3.14](https://formulae.brew.sh/formula/python-tk@3.14); Tk is needed for the setup/connection information and folder-selection windows. The initial administrator password is entered in the browser. [Node.js 22](https://formulae.brew.sh/formula/node@22) matches the existing build workflow, and the pinned MediaMTX source requires [Go 1.27 or newer](https://formulae.brew.sh/formula/go).

## 2. Get the updated source

Create a dedicated checkout of the public source; no GitHub login is required. Choose a path without spaces. If you used the earlier private repository, clone into a new directory instead of pulling its unrelated history.

```sh
mkdir -p ~/Developer
cd ~/Developer
git clone --branch main https://github.com/noguhiro2002/FlintEye.git FlintEye-build
cd FlintEye-build
```

For subsequent builds, update that checkout instead of cloning again:

```sh
cd ~/Developer/FlintEye-build
git switch main
git pull --ff-only
```

Keep this checkout clean. The helper builds a fresh snapshot of the current commit, so it will stop if there are uncommitted source changes. Ignored recordings, runtime settings, old build directories and dependency folders are not copied into the snapshot.

## 3. Build and automatically verify the DMG

Quit any running FlintEye from its menu-bar icon using **Quit FlintEye**. Also stop any separate MediaMTX instance using ports 8554, 8889, 9997 or UDP 8189. Closing the browser alone does not stop monitoring.

Check the tools first:

```sh
/opt/homebrew/opt/python@3.14/bin/python3.14 packaging/build_macos_local.py --check-only
```

Then build. `caffeinate` keeps the Mac awake while this command runs; keep the lid open:

```sh
caffeinate -i /opt/homebrew/opt/python@3.14/bin/python3.14 packaging/build_macos_local.py
```

The helper uses two compile jobs by default for an M1 MacBook Air. If memory is tight, repeat with `--jobs 1`. Each attempt gets its own directory under `dist/local-macos/`, so a retry does not overwrite a previous build.

It performs these steps in order:

1. Extract the committed source into a fresh build directory and install constrained Python dependencies in a separate environment.
2. Run the MediaMTX startup regression tests, compile the pinned media tools, and test authenticated media input.
3. Rebuild the shared web interface and package it with Python and the media tools into an ARM64 app and DMG. Apply the same local ad-hoc signature as the regular build; no Apple developer account is required.
4. Mount the DMG, verify the final app with `codesign --verify --deep --strict`, copy the app with its internal links preserved, and eject the DMG. Verify the copied app and prove that a deliberately modified copy fails verification before restoring it. Record the Gatekeeper assessment separately; an ad-hoc signature does not imply Developer ID trust or notarization. Then test setup and media. Check setup, authentication, worker loading, MediaMTX, synthetic recording and playback download.
5. Move that test app to a different directory and restart it with the same temporary profile. This checks the saved-path repair that addresses the macOS startup failure.

The automated test uses temporary accounts and generated video. It does not open your cameras, use your saved password, or modify your existing recordings.

Success ends with **Local DMG verified:** and the exact file path. Open the `artifacts` folder under that build directory. It contains:

- `FlintEye-VERSION-local-<commit>-macos-arm64.dmg`
- Corresponding media sources and licenses
- `vendor-sha256.json`, `build-info.json`, the `-signature.json` integrity/Gatekeeper report, and `SHA256SUMS`

The application reports the numeric version from the selected source; the filename and build information identify the new source commit. This is not a replacement for an existing release. To check file integrity, open Terminal in the `artifacts` folder and run:

```sh
shasum -a 256 -c SHA256SUMS
```

If a step fails, the helper stops and prints the working directory. Keep its `build.log` when reporting the failure. A DMG left inside `source/dist` after a failed test is not a verified result. Rerunning the helper starts a fresh build. Source downloads retain HTTPS certificate and checksum verification.

## 4. Install and check your existing setup

1. Ensure the old FlintEye is stopped. Open the newly verified DMG, replace `/Applications/FlintEye.app` with the complete app, and eject the DMG. Open the installed app. Do not delete `~/Library/Application Support/FlintEye`.
2. Sign in with your existing administrator password. Check that your cameras and recording settings remain present. If macOS requests confirmation, use the app-specific **Privacy & Security → Open Anyway** action described in the [installation guide](INSTALL.md).
3. Check that MediaMTX starts and **Live View** displays video. An old saved `AppTranslocation` executable path should be repaired automatically. Verify that the camera no longer cycles on and off, then record and play a short clip.
4. Open **Settings**. The separate **Recording storage and viewer access** panel should be gone. Use **Recording** for the folder, quota and retention, **Runtime & access** for the viewer password, and **General** for update checks. Save recording changes with **Save changes**. Check `/docs` and `/redoc` for the title **FlintEye API**.
5. Quit and reopen the app, then check login autostart separately. Keep these physical-camera and desktop checks distinct from the automated build result.

If video still fails, inspect `orchestrator.log` and `mediamtx.log` under `~/Library/Application Support/FlintEye/logs/`. A fixed startup path does not rule out a camera permission, port conflict or capture-format problem.

## The same Settings design on other installations

Windows, macOS, Linux packages, Docker and source installations use the same `frontend/src` interface. The old oversized panel has been removed there for all platforms. The native bundle builder and Docker builder both rebuild that interface from source.

An already downloaded installer or already built Docker image keeps its old interface. Rebuild and install the corresponding platform's package, or rebuild the container, to get the change. Reopening an old installer cannot update its embedded screen. This M1 procedure creates an ARM64 macOS DMG only; Windows and Linux builds use their own [native build instructions](RELEASING.md#local-native-build).

The current Windows source also suppresses console windows for camera discovery, thumbnail updates and other background media processes while preserving their error output. That fix requires a newly built Windows installer; it does not change existing `.exe` downloads.

The current source also includes [complete shutdown and uninstall fixes](STOP_AND_UNINSTALL.md). The installed-bundle test requests shutdown and checks that the API and MediaMTX listening ports close. On your Mac, additionally choose **Quit FlintEye** while a camera is streaming, verify that its indicator turns off and the icon disappears, then reopen FlintEye and check that the saved configuration still works.

The local M1 build also runs the native AppKit quit-delegate test. After installation, test both the menu-bar stop action and the normal Quit action from the Dock while a camera is streaming. These physical-device checks remain necessary.
