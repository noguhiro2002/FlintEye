"""Exercise actual child processes; do not touch real cameras or user profiles."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, call, patch

from flinteye_app.instance_control import InstanceControl, request_local_browser

ROOT = Path(__file__).resolve().parents[1]


class ProcessLifetimeTests(unittest.TestCase):
    def test_browser_address_uses_live_binding_and_rejects_wildcard_destinations(self):
        from flinteye_app.instance_control import active_listener_url, browser_url
        self.assertEqual(browser_url('0.0.0.0', 18080), 'http://127.0.0.1:18080')
        self.assertEqual(browser_url('::', 18080), 'http://[::1]:18080')
        self.assertEqual(browser_url('192.168.1.10', 18081), 'http://192.168.1.10:18081')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'instance-control.json').write_text(json.dumps({'url': 'http://192.168.1.10:18081'}))
            self.assertEqual(active_listener_url(root, 'http://127.0.0.1:18080'), 'http://192.168.1.10:18081')
    def test_failed_normal_quit_keeps_control_available_for_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempts = []
            def stop():
                attempts.append(True)
                return len(attempts) > 1
            control = InstanceControl(root, stop)
            try:
                for expected in (1, 2):
                    (root/'stop-request.json').write_text(json.dumps({'token': control.token}))
                    for _ in range(40):
                        if len(attempts) == expected: break
                        time.sleep(.05)
                    self.assertEqual(len(attempts), expected)
            finally: control.close()
    def isolated(self, script):
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_shutdown_reaps_owned_children_and_keeps_unrelated_process(self):
        result = self.isolated('''
import subprocess, sys
from flinteye_app.process_lifetime import popen_background, stop_background_processes
command = [sys.executable, '-c', 'import time; time.sleep(60)']
unrelated = subprocess.Popen(command)
try:
    owned = popen_background(command)
    stop_background_processes()
    assert owned.poll() is not None
    assert unrelated.poll() is None
    try: popen_background(command)
    except RuntimeError: pass
    else: raise AssertionError('launch after shutdown')
    stop_background_processes()
finally:
    unrelated.kill(); unrelated.wait()
print('owned stopped; unrelated preserved')
''')
        self.assertIn('unrelated preserved', result.stdout)

    def test_run_keeps_input_output_exit_codes_and_timeout_cleanup(self):
        self.isolated('''
import subprocess, sys
from flinteye_app.process_lifetime import run_background, stop_background_processes
p = run_background([sys.executable, '-c', 'import sys; print(sys.stdin.read()); print("error",file=sys.stderr)'], input='private', capture_output=True, text=True)
assert p.stdout.strip() == 'private' and p.stderr.strip() == 'error'
try: run_background([sys.executable, '-c', 'raise SystemExit(3)'],check=True)
except subprocess.CalledProcessError as e: assert e.returncode == 3
else: raise AssertionError('missing exit failure')
try: run_background([sys.executable, '-c', 'import time; print("ready",flush=True); time.sleep(60)'],capture_output=True,text=True,timeout=1)
except subprocess.TimeoutExpired as e: assert 'ready' in e.output
else: raise AssertionError('missing timeout')
stop_background_processes()
''')

    def test_owner_request_requires_token_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stopped = threading.Event()
            control = InstanceControl(root, stopped.set)
            try:
                request = root / 'stop-request.json'
                request.write_text(json.dumps({'token':'wrong'}))
                self.assertFalse(stopped.wait(.4))
                request.write_text(json.dumps({'token':control.token}), encoding='utf-8-sig')
                self.assertTrue(stopped.wait(3))
            finally:
                control.close()
            self.assertFalse((root/'instance-control.json').exists())
            self.assertFalse(request.exists())

    def test_duplicate_launch_opens_the_ready_owner_browser_without_stopping_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            opened = threading.Event()
            stopped = threading.Event()
            control = InstanceControl(root, stopped.set, open_browser=opened.set)
            try:
                request = root / 'open-browser-request.json'
                request.write_text(json.dumps({'token': 'wrong'}))
                control.write_connection(ready=True)
                self.assertFalse(opened.wait(.4))
                self.assertTrue(request_local_browser(root))
                self.assertTrue(opened.wait(3))
                self.assertFalse(stopped.is_set())
                self.assertFalse(request.exists())
            finally:
                control.close()
            self.assertFalse(request_local_browser(root))

    @unittest.skipIf(os.name == 'nt', 'POSIX process groups')
    def test_macos_stop_ignores_zombie_only_group_and_keeps_live_group_for_retry(self):
        from flinteye_app.orchestrator_supervisor import ManagedProcess, OrchestratorSupervisor
        supervisor = OrchestratorSupervisor.__new__(OrchestratorSupervisor)
        group_id = 1234
        for state in ('Z', 'S'):
            with self.subTest(state=state):
                process = Mock(pid=group_id)
                process.wait.return_value = -signal.SIGTERM
                process.poll.return_value = -signal.SIGTERM
                managed = ManagedProcess('camera:qa', 'camera', process=process, desired=True)
                snapshot = subprocess.CompletedProcess([], 0, stdout=f' 1234 {state}\n 2345 R\n')
                with (
                    patch('flinteye_app.orchestrator_supervisor.sys.platform', 'darwin'),
                    patch('flinteye_app.orchestrator_supervisor.os.killpg',
                          side_effect=[None, PermissionError(1, 'Operation not permitted')]) as kill,
                    patch('flinteye_app.orchestrator_supervisor.subprocess.run', return_value=snapshot),
                ):
                    if state == 'Z':
                        supervisor._stop_process(managed)
                        self.assertIsNone(managed.process)
                    else:
                        with self.assertRaises(PermissionError):
                            supervisor._stop_process(managed)
                        self.assertIs(managed.process, process)
                    self.assertFalse(managed.desired)
                    self.assertEqual(kill.call_args_list,
                                     [call(group_id, signal.SIGTERM), call(group_id, signal.SIGKILL)])

    @unittest.skipIf(os.name == 'nt', 'Requires the full API test environment')
    def test_desktop_quit_stops_children_even_with_open_stream_client(self):
        self.isolated('''
import asyncio, socket, sys, tempfile, time, urllib.request
from pathlib import Path
from starlette.responses import StreamingResponse
from flinteye_app import cli, flinteye_desktop
from flinteye_app.orchestrator_api import app
from flinteye_app.process_lifetime import popen_background
@app.get('/test-long-stream')
async def stream():
    async def chunks():
        yield b'ready\\n'
        await asyncio.sleep(60)
    return StreamingResponse(chunks())
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
children=[]; connections=[]
def desktop(url,server,root,monitoring,open_browser):
    children.append(popen_background([sys.executable,'-c','import time;time.sleep(60)']))
    connections.append(urllib.request.urlopen(url+'/test-long-stream',timeout=10))
    assert connections[0].readline()==b'ready\\n'
    server.should_exit=True
cli.desktop_available=lambda: True
cli.enable_autostart=lambda: None
flinteye_desktop.run_desktop=desktop
with tempfile.TemporaryDirectory() as tmp:
    sys.argv=['FlintEye','--background','--data-dir',tmp,'--port',str(port)]
    started=time.monotonic()
    assert cli.main()==0
    assert time.monotonic()-started<15
    assert children[0].poll() is not None
    assert not (Path(tmp)/'instance-control.json').exists()
    for connection in connections: connection.close()
''')

    @unittest.skipUnless(os.name == 'nt', 'Windows job ownership')
    def test_parent_crash_kills_nested_children_but_not_unrelated_process(self):
        self.isolated(r'''
import ctypes, os, subprocess, sys, tempfile, time
from pathlib import Path
from ctypes import wintypes as w
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; k.OpenProcess.restype=w.HANDLE
k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]; k.WaitForSingleObject.restype=w.DWORD
k.CloseHandle.argtypes=[w.HANDLE]
unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
try:
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'pids'
        # Nested worker also owns its FFmpeg-equivalent child in a nested job.
        worker='from flinteye_app.process_lifetime import popen_background; import os,sys,time; from pathlib import Path; p=popen_background([sys.executable,"-c","import time;time.sleep(60)"]); Path(sys.argv[1]).write_text(str(os.getpid())+" "+str(p.pid)); time.sleep(60)'
        parent='from flinteye_app.process_lifetime import popen_background; import os,sys,time; from pathlib import Path; p=popen_background([sys.executable,"-c",sys.argv[1],sys.argv[2]],stdout=-3,stderr=-3); deadline=time.monotonic()+10\nwhile not Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.05)\nos._exit(7)'
        result=subprocess.run([sys.executable,'-c',parent,worker,str(path)],timeout=15)
        assert result.returncode==7 and path.exists()
        for pid in map(int,path.read_text().split()):
            handle=k.OpenProcess(0x100000,False,pid)
            if handle:
                try: assert k.WaitForSingleObject(handle,5000)==0, 'orphan after parent crash'
                finally: k.CloseHandle(handle)
        assert unrelated.poll() is None
finally:
    unrelated.kill(); unrelated.wait()
''')

    @unittest.skipIf(os.name == 'nt', 'POSIX process groups')
    def test_exited_worker_does_not_leave_term_ignoring_child(self):
        self.isolated('''
import os, signal, subprocess, sys, tempfile, time
from pathlib import Path
from flinteye_app.orchestrator_supervisor import ManagedProcess, OrchestratorSupervisor
from flinteye_app.orchestrator_logging import LogManager
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary); (root/'logs').mkdir()
    child_script='import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'
    parent_script='import subprocess,sys; p=subprocess.Popen([sys.executable,"-c",sys.argv[1]],stdout=subprocess.PIPE,text=True); p.stdout.readline(); print(p.pid,flush=True)'
    leader=subprocess.Popen([sys.executable,'-c',parent_script,child_script],stdout=subprocess.PIPE,text=True,start_new_session=True)
    child_pid=int(leader.stdout.readline()); leader.wait(timeout=5)
    supervisor=OrchestratorSupervisor(workspace_dir=temporary,env_file='',log_manager=LogManager(workspace_dir=temporary))
    try:
        proc=ManagedProcess(key='camera:test',kind='camera',command=[])
        proc.process=leader
        supervisor._stop_process(proc)
        for _ in range(50):
            stat=Path('/proc')/str(child_pid)/'stat'
            try:
                if sys.platform.startswith('linux') and stat.read_text().split()[2]=='Z': break
                os.kill(child_pid,0)
            except (ProcessLookupError,FileNotFoundError): break
            time.sleep(.05)
        else: raise AssertionError('orphan is still running')
    finally:
        supervisor.shutdown()
        try: os.killpg(leader.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        leader.stdout.close()
''')


if __name__ == '__main__':
    unittest.main()
