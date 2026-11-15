# Monitoring status and desktop controls

[日本語](MONITORING.ja.md) · [Documentation](README.md) · [Stop and uninstall](STOP_AND_UNINSTALL.md)

These controls are new in the **1.1.3 development build**. Older downloaded installers keep their original behavior until replaced. The build remains under development; the [acceptance checklist](ACCEPTANCE.md) records the device checks still required.

## Find the controls

- **Windows:** the FlintEye icon is in the notification area. Check the hidden-icons arrow if it is not visible.
- **macOS:** the FlintEye icon is in the top menu bar. The menu and the normal Dock Quit action use the same recording-safe shutdown.
- **Linux desktop:** a small control window is always available. Where an X11 tray is supported, clicking its icon opens the controls. No desktop extension is installed automatically.
- **Docker, systemd and CLI:** no tray, control window, camera setup window or login-start entry is created. Use `--headless` explicitly for server operation. Linux without a desktop display and remote macOS shell sessions select headless operation automatically.

A one-command desktop installation uses the same controls as the installer. The execution environment determines whether desktop controls are shown.

## Understand the indicator

The eye icon has a colored badge and a shape. Its menu and the WebApp show words and camera counts, so color is not the only indication.

| Indicator | Meaning |
| --- | --- |
| Green, play symbol | Configured monitoring targets are receiving data. Recording is counted separately from reception. |
| Red, stop symbol | Monitoring was intentionally stopped. Settings and the API remain available. |
| Red, cross | The media server or all expected camera feeds are unavailable. |
| Amber, warning symbol | Starting, stopping, finishing recordings, partial camera failure, or unavailable status. |
| Gray, dash | Initial setup is incomplete or no camera is selected for monitoring. |

The counts distinguish **configured cameras**, **monitoring targets**, **receiving cameras** and **recording cameras**. A running process or an enabled recording checkbox alone is not evidence of reception or recording. Health is checked approximately every 2 seconds; 15 seconds without advancing reception is treated as a stalled feed. Camera details include the last observed reception time. A short restart can temporarily show amber.

FlintEye enables the health API on loopback for its own bundled MediaMTX configuration. An external MediaMTX server is not reconfigured to expose its API. If its health cannot be queried, status stays unavailable rather than green.

## Stop monitoring or quit

**Stop monitoring** stops camera publishers, waits for recording completion and index registration, then stops the managed media server. The WebApp, settings and native controls stay open. Use **Start monitoring** to resume. **Restart monitoring** is available only while monitoring is enabled. Operations in progress disable repeated control clicks.

**Quit FlintEye** finishes recordings and closes the API and native controls as well. Closing the browser or signing out leaves monitoring running. The application only cleans up processes belonging to its own installation; unrelated browsers, FFmpeg instances and external media servers are preserved.

The completion check waits up to **30 seconds**. Unavailable storage, missing completion callbacks or an index error leave an amber finishing state and a pending-segment count. Reconnect storage and use **Retry Stop**. A separate **Force quit** action requires confirmation and may leave incomplete recordings. Filesystem or operating-system shutdown delays can extend the total exit time beyond the completion waiting period.

Normal application exit and the Windows uninstaller use the same completion check. OS termination/uninstall has a bounded fallback so it cannot leave an invisible application running indefinitely. The local `last-monitoring-stop.json` receipt distinguishes completed recording shutdown from forced or unverified shutdown; Windows `last-stop-result.json` reports process cleanup separately. Play the final segment during device acceptance; process exit alone is not proof of usable media. Recordings managed by another service without FlintEye completion hooks cannot be certified by this check; manage that recorder separately.

The separate `recording-events.sqlite3` ledger tracks segment creation/completion. The existing `recordings.sqlite3` inventory and its retention rules are preserved. Incomplete files are not automatically deleted by retention. A previous session's incomplete count remains a warning rather than silently marking those files successful.

## Startup preferences

Open **Settings → Quick settings → Monitoring and startup**. These preferences save immediately.

- **Always resume monitoring when FlintEye starts:** off by default. With it off, an explicit Stop remains stopped across app and computer restarts. Quitting while running preserves the running preference, so reopening resumes monitoring. Turn this option on to start monitoring even after a prior Stop.
- **Start FlintEye when I log in:** starts the desktop application for the current user. It is independent of the monitoring preference. This setting is available only to an administrator using the local desktop installation. A registration belonging to another profile or installation is preserved.

Stopping monitoring releases the desktop's automatic sleep prevention after recording finalization. Manual sleep, logout and OS shutdown still interrupt monitoring. Servers should use Docker/systemd rather than depend on a logged-in desktop.

## Network access

The desktop WebApp listens on loopback by default. A Windows firewall prompt can still relate to MediaMTX's WebRTC media transport; it does not by itself mean the WebApp is published to the LAN. Do not grant broader network access just to dismiss a prompt. Local viewing and LAN viewing are separate checks. For other devices, follow the [HTTPS/LAN deployment guide](DISTRIBUTION.md#user-installation) and allow only the required network and ports. Authentication remains required for protected routes.

## API and build identity

`GET /api/v1/status/monitoring` requires viewer access and reports the same state as the desktop controls. The existing administrator-only `POST /api/v1/control/start`, `stop` and `restart` routes use the shared controller. `GET /api/v1/health` continues to mean that the API is alive; it does not certify camera reception.

**Information** shows the application version, development channel and bundled source commit. A source checkout without packaged build metadata explicitly shows that the commit was not recorded. The Recordings date is labeled **Updated**, because it currently comes from the file modification time, not a verified capture-start timestamp.
