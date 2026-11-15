"""Desktop lifetime and sleep inhibition. Recording continues after closing the browser."""
from __future__ import annotations
from contextlib import contextmanager, nullcontext
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import webbrowser


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
    try: yield
    finally:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        if process:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()


def run_desktop(url, server, root: Path):
    if sys.platform.startswith('linux'):
        # A control window also works on desktops without an AppIndicator extension.
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.title('FlintEye — monitoring')
        tk.Label(window, text='FlintEye is monitoring.\nClosing the browser does not stop recording.', padx=24, pady=18).pack()
        tk.Button(window, text='Open FlintEye', command=lambda: webbrowser.open(url)).pack(pady=8)
        def stop_window():
            if messagebox.askyesno('Stop monitoring?', 'Stop recording and quit FlintEye?'):
                server.should_exit = True
                window.destroy()
        tk.Button(window, text='Stop monitoring and quit', command=stop_window).pack(pady=12)
        window.protocol('WM_DELETE_WINDOW', stop_window)
        def check_shutdown():
            if server.should_exit:
                window.destroy()
            else:
                window.after(200, check_shutdown)
        window.after(200, check_shutdown)
        with inhibit_sleep(): window.mainloop()
        return
    import pystray
    from PIL import Image, ImageDraw
    icon_image = Image.new('RGB', (64, 64), '#173647')
    ImageDraw.Draw(icon_image).ellipse((12, 18, 52, 46), fill='#57d6aa')
    def stop(icon, item):
        # Explicit action; closing the browser never stops recording.
        server.should_exit = True
        icon.stop()
    def prepare_removal(icon, item):
        from flinteye_app.cli import disable_autostart
        disable_autostart()
        stop(icon, item)
    icon = pystray.Icon('FlintEye', icon_image, 'FlintEye — monitoring', menu=pystray.Menu(
        pystray.MenuItem('Open FlintEye', lambda: webbrowser.open(url), default=True),
        pystray.MenuItem('Open logs', lambda: webbrowser.open((root / 'logs').as_uri())),
        pystray.MenuItem('Disable start at login and quit', prepare_removal),
        pystray.MenuItem('Stop monitoring and quit', stop)))
    watcher_done = threading.Event()
    def ready(icon):
        icon.visible = True
        def check_shutdown():
            while not watcher_done.wait(.2):
                if server.should_exit:
                    icon.stop()
                    return
        threading.Thread(target=check_shutdown, name='flinteye-tray-stop', daemon=True).start()
    try:
        termination = nullcontext()
        if sys.platform == 'darwin':
            from flinteye_app.macos_lifecycle import graceful_application_quit
            termination = graceful_application_quit(icon, server)
        with inhibit_sleep(), termination:
            icon.run(setup=ready)
    finally:
        watcher_done.set()
