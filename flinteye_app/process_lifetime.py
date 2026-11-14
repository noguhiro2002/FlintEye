"""Own only FlintEye's explicitly launched background processes."""
from __future__ import annotations

import subprocess
import logging
import sys
import threading
import time

_lock = threading.RLock()
_children = set()
_stopping = False
_job = None
logger = logging.getLogger(__name__)


class WindowsJob:
    """Put suspended media children in a kill-on-close job before they run.

    The app itself and browsers opened by the shell are deliberately not members.
    Windows also closes this non-inherited handle after a parent process crash.
    """
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.api = k = c.WinDLL('kernel32', use_last_error=True)
        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                        ('min_ws', c.c_size_t), ('max_ws', c.c_size_t), ('process_limit', w.DWORD),
                        ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', c.c_uint64 * 6),
                        ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                        ('peak_process_memory', c.c_size_t), ('peak_job_memory', c.c_size_t)]
        class ThreadEntry(c.Structure):
            _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('tid', w.DWORD),
                        ('pid', w.DWORD), ('base_priority', w.LONG), ('delta_priority', w.LONG), ('flags', w.DWORD)]
        self.ThreadEntry = ThreadEntry
        signatures = {
            'CreateJobObjectW': ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            'SetInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
            'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
            'CreateToolhelp32Snapshot': ([w.DWORD, w.DWORD], w.HANDLE),
            'Thread32First': ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            'Thread32Next': ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            'OpenThread': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'ResumeThread': ([w.HANDLE], w.DWORD),
            'CloseHandle': ([w.HANDLE], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(k, name)
            function.argtypes, function.restype = arguments, result
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def attach_and_resume(self, process):
        c, k = self.c, self.api
        if not k.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise c.WinError(c.get_last_error())
        snapshot = k.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = self.ThreadEntry()
            entry.size = c.sizeof(entry)
            more = k.Thread32First(snapshot, c.byref(entry))
            while more:
                if entry.pid == process.pid:
                    thread = k.OpenThread(2, False, entry.tid)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise c.WinError(c.get_last_error())
                    try:
                        if k.ResumeThread(thread) == 0xFFFFFFFF:
                            raise c.WinError(c.get_last_error())
                        return
                    finally:
                        k.CloseHandle(thread)
                more = k.Thread32Next(snapshot, c.byref(entry))
            raise OSError('Could not find suspended background process thread')
        finally:
            k.CloseHandle(snapshot)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def popen_background(*args, **kwargs):
    global _job
    with _lock:
        if _stopping:
            raise RuntimeError('FlintEye is shutting down; background launches are stopped')
        if sys.platform == 'win32':
            if _job is None:
                _job = WindowsJob()
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x08000004  # NO_WINDOW | SUSPENDED
        process = subprocess.Popen(*args, **kwargs)
        try:
            if sys.platform == 'win32':
                _job.attach_and_resume(process)
        except BaseException:
            process.kill()
            process.wait()
            raise
        # Reap finished direct children; a Windows job still owns descendants.
        _children.difference_update(child for child in tuple(_children) if child.poll() is not None)
        _children.add(process)
        return process


def run_background(*args, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('input and stdin cannot both be provided')
        kwargs['stdin'] = subprocess.PIPE
    if capture_output:
        if 'stdout' in kwargs or 'stderr' in kwargs:
            raise ValueError('capture_output cannot be combined with stdout/stderr')
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process = popen_background(*args, **kwargs)
    try:
        with process:
            try:
                stdout, stderr = process.communicate(input, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(process.args, timeout, output=stdout, stderr=stderr) from exc
            except BaseException:
                process.kill()
                process.wait()
                raise
            if check and process.returncode:
                raise subprocess.CalledProcessError(process.returncode, process.args, output=stdout, stderr=stderr)
            return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    finally:
        with _lock:
            _children.discard(process)


def stop_background_processes():
    global _stopping, _job
    with _lock:
        _stopping = True
        children = tuple(_children)
        if _job is not None:
            _job.close()
            _job = None
        for process in children:
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                except OSError:
                    logger.exception('Could not terminate background process %s', process.pid)
    deadline = time.monotonic() + 5
    for process in children:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                logger.exception('Could not reap background process %s', process.pid)
    with _lock:
        _children.clear()
