# Using FlintEye

[日本語](USER_GUIDE.ja.md)

[Documentation](README.md)

## Start and sign in

Open FlintEye from the Start menu (Windows), Applications (macOS), or application launcher (Linux).
The first-run window asks for an administrator password: 12–1024 characters, entered twice.
There is no default password. Closing setup postpones it until the next launch.
The browser opens at http://127.0.0.1:18080; sign in as `admin`.

The English getting-started tour introduces cameras and storage.
You can skip it and reopen it from the application.

## Add cameras

In **Settings**, discover a connected USB camera or add an IP camera.
For an IP camera, enter its address and credentials on this screen; avoid placing credentials in terminal commands.
Apply the settings and check **Live View**. For a supported ONVIF camera, discovery and PTZ controls are available.

The operating system may ask for camera access. Grant it to FlintEye.
Only the administrator can change camera and system settings.

## Recording and storage

Enable recording for the camera in Settings. Open **Recordings**, select a stream and a recording, and play it.

The initial retention limit is **7 days**. The initial capacity suggestion is **50 GB or half the free space in the selected folder**, whichever is smaller.
It is saved as a fixed setting; it does not grow automatically with free space.
Whichever limit comes first removes the oldest completed recordings. Seven days is a maximum, not a guaranteed history length.

Choose another folder or adjust the limits in **Settings → Recording**, then click **Save changes**. The folder picker is available when using the desktop app on the installation computer; remote browsers enter a path on the server. **Suggest from free space** fills in a proposed capacity without saving it. All recording settings now share the main Settings form; the separate installation settings panel has been removed.
Changing folders does not move existing files. **Show recordings from previous locations** is on by default.
Turning it off hides those recordings from lists and playback; it does not delete them or disable their existing retention rules.
An unavailable disk makes recordings inaccessible until it is reconnected.

FlintEye pauses recording if it cannot maintain its free-space reserve.
A banner explains the condition. See the [storage details](DISTRIBUTION.md#recording-lifecycle) for cleanup timing and imported files.

## Viewer access and other devices

Set the `viewer` password in **Settings → Runtime & access** before sharing access. Save or discard other pending changes first. Updating the password signs everyone out; sign in again as administrator afterward. Viewers can watch but cannot change configuration.
LAN access requires an HTTPS reverse proxy; follow the [server guide](DISTRIBUTION.md#user-installation).
Keep the local HTTP and MediaMTX listeners on loopback. Do not expose them directly to the Internet.

## Stop, update, or uninstall

Closing a browser tab keeps recording running.
Choose **Stop monitoring and quit** in the Windows/macOS tray menu or Linux control window to stop.
Desktop startup runs after login; use systemd or Docker for unattended server operation.
Manual sleep, logout, or shutdown interrupts monitoring.

Check for updates in **Settings → General → Software updates**. Updates are installed manually. The **Getting started** button in the top bar reopens the introductory tour.
Stop monitoring, back up configuration and recording inventory, install the replacement package, and restart.
Uninstalling normally keeps settings and recordings. Data deletion requires a separate explicit choice.
