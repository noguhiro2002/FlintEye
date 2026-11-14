"""Build and verify a local Apple Silicon DMG without GitHub Actions.

Run with Homebrew's native Python 3.14; see docs/LOCAL_MACOS_BUILD.md.
Each build uses a fresh snapshot of the committed source and a private venv.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile

from release_lib import digest

ROOT = Path(__file__).resolve().parents[1]


def build_environment(jobs: int) -> dict[str, str]:
    env = os.environ.copy()
    # Do not inherit an active Conda/venv compiler or an Intel Homebrew toolchain.
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CC', 'CXX', 'AR', 'RANLIB',
                'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'CPPFLAGS', 'PKG_CONFIG_PATH',
                'CMAKE_PREFIX_PATH', 'SDKROOT', 'GOARCH', 'GOOS', 'GOTOOLCHAIN'):
        env.pop(key, None)
    env.update(PATH='/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
               MACOSX_DEPLOYMENT_TARGET='14.0', FLINTEYE_BUILD_JOBS=str(jobs), GOMAXPROCS=str(jobs))
    return env


def output(command: list[str], env: dict[str, str], cwd: Path = ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, env=env, text=True, stderr=subprocess.STDOUT).strip()


def preflight(env: dict[str, str]) -> dict[str, str]:
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Use a native Apple Silicon Terminal (not Rosetta) on the Mac being tested.')
    if sys.version_info[:2] != (3, 14) or sys.version_info[:3] < (3, 14, 10):
        raise RuntimeError('Use /opt/homebrew/opt/python@3.14/bin/python3.14 (3.14.10 or newer 3.14).')
    if any(character.isspace() for character in str(ROOT)):
        raise RuntimeError('Clone into a path without spaces, such as ~/Developer/FlintEye-build.')
    for tool in ('git', 'node', 'npm', 'go', 'cmake', 'pkg-config', 'ninja', 'clang',
                 'make', 'patch', 'xcrun', 'hdiutil', 'codesign'):
        if not shutil.which(tool, path=env['PATH']):
            raise RuntimeError(f'Missing build tool: {tool}. Follow docs/LOCAL_MACOS_BUILD.md.')
    node = output(['node', '--version'], env)
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', node)
    if not match or int(match[1]) != 22 or int(match[2]) < 12:
        raise RuntimeError('Node.js 22.12 or newer 22.x is required.')
    if output(['node', '-p', 'process.arch'], env) != 'arm64':
        raise RuntimeError('Install the Apple Silicon Node.js build under /opt/homebrew.')
    go = output(['go', 'version'], env)
    match = re.search(r'go(\d+)\.(\d+)', go)
    if not match or tuple(map(int, match.groups())) < (1, 27) or 'darwin/arm64' not in go:
        raise RuntimeError('Native Go 1.27 or newer is required by the pinned MediaMTX source.')
    output(['xcrun', '--find', 'clang'], env)
    try:
        import tkinter
    except ImportError as exc:
        raise RuntimeError('Install python-tk@3.14 with the matching Homebrew Python.') from exc
    try:
        window = tkinter.Tk()
        window.withdraw()
        window.destroy()
    except tkinter.TclError as exc:
        raise RuntimeError('Tk could not open a window. Run from Terminal in the Mac desktop session.') from exc
    # The packaged smoke test uses fixed media ports but its own data directory.
    for port, kind in ((8554, socket.SOCK_STREAM), (8889, socket.SOCK_STREAM),
                       (9997, socket.SOCK_STREAM), (8189, socket.SOCK_DGRAM)):
        with socket.socket(socket.AF_INET, kind) as listener:
            try:
                listener.bind(('127.0.0.1', port))
            except OSError as exc:
                raise RuntimeError(f'Port {port} is busy. Stop FlintEye/MediaMTX before building.') from exc
    return {'python': platform.python_version(), 'node': node, 'go': go, 'macos': platform.mac_ver()[0]}


def snapshot(destination: Path, env: dict[str, str]) -> str:
    if output(['git', 'status', '--porcelain'], env):
        raise RuntimeError('Use a clean checkout. Commit or set aside source changes before building.')
    commit = output(['git', 'rev-parse', 'HEAD'], env)
    destination.mkdir(parents=True)
    archive = destination.parent / 'source.tar'
    subprocess.run(['git', 'archive', '--format=tar', f'--output={archive}', commit],
                   cwd=ROOT, env=env, check=True)
    with tarfile.open(archive) as source:
        source.extractall(destination, filter='data')
    archive.unlink()
    return commit


def run(command: list[str], *, cwd: Path, env: dict[str, str], log) -> None:
    print('\nRunning: ' + ' '.join(command), flush=True)
    log.write('\nRunning: ' + ' '.join(command) + '\n')
    log.flush()
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors='replace') as process:
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
        log.flush()
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, command)


def collect_artifacts(source: Path, destination: Path, commit: str,
                      toolchain: dict[str, str], app_version: str) -> Path:
    # Called only after the actual mounted/copied DMG has passed the smoke test.
    destination.mkdir()
    base = f'FlintEye-{app_version}-macos-arm64'
    local = f'FlintEye-{app_version}-local-{commit[:12]}-macos-arm64'
    for suffix in ('.dmg', '-sources.tar.gz', '-licenses.zip'):
        shutil.copy2(source / 'dist' / (base + suffix), destination / (local + suffix))
    shutil.copy2(source / 'dist/vendor-sha256.json', destination)
    receipt = {'version': app_version, 'commit': commit, 'platform': 'macos-arm64',
               'channel': 'local-test', 'toolchain': toolchain,
               'verified': ['media-startup-regressions', 'native-private-media-input',
                            'installed-dmg-setup-auth-recording', 'moved-app-same-profile'],
               'pending': ['physical-camera-live-view-recording-playback', 'desktop-settings', 'login-autostart']}
    (destination / 'build-info.json').write_text(json.dumps(receipt, indent=2) + '\n')
    lines = [f'{digest(path)}  {path.name}\n' for path in sorted(destination.iterdir()) if path.is_file()]
    (destination / 'SHA256SUMS').write_text(''.join(lines))
    return destination / (local + '.dmg')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=2, help='Parallel compile jobs (default: 2 for an M1 Air)')
    parser.add_argument('--check-only', action='store_true', help='Check tools and ports without compiling')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    env = build_environment(args.jobs)
    work = None
    try:
        toolchain = preflight(env)
        if args.check_only:
            print('Preflight passed. ' + json.dumps(toolchain))
            return 0
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        work = ROOT / 'dist/local-macos' / timestamp
        source = work / 'source'
        commit = snapshot(source, env)
        with (work / 'build.log').open('w', encoding='utf-8') as log:
            run([sys.executable, '-m', 'venv', str(work / 'venv')], cwd=source, env=env, log=log)
            python = str(work / 'venv/bin/python')
            env.update(PATH=str(work / 'venv/bin') + ':' + env['PATH'], FLINTEYE_PYTHON=python)
            commands = [
                [python, '-m', 'pip', 'install', '-c', 'packaging/constraints.txt', '-r', 'requirements.txt',
                 '-r', 'packaging/requirements-build.txt', 'meson==1.9.1', 'ninja==1.13.0'],
                [python, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_media_startup.py', '-v'],
                [python, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_process_lifetime.py', '-v'],
                [python, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_macos_lifecycle.py', '-v'],
                ['bash', 'packaging/build_vendor.sh'],
                [python, 'packaging/build_bundle.py', '--vendor', 'vendor'],
                [python, 'packaging/smoke_desktop_bundle.py'],
            ]
            for command in commands:
                run(command, cwd=source, env=env, log=log)
        app_version = output([python, 'packaging/release.py', 'version'], env, source)
        dmg = collect_artifacts(source, work / 'artifacts', commit, toolchain, app_version)
        print(f'\nLocal DMG verified: {dmg}\nBuild log: {work / "build.log"}')
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Build stopped: {exc}', file=sys.stderr)
        if work:
            print(f'Working files and any build log: {work}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
