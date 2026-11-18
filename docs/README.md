# FlintEye documentation

[日本語](README.ja.md)

[Project home](../README.md)

**UNDER DEVELOPMENT.** Source, public preview installers and GHCR images are available. Physical-device acceptance is still in progress.

- [Known issues and verification limits](KNOWN_ISSUES.md)
- [Contributing](../.github/CONTRIBUTING.md)
- [Report a security issue privately](../.github/SECURITY.md)

## Use FlintEye

- [Install on Windows, macOS, or Linux](INSTALL.md)
- [Uninstall by OS and installation method; keep or erase data](STOP_AND_UNINSTALL.md)
- [Add cameras, watch live video, and manage recordings](USER_GUIDE.md)
- [Monitoring indicators, pause/resume and desktop startup](MONITORING.md)
- [Docker Compose](DOCKER.md)
- [Server deployment, HTTPS/LAN access, storage, and systemd](DISTRIBUTION.md)

## Develop and distribute

- [Run from source](MANUAL_INSTALL.md)
- [Build packages and publish releases / GHCR](RELEASING.md)
- [Build and verify a local DMG on an M1 / Apple Silicon Mac](LOCAL_MACOS_BUILD.md)
- [Final checks on your own computers](ACCEPTANCE.md)
- [Required device checks before 1.2.0 stable distribution](RELEASE_CHECKLIST_1_2_0.md)
- [License and permitted uses](LICENSING.md)
- [Environment reference](advanced/ENV_OPTIONS.md)

## Advanced reference

Commands in these guides are for source installations and standalone tools.
Packaged FlintEye manages its own MediaMTX configuration and recording retention.

- [Camera tools and troubleshooting](advanced/CAMERA_TOOLS.md)
- [Multiview, standalone MediaMTX recording, NTP and latency](advanced/MEDIA_OPERATIONS.md)
- [API, authentication and logging](advanced/API.md)
- [Frontend development](advanced/DEVELOPMENT.md)
