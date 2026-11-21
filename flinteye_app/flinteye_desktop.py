"""Native monitoring controls. Closing a browser never ends monitoring."""
from __future__ import annotations
from contextlib import contextmanager, nullcontext, ExitStack
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import webbrowser

logger = logging.getLogger(__name__)
COLORS = {'green': '#1c9b55', 'red': '#d12f3e', 'amber': '#b77500', 'gray': '#64748b'}


@contextmanager
def inhibit_sleep():
    process = None
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    elif sys.platform == 'darwin':
        process = subprocess.Popen(['caffeinate', '-i', '-w', str(os.getpid())])
    elif shutil.which('systemd-inhibit'):
        process = subprocess.Popen(['systemd-inhibit', '--what=sleep:idle', '--mode=block',
                                    '--why=FlintEye camera monitoring', 'cat'], stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield
    finally:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        if process:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def tray_image(status):
    """The eye mark and a high-contrast shape convey status without color alone."""
    from PIL import Image, ImageDraw
    from flinteye_app.flinteye_runtime import application_dir
    asset = application_dir()/'images/icons/flinteye-symbol.png'
    image = Image.open(asset).convert('RGBA').resize((96, 96), Image.Resampling.LANCZOS) if asset.is_file() else Image.new('RGBA', (96, 96))
    draw = ImageDraw.Draw(image)
    draw.ellipse((50, 50, 94, 94), fill=COLORS.get(status['color'], COLORS['amber']), outline='white', width=3)
    state = status['state']
    if state == 'running':
        draw.polygon([(67, 61), (67, 83), (82, 72)], fill='white')
    elif state == 'stopped':
        draw.rectangle((64, 64, 80, 80), fill='white')
    elif status['color'] == 'red':
        draw.line((64, 64, 80, 80), fill='white', width=5)
        draw.line((80, 64, 64, 80), fill='white', width=5)
    elif status['color'] == 'gray':
        draw.line((62, 72, 82, 72), fill='white', width=5)
    else:
        draw.line((72, 61, 72, 75), fill='white', width=4)
        draw.ellipse((70, 80, 74, 84), fill='white')
    return image


def status_text(status):
    counts = status['counts']
    return f"{status['label']} — {counts['receiving']}/{counts['targets']} receiving, {counts['recording']} recording"


class DesktopActions:
    def __init__(self, controller, server):
        self.controller, self.server = controller, server
        self.lock = threading.Lock()
        self.message = ''

    @property
    def busy(self):
        return self.lock.locked() or self.controller.status()['busy']

    def submit(self, action, *, force=False, startup=None, remove_startup=False):
        if not self.lock.acquire(blocking=False):
            return
        def work():
            try:
                from flinteye_app.cli import set_autostart
                self.message = ''
                if startup is not None:
                    set_autostart(startup)
                    return
                if remove_startup:
                    set_autostart(False)
                result = self.controller.perform(action, force=force)
                if action == 'quit' and (result['ok'] or force):
                    self.server.should_exit = True
                elif not result['ok']:
                    self.message = result['message']
            except Exception as exc:
                self.message = str(exc)
                logger.exception('Desktop action failed')
            finally:
                self.lock.release()
        threading.Thread(target=work, name='desktop-action', daemon=True).start()


def _sleep_watcher(controller, done):
    # Windows execution state is thread-local: acquire AND release here.
    active = None
    try:
        while not done.wait(.3):
            status = controller.status()
            needed = ((status['desired_running'] and status['counts']['targets'] > 0)
                      or status['phase'] in {'stopping', 'finalizing'})
            if needed and active is None:
                active = ExitStack()
                try:
                    active.enter_context(inhibit_sleep())
                except OSError:
                    logger.exception('Could not inhibit sleep')
                    active.close()
                    active = None
            elif not needed and active is not None:
                active.close()
                active = None
    finally:
        if active is not None:
            active.close()


def _confirm_force_quit():
    text = 'Some recordings may be incomplete. Force quit FlintEye and stop all its processes?'
    if sys.platform == 'darwin':
        import AppKit
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_('Force quit FlintEye?')
        alert.setInformativeText_(text)
        alert.addButtonWithTitle_('Cancel')
        alert.addButtonWithTitle_('Force quit')
        return alert.runModal() == AppKit.NSAlertSecondButtonReturn
    if sys.platform == 'win32':
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None, text, 'Force quit FlintEye?', 0x134) == 6
    from tkinter import messagebox
    return messagebox.askyesno('Force quit FlintEye?', text, default='no')


def _run_tray(server, root, controller, actions, open_browser):
    import pystray
    from flinteye_app.desktop_icon import apply_application_icon
    apply_application_icon()
    from flinteye_app.cli import autostart_status
    snapshot = controller.status()
    startup = autostart_status()
    last = None
    done = threading.Event()
    def connection_info():
        from flinteye_app.flinteye_runtime import launch_command
        from flinteye_app.process_lifetime import popen_background
        from flinteye_app.subprocess_utils import background_process_options
        popen_background(launch_command() + ['--connection-info', '--data-dir', str(root)], **background_process_options())
    def force_quit():
        if _confirm_force_quit():
            actions.submit('quit', force=True)
    icon = pystray.Icon('FlintEye', tray_image(snapshot), 'FlintEye', menu=pystray.Menu(
        pystray.MenuItem(lambda item: status_text(snapshot), None, enabled=False),
        pystray.MenuItem(lambda item: (actions.message or snapshot['message'])[:140], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Open FlintEye', lambda: open_browser(), default=True),
        pystray.MenuItem('Address and setup assistance', connection_info),
        pystray.MenuItem('Start monitoring', lambda: actions.submit('start'),
                         enabled=lambda item: not actions.busy and not snapshot['desired_running'] and snapshot['phase'] != 'finalizing'),
        pystray.MenuItem('Stop monitoring', lambda: actions.submit('stop'),
                         enabled=lambda item: not actions.busy and (snapshot['desired_running'] or snapshot['phase'] == 'finalizing')),
        pystray.MenuItem('Restart monitoring', lambda: actions.submit('restart'),
                         enabled=lambda item: not actions.busy and snapshot['desired_running'] and snapshot['phase'] != 'finalizing'),
        pystray.MenuItem('Open logs', lambda: webbrowser.open((root / 'logs').as_uri())),
        pystray.MenuItem('Start at login', lambda: actions.submit(None, startup=not startup['enabled']),
                         checked=lambda item: startup['enabled'], enabled=lambda item: not actions.busy and startup['available']),
        pystray.MenuItem('Disable start at login and quit', lambda: actions.submit('quit', remove_startup=True),
                         enabled=lambda item: not actions.busy and startup['available']),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Quit FlintEye', lambda: actions.submit('quit'), enabled=lambda item: not actions.busy),
        pystray.MenuItem('Force quit (recordings may be incomplete)', force_quit,
                         visible=lambda item: (snapshot['phase'] == 'finalizing' or snapshot.get('previous_stop_unknown')) and not actions.busy)))

    def update():
        nonlocal snapshot, startup, last
        if done.is_set():
            return
        if server.should_exit:
            icon.stop()
            return
        snapshot = controller.status()
        startup = autostart_status()
        key = (snapshot['state'], snapshot['color'])
        if key != last:
            icon.icon = tray_image(snapshot)
            last = key
        icon.title = 'FlintEye — ' + status_text(snapshot)
        icon.update_menu()

    def schedule(callback):
        if sys.platform == 'darwin':
            from PyObjCTools.AppHelper import callAfter
            callAfter(callback)
        else:
            callback()  # Win32 notification-area updates use thread-safe shell calls.

    def ready(icon):
        schedule(lambda: setattr(icon, 'visible', True))
        def watch():
            while not done.wait(.5):
                schedule(update)
        threading.Thread(target=watch, name='tray-status', daemon=True).start()
    termination = nullcontext()
    if sys.platform == 'darwin':
        from flinteye_app.macos_lifecycle import graceful_application_quit
        termination = graceful_application_quit(icon, server, on_quit=lambda: actions.submit('quit'))
    try:
        with termination:
            icon.run(setup=ready)
    finally:
        done.set()


def _run_control_window(url, server, root, controller, actions, open_browser):
    import tkinter as tk
    from tkinter import ttk, messagebox
    from flinteye_app.cli import autostart_status
    window = tk.Tk()
    window.title('FlintEye')
    window.geometry('440x420')
    window.minsize(360, 340)
    from flinteye_app.desktop_icon import apply_application_icon
    apply_application_icon(window)
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill='both', expand=True)
    state = ttk.Label(frame, font=('', 13, 'bold'), wraplength=430)
    state.pack(anchor='w', pady=(0, 10))
    message = ttk.Label(frame, wraplength=430)
    message.pack(anchor='w', pady=(0, 10))
    ttk.Label(frame, text=url, wraplength=400).pack(anchor='w')
    def copy_url():
        window.clipboard_clear(); window.clipboard_append(url); window.update()
    row = ttk.Frame(frame); row.pack(fill='x')
    ttk.Button(row, text='Open FlintEye', command=open_browser).pack(side='left', pady=3)
    ttk.Button(row, text='Copy address', command=copy_url).pack(side='left', padx=6)
    def connection_info():
        from flinteye_app.flinteye_runtime import launch_command
        from flinteye_app.process_lifetime import popen_background
        from flinteye_app.subprocess_utils import background_process_options
        popen_background(launch_command() + ['--connection-info', '--data-dir', str(root)], **background_process_options())
    ttk.Button(frame, text='Address and setup assistance', command=connection_info).pack(anchor='w', pady=3)
    controls = ttk.Frame(frame); controls.pack(fill='x')
    buttons = {}
    for action in ('start', 'stop', 'restart'):
        buttons[action] = ttk.Button(controls, text=action.capitalize(), command=lambda a=action: actions.submit(a))
        buttons[action].pack(side='left', padx=(0, 5), pady=4)
    ttk.Button(frame, text='Open logs', command=lambda: webbrowser.open((root / 'logs').as_uri())).pack(fill='x', pady=3)
    startup_value = tk.BooleanVar()
    startup_button = ttk.Checkbutton(frame, text='Start at login', variable=startup_value,
                                    command=lambda: actions.submit(None, startup=startup_value.get()))
    startup_button.pack(anchor='w', pady=5)
    ttk.Label(frame, text='Closing the browser keeps monitoring running.', wraplength=430).pack(anchor='w', pady=6)
    quit_button = ttk.Button(frame, text='Quit FlintEye', command=lambda: actions.submit('quit'))
    quit_button.pack(fill='x', pady=3)
    force_button = ttk.Button(frame, text='Force quit (recordings may be incomplete)',
                              command=lambda: actions.submit('quit', force=True) if _confirm_force_quit() else None)
    def close_window():
        if messagebox.askyesno('Quit FlintEye?', 'Stop monitoring, finish recordings, and quit FlintEye?', default='no'):
            actions.submit('quit')
    window.protocol('WM_DELETE_WINDOW', close_window)
    icon = None
    commands = queue.SimpleQueue()
    if sys.platform.startswith('linux') and os.environ.get('DISPLAY'):
        # Xorg supports a default click action but no menus. Only use it if a
        # system tray manager exists; the small controller remains available.
        try:
            from Xlib.display import Display
            display = Display()
            owner = display.get_selection_owner(display.intern_atom('_NET_SYSTEM_TRAY_S' + str(display.get_default_screen())))
            display.close()
            if owner:
                import pystray
                icon = pystray.Icon('FlintEye', tray_image(controller.status()), 'FlintEye', menu=pystray.Menu(
                    pystray.MenuItem('Open controls', lambda: commands.put('show'), default=True)))
                icon.run_detached()
        except Exception:
            logger.info('Desktop tray unavailable; using the control window', exc_info=True)
    def refresh():
        if server.should_exit:
            window.destroy()
            return
        while not commands.empty():
            commands.get()
            window.deiconify()
            window.lift()
        status = controller.status()
        state.configure(text=status_text(status), foreground=COLORS[status['color']])
        message.configure(text=actions.message or status['message'])
        enabled = not actions.busy
        buttons['start'].configure(state='normal' if enabled and not status['desired_running'] and status['phase'] != 'finalizing' else 'disabled')
        buttons['stop'].configure(state='normal' if enabled and (status['desired_running'] or status['phase'] == 'finalizing') else 'disabled')
        buttons['restart'].configure(state='normal' if enabled and status['desired_running'] and status['phase'] != 'finalizing' else 'disabled')
        startup = autostart_status()
        startup_value.set(startup['enabled'])
        startup_button.configure(state='normal' if enabled and startup['available'] else 'disabled')
        quit_button.configure(state='normal' if enabled else 'disabled')
        if (status['phase'] == 'finalizing' or status.get('previous_stop_unknown')) and enabled:
            force_button.pack(fill='x', pady=3)
        else:
            force_button.pack_forget()
        if icon:
            icon.icon = tray_image(status)
            icon.title = 'FlintEye — ' + status_text(status)
        window.after(500, refresh)
    window.after(0, refresh)
    try:
        window.mainloop()
    finally:
        if icon:
            icon.stop()


def run_desktop(url, server, root: Path, controller, open_browser):
    actions = DesktopActions(controller, server)
    done = threading.Event()
    sleeper = threading.Thread(target=_sleep_watcher, args=(controller, done), name='desktop-sleep', daemon=True)
    sleeper.start()
    try:
        if sys.platform.startswith('linux'):
            _run_control_window(url, server, root, controller, actions, open_browser)
        else:
            _run_tray(server, root, controller, actions, open_browser)
    finally:
        done.set()
        sleeper.join(timeout=5)
