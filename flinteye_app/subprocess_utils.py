"""Background media processes without console popups on Windows."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import TextIO


def background_process_options(*, new_process_group: bool = False) -> dict[str, int]:
    # Capturing stdout/stderr alone does not suppress a console launched by a
    # windowed parent. Keep process-tree termination and pipe redirection intact.
    if sys.platform != 'win32':
        return {}
    flags = subprocess.CREATE_NO_WINDOW
    if new_process_group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return {'creationflags': flags}


def _redirected_windows_stream(name: str) -> TextIO | None:
    """Recover a parent's redirected pipe/file in a PyInstaller windowed child.

    The windowed bootloader leaves Python's standard streams as None even when
    the supervisor supplied OS handles. Never attach or allocate a console.
    Duplicate the handle so closing the Python stream cannot close the original.
    """
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                      ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                      wintypes.BOOL, wintypes.DWORD]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.GetStdHandle({'stdin': -10, 'stdout': -11, 'stderr': -12}[name])
    if not handle or handle == ctypes.c_void_p(-1).value:
        return None
    if kernel.GetFileType(handle) not in (1, 3):  # FILE_TYPE_DISK / FILE_TYPE_PIPE
        return None
    process = kernel.GetCurrentProcess()
    duplicate = wintypes.HANDLE()
    if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
        raise ctypes.WinError(ctypes.get_last_error())
    reading = name == 'stdin'
    try:
        descriptor = msvcrt.open_osfhandle(duplicate.value, os.O_RDONLY if reading else os.O_WRONLY)
    except OSError:
        kernel.CloseHandle(duplicate)
        raise
    try:
        return os.fdopen(descriptor, 'r' if reading else 'w', buffering=-1 if reading else 1)
    except Exception:
        os.close(descriptor)
        raise


def ensure_standard_streams() -> None:
    for name in ('stdin', 'stdout', 'stderr'):
        if getattr(sys, name) is not None:
            continue
        stream = _redirected_windows_stream(name) if sys.platform == 'win32' else None
        if stream is None:
            stream = open(os.devnull, 'r' if name == 'stdin' else 'w')
        setattr(sys, name, stream)
