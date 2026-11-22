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

<a id="event-recordings"></a>
## Keep the video leading up to an equipment event

1. As an administrator, open **Settings → Recording → Event recordings**. Enable the feature and enter an existing, writable folder on the FlintEye server outside the current and previous loop recording folders. For Docker, use a path inside a persistent mount.
2. Save the settings and copy the event token. Set the maximum lookback if the default of 600 seconds is insufficient. Camera recording must already be enabled for the relevant cameras.
3. Send the camera IDs and lookback from the equipment. If you omit the event timestamp, FlintEye uses the time it receives the request. [Equipment API example](advanced/API.md#equipment-recording-events)

Open **Recordings → Event recordings** to see what was saved. If the requested interval overlaps an open segment, FlintEye waits for it to close normally. With 10-minute segments, this can take several minutes. If footage is missing, the list shows the available portions. Loop retention leaves the saved event clips in the event folder.

## Viewer access and other devices

Set the `viewer` password in **Settings → Runtime & access** before sharing access. Save or discard other pending changes first. Updating the password signs everyone out; sign in again as administrator afterward. Viewers can watch but cannot change configuration.
LAN access requires an HTTPS reverse proxy; follow the [server guide](DISTRIBUTION.md#user-installation).
Keep the local HTTP and MediaMTX listeners on loopback. Do not expose them directly to the Internet.

## Stop, update, or uninstall

Closing a browser tab keeps recording running.
Choose **Stop monitoring** to pause cameras and recording while keeping settings available. Choose **Quit FlintEye** in the Windows/macOS tray menu or Linux control window to exit completely. The stopped state is remembered by default. See [monitoring indicators and startup preferences](MONITORING.md).
Desktop startup runs after login; use systemd or Docker for unattended server operation.
Manual sleep, logout, or shutdown interrupts monitoring.

Check for updates in **Settings → General → Software updates**. Updates are installed manually. The **Getting started** button in the top bar reopens the introductory tour.
Quit FlintEye, back up configuration and recording inventory, install the replacement package, and restart.
Uninstalling normally keeps settings and recordings. Data deletion requires a separate explicit choice.

## Camera audio (next development build)

In **Settings → Cameras**, open **Camera audio** for a saved USB or IP camera and select **Check audio input**. Audio starts off for each camera. If the camera has no detected microphone or audio stream, the checkbox stays disabled. On Linux, USB microphones use ALSA device permissions. On macOS and Windows, allow microphone access for the application if prompted.

Choose **Standard** (16 kHz, 16-bit mono PCM), **High** (48 kHz, 24-bit), **Middle** (12 kHz, 16-bit), **Low** (8 kHz, 16-bit), or **Custom**. Custom can change the sample rate and channel count and use PCM depth or AAC target bitrate. Higher rates may increase file size without improving a source that captures at a lower rate. Save the setting. Use the player volume control in **Live View**, and open a new completed recording in **Recordings** to play its audio. The volume control starts muted in Live View.
