# Run from source

[日本語](MANUAL_INSTALL.ja.md)

[Documentation](README.md)

This route is for developers. General users should use the [desktop installer](INSTALL.md).

## Requirements

- Python 3.13 or 3.14 (use 3.14.10 on Windows/macOS), Node.js 22.12+, npm
- FFmpeg/FFprobe with `libx264`, `drawtext`, HTTP/HTTPS/RTSP, and concat-demuxer support
- MediaMTX 1.21.2 on PATH, or at `bin/mediamtx` (`bin/mediamtx.exe` on Windows)
- Tk for the desktop launcher; Linux packages commonly call it `python3-tk`

### Linux Python prerequisites

Install virtual-environment support for the Python interpreter you actually use before running `-m venv`. Debian/Ubuntu split this into a separate package: `python3-venv` for the distribution's default Python, or a matching version such as `python3.13-venv`. Install the matching Tk package for desktop setup as well. If `ensurepip` is unavailable, install that venv package and recreate the incomplete environment; installing application requirements cannot repair it.

The interpreter still needs to meet the Python version requirement above. A distribution's default Python may be older; use a separately installed supported interpreter and its matching venv/Tk components. Do not replace or remove the operating system's Python. For example, with packaged Python 3.13 on Debian:

```sh
sudo apt-get install python3.13-venv python3-tk
python3.13 -m venv .venv
```

Clone the repository and run commands from its root:

```sh
git clone https://github.com/noguhiro2002/FlintEye.git
cd FlintEye
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -c packaging/constraints.txt -r requirements.txt -r packaging/requirements-build.txt
npm --prefix frontend ci
npm --prefix frontend run build
python flinteye.py
```

On Windows use `py -3.14 -m venv .venv`, then `.venv\Scripts\python.exe` instead of `python`.
The public source can be cloned without GitHub authentication. If you used the earlier private repository, create a new checkout instead of merging its unrelated history.

The launcher uses the same password setup, local data directory, and browser UI as the package.
To run without a desktop, use `python flinteye.py --headless`; read the generated `setup-token` file and finish setup through the local browser or SSH tunnel.
Never put passwords in process arguments.

## Develop the frontend

Use the separate development stack for hot reload:

```sh
cp config/examples/.env.example.linux .env
python -m tools.manage_auth init-local --runtime-file runtime.json
python -m tools.start_orchestrator_stack --env-file .env --runtime-file runtime.json
```

Choose the macOS/Windows environment template on those systems.
Development uses its own `runtime.json`; do not run it on the same ports as the desktop application.
Keep API and Vite listeners on loopback.

[API reference](advanced/API.md) · [Camera tools](advanced/CAMERA_TOOLS.md) · [Frontend details](advanced/DEVELOPMENT.md)

## Uninstall a source environment

Disable any login startup configured by the desktop launcher before removing the source. Choose **Quit FlintEye**, or press Ctrl+C and wait in each terminal running the API, frontend development server or tools. Stop and disable any [systemd service](STOP_AND_UNINSTALL.md#systemd) or [Compose deployment](STOP_AND_UNINSTALL.md#docker-compose) configured to restart it.

Preserve `.env`, `runtime.json`, recordings and any other data inside the checkout. Deactivate the virtual environment with `deactivate` if active, then remove the dedicated checkout and virtual environment with your file manager. Remove an environment outside the checkout separately. Default desktop data and custom external recording folders are kept unless you deliberately delete them. [Source removal and shared dependencies](STOP_AND_UNINSTALL.md#manual-source-and-virtual-environment) · [Optional data erasure](STOP_AND_UNINSTALL.md#permanently-erase-data-optional)

## Verify changes

```sh
python -m unittest discover -s tests -v
npm --prefix frontend ci
npm --prefix frontend run build
python packaging/check_docs.py
```

Application distribution through pip is deferred. Installing `requirements.txt` installs dependencies, not a standalone FlintEye application.
