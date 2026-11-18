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
from flinteye_app.flinteye_runtime import application_dir, data_dir, default_data_dir, launch_command

WORKERS = {'uvc_to_rtsp', 'ip_camera_to_rtsp', 'multiview_input_to_rtsp',
           'multiview_buffer_to_rtsp', 'multiview_raw_compositor', 'multiview_to_rtsp'}
from flinteye_app._version import RELEASE_VERSION
from flinteye_app.desktop_icon import create_window


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
    if media.control_mode != 'direct' or media.direct.source == 'external' or len(command) != 2:
        return
    old = Path(command[0])
    name = 'mediamtx.exe' if sys.platform == 'win32' else 'mediamtx'
    mac_bundle = old.parts[-5:] in (
        ('FlintEye.app', 'Contents', 'Frameworks', 'bin', name),
        ('FlintEye.app', 'Contents', 'Resources', 'bin', name),
    )
    onedir_bundle = old.parts[-3:] == ('_internal', 'bin', name)
    own_config = Path(command[1]).name == 'mediamtx.yml' and (
        command[1] == str(root / 'mediamtx.yml') or media.direct.working_dir == str(Path(command[1]).parent))
    if not own_config or (command[0] != name and not mac_bundle and not onedir_bundle):
        return
    binary = application_dir() / 'bin' / name
    if not binary.is_file():
        raise FileNotFoundError(f'Bundled MediaMTX is missing: {binary}. Reinstall the complete FlintEye application.')
    changes = {}
    if command[0] != str(binary) or command[1] != str(root/'mediamtx.yml'):
        changes['direct'] = {'command': [str(binary), str(root/'mediamtx.yml')]}
    if media.direct.working_dir != str(root) and (media.direct.source == 'bundled' or media.direct.working_dir == str(Path(command[1]).parent)):
        changes.setdefault('direct', {})['working_dir'] = str(root)
    # MediaMTX 1.21 enables MoQ by default. The desktop uses RTSP/WebRTC;
    # avoid starting an unused listener when upgrading an older profile.
    if media.managed.enabled and 'moq' not in media.managed.global_:
        changes['managed'] = {'global': {**media.managed.global_, 'moq': False}}
    if media.managed.enabled:
        globals_ = changes.get('managed', {}).get('global', media.managed.global_)
        changes['managed'] = {'global': {**globals_, 'api': True, 'apiAddress': '127.0.0.1:9997', 'apiEncryption': False}}
    if changes:
        store.patch_runtime({'mediamtx': changes})


def initialize(root: Path) -> Path:
    from flinteye_app.orchestrator_store import RuntimeStore
    from flinteye_app.flinteye_storage import suggested_quota
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime = root / 'runtime.json'
    if runtime.exists():
        from flinteye_app.network_access import backup_profile
        backup_profile(root)
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
                    'direct': {'source': 'bundled' if getattr(sys, 'frozen', False) else 'auto',
                               'command': [str(binary) if binary.exists() else exe, str(config)],
                               'working_dir': str(root)},
                    'managed': {'enabled': True, 'global': {
                        'rtspAddress': '127.0.0.1:8554', 'webrtcAddress': '127.0.0.1:8889',
                        'api': True, 'apiAddress': '127.0.0.1:9997', 'apiEncryption': False, 'hls': False, 'rtmp': False,
                        'srt': False, 'moq': False, 'playback': False,
                        'rtspTransports': ['tcp'], 'webrtcLocalUDPAddress': '127.0.0.1:8189',
                        'webrtcIPsFromInterfaces': False, 'webrtcAdditionalHosts': ['127.0.0.1']}}}})
    return runtime


def select_setup_network():
    """Ask the installer owner before making a new profile reachable."""
    import tkinter as tk
    from tkinter import ttk
    from flinteye_app.network_access import lan_candidates

    try:
        candidates = lan_candidates()
    except (OSError, ValueError, subprocess.SubprocessError):
        candidates = []
    window = create_window('FlintEye — Choose where to connect')
    frame = ttk.Frame(window, padding=20)
    frame.pack()
    options = ['This computer only'] + [f'{name} — {address} ({source})' for name, address, source in candidates]
    ttk.Label(frame, text='Choose a trusted network to open FlintEye from another device.',
              wraplength=460).pack(anchor='w')
    choice = ttk.Combobox(frame, values=options, state='readonly', width=49)
    choice.pack(fill='x', pady=8)
    choice.current(1 if len(candidates) == 1 else 0)
    if not candidates:
        ttk.Label(frame, text='No eligible private network was detected. Start locally and set a network later.',
                  wraplength=460).pack(anchor='w')
    selection = None

    def accept():
        nonlocal selection
        index = choice.current()
        if index > 0:
            _, address, source = candidates[index - 1]
            selection = address, source
        window.destroy()

    ttk.Button(frame, text='Start FlintEye', command=accept).pack(anchor='e', pady=8)
    window.mainloop()
    return selection


def _connection_state(root: Path) -> dict:
    try:
        return json.loads((root/'instance-control.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _print_connection(root: Path, connection: dict) -> None:
    lan = connection.get('lan_url')
    local = connection.get('url')
    setup = (root/'setup-token').is_file()
    action = 'Open this address to complete initial setup:' if setup else 'Open FlintEye:'
    print(f'FlintEye is running. {action} {lan or local}', flush=True)
    if lan:
        print(f'On the server: {local}. Certificate and trust guide: {root / "connection-guide"}', flush=True)
    elif connection.get('lan_error'):
        print(connection['lan_error'], flush=True)
    else:
        print('Access is local to this computer. Choose a trusted network to connect from another device.', flush=True)
    if setup:
        print(f'One-use setup code: read {root / "setup-token"} on the server.', flush=True)


def setup_dialog(runtime: Path) -> None:
    """Accessible password form lives in the browser; this window conveys ownership."""
    from flinteye_app.orchestrator_store import RuntimeStore
    from flinteye_app.orchestrator_auth import local_auth_is_configured
    from flinteye_app.instance_control import active_listener_port, active_listener_url, browser_url
    if local_auth_is_configured(RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False).get_effective().auth):
        return
    import tkinter as tk
    from tkinter import ttk
    root = runtime.parent
    window = create_window('FlintEye — Installation complete')
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=20); frame.pack()
    connection = _connection_state(root)
    ttk.Label(frame, text=f'FlintEye {RELEASE_VERSION}').pack(anchor='w', pady=(0, 8))
    ttk.Label(frame, text='FlintEye is running. Open the address below to finish setup.',
              wraplength=460).pack(anchor='w')
    ttk.Label(frame, text='Copy this one-use setup token into the web form. It expires in 30 minutes.', wraplength=460).pack(anchor='w', pady=8)
    token = tk.StringVar(value=(root/'setup-token').read_text())
    entry = ttk.Entry(frame, textvariable=token, width=48, state='readonly'); entry.pack(fill='x')
    def copy_token():
        window.clipboard_clear(); window.clipboard_append(token.get()); window.update()
    ttk.Button(frame, text='Copy setup token', command=copy_token).pack(anchor='w', pady=8)
    port = active_listener_port(root, 18080)
    config = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False).get_effective()
    url = active_listener_url(root, browser_url(config.api.host, port))
    ttk.Label(frame, text=url).pack(anchor='w')
    ttk.Button(frame, text='Open setup in browser', command=lambda: webbrowser.open(url)).pack(anchor='w', pady=8)
    if connection.get('lan_url'):
        lan_url = connection['lan_url']
        def copy_lan_url():
            window.clipboard_clear()
            window.clipboard_append(lan_url)
            window.update()
        ttk.Label(frame, text='From another device on the selected network: ' + lan_url,
                  wraplength=460).pack(anchor='w')
        ttk.Button(frame, text='Copy HTTPS address', command=copy_lan_url).pack(anchor='w', pady=5)
        ttk.Label(frame, text=f'Certificate and trust instructions: {root / "connection-guide"}',
                  wraplength=460).pack(anchor='w')
    elif connection.get('lan_error'):
        ttk.Label(frame, text=connection['lan_error'], wraplength=460).pack(anchor='w')
    else:
        ttk.Label(frame, text='This address works on this computer. To connect from another device, choose a network in Settings.',
                  wraplength=460).pack(anchor='w')
    def check():
        if local_auth_is_configured(RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False).get_effective().auth):
            window.destroy()
        else:
            try: token.set((root/'setup-token').read_text())
            except FileNotFoundError: pass
            window.after(1000, check)
    window.after(1000, check)
    entry.focus_set()
    window.mainloop()


def _startup_command() -> list[str]:
    if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
        return ['/usr/bin/open', '-a', str(Path(sys.executable).resolve().parents[2]), '--args']
    return launch_command()


def connection_information(root: Path, url: str) -> None:
    import tkinter as tk
    from tkinter import ttk
    window = create_window('FlintEye connection information')
    frame = ttk.Frame(window, padding=18); frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Open this address in your browser:').pack(anchor='w')
    text = tk.StringVar(value=url)
    ttk.Entry(frame, textvariable=text, width=50, state='readonly').pack(fill='x', pady=8)
    def copy(value):
        window.clipboard_clear(); window.clipboard_append(value); window.update()
    ttk.Button(frame, text='Copy address', command=lambda: copy(url)).pack(anchor='w')
    ttk.Button(frame, text='Open FlintEye', command=lambda: webbrowser.open(url)).pack(anchor='w', pady=6)
    connection = _connection_state(root)
    if lan_url := connection.get('lan_url'):
        ttk.Label(frame, text=lan_url).pack(anchor='w')
        ttk.Button(frame, text='Copy HTTPS address', command=lambda: copy(lan_url)).pack(anchor='w')
        ttk.Label(frame, text=f'Certificate and guide: {root / "connection-guide"}',
                  wraplength=420).pack(anchor='w')
    token = tk.StringVar()
    ttk.Label(frame, text='Initial setup token (only shown before administrator setup):', wraplength=420).pack(anchor='w')
    ttk.Entry(frame, textvariable=token, width=50, state='readonly').pack(fill='x', pady=6)
    ttk.Button(frame, text='Copy setup token', command=lambda: copy(token.get())).pack(anchor='w')
    def renew():
        from flinteye_app.network_access import private_write
        owner = json.loads((root/'instance-control.json').read_text())
        private_write(root/'stop-request.json', json.dumps({'token': owner['token'], 'action': 'renew-setup'}).encode())
    ttk.Button(frame, text='Renew setup token (30 minutes)', command=renew).pack(anchor='w', pady=6)
    def refresh():
        try: token.set((root/'setup-token').read_text())
        except FileNotFoundError: token.set('Setup already completed')
        window.after(1000, refresh)
    window.after(0, refresh)
    window.mainloop()


def _read_startup():
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                return winreg.QueryValueEx(key, 'FlintEye')[0]
        except FileNotFoundError:
            return None
    path = (Path.home()/'Library/LaunchAgents/community.flinteye.plist' if sys.platform == 'darwin'
            else Path.home()/'.config/autostart/flinteye.desktop')
    if not path.exists():
        return None
    # Preserve an unfamiliar or binary registration rather than replacing it.
    return path.read_text(encoding='utf-8', errors='replace')


def _owns_startup(existing, *, allow_legacy_bundle_id: bool = False) -> bool:
    if existing is None:
        return True
    owner = default_data_dir()/'autostart-owner.json'
    if owner.exists():
        try:
            record = json.loads(owner.read_text())
        except (OSError, ValueError):
            return False
        if not isinstance(record, dict):
            return False
        return (record.get('profile') == str(data_dir())
                and record.get('registration') == existing
                and record.get('installation') == launch_command())
    # Earlier versions had a single default-profile entry. Never remove a
    # different installation's command or guess ownership for a custom profile.
    if data_dir() != default_data_dir():
        return False
    command = _startup_command() + ['--background']
    if sys.platform == 'win32':
        return existing == subprocess.list2cmdline(command)
    if sys.platform == 'darwin':
        import plistlib
        try:
            registration = plistlib.loads(existing.encode())
            legacy = ['/usr/bin/open', '-b', 'community.flinteye', '--args', '--background']
            return isinstance(registration, dict) and (registration.get('ProgramArguments') == command
                or (allow_legacy_bundle_id and registration.get('ProgramArguments') == legacy))
        except (ValueError, plistlib.InvalidFileException):
            return False
    return ('Exec=' + _desktop_command(command) + '\n' in existing
            or 'Exec=' + _desktop_command(command[:-1]) + ' --background\n' in existing)


def _desktop_command(command):
    return ' '.join('"' + arg.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"' for arg in command)


def enable_autostart() -> bool:
    if sys.platform == 'darwin' and '/AppTranslocation/' in sys.executable:
        # A temporary Gatekeeper path cannot be used at the next login.
        return False
    if (data_dir()/'autostart-disabled').exists() or not _owns_startup(_read_startup()):
        return False
    command = _startup_command() + ['--background', '--data-dir', str(data_dir())]
    if sys.platform == 'win32':
        import winreg
        registration = subprocess.list2cmdline(command)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.SetValueEx(key, 'FlintEye', 0, winreg.REG_SZ, registration)
    elif sys.platform == 'darwin':
        import plistlib
        dest = Path.home()/'Library/LaunchAgents/community.flinteye.plist'
        dest.parent.mkdir(parents=True, exist_ok=True)
        registration = plistlib.dumps({'Label': 'community.flinteye', 'ProgramArguments': command, 'RunAtLoad': True}).decode()
        dest.write_text(registration, encoding='utf-8')
    else:
        dest = Path.home()/'.config/autostart/flinteye.desktop'
        dest.parent.mkdir(parents=True, exist_ok=True)
        registration = '[Desktop Entry]\nType=Application\nName=FlintEye\nExec=' + _desktop_command(command) + '\n'
        dest.write_text(registration, encoding='utf-8')
    owner = default_data_dir()/'autostart-owner.json'
    owner.parent.mkdir(parents=True, exist_ok=True)
    owner.write_text(json.dumps({'profile':str(data_dir()), 'registration':registration,
                                'installation':launch_command()}), encoding='utf-8')
    return True


def disable_autostart() -> None:
    """Remove this profile's login registration; preserve other installations/data."""
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    # Explicit removal may also clean the old default-profile, shared bundle-ID
    # registration. Automatic startup must never take over that ambiguous entry.
    if _owns_startup(_read_startup(), allow_legacy_bundle_id=True):
        if sys.platform == 'win32':
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run',
                                    0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, 'FlintEye')
            except FileNotFoundError:
                pass
        elif sys.platform == 'darwin':
            (Path.home()/'Library/LaunchAgents/community.flinteye.plist').unlink(missing_ok=True)
            subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/community.flinteye'],
                           capture_output=True, check=False, timeout=10)
        else:
            (Path.home()/'.config/autostart/flinteye.desktop').unlink(missing_ok=True)
        (default_data_dir()/'autostart-owner.json').unlink(missing_ok=True)
    (root/'autostart-disabled').write_text('Disabled by the user.\n', encoding='utf-8')


def autostart_status() -> dict:
    existing = _read_startup()
    owned = _owns_startup(existing)
    return {'enabled': existing is not None and owned, 'available': owned,
            'message': '' if owned else 'Start at login belongs to another installation or profile.'}


def set_autostart(enabled: bool):
    if not _owns_startup(_read_startup()):
        raise ValueError('Start at login belongs to another installation or profile; it was preserved.')
    if enabled:
        marker = data_dir()/'autostart-disabled'
        marker.unlink(missing_ok=True)
        if not enable_autostart():
            marker.write_text('Start at login could not be enabled.\n', encoding='utf-8')
            raise ValueError('Move FlintEye to Applications before enabling start at login.')
    else:
        disable_autostart()


def desktop_available() -> bool:
    if os.environ.get('FLINTEYE_HEADLESS') == '1':
        return False
    if sys.platform.startswith('linux'):
        return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    if sys.platform == 'darwin':
        return not bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'))
    return os.environ.get('SESSIONNAME', '').lower() != 'services'


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
    if '--segment-complete' in sys.argv or '--segment-created' in sys.argv:
        from flinteye_app.recording_events import record_event
        flag = '--segment-complete' if '--segment-complete' in sys.argv else '--segment-created'
        session = sys.argv[sys.argv.index('--recording-session') + 1] if '--recording-session' in sys.argv else None
        record_event(Path(sys.argv[sys.argv.index(flag) + 1]), Path(os.environ['MTX_SEGMENT_PATH']),
                     complete=flag == '--segment-complete', session=session)
        return 0
    if '--pick-folder' in sys.argv:
        import tkinter as tk
        from tkinter import filedialog
        window = create_window('FlintEye — Choose recording folder'); window.withdraw()
        selected = filedialog.askdirectory(title='Choose the recording folder on this computer')
        Path(sys.argv[sys.argv.index('--pick-folder') + 1]).write_text(json.dumps({'path': selected}), encoding='utf-8')
        window.destroy()
        return 0
    parser = argparse.ArgumentParser(description='FlintEye')
    parser.add_argument('--version', action='version', version=RELEASE_VERSION)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--setup-only', action='store_true')
    parser.add_argument('--background', action='store_true')
    startup = parser.add_mutually_exclusive_group()
    startup.add_argument('--disable-autostart', action='store_true', help='Remove FlintEye login startup and exit; preserve data')
    startup.add_argument('--enable-autostart', action='store_true', help='Enable FlintEye login startup and exit')
    parser.add_argument('--data-dir', type=Path, default=data_dir())
    parser.add_argument('--lan-address', help='Explicitly enable LAN HTTPS on this server IPv4 address')
    parser.add_argument('--lan-source', action='append', default=[], help='Allowed private IPv4 CIDR; repeat for more ranges')
    parser.add_argument('--disable-lan', action='store_true', help='Disable LAN access; keep local HTTP and recordings')
    parser.add_argument('--export-connection-guide', action='store_true', help='Write public certificate and trust guide, then exit')
    parser.add_argument('--remove-firewall-rules', action='store_true', help='Remove only this profile installation Firewall rules with explicit UAC approval')
    parser.add_argument('--remove-installation-firewall-rules', action='store_true', help='Remove this executable installation LAN rules across profiles, with explicit UAC approval')
    parser.add_argument('--connection-info', action='store_true', help='Show the running profile address and initial setup assistance')
    parser.add_argument('--port', type=int, help='Override the saved API port for this launch only')
    args = parser.parse_args()
    args.headless = args.headless or not desktop_available()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    root = args.data_dir.expanduser().resolve()
    os.environ['FLINTEYE_DATA_DIR'] = str(root)
    if args.remove_installation_firewall_rules:
        from flinteye_app.windows_maintenance import remove_installation_firewall
        remove_installation_firewall()
        return 0
    if args.connection_info:
        if args.headless:
            for _ in range(50):
                connection = _connection_state(root)
                if connection.get('ready'):
                    _print_connection(root, connection)
                    return 0
                time.sleep(.2)
            print('FlintEye has not reported a ready listener. Check service startup logs.', file=sys.stderr)
            return 1
        from flinteye_app.instance_control import active_listener_port, active_listener_url
        connection_information(root, active_listener_url(root, f'http://127.0.0.1:{active_listener_port(root, 18080)}'))
        return 0
    if args.disable_autostart:
        disable_autostart()
        return 0
    if args.enable_autostart:
        if not _owns_startup(_read_startup()):
            print('Start at login belongs to another FlintEye installation or profile; it was preserved.', file=sys.stderr)
            return 1
        (root/'autostart-disabled').unlink(missing_ok=True)
        return 0 if enable_autostart() else 1
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
            from flinteye_app.orchestrator_store import RuntimeStore
            existing = RuntimeStore(env_file='', runtime_file=str(root/'runtime.json'), use_env=False)
            from flinteye_app.instance_control import active_listener_port, active_listener_url, browser_url
            api = existing.get_effective().api
            webbrowser.open(active_listener_url(root, browser_url(api.host, active_listener_port(root, api.port))))
        return 0
    first_install = not (root/'runtime.json').exists()
    runtime = initialize(root)
    from flinteye_app.orchestrator_store import RuntimeStore
    store = RuntimeStore(env_file='', runtime_file=str(runtime), use_env=False)
    if args.remove_firewall_rules:
        from flinteye_app.windows_maintenance import manage_firewall
        manage_firewall(root, store.get_effective(), 'remove')
        return 0
    lan_error = ''
    selected_network = False
    if first_install and not (args.lan_address or args.disable_lan):
        args.lan_address = os.environ.get('FLINTEYE_LAN_ADDRESS', '')
        args.lan_source = [value.strip() for value in os.environ.get('FLINTEYE_LAN_SOURCES', '').split(',')
                           if value.strip()]
        if not args.lan_address and not (args.headless or args.background or args.setup_only):
            selection = select_setup_network()
            if selection:
                args.lan_address, source = selection
                args.lan_source = [source]
                selected_network = True
    if args.lan_address or args.disable_lan:
        from flinteye_app.orchestrator_models import NetworkAccessConfig
        from flinteye_app.network_access import ensure_certificates, lan_media_patch
        try:
            network = NetworkAccessConfig(enabled=not args.disable_lan, address=args.lan_address or '',
                                          allowed_subnets=args.lan_source,
                                          rtsp_enabled=store.get_effective().network.rtsp_enabled)
            if network.enabled:
                if os.environ.get('FLINTEYE_CONTAINER_BRIDGE') == '1':
                    raise ValueError('LAN HTTPS for Docker needs Linux host networking')
                ensure_certificates(root, network.address)
            patch = lan_media_patch(store.get_effective()) if network.enabled else {}
            if selected_network and sys.platform == 'win32':
                from flinteye_app.windows_maintenance import manage_firewall

                config = store.get_effective().model_copy(update={'network': network})
                if args.port:
                    config.api = config.api.model_copy(update={'port': args.port})
                manage_firewall(root, config, 'apply')
            store.patch_runtime({'network': network.model_dump(), 'api': {'host': '127.0.0.1'}, **patch})
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            if not first_install:
                raise
            lan_error = f'LAN HTTPS could not be prepared: {error}'
    if args.export_connection_guide:
        from flinteye_app.network_access import export_guide
        config = store.get_effective()
        if not config.network.enabled: parser.error('Enable LAN access before exporting the connection guide')
        print(export_guide(root, config.network.address, args.port or config.api.port))
        return 0
    config = store.get_effective()
    if config.network.enabled:
        from flinteye_app.network_access import lan_media_patch
        # Also reassert the authenticated media bridge after an upgrade or saved edit.
        store.patch_runtime(lan_media_patch(config))
        config = store.get_effective()
    if config.network.enabled and config.auth.provider == 'local' and not config.auth.viewer_auth_required:
        store.patch_runtime({'auth': {'viewer_auth_required': True}})
        config = store.get_effective()
    if config.mediamtx.control_mode == 'direct' and config.mediamtx.managed.enabled:
        options = dict(config.mediamtx.managed.global_)
        # The built-in bridge owns its internal transports, never a user's external MediaMTX.
        options.update(rtspTransports=['tcp'])
        if config.network.enabled:
            options.update(webrtcLocalUDPAddress=config.network.address + ':8189', webrtcIPsFromInterfaces=False,
                           webrtcAdditionalHosts=[config.network.address])
        elif not os.environ.get('FLINTEYE_CONTAINER_BRIDGE'):
            options.update(webrtcLocalUDPAddress='127.0.0.1:8189', webrtcIPsFromInterfaces=False,
                           webrtcAdditionalHosts=['127.0.0.1'])
        if os.environ.get('FLINTEYE_CONTAINER_BRIDGE') == '1':
            options.update(webrtcLocalUDPAddress=':8189', webrtcIPsFromInterfaces=False,
                           webrtcAdditionalHosts=['127.0.0.1'])
        if options != config.mediamtx.managed.global_:
            store.patch_runtime({'mediamtx': {'managed': {'global': options}}})
    if not args.headless:
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
    host = '0.0.0.0' if os.environ.get('FLINTEYE_CONTAINER_BRIDGE') == '1' else context.store.get_effective().api.host
    port = args.port or context.store.get_effective().api.port
    from flinteye_app.instance_control import browser_url
    url = browser_url(host, port)
    network = context.store.get_effective().network
    context.supervisor.rtsps_profile = root
    context.supervisor.rtsps_network = network
    context.listener = {'host': host, 'port': port, 'scheme': 'http', 'url': url,
                        'lan_url': f'https://{network.address}:{port}' if network.enabled else None,
                        'source': 'command line' if args.port else 'saved configuration'}
    from flinteye_app.server_runtime import ListenerGroup
    server = ListenerGroup(app, root=root, host=host, port=port, network=network)
    context.listener_group = server
    from flinteye_app.instance_control import InstanceControl
    def renew_setup():
        if not local_auth_is_configured(context.store.get_effective().auth): context.bootstrap.renew()
    def requested_quit():
        from flinteye_app.monitoring import MonitoringConflict
        try:
            result = context.monitoring.perform('quit')
        except MonitoringConflict:
            return False
        if not result['ok']:
            return False
        server.should_exit = True
        return True
    control = InstanceControl(root, requested_quit, port=port, renew_setup=renew_setup, url=url)
    def ready():
        lan_url = context.listener['lan_url'] if server.lan_started else None
        context.listener['lan_url'] = lan_url
        message = lan_error or server.lan_error
        if lan_url:
            from flinteye_app.network_access import export_guide
            try:
                export_guide(root, network.address, port)
            except (OSError, ValueError):
                message = 'Could not save the trust guide. Export it from the server Settings.'
        control.write_connection(ready=True, lan_url=lan_url, lan_error=message)
        _print_connection(root, control.metadata)

    server.on_ready = ready
    thread = None
    try:
        if args.headless:
            server.run()
            return 0
        thread = threading.Thread(target=server.run, name='flinteye-api')
        thread.start()
        for _ in range(100):
            if control.metadata.get('ready'): break
            if not thread.is_alive(): raise RuntimeError('Could not start FlintEye. Check logs or port conflicts.')
            time.sleep(.1)
        else: raise RuntimeError('FlintEye did not become ready.')
        from flinteye_app.flinteye_desktop import run_desktop
        if not args.background: webbrowser.open(url)
        setup_dialog(runtime)
        if args.setup_only: return 0
        run_desktop(url, server, root, context.monitoring)
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
        if '--headless' not in sys.argv and '--worker' not in sys.argv and desktop_available() and not any(arg.startswith('--segment-') for arg in sys.argv):
            import tkinter as tk
            from tkinter import messagebox
            window = create_window('FlintEye could not start'); window.withdraw()
            messagebox.showerror('FlintEye could not start', str(error))
            window.destroy()
        raise


if __name__ == '__main__':
    entrypoint()
