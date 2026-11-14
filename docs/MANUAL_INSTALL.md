# Run from source

[日本語](MANUAL_INSTALL.ja.md)

[Documentation](README.md)

This route is for developers. General users should use the [desktop installer](INSTALL.md) once it is released.

## Requirements

- Python 3.13 or 3.14 (use 3.14.10 on Windows/macOS), Node.js 22.12+, npm
- FFmpeg/FFprobe with `libx264`, `drawtext`, HTTP/HTTPS/RTSP, and concat-demuxer support
- MediaMTX 1.21.2 on PATH, or at `bin/mediamtx` (`bin/mediamtx.exe` on Windows)
- Tk for the desktop launcher; Linux packages commonly call it `python3-tk`

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

## Verify changes

```sh
python -m unittest discover -s tests -v
npm --prefix frontend ci
npm --prefix frontend run build
python packaging/check_docs.py
```

Application distribution through pip is deferred. Installing `requirements.txt` installs dependencies, not a standalone FlintEye application.
