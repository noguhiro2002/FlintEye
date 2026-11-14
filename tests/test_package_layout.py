"""Exercise source dispatch and resource discovery outside the checkout directory."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from flinteye_app._version import VERSION
from flinteye_app.cli import WORKERS
from flinteye_app.flinteye_runtime import application_dir, worker_command
from flinteye_app.orchestrator_supervisor import _protected_worker_command

ROOT = Path(__file__).resolve().parents[1]


class LayoutTests(unittest.TestCase):
    def test_source_launcher_and_every_worker_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory(prefix='FlintEye unrelated cwd ') as cwd:
            env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH'}
            result = subprocess.run([sys.executable,str(ROOT/'flinteye.py'),'--version'],cwd=cwd,env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),VERSION)
            for worker in sorted(WORKERS):
                with self.subTest(worker=worker):
                    result=subprocess.run([*worker_command(worker),'--help'],cwd=cwd,env=env,capture_output=True,text=True,timeout=20)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('usage:',result.stdout.lower())

    def test_source_and_frozen_resource_roots(self):
        self.assertEqual(application_dir(),ROOT)
        with tempfile.TemporaryDirectory() as directory, patch('sys._MEIPASS',directory,create=True), patch('sys.frozen',True,create=True):
            self.assertEqual(application_dir(),Path(directory))
            self.assertEqual(worker_command('uvc_to_rtsp'),[sys.executable,'--worker','uvc_to_rtsp'])

    def test_relocated_worker_still_receives_credentials_only_over_stdin(self):
        for frozen in (False,True):
            for name in ('ip_camera_to_rtsp','multiview_input_to_rtsp'):
                with self.subTest(frozen=frozen,worker=name),patch('sys.frozen',frozen,create=True):
                    url='rtsp://user:private-camera-password@192.0.2.10/live'
                    safe,secrets=_protected_worker_command([*worker_command(name),'--source-url',url,'--onvif-password','private-onvif-password'])
                    self.assertNotIn('private-camera-password',' '.join(safe))
                    self.assertNotIn('private-onvif-password',' '.join(safe))
                    self.assertIn('--secret-stdin',safe)
                    self.assertEqual(secrets['source_url'],url)
                    self.assertEqual(secrets['onvif_password'],'private-onvif-password')

    @unittest.skipUnless((ROOT/'frontend/dist/index.html').exists(),'Build frontend before UI smoke test')
    def test_headless_ui_and_initial_setup_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory(prefix='FlintEye source smoke ') as directory:
            directory=Path(directory)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
            with (directory/'server.log').open('w+') as log:
                process=subprocess.Popen([sys.executable,str(ROOT/'flinteye.py'),'--headless','--port',str(port),'--data-dir',str(directory/'data')],cwd=directory,stdout=log,stderr=log)
                try:
                    for _ in range(100):
                        try:
                            with urlopen(f'http://127.0.0.1:{port}/',timeout=1) as response:
                                html=response.read().decode();break
                        except (URLError,TimeoutError):
                            if process.poll() is not None:
                                log.seek(0); self.fail(log.read())
                            time.sleep(.1)
                    else:
                        self.fail('Source launcher never served the UI')
                    self.assertIn('<!doctype html>',html.lower())
                    self.assertTrue((directory/'data/setup-token').is_file())
                    with self.assertRaises(HTTPError) as error:
                        urlopen(f'http://127.0.0.1:{port}/api/v1/config/effective',timeout=3)
                    self.assertIn(error.exception.code,(401,503))
                    error.exception.close()
                finally:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':unittest.main()
