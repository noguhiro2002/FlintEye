# LAN access and certificate trust — 1.2.0 development

[日本語](LAN_ACCESS.ja.md) · [Installation](INSTALL.md) · [Monitoring](MONITORING.md)

**UNDER DEVELOPMENT. These changes require a rebuilt 1.2.0 package. Public 1.1.3-preview.1 does not include them. Physical LAN and mobile acceptance is pending.**

## Enable access

On the server computer, complete administrator setup in the browser using the setup token displayed by FlintEye. Open **Settings → Runtime & access → LAN connection and certificate trust**. Select **Enable LAN HTTPS**, enter an IPv4 address actually assigned to this server, and enter the private source networks permitted to connect (for example `192.168.1.0/24`). Leave access disabled to use only this PC.

Save the connection settings. Select **Save public certificate and connection guide**. The displayed folder contains a CA certificate, its fingerprint, an iOS/iPadOS certificate profile and these instructions. It contains no private key or setup token. Transfer this folder using a method you control, such as USB storage, AirDrop or an existing authenticated file share. Compare the CA SHA-256 fingerprint with the server's display before trusting it. Do not use a browser's certificate-warning bypass to retrieve the certificate.

On Windows, **allow selected LAN access** requests UAC approval and a second confirmation of the actual settings. The helper adds HTTPS TCP on the configured API port (18080 by default) and WebRTC UDP 8189 for the selected server IP and permitted sources, on a **Private** network only. Refusing approval preserves local operation. Domain networks require administrator-managed rules. On Linux and macOS, ask the machine administrator to permit these same specific inbound flows in the active firewall; FlintEye does not disable that firewall. macOS may also ask for application-level network permission. Do not expose MediaMTX TCP 8554, 8889 or 9997 or unused RTP ports.

Restart FlintEye. On another permitted device open **`https://SERVER-IP:18080`** (use the chosen API port if different). Use this same address for login, settings allowed by your role, Live View, Multiview and recording playback. The local server control address stays `http://127.0.0.1:18080` for recovery. Plain HTTP on the LAN IP is not an entry point.

The server must keep the selected address. Use your router's DHCP reservation or an administrator-assigned address. Sleep prevents recording and viewing; keep the server awake. No port forwarding, public Internet access, automatic router configuration or TURN relay is provided.

## Trust the certificate once on each viewing device

The installation-specific CA can establish trust for server certificates. Install it only after checking the fingerprint and only on devices where you are authorized to add trust. A device administrator or organizational policy may prevent this operation. FlintEye never installs trust silently and never exports the CA private key.

- **Windows Edge/Chrome:** open `FlintEye-CA.crt`, choose Install Certificate for the current user, and explicitly select **Trusted Root Certification Authorities**. Confirm the displayed fingerprint. Restart the browser if needed. Remove this particular CA later through the current user's certificate manager (`certmgr.msc`). Do not remove other certificates.
- **macOS Safari/Chrome:** import `FlintEye-CA.crt` into the login keychain using Keychain Access. Check its fingerprint, open its Trust settings and explicitly allow SSL trust. macOS may request your account password. To withdraw trust, remove this exact FlintEye certificate from the keychain. [Apple certificate trust](https://support.apple.com/guide/keychain-access/change-the-trust-settings-of-a-certificate-kyca11871/mac)
- **Linux:** import the CA into the browser's authority certificate store, or have your administrator add it to the OS trust store used by that browser. Firefox may use its own certificate store. Verify the fingerprint and remove only this installation's authority when finished.
- **iPhone/iPad Safari:** open `FlintEye.mobileconfig`, install the downloaded profile in Settings → General → VPN & Device Management, then enable this FlintEye root in Settings → General → About → Certificate Trust Settings. Installing a profile alone does not enable TLS trust. Remove the exact FlintEye profile to withdraw it. [Apple instructions](https://support.apple.com/en-ie/102390)
- **Android Chrome:** copy `FlintEye-CA.crt` to the device and choose the **CA certificate** installation option under Security → Encryption & credentials (names differ by manufacturer). Device unlock or administrator approval may be required. Verify this installation's fingerprint. Remove this exact certificate under user credentials when finished; do not clear all credentials. Managed devices or browsers may reject user authorities. [Google certificate help](https://support.google.com/pixelphone/answer/2844832)

## Initial ownership and everyday use

A LAN visitor cannot claim administrator access without the server's one-use setup token. For a headless installation enabled before setup, the owner reads `setup-token` in its data directory and enters it over the trusted HTTPS connection. The token expires after 30 minutes; restart the server or use **Address and setup assistance → Renew setup token** on the server to replace it. Setup attempts are rate limited. Tokens and passwords must never appear in URLs, shared instructions, logs or screenshots.

After setup, the existing admin account remains in place after application/OS restart and reinstallation. Set a viewer password before sharing viewer access. Viewers can watch authorized video and recordings but cannot change administrator configuration or start/stop monitoring. Closing the browser leaves the server running. Use **Dashboard → Stop monitoring** to pause monitoring or the native **Quit FlintEye** action to finish recordings and stop all bundled processes.

## Certificate renewal and recovery

Server certificates last 90 days and renew within 30 days of expiry using the same installation CA. New TLS connections use the renewed certificate; clients do not need a new CA. The CA lasts five years. Its expiry is shown in local connection settings; renew it explicitly before expiry and redistribute the guide to every device. **Renew trust certificate** replaces the CA and requires renewed trust on every viewing device. Keep the private data directory secure; its TLS private keys should never be sent for support.

After choosing **Renew trust certificate**, restart FlintEye so its HTTPS listener uses the new certificate, then reconnect from each device after updating trust.

If DHCP changes the server IP, FlintEye does not silently expose another interface. Open the local server address, select the new IP, export the updated guide and restart. A new leaf certificate is issued under the same CA. If the local port is occupied, stop the conflicting instance or use the launcher's `--port` override; the control window shows the actual local URL.

An unreachable page, an untrusted certificate, a rejected source network, incorrect credentials and a page with no video are different problems. Check the local settings error, selected bind address, firewall and certificate fingerprint first. For video, check the selected IP advertised by WebRTC and UDP 8189. HTTPS page access alone does not prove video reachability. A browser may also request local-network access; make a deliberate per-site decision. Public network profiles are not automatically opened.

Disable LAN access and restart to close the HTTPS listener. On Windows remove this installation's firewall rules with the dedicated button. Remove the FlintEye CA from every viewing device when it is no longer needed. Uninstall does not remotely remove client trust; retained data includes the existing installation's certificates. Explicit data deletion removes those certificates too, so reinstalling with erased data requires fresh trust.

Windows removal also checks the Firewall ownership records saved by this FlintEye installation, including custom profiles that have already stopped or been deleted. With explicit UAC and confirmation it removes only the recognized HTTPS/WebRTC rules whose program paths belong to this installation, including interrupted staging rules. Other installations and manually named rules are preserved. If approval or cleanup fails, removal stops and the records remain available for retry. The local recovery command is `FlintEye.exe --remove-installation-firewall-rules`; it does not initialize a new camera profile. If you tested an earlier experimental 1.2 build without these ownership records, run this recovery command from the updated installation before uninstalling it.

## Headless and existing proxy deployments

For an explicit headless opt-in, run the installed executable as its normal service user with the same data directory used by the service:

```sh
/opt/flinteye/FlintEye --headless --data-dir /PATH/TO/DATA --lan-address 192.168.1.10 --lan-source 192.168.1.0/24
```

Quit any existing instance of that profile first. To export the guide after stopping the instance:

```sh
/opt/flinteye/FlintEye --data-dir /PATH/TO/DATA --export-connection-guide
```

Use `--disable-lan` with that same profile to return to local-only operation. These flags do not manage a Linux firewall. Existing administrator-controlled reverse proxies can remain in use with built-in LAN mode disabled; the public Web URL, API bind and media upstream are distinct settings. The built-in LAN path does not trust forwarded identity headers.

Docker Desktop's supplied bridge Compose is for its host browser only. For a LAN Docker server use Linux Engine with the host-network configuration and the explicit LAN settings above. See [Docker](DOCKER.md).
