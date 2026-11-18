"""Keep native dialogs and the running application's icon consistent."""
import logging
import sys

from flinteye_app.flinteye_runtime import application_dir


def apply_application_icon(window=None) -> None:
    try:
        if sys.platform == 'darwin':
            import AppKit
            asset = application_dir() / 'images/icons/flinteye.icns'
            icon = AppKit.NSImage.alloc().initWithContentsOfFile_(str(asset))
            if icon is not None:
                AppKit.NSApplication.sharedApplication().setApplicationIconImage_(icon)
        elif window is not None:
            from PIL import Image, ImageTk
            image = ImageTk.PhotoImage(Image.open(application_dir() / 'images/icons/flinteye-symbol.png'), master=window)
            window.iconphoto(True, image)
            window._flinteye_icon = image
    except (ImportError, OSError, RuntimeError):
        logging.getLogger(__name__).exception('Could not set the FlintEye application icon')


def create_window(title: str):
    import tkinter as tk
    window = tk.Tk()
    window.title(title)
    # Aqua/Tk may replace the Dock image when its first window is created.
    apply_application_icon(window)
    return window
