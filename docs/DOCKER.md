# Docker Compose

[日本語](DOCKER.ja.md)

[Documentation](README.md) · [GHCR publication setup](RELEASING.md#ghcr-setup)

Use this route on a Linux server with Docker Engine and the Compose plugin.
Images target `linux/amd64` and `linux/arm64`. Native desktop packages are the recommended Windows/macOS route.
Host networking preserves ONVIF discovery and WebRTC. Docker Desktop USB forwarding is not included.

## Install without cloning

**UNDER DEVELOPMENT.** Public GHCR images are not available yet. The first planned image is `ghcr.io/noguhiro2002/flinteye:1.1.2-preview.1`. Use [the local development build](#build-the-development-image) meanwhile. The pull instructions below apply only after publication.

Published public images can be pulled without a GitHub account or token. If Docker has an expired saved credential, use `docker logout ghcr.io` before pulling anonymously. Private maintainer testing still requires an authorized account and a classic token with `read:packages`, entered at `docker login ghcr.io -u YOUR_GITHUB_USERNAME`'s password prompt; never put tokens in `.env` or command arguments.

Download `compose.yaml` from the same version's GitHub Release, put it in a new directory, and create `.env`:

```dotenv
FLINTEYE_IMAGE=ghcr.io/noguhiro2002/flinteye:1.1.2-preview.1
```

The preview will have no `latest` image tag. Pin the exact tested version as above. Publication requires automated and real-device checks; no public image is claimed to exist yet.

From that directory:

```sh
docker compose pull
docker compose up -d
docker compose exec flinteye cat /data/setup-token
```

Open http://127.0.0.1:18080, enter the one-use token and create the administrator password.
On a remote server, first create an SSH tunnel:

```sh
ssh -L 18080:127.0.0.1:18080 your-server
```

Do not post the setup token in an issue or put a password into command arguments.
For other LAN users, configure the [HTTPS reverse proxy](DISTRIBUTION.md#user-installation).
The HTTP/API/MediaMTX listeners stay on loopback; WebRTC also needs UDP 8189.

## Storage and cameras

The named volume `flinteye-data` persists settings, inventory and recordings across container replacement.
The process uses UID/GID 10001. Bind-mounted folders must be writable by that identity.
Paths selected in the Web UI refer to paths inside the container. Mount additional recording disks explicitly.

IP cameras need network access. Optional USB mappings are shown in `compose.yaml`; select the host's actual device and video-group GID.
The optional native Raspberry Pi CSI helper is not bundled; USB/IP inputs work on the ARM64 build.

## Update and rollback

Review the release notes and back up configuration/inventory first. Change the pinned version in `.env`, then run:

```sh
docker compose pull
docker compose up -d
docker compose logs --tail=50 flinteye
```

Replacing the container briefly interrupts monitoring. Updates are never applied automatically.
For rollback, put the previous exact `ghcr.io/noguhiro2002/flinteye:VERSION` back in `.env`, then run `docker compose pull` and `docker compose up -d`. Restore the matching configuration backup if a release requires it. Keep the old version and its configuration backup until the upgrade is verified.

`docker compose down` stops/removes the container while preserving the volume.
Do not add `-v` unless you explicitly intend to erase stored data.

## Build the development image

From a repository checkout:

```sh
docker compose -f deploy/compose.dev.yaml up -d --build
docker compose -f deploy/compose.dev.yaml exec flinteye cat /data/setup-token
```

This creates a local `flinteye:development` image and does not publish it.
Do not run development and installed instances simultaneously on the same ports.

### If the MediaMTX download times out

A `TLS handshake operation timed out` error from `packaging/vendor.py` means the build could not download an upstream file. It is a network/download failure, not a compiler error. Downloads now retry transient failures up to three attempts and reuse verified files. SHA-256 and TLS certificate checks remain enabled. Go module/build caches also reduce repeated work.

To prepare the MediaMTX download cache on the host, run these commands from the checkout root with Python 3.11 or newer and a current Docker Compose plugin ([2.17.0 or newer](https://docs.docker.com/reference/compose-file/build/#additional_contexts)):

```sh
python3 packaging/vendor.py media-cache
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

If you already have a corresponding MediaMTX source archive from a trusted FlintEye build, import its pinned files instead of downloading them again. Replace `MEDIA_SOURCE_ARCHIVE` with the actual archive path:

```sh
python3 packaging/vendor.py media-cache --from-source-archive MEDIA_SOURCE_ARCHIVE
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

The importer verifies the three selected files against the pinned MediaMTX/HLS checksums before reusing them; it does not extract arbitrary archive paths. The source downloads work for either CPU architecture. A source archive from another version is usable only if its checksums match the current checkout.

This bypasses the MediaMTX source, HLS bundle and license downloads only. Base images, system packages, Go modules, Python packages and frontend dependencies still need network access. If those fail, check the Docker daemon/build network and proxy settings rather than disabling verification.

Keep `FLINTEYE_VENDOR_CACHE` set when rebuilding with this cache. Without it, Compose uses the empty cache context and downloads normally. The project name and `flinteye-data` volume are unchanged; do not use `down -v` during recovery.
