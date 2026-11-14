#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start orchestrator API and frontend UI together.",
    )
    parser.add_argument("--env-file", default=".env", help="Path to .env file for orchestrator_api.py")
    parser.add_argument("--runtime-file", default="runtime.json", help="Path to runtime JSON")
    parser.add_argument("--api-host", help="API host passed to orchestrator_api.py")
    parser.add_argument("--api-port", type=int, help="API port passed to orchestrator_api.py")
    parser.add_argument("--ui-host", help="Vite host")
    parser.add_argument("--ui-port", type=int, help="Vite port")
    parser.add_argument(
        "--skip-npm-install",
        action="store_true",
        help="Skip npm install check in frontend directory",
    )
    parser.add_argument(
        "--npm-command",
        default="npm",
        help="npm executable (default: npm)",
    )
    return parser.parse_args(argv)


def _load_env_file(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    file_path = Path(path)
    if not path or not file_path.is_file():
        return env

    with file_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and (
                (value[0] == "'" and value[-1] == "'")
                or (value[0] == '"' and value[-1] == '"')
            ):
                value = value[1:-1]
            env[key] = value
    return env


def _resolve_int(cli_value: int | None, env_value: str | None, default: int) -> int:
    if cli_value is not None:
        return cli_value
    if env_value is None or env_value == "":
        return default
    try:
        return int(env_value)
    except ValueError:
        return default


def _resolve_str(cli_value: str | None, env_value: str | None, default: str) -> str:
    if cli_value:
        return cli_value
    if env_value:
        return env_value
    return default


def _default_api_proxy_target(api_host: str, api_port: int) -> str:
    host = (api_host or "").strip()
    if not host or host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{api_port}"


def _spawn(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    popen_env = os.environ.copy()
    if env:
        popen_env.update(env)

    kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "env": popen_env,
    }
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if creationflags:
            kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _kill_process_tree_windows(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return result.returncode == 0


def _resolve_command(command: str) -> str:
    if not command:
        return command

    direct = shutil.which(command)
    if direct:
        return direct

    if os.name != "nt":
        return command

    cmd_path = Path(command)
    if cmd_path.suffix:
        return command

    for suffix in (".cmd", ".bat", ".exe"):
        candidate = f"{command}{suffix}"
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return command


def _terminate(proc: subprocess.Popen[bytes], *, label: str) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            if not _kill_process_tree_windows(proc.pid):
                proc.terminate()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        pass

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    try:
        if os.name == "nt":
            if not _kill_process_tree_windows(proc.pid):
                proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass

    print(f"[warn] force killed {label}", flush=True)


def _run_npm_install(frontend_dir: Path, npm_command: str) -> None:
    node_modules = frontend_dir / "node_modules"
    expected_rollup_native = _expected_rollup_native_package(frontend_dir)
    if node_modules.is_dir() and (expected_rollup_native is None or expected_rollup_native.is_dir()):
        return
    if expected_rollup_native is not None and not expected_rollup_native.is_dir():
        print(
            f"[info] missing platform Rollup package: {expected_rollup_native.relative_to(frontend_dir)}",
            flush=True,
        )
    print("[info] running npm install in frontend...", flush=True)
    subprocess.run(
        [npm_command, "install", "--no-audit", "--no-fund"],
        cwd=str(frontend_dir),
        check=True,
    )


def _expected_rollup_native_package(frontend_dir: Path) -> Path | None:
    machine = platform.machine().lower()
    if os.name == "nt":
        if "arm64" in machine or "aarch64" in machine:
            package_name = "rollup-win32-arm64-msvc"
        elif "64" in machine or machine in {"amd64", "x86_64"}:
            package_name = "rollup-win32-x64-msvc"
        else:
            package_name = "rollup-win32-ia32-msvc"
        return frontend_dir / "node_modules" / "@rollup" / package_name

    if sys.platform == "darwin":
        package_name = "rollup-darwin-arm64" if "arm64" in machine else "rollup-darwin-x64"
        return frontend_dir / "node_modules" / "@rollup" / package_name

    if sys.platform.startswith("linux"):
        package_name = "rollup-linux-arm64-gnu" if "arm64" in machine or "aarch64" in machine else "rollup-linux-x64-gnu"
        return frontend_dir / "node_modules" / "@rollup" / package_name

    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = Path(__file__).resolve().parents[1]
    frontend_dir = workspace / "frontend"
    api_path = workspace / "flinteye_app" / "orchestrator_api.py"
    env_values = _load_env_file(args.env_file)
    api_host = _resolve_str(args.api_host, env_values.get("API_HOST"), "127.0.0.1")
    api_port = _resolve_int(args.api_port, env_values.get("API_PORT"), 18080)
    ui_host = _resolve_str(args.ui_host, env_values.get("WEBUI_HOST"), "127.0.0.1")
    ui_port = _resolve_int(args.ui_port, env_values.get("WEBUI_PORT"), 5173)
    ui_api_proxy_target = env_values.get("WEBUI_API_PROXY_TARGET") or _default_api_proxy_target(api_host, api_port)
    ui_mtx_api_proxy_target = env_values.get("WEBUI_MTX_API_PROXY_TARGET") or "http://127.0.0.1:9997"
    npm_command = _resolve_command(args.npm_command)

    if not api_path.is_file():
        print(f"[error] orchestrator_api.py not found: {api_path}", file=sys.stderr)
        return 1
    if not frontend_dir.is_dir():
        print(f"[error] frontend directory not found: {frontend_dir}", file=sys.stderr)
        return 1
    if shutil.which(npm_command) is None and not Path(npm_command).exists():
        print(
            f"[error] npm executable not found: {args.npm_command} (resolved={npm_command})",
            file=sys.stderr,
        )
        if os.name == "nt":
            print("[error] Install Node.js and ensure npm.cmd is on PATH.", file=sys.stderr)
        return 1

    if not args.skip_npm_install:
        try:
            _run_npm_install(frontend_dir, npm_command)
        except subprocess.CalledProcessError as e:
            print(f"[error] npm install failed (exit={e.returncode})", file=sys.stderr)
            return e.returncode or 1
        except FileNotFoundError as e:
            print(f"[error] failed to run npm install: {e}", file=sys.stderr)
            return 1

    api_cmd = [
        sys.executable,
        "-m", "flinteye_app.orchestrator_api",
        "--env-file",
        args.env_file,
        "--runtime-file",
        args.runtime_file,
        "--host",
        api_host,
        "--port",
        str(api_port),
    ]
    ui_cmd = [
        npm_command,
        "run",
        "dev",
        "--",
        "--host",
        ui_host,
        "--port",
        str(ui_port),
    ]
    ui_env = {
        "VITE_API_PROXY_TARGET": ui_api_proxy_target,
        "VITE_API_DIRECT_BASE": ui_api_proxy_target,
        "VITE_MTX_API_PROXY_TARGET": ui_mtx_api_proxy_target,
    }

    print("[info] starting orchestrator API...", flush=True)
    api_proc = _spawn(api_cmd, cwd=workspace)
    print("[info] starting frontend UI...", flush=True)
    try:
        ui_proc = _spawn(ui_cmd, cwd=frontend_dir, env=ui_env)
    except FileNotFoundError as e:
        _terminate(api_proc, label="orchestrator_api")
        print(f"[error] failed to start frontend UI: {e}", file=sys.stderr)
        print(f"[error] attempted command: {ui_cmd[0]}", file=sys.stderr)
        return 1

    print(
        f"[info] stack started: API=http://{api_host}:{api_port} UI=http://{ui_host}:{ui_port}",
        flush=True,
    )
    print("[info] press Ctrl+C to stop both processes", flush=True)

    try:
        while True:
            api_exit = api_proc.poll()
            ui_exit = ui_proc.poll()
            if api_exit is not None:
                print(f"[error] API process exited (code={api_exit})", flush=True)
                return api_exit
            if ui_exit is not None:
                print(f"[error] UI process exited (code={ui_exit})", flush=True)
                return ui_exit
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[info] stopping stack...", flush=True)
        return 0
    finally:
        _terminate(ui_proc, label="frontend")
        _terminate(api_proc, label="orchestrator_api")


if __name__ == "__main__":
    raise SystemExit(main())
