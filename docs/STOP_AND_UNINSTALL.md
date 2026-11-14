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

FastAPI is part of the bundled Python application; it is not a separate Windows service installed by the desktop installer. You do not need to uninstall Python, FastAPI or FFmpeg globally. The Windows login-start entry and shortcuts are removed with the app. The optional data-deletion question defaults to **No**; silent uninstall always keeps data. External recording folders are never removed by this uninstaller.

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

This invocation changes the execution policy only for that PowerShell process. The helper checks executable paths and ownership; it does not delete files. If the API still responds afterward, identify the process listening on that port: it may be another installation, a manually started server, Docker, or a cached page. Do not indiscriminately terminate every `python.exe` or `ffmpeg.exe` process.

## macOS and Linux

Stop monitoring before replacing or deleting the app. On macOS, remove the installed `FlintEye.app`; on Linux, remove the package through the package manager. Keep the data directories listed in [Recording lifecycle](DISTRIBUTION.md#recording-lifecycle) unless you deliberately want to erase them. A manually configured systemd service or Docker container is administered separately and must be stopped through its own deployment tools.

## Which builds contain this change?

These fixes require a rebuilt installer. Previously downloaded 1.1.0/1.1.1 installers are unchanged; a local build still reports 1.1.1, so check the source commit in its build information. The [M1 build guide](LOCAL_MACOS_BUILD.md) builds the current committed source without GitHub Actions.

Automated checks cover owned-process cleanup, an exited worker with a surviving child, Windows job ownership under Wine, and the installed-bundle shutdown request. Wine does not replace a real Windows uninstall test. Verify quit, camera release and restart on each target device; check that unrelated applications remain running and that uninstall retains accounts and recordings.

On macOS, the normal Quit action from the Dock also goes through this shutdown sequence. Force Quit and operating-system termination are separate cases; the normal Quit path is the one to use when testing camera release.
