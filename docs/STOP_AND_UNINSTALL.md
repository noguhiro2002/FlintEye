# Stop and uninstall FlintEye

[日本語](STOP_AND_UNINSTALL.ja.md) · [Documentation](README.md) · [Installation](INSTALL.md)

Choose your installation method below, finish the application shutdown, then remove the application. Keep your data for a later reinstall, or follow [explicit data erasure](#permanently-erase-data-optional) only when you want to delete it.

## Remove by installation method

**Keep accounts, settings and recordings unless you deliberately choose to erase them.** A one-command installer installs the same native application as the binary installer. Its bundled Python/FastAPI, FFmpeg, FFprobe and MediaMTX are removed with the application; do not remove system-wide copies used by other software.

| How you installed | Stop and remove |
| --- | --- |
| Windows script / EXE / Actions package | [Windows](#windows-uninstall-the-application): quit, then uninstall through Windows Settings. |
| macOS script / Actions `install.sh` | [macOS](#macos): disable login startup, quit, and remove `~/Applications/FlintEye.app` or the custom installed copy. |
| macOS DMG / locally built DMG | [macOS](#macos): disable login startup, quit, and remove `/Applications/FlintEye.app` or the copy you dragged elsewhere. |
| Linux script with `--user` | Quit, then run `bash ./install.sh --user --uninstall` with the downloaded script. [User installation and removal](../README.md#install-without-administrator-privileges) |
| Linux script / DEB / RPM | [Linux packages](#linux-packages): disable login startup, quit, then remove the package with apt-get or dnf. |
| Docker Engine / Docker Desktop / development Compose | [Docker Compose](#docker-compose): stop/remove the containers with the same Compose file and project used at installation. |
| systemd | [systemd](#systemd): stop and disable the service before removing its unit and application. |
| Manual source / virtual environment | [Source removal](#manual-source-and-virtual-environment): stop all source processes and preserve any data in the checkout before removing the dedicated environment. |

`docker compose down` keeps named volumes. Do not add `--volumes` / `-v` unless you intend to delete data. Downloaded installer/Actions ZIP files can also be removed independently. If both `/Applications/FlintEye.app` and `~/Applications/FlintEye.app` exist, they are separate copies: quit the active one and remove each copy you no longer need. Avoid launching the older copy during verification.

## Stop monitoring and quit

To exit completely, on Windows choose **Quit FlintEye** from the FlintEye notification-area icon (check the hidden-icons arrow). On macOS, use the FlintEye menu-bar icon. On Linux, use the compact FlintEye control window. **Stop monitoring** instead pauses cameras/recording while leaving settings and the API available; **Start monitoring** resumes. [Status colors, recording finalization and startup preferences](MONITORING.md). Closing the browser or signing out only closes the viewing session; it intentionally leaves monitoring running.

The updated application stops its camera workers, FFmpeg/FFprobe tasks, MediaMTX and API before exiting. It prevents new worker launches during shutdown and cleans up descendants even if a worker has already exited. Windows media children are owned by a kill-on-close job, so an app crash also ends those children. The browser and media tools started by other applications are not part of that job.

Verify that the FlintEye icon disappears, the camera indicator switches off if no other app is using it, and a fresh request to the local FlintEye URL no longer connects. A previously opened browser page can remain visible from memory after the server stops. Restarting FlintEye should restore your saved settings and recordings.

## Windows: uninstall the application

Choose **Quit FlintEye** from the notification-area icon, then use the route for your Windows version:

- **Windows 11:** **Settings → Apps → Installed apps → FlintEye → Uninstall**.
- **Windows 10:** **Settings → Apps → Apps & features → FlintEye → Uninstall**.

Wait for removal to finish. The uninstaller requests normal application shutdown and recording completion, checks for remaining processes and locks from that installation, and removes its bundled program files. If stopping or lock checks fail, removal is cancelled; follow the reported recovery steps and retry. Keep the default **No** answer to the separate data-deletion question to retain accounts, settings and recordings. If this installation created firewall rules, approve their removal when prompted.

The usual locations are:

| Location | Contents | Normal uninstall |
| --- | --- | --- |
| `%LOCALAPPDATA%\Programs\FlintEye` | Application, bundled Python/FastAPI, FFmpeg, FFprobe, MediaMTX and uninstaller | Removed |
| `%LOCALAPPDATA%\FlintEye` | Accounts, settings, logs, recording index and default recordings | Kept |
| A recording folder you selected elsewhere | Recordings | Kept |

FastAPI is part of the bundled Python application; it is not a separate Windows service installed by the desktop installer. You do not need to uninstall Python, FastAPI or FFmpeg globally. The Windows login-start entry for this installation and its shortcuts are removed with the app; a registration pointing at another installation is preserved. Login startup is registered by the desktop app after first setup, not by a silent installer. The optional data-deletion question defaults to **No**; silent uninstall always keeps data. External recording folders are never removed by this uninstaller.

## Recover an older Windows installation

Older installers can leave background processes running after the launcher exits or after removal. Their uninstallers do not contain the new stop procedure. Deleting the data folder will not stop a running API and can destroy settings or recordings.

1. Try **Quit FlintEye** if the icon still exists.
2. If it does not stop, restart Windows. Avoid reopening FlintEye. If a leftover login entry starts it again, disable the FlintEye entry in **Settings → Apps → Startup**, then restart again.
3. If FlintEye is still listed under Installed apps (Windows 11) or Apps & features (Windows 10), uninstall it. If it is no longer listed, open `%LOCALAPPDATA%\Programs` in File Explorer and remove only the leftover **FlintEye** program folder. Keep `%LOCALAPPDATA%\FlintEye` unless you explicitly want to erase your data.
4. Reinstall the fixed package when ready. Your retained data can be reused.

For administrators who want to stop the old installation without rebooting, the updated source includes [stop_windows.ps1](../packaging/stop_windows.ps1). Run the reviewed local script as the same Windows user, adjusting the installation folder if necessary:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packaging\stop_windows.ps1 -InstallDir "$env:LOCALAPPDATA\Programs\FlintEye"
```

This invocation changes the execution policy only for that PowerShell process. The helper checks executable paths and ownership; it does not delete files. It discovers `--data-dir` arguments and requests shutdown for each current-user instance in the selected installation. To target one profile, add `-DataDir "C:\path\to\profile"`; this also handles a profile chosen through an environment variable. Without `-Force`, a timeout is an error. Use `-Force` only when you intend to terminate the matching processes after the timeout. The updated uninstaller requests normal shutdown and cancels incomplete stops; it does not choose this forced fallback for you.

`last-stop-result.json` in the selected data directory (or `%LOCALAPPDATA%\FlintEye` for installation-wide stops) distinguishes `already-stopped`, `requested-shutdown-completed`, `forced`, and `incomplete`. Exit 0 means the selected processes are gone; exit 1 means stopping was incomplete. The separate `last-monitoring-stop.json` receipt records recording completion and pending/forced outcomes. The Windows helper incorporates fresh receipts into its `media_finalization` report; missing or stale receipts remain unverified. A process exit alone does not prove recording completion. Check the final recording and recording index when testing a stop during recording. If the API still responds afterward, identify the process listening on that port: it may be another installation, a manually started server, Docker, or a cached page. Do not indiscriminately terminate every `python.exe` or `ffmpeg.exe` process.

<a id="macos-and-linux"></a>
## macOS

These steps apply to Apple Silicon and Intel Macs, including locally built DMGs. First choose **Disable start at login and quit** from the FlintEye menu-bar icon and wait for the icon to disappear. In Finder choose **Go → Go to Folder**, open the applicable folder below and move the app to Trash.

| Installation | Folder / files to remove |
| --- | --- |
| One-command installer or Actions `install.sh` | `~/Applications/FlintEye.app`; use your selected folder if you passed `--install-directory`. |
| Downloaded or locally built DMG | `/Applications/FlintEye.app`, or the destination where you dragged the app. |
| Previous copy kept by the script | `FlintEye.previous.app` in the same folder, if rollback is no longer needed. |

Eject any mounted FlintEye DMG and delete downloaded DMGs/ZIPs if you no longer need them. Removing the download alone does not remove the installed app. If both application folders contain a copy, remove each unwanted copy after disabling its login startup.

On macOS, choose **Disable start at login and quit** from the FlintEye menu-bar icon before moving `FlintEye.app` to Trash. This removes `~/Library/LaunchAgents/community.flinteye.plist` when it belongs to the current installation/profile, unloads that login registration, and remembers that autostart is disabled. This explicit action can also remove the older default-profile registration that used only the shared bundle ID. Automatic startup does not replace that ambiguous legacy entry. Dragging an app to Trash by itself does not run an uninstaller or remove its LaunchAgent.

If the app is already stopped, disable login startup before removing it. For a one-command installation, run:

```sh
"$HOME/Applications/FlintEye.app/Contents/MacOS/FlintEye" --disable-autostart
```

For a DMG copied to the system Applications folder, run instead:

```sh
/Applications/FlintEye.app/Contents/MacOS/FlintEye --disable-autostart
```

Adjust the app path if installed elsewhere, and add `--data-dir` for a custom profile. This command changes login startup only; it does not stop another running instance or delete settings/recordings. To restore login startup later, run the same app with `--enable-autostart`. New Mac registrations target the specific installed app copy; first move the app to Applications, because temporary App Translocation paths are not registered. A registration owned by another installation/profile is preserved, and the enable command reports failure instead of replacing it. If the app was already deleted, remove only the FlintEye LaunchAgent named above, then log out and back in to verify it no longer starts.

## Linux packages

The one-command installer uses your distribution's DEB or RPM package manager. The same removal steps apply to packages opened manually, including ARM64 Raspberry Pi packages.

1. Disable **Start at login** in FlintEye, choose **Quit FlintEye**, and wait for camera/recording shutdown. If you configured a service, [stop and disable it first](#systemd).
2. Run the command for the package type you installed.

**Ubuntu / Debian / Raspberry Pi OS — DEB:**

```sh
sudo apt-get remove flinteye
```

**Rocky Linux / AlmaLinux / RHEL — RPM:**

```sh
sudo dnf remove flinteye
```

If the app is already stopped, `/opt/flinteye/FlintEye --disable-autostart` disables its login entry before package removal. Run it as your desktop user, without sudo; add `--data-dir` if you used a custom profile. If the package was already removed, remove only this installation's leftover `~/.config/autostart/flinteye.desktop` after checking that it does not point to another installation. User data and external recording folders are retained.

## Docker Compose

Run the matching command from the original deployment directory or checkout root. Keep the same Compose file(s), `.env`, project name and any `-p` / `--project-name` or `--env-file` options used at startup; they identify which containers and volume belong to the installation.

| Deployment | Working directory | Stop and remove containers |
| --- | --- | --- |
| Linux Docker Engine, downloaded `compose.yaml` | Folder containing the downloaded file and `.env` | `docker compose down` |
| Docker Desktop, downloaded `compose.desktop.yaml` | Folder containing the downloaded file and `.env` | `docker compose -f compose.desktop.yaml down` |
| Linux Docker Engine from source | Checkout root | `docker compose down` |
| Docker Desktop from source | Checkout root | `docker compose -f deploy/compose.desktop.yaml down` |
| Development image | Checkout root | `docker compose -f deploy/compose.dev.yaml down` |

Wait for the command to finish so recordings can finalize. It removes the containers and their owned processes, including FastAPI, FFmpeg and MediaMTX. Named volumes and bind-mounted recordings remain. Do not add `--volumes` / `-v` for a normal uninstall.

The downloaded image stays cached after `down`. To reclaim that space, optionally remove only the FlintEye image you used, for example `docker image rm ghcr.io/noguhiro2002/flinteye:1.2.0-preview.10`, or `docker image rm flinteye:development` for the development image. Adjust the version to your installed tag; do not force removal if another container uses it. Docker itself and images/layers used by other applications stay installed. Keep the Compose files and `.env` for a later reinstall; remove them only if you no longer need the deployment definition.

## systemd

For the system service in the server guide:

```sh
sudo systemctl disable --now flinteye
```

Wait for shutdown. Remove the manually installed `/etc/systemd/system/flinteye.service` and any drop-ins you created for this service, then reload systemd:

```sh
sudo systemctl daemon-reload
```

If you installed a DEB/RPM, remove the application through its [package manager](#linux-packages). If you manually extracted a bundle to `/opt/flinteye`, remove only that dedicated program folder after preserving any data you stored inside it. Keep `/var/lib/flinteye`, your custom data directory and external recordings for reuse. A user service instead needs `systemctl --user disable --now YOUR_UNIT.service`, removal of that actual user unit/drop-ins and `systemctl --user daemon-reload`. Use the name and location you configured; the desktop installer does not automatically create a system service.

## Manual source and virtual environment

This route applies to source execution on Windows, macOS and Linux. Disable any desktop login startup while the source launcher is still available. Stop the desktop launcher with **Quit FlintEye**, or press Ctrl+C in each terminal running the API, frontend development server or standalone tools, and wait for shutdown. If systemd or Compose starts it, use that deployment's stop/remove steps first.

Back up `.env`, `runtime.json`, recordings and any custom data kept in the checkout. Deactivate an activated virtual environment with `deactivate`, then remove only the dedicated FlintEye checkout and virtual environment using your file manager. This also removes its `node_modules` and generated frontend files. An environment created outside the checkout must be removed separately. The default desktop data folder remains available for a reinstall.

FlintEye is not installed as a pip application package; `requirements.txt` installs dependencies. Do not use `pip uninstall flinteye` as the removal procedure or remove shared Python, Node.js, FFmpeg or MediaMTX installations used by other software. Remove manually configured source autostart entries only if they belong to this installation.

## Permanently erase data (optional)

**This is separate from normal application removal and permanently deletes accounts, settings, logs and recordings.** Back up anything you need, stop every instance using the selected data, and disable its startup before proceeding. If you want to keep your setup for reinstalling, leave these locations untouched.

| Installation | Data retained by normal removal |
| --- | --- |
| Windows desktop | `%LOCALAPPDATA%\FlintEye`. The uninstaller's separate deletion question defaults to **No**; choose **Yes** only to erase this default folder, or delete the retained folder in File Explorer after shutdown. Silent removal always keeps it. |
| macOS desktop | `~/Library/Application Support/FlintEye`. Open it with Finder's **Go → Go to Folder** and move the FlintEye data folder to Trash only if erasure is intended. |
| Linux desktop | `~/.local/share/flinteye`, or `$XDG_DATA_HOME/flinteye` when `XDG_DATA_HOME` is set. Delete only the selected FlintEye folder after shutdown. |
| systemd | `/var/lib/flinteye`, unless you configured another data directory. An administrator must remove it separately if erasure is intended. |
| Docker | The named volume mounted at `/data`, plus any separately bind-mounted recording folders. |
| Custom source or desktop profile | The directory chosen with `--data-dir` or `FLINTEYE_DATA_DIR`, plus external recording folders. |

External recording locations and custom profiles are not erased by the Windows uninstaller's default-folder deletion. Inspect those locations separately before deleting them. For Docker, adding `--volumes` to the matching `down` command explicitly deletes the project's Compose-managed named volumes; it does not delete bind-mounted host folders or external volumes. Confirm the project and volume contents first, especially if the Compose file includes other services. Avoid broad Docker prune commands.

### Remove leftover startup and LAN trust

Use the [macOS](#macos), [Linux](#linux-packages) or [older Windows recovery](#recover-an-older-windows-installation) instructions for a leftover startup registration. Remove only entries belonging to the installation you are retiring. For systemd or Docker, disabling/removing their deployment is separate from desktop login startup.

Uninstalling the server does not remove the certificate you trusted on other computers and phones. On **each viewing device**, remove only this installation's FlintEye CA or configuration profile after checking its fingerprint. Follow the [per-device certificate instructions](LAN_ACCESS.md#trust-the-certificate-once-on-each-viewing-device). Windows removes product-owned firewall rules through its uninstaller; Linux/macOS firewall or reverse-proxy rules you configured manually need separate administrator cleanup.

## Which builds contain this change?

Preview 10 includes these shutdown and removal fixes. Older downloaded installers retain their original behavior. Check the complete release version and source commit in **Information**. The [M1 build guide](LOCAL_MACOS_BUILD.md) can also build the current committed source without GitHub Actions.

Automated checks cover owned-process cleanup, an exited worker with a surviving child, Windows job ownership under Wine, and the installed-bundle shutdown request. Wine does not replace a real Windows uninstall test. Verify quit, camera release and restart on each target device; check that unrelated applications remain running and that uninstall retains accounts and recordings.

On macOS, the normal Quit action from the Dock also goes through this shutdown sequence. Force Quit and operating-system termination are separate cases; the normal Quit path is the one to use when testing camera release.


## 1.2.0 development removal

Windows Settings uses a maintenance launcher that excludes duplicate removal for one installation, requests normal recording completion, checks locks on uninstall data and then runs the uninstaller. Forced termination is not the default. Failure leaves a diagnostic in the default data folder and offers a safe retry. Another program’s lock must not be removed by deleting unins000.dat or killing unrelated processes. The owner’s reported Error 32 still requires real-machine retest. Product-owned Firewall rules are removed with explicit UAC approval; refusal interrupts removal so residual access is not concealed. Client certificate trust must be removed on each viewing device. Settings and recordings remain by default; explicit deletion targets the default data directory only. [LAN trust removal](LAN_ACCESS.md)
