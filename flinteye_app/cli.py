"""Production entry point. No Node.js or system Python is needed in a bundle."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import runpy
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from flinteye_app.flinteye_runtime import application_dir, data_dir, launch_command

WORKERS = {'uvc_to_rtsp', 'ip_camera_to_rtsp', 'multiview_input_to_rtsp',
           'multiview_buffer_to_rtsp', 'multiview_raw_compositor', 'multiview_to_rtsp'}
from flinteye_app._version import VERSION


def _repair_bundled_media_path(runtime: Path, root: Path) -> None:
    """Rebase our own persisted command after a bundle move or App Translocation.

    Explicit external commands, custom config files and extra arguments are kept.
    Never retain a one-time macOS AppTranslocation directory across launches.
    """
    if not getattr(sys, 'frozen', False):
        return
    from flinteye_app.orchestrator_store import RuntimeStore
    store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
    media = store.get_effective().mediamtx
    command = media.direct.command
    if media.control_mode != 'direct' or len(command) != 2 or command[1] != str(root / 'mediamtx.yml'):
        return
    old = Path(command[0])
    name = 'mediamtx.exe' if sys.platform == 'win32' else 'mediamtx'
    mac_bundle = old.parts[-5:] in (
        ('FlintEye.app', 'Contents', 'Frameworks', 'bin', name),
        ('FlintEye.app', 'Contents', 'Resources', 'bin', name),
    )
    onedir_bundle = old.parts[-4:] == ('FlintEye', '_internal', 'bin', name)
    if command[0] != name and not mac_bundle and not onedir_bundle:
        return
    binary = application_dir() / 'bin' / name
    if not binary.is_file():
        raise FileNotFoundError(f'Bundled MediaMTX is missing: {binary}. Reinstall the complete FlintEye application.')
    changes = {}
    if command[0] != str(binary):
        changes['direct'] = {'command': [str(binary), command[1]]}
    # MediaMTX 1.21 enables MoQ by default. The desktop uses RTSP/WebRTC;
    # avoid starting an unused listener when upgrading an older profile.
    if media.managed.enabled and 'moq' not in media.managed.global_:
        changes['managed'] = {'global': {**media.managed.global_, 'moq': False}}
    if changes:
        store.patch_runtime({'mediamtx': changes})


def initialize(root: Path) -> Path:
    from flinteye_app.orchestrator_store import RuntimeStore
    from flinteye_app.flinteye_storage import suggested_quota
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime = root / 'runtime.json'
    if runtime.exists():
        _repair_bundled_media_path(runtime, root)
        return runtime
    exe = 'mediamtx.exe' if sys.platform == 'win32' else 'mediamtx'
    binary = application_dir() / 'bin' / exe
    if getattr(sys, 'frozen', False) and not binary.is_file():
        raise FileNotFoundError(f'Bundled MediaMTX is missing: {binary}. Reinstall the complete FlintEye application.')
    recordings = root / 'recordings'
    recordings.mkdir(mode=0o700)
    config = root / 'mediamtx.yml'
    config.write_text('paths:\n  all_others: {}\n', encoding='utf-8')
    RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False).set_runtime({
        'auth': {'provider': 'local', 'viewer_auth_required': True},
        'api': {'host': '127.0.0.1', 'port': 18080},
        'ui': {'app_title': 'FlintEye', 'sidebar_title': 'FlintEye'},
        'logging': {'directory': str(root / 'logs')},
        'recording': {'record_root': str(recordings), 'record_delete_after': '168h',
                      'max_bytes': suggested_quota(recordings), 'managed_storage': True},
        'multiview': {'enabled': False, 'status_file': str(root / 'logs/runtime/multiview.json')},
        'cameras': [],
        'mediamtx': {'control_mode': 'direct', 'webrtc_base_url': '/media',
                    'direct': {'command': [str(binary) if binary.exists() else exe, str(config)],
                               'working_dir': str(root)},
                    'managed': {'enabled': True, 'global': {
                        'rtspAddress': '127.0.0.1:8554', 'webrtcAddress': '127.0.0.1:8889',
                        'apiAddress': '127.0.0.1:9997', 'hls': False, 'rtmp': False,
                        'srt': False, 'moq': False, 'playback': False}}}})
    return runtime


def setup_dialog(runtime: Path) -> None:
    """The installer opens this window in the installing user's session."""
    from flinteye_app.orchestrator_store import RuntimeStore
    from flinteye_app.orchestrator_auth import local_auth_is_configured, hash_password, generate_session_secret
    store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
    if local_auth_is_configured(store.get_effective().auth):
        return
    import tkinter as tk
    from tkinter import messagebox
    window = tk.Tk()
    window.title('FlintEye Setup')
    window.resizable(False, False)
    frame = tk.Frame(window, padx=28, pady=24)
    frame.pack()
    tk.Label(frame, text='Create your administrator password', font=('', 15, 'bold')).pack(pady=8)
    tk.Label(frame, text='Username: admin\nUse at least 12 characters. You can set the viewer password later.').pack()
    password = tk.Entry(frame, show='*', width=38)
    confirm = tk.Entry(frame, show='*', width=38)
    for label, entry in [('Password', password), ('Confirm password', confirm)]:
        tk.Label(frame, text=label).pack(anchor='w', pady=(12, 0))
        entry.pack()
    def save():
        value = password.get()
        if len(value) < 12 or len(value) > 1024 or value != confirm.get():
            messagebox.showerror('Check password', 'Passwords must match and contain 12–1024 characters.')
            return
        store.patch_runtime({'auth': {'provider': 'local', 'session_secret': generate_session_secret(),
                             'local': {'admin': {'username': 'admin', 'password_hash': hash_password(value)}}}})
        window.destroy()
    tk.Button(frame, text='Finish setup and open FlintEye', command=save).pack(pady=18)
    password.focus_set()
    window.mainloop()
    if not local_auth_is_configured(store.get_effective().auth):
        raise SystemExit(0)


def enable_autostart() -> None:
    import shlex
    command = launch_command()
    if sys.platform == 'win32':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.SetValueEx(key, 'FlintEye', 0, winreg.REG_SZ, subprocess.list2cmdline(command + ['--background']))
    elif sys.platform == 'darwin':
        import plistlib
        if getattr(sys, 'frozen', False):
            # LaunchServices resolves the installed app; sys.executable may be
            # inside a temporary AppTranslocation directory that expires.
            command = ['/usr/bin/open', '-b', 'community.flinteye', '--args']
        dest = Path.home() / 'Library/LaunchAgents/community.flinteye.plist'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(plistlib.dumps({'Label': 'community.flinteye', 'ProgramArguments': command + ['--background'], 'RunAtLoad': True}))
    else:
        dest = Path.home() / '.config/autostart/flinteye.desktop'
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Desktop Entry Exec uses double quotes, not shell single-quote escaping.
        quoted = ' '.join('"' + arg.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"' for arg in command)
        dest.write_text('[Desktop Entry]\nType=Application\nName=FlintEye\nExec=' + quoted + ' --background\n', encoding='utf-8')


def main() -> int:
    from flinteye_app.subprocess_utils import ensure_standard_streams
    ensure_standard_streams()
    if len(sys.argv) > 2 and sys.argv[1] == '--worker':
        name = sys.argv[2]
        if name not in WORKERS:
            raise SystemExit('Unknown worker')
        sys.argv = [name + '.py', *sys.argv[3:]]
        runpy.run_module('flinteye_app.workers.' + name, run_name='__main__')
        return 0
    if '--segment-complete' in sys.argv:
        from flinteye_app.flinteye_storage import register_segment
        register_segment(Path(sys.argv[-1]), Path(os.environ['MTX_SEGMENT_PATH']))
        return 0
    if '--pick-folder' in sys.argv:
        import tkinter as tk
        from tkinter import filedialog
        window = tk.Tk(); window.withdraw()
        selected = filedialog.askdirectory(title='Choose the recording folder on this computer')
        Path(sys.argv[sys.argv.index('--pick-folder') + 1]).write_text(json.dumps({'path': selected}), encoding='utf-8')
        window.destroy()
        return 0
    parser = argparse.ArgumentParser(description='FlintEye')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--setup-only', action='store_true')
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=data_dir())
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    root = args.data_dir.expanduser().resolve()
    os.environ['FLINTEYE_DATA_DIR'] = str(root)
    os.environ['FLINTEYE_PACKAGED'] = '1'
    os.environ['PATH'] = str(application_dir() / 'bin') + os.pathsep + os.environ.get('PATH', '')
    # Keep a process-owned lock; OS releases it after crashes. Never kill unrelated processes.
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (root / 'instance.lock').open('a+b')
    try:
        if sys.platform == 'win32':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if not args.headless:
            webbrowser.open(f'http://127.0.0.1:{args.port}')
        return 0
    runtime = initialize(root)
    if not args.headless:
        setup_dialog(runtime)
        if args.setup_only: return 0
        enable_autostart()
    from flinteye_app.orchestrator_api import app, AppContext, set_app_context
    from flinteye_app.orchestrator_auth import local_auth_is_configured
    from flinteye_app.flinteye_routes import install_routes
    context = AppContext(env_file='', runtime_file=str(runtime), no_env=True)
    set_app_context(context)
    token_file = root / 'setup-token'
    token = secrets.token_urlsafe(32) if not local_auth_is_configured(context.store.get_effective().auth) else ''
    if token:
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write(token)
        print(f'Initial setup: open the web UI and enter the token from {token_file}', flush=True)
    install_routes(app, context, setup_token=token, desktop=not args.headless)
    url = f'http://127.0.0.1:{args.port}'
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host=context.store.get_effective().api.host,
                                          port=args.port, log_config=None, proxy_headers=True,
                                          timeout_graceful_shutdown=5,
                                          forwarded_allow_ips='127.0.0.1,::1'))
    from flinteye_app.instance_control import InstanceControl
    control = InstanceControl(root, lambda: setattr(server, 'should_exit', True))
    thread = None
    try:
        if args.headless:
            server.run()
            return 0
        thread = threading.Thread(target=server.run, name='flinteye-api')
        thread.start()
        for _ in range(100):
            if server.started: break
            if not thread.is_alive(): raise RuntimeError('Could not start FlintEye. Check logs or port conflicts.')
            time.sleep(.1)
        else: raise RuntimeError('FlintEye did not become ready.')
        from flinteye_app.flinteye_desktop import run_desktop
        if not args.background: webbrowser.open(url)
        run_desktop(url, server, root)
    finally:
        server.should_exit = True
        try:
            # Stop publishers and MediaMTX even if open clients delay ASGI shutdown.
            context.shutdown()
        finally:
            from flinteye_app.process_lifetime import stop_background_processes
            try:
                stop_background_processes()
            finally:
                if thread is not None:
                    thread.join()
                control.close()
    return 0


def entrypoint() -> None:
    try:
        raise SystemExit(main())
    except Exception as error:
        if '--headless' not in sys.argv and '--worker' not in sys.argv:
            import tkinter as tk
            from tkinter import messagebox
            window = tk.Tk(); window.withdraw()
            messagebox.showerror('FlintEye could not start', str(error))
            window.destroy()
        raise


if __name__ == '__main__':
    entrypoint()
