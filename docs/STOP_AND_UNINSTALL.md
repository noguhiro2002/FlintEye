# Stop and uninstall FlintEye

[日本語](STOP_AND_UNINSTALL.ja.md) · [Documentation](README.md) · [Installation](INSTALL.md)

## Stop monitoring

On Windows, choose **Stop monitoring and quit** from the FlintEye notification-area icon (check the hidden-icons arrow). On macOS, use the FlintEye menu-bar icon. On Linux, use that button in the FlintEye desktop window. Closing the browser or signing out only closes the viewing session; it intentionally leaves monitoring running.

The updated application stops its camera workers, FFmpeg/FFprobe tasks, MediaMTX and API before exiting. It prevents new worker launches during shutdown and cleans up descendants even if a worker has already exited. Windows media children are owned by a kill-on-close job, so an app crash also ends those children. The browser and media tools started by other applications are not part of that job.

Verify that the FlintEye icon disappears, the camera indicator switches off if no other app is using it, and a fresh request to the local FlintEye URL no longer connects. A previously opened browser page can remain visible from memory after the server stops. Restarting FlintEye should restore your saved settings and recordings.

## Windows: uninstall the application

Use **Settings → Apps → Installed apps → FlintEye → Uninstall**. The updated uninstaller first asks the installed app to stop, waits for it, then checks for remaining processes from that exact installation belonging to the current Windows user. It stops any remaining bundled processes before deleting the program files. If it cannot confirm that they stopped, removal is aborted with an error so you can restart Windows and try again.

The usual locations are:

| Location | Contents | Normal uninstall |
| --- | --- | --- |
| `%LOCALAPPDATA%\Programs\FlintEye` | Application, bundled Python/FastAPI, FFmpeg, FFprobe, MediaMTX and uninstaller | Removed |
| `%LOCALAPPDATA%\FlintEye` | Accounts, settings, logs, recording index and default recordings | Kept |
| A recording folder you selected elsewhere | Recordings | Kept |

FastAPI is part of the bundled Python application; it is not a separate Windows service installed by the desktop installer. You do not need to uninstall Python, FastAPI or FFmpeg globally. The Windows login-start entry for this installation and its shortcuts are removed with the app; a registration pointing at another installation is preserved. Login startup is registered by the desktop app after first setup, not by a silent installer. The optional data-deletion question defaults to **No**; silent uninstall always keeps data. External recording folders are never removed by this uninstaller.

## Recover an older Windows installation

Older installers can leave background processes running after the launcher exits or after removal. Their uninstallers do not contain the new stop procedure. Deleting the data folder will not stop a running API and can destroy settings or recordings.

1. Try **Stop monitoring and quit** if the icon still exists.
2. If it does not stop, restart Windows. Avoid reopening FlintEye. If a leftover login entry starts it again, disable the FlintEye entry in **Settings → Apps → Startup**, then restart again.
3. If FlintEye is still listed in Installed apps, uninstall it. If it is no longer listed, open `%LOCALAPPDATA%\Programs` in File Explorer and remove only the leftover **FlintEye** program folder. Keep `%LOCALAPPDATA%\FlintEye` unless you explicitly want to erase your data.
4. Reinstall the fixed package when ready. Your retained data can be reused.

For administrators who want to stop the old installation without rebooting, the updated source includes [stop_windows.ps1](../packaging/stop_windows.ps1). Run the reviewed local script as the same Windows user, adjusting the installation folder if necessary:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packaging\stop_windows.ps1 -InstallDir "$env:LOCALAPPDATA\Programs\FlintEye"
```

This invocation changes the execution policy only for that PowerShell process. The helper checks executable paths and ownership; it does not delete files. It discovers `--data-dir` arguments and requests shutdown for each current-user instance in the selected installation. To target one profile, add `-DataDir "C:\path\to\profile"`; this also handles a profile chosen through an environment variable. Without `-Force`, a timeout is an error. Use `-Force` only when you intend to terminate the matching processes after the timeout. The uninstaller uses that bounded fallback for its own installation.

`last-stop-result.json` in the selected data directory (or `%LOCALAPPDATA%\FlintEye` for installation-wide stops) distinguishes `already-stopped`, `requested-shutdown-completed`, `forced`, and `incomplete`. Exit 0 means the selected processes are gone; exit 1 means stopping was incomplete. A successful parent shutdown request does not prove that an in-progress recording was finalized: Windows currently uses process-tree termination for media children. Check the final recording and recording index when testing a stop during recording. If the API still responds afterward, identify the process listening on that port: it may be another installation, a manually started server, Docker, or a cached page. Do not indiscriminately terminate every `python.exe` or `ffmpeg.exe` process.

## macOS and Linux

On macOS, choose **Disable start at login and quit** from the FlintEye menu-bar icon before moving `FlintEye.app` to Trash. This removes `~/Library/LaunchAgents/community.flinteye.plist` when it belongs to the current installation/profile, unloads that login registration, and remembers that autostart is disabled. This explicit action can also remove the older default-profile registration that used only the shared bundle ID. Automatic startup does not replace that ambiguous legacy entry. Dragging an app to Trash by itself does not run an uninstaller or remove its LaunchAgent.

If the app is already stopped, run this command before removing it:

```sh
/Applications/FlintEye.app/Contents/MacOS/FlintEye --disable-autostart
```

Adjust the app path if installed elsewhere, and add `--data-dir` for a custom profile. This command changes login startup only; it does not stop another running instance or delete settings/recordings. To restore login startup later, run the same app with `--enable-autostart`. New Mac registrations target the specific installed app copy; first move the app to Applications, because temporary App Translocation paths are not registered. A registration owned by another installation/profile is preserved, and the enable command reports failure instead of replacing it. If the app was already deleted, remove only the FlintEye LaunchAgent named above, then log out and back in to verify it no longer starts.

On Linux, stop monitoring and remove the package through the package manager. Keep the data directories listed in [Recording lifecycle](DISTRIBUTION.md#recording-lifecycle) unless you deliberately want to erase them. A manually configured systemd service or Docker container is administered separately and must be stopped through its own deployment tools.

## Which builds contain this change?

These fixes require a rebuilt installer. Previously downloaded installers are unchanged. Check the source commit in the build information: the application version alone does not identify these changes. The [M1 build guide](LOCAL_MACOS_BUILD.md) builds the current committed source without GitHub Actions.

Automated checks cover owned-process cleanup, an exited worker with a surviving child, Windows job ownership under Wine, and the installed-bundle shutdown request. Wine does not replace a real Windows uninstall test. Verify quit, camera release and restart on each target device; check that unrelated applications remain running and that uninstall retains accounts and recordings.

On macOS, the normal Quit action from the Dock also goes through this shutdown sequence. Force Quit and operating-system termination are separate cases; the normal Quit path is the one to use when testing camera release.
