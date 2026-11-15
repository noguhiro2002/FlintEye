"""Regressions observed in the 2026-11-15 physical-device review."""
from contextlib import contextmanager
from email.message import Message
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'packaging'))
import collect_licenses
import verify_macos
from flinteye_app.orchestrator_models import UiConfig


class LicenseCollectionTests(unittest.TestCase):
    def test_notices_survive_but_copying_test_binaries_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ['pkg.dist-info/licenses/LICENSE', 'pkg.dist-info/licenses/nested/MIT.txt',
                     'COPYING.LESSER', 'PyObjCTest/copying.cpython-314-darwin.so',
                     'PyObjCTest/copying.cpython-314-darwin.so.dSYM/Contents/Resources/DWARF/copying.cpython-314-darwin.so']
            for name in names:
                file = root/name; file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'\xcf\xfa\xed\xfe\0binary' if name.endswith('.so') else b'License notice\n')
            metadata = Message(); metadata['Name'] = 'pyobjc-core'; metadata['License-Expression'] = 'MIT'
            dist = SimpleNamespace(metadata=metadata, version='test', files=list(map(Path,names)), locate_file=lambda item: root/item)
            destination = root/'licenses/runtime'; destination.mkdir(parents=True)
            (destination/'stale.so').write_bytes(b'old wrong file')
            (root/'licenses/vendor-LICENSE').write_text('retain')
            with patch.object(collect_licenses.importlib.metadata, 'distributions', return_value=[dist]), \
                 patch.object(collect_licenses, 'ROOT', root), patch('sys.base_prefix', str(root)), \
                 patch('sys.platform','darwin'), patch('tkinter.Tcl', side_effect=RuntimeError):
                collect_licenses.collect(destination)
            collected = [file for file in destination.rglob('*') if file.is_file()]
            self.assertEqual(sum(file.name != 'inventory.json' for file in collected), 3)
            self.assertFalse(any('PyObjCTest' in str(file) or file.name == 'stale.so' for file in collected))
            self.assertEqual((root/'licenses/vendor-LICENSE').read_text(), 'retain')
            self.assertEqual(json.loads((destination/'inventory.json').read_text())[0]['name'], 'pyobjc-core')

    def test_bad_signature_is_fatal_but_untrusted_preview_is_reported(self):
        with patch.object(verify_macos.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'codesign')):
            with self.assertRaises(subprocess.CalledProcessError):
                verify_macos.verify_app(Path('FlintEye.app'))
        with tempfile.TemporaryDirectory() as tmp, patch.object(verify_macos.subprocess, 'run',
                return_value=SimpleNamespace(returncode=3, stdout='', stderr='rejected')):
            receipt=Path(tmp)/'result.json'
            verify_macos.assess_gatekeeper(Path('FlintEye.app'), receipt)
            report=json.loads(receipt.read_text())
            self.assertFalse(report['gatekeeper_accepted'])
            self.assertFalse(report['notarized'])


class BootstrapTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'The README shell bootstrap is for macOS/Linux')
    def test_readme_download_failure_never_executes_partial_script_and_returns_failure(self):
        command=next(line for line in (ROOT/'README.md').read_text().splitlines() if line.startswith("bash -c 'set -e; script="))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); fake=root/'curl'
            fake.write_text('#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\nprintf "touch \\\"%s\\\"\\nexit %s\\n" "$MARKER" "$SCRIPT_EXIT" > "$2"\nexit "$DOWNLOAD_EXIT"\n')
            fake.chmod(0o755)
            for download, script, expected in [(0,0,0), (22,0,22), (7,0,7), (18,0,18), (0,23,23)]:
                marker=root/'ran'; marker.unlink(missing_ok=True)
                env={**os.environ, 'PATH': str(root)+os.pathsep+os.environ['PATH'], 'TMPDIR':str(root),
                     'MARKER':str(marker), 'DOWNLOAD_EXIT':str(download), 'SCRIPT_EXIT':str(script)}
                result=subprocess.run(['bash','-c',command],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertEqual(marker.exists(),download==0)
                self.assertEqual(list(root.glob('tmp.*')),[])
            result=subprocess.run(['bash',str(ROOT/'packaging/install.sh'),'--version','not-a-version'],capture_output=True)
            self.assertNotEqual(result.returncode,0)

    def test_legacy_display_labels_are_normalized_but_custom_branding_is_preserved(self):
        self.assertEqual(UiConfig(app_title='Unified Camera Orchestrator', sidebar_title='Orchestrator UI').app_title, 'FlintEye')
        self.assertEqual(UiConfig(app_title='Lab cameras').app_title,'Lab cameras')

    def test_disable_macos_autostart_retains_profile_and_is_not_recreated(self):
        from flinteye_app import cli
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); profile=home/'profile'; profile.mkdir()
            (profile/'runtime.json').write_text('retain settings')
            agent=home/'Library/LaunchAgents/community.flinteye.plist'; agent.parent.mkdir(parents=True)
            with patch('sys.platform','darwin'), patch.object(Path,'home',return_value=home), patch('os.getuid',return_value=1000,create=True), \
                 patch.object(cli,'data_dir',return_value=profile), patch.object(cli.subprocess,'run') as run:
                cli.enable_autostart(); cli.disable_autostart(); cli.enable_autostart()
            self.assertFalse(agent.exists())
            self.assertTrue((profile/'autostart-disabled').exists())
            self.assertEqual((profile/'runtime.json').read_text(),'retain settings')
            self.assertIn('bootout',run.call_args.args[0])

    def test_media_update_stops_publishers_before_reconfiguring_recorder(self):
        from flinteye_app.orchestrator_supervisor import OrchestratorSupervisor
        import threading
        supervisor=OrchestratorSupervisor.__new__(OrchestratorSupervisor)
        supervisor._lock=threading.RLock()
        supervisor._processes={key:SimpleNamespace(key=key) for key in ['mediamtx:direct','camera:a','multiview','multiview-input:a','multiview-buffer:a']}
        events=[]
        with patch.object(supervisor,'_stop_process',side_effect=lambda process:events.append(process.key)):
            with supervisor.media_update():
                events.append('apply-media-config')
        self.assertEqual(events,['camera:a','multiview','multiview-input:a','multiview-buffer:a','apply-media-config'])

    def test_whole_stack_restart_starts_publishers_only_once(self):
        from flinteye_app.orchestrator_supervisor import OrchestratorSupervisor
        from flinteye_app.orchestrator_models import RuntimeConfig
        from unittest.mock import Mock
        import threading
        supervisor=OrchestratorSupervisor.__new__(OrchestratorSupervisor)
        supervisor._lock=threading.RLock(); supervisor._processes={}
        supervisor._monitoring_enabled = True
        supervisor.reconcile=Mock()
        with patch.object(supervisor,'_restart_mediamtx',return_value={'ok':True}):
            for mode in ['direct','external']:
                config=RuntimeConfig(mediamtx={'control_mode':mode})
                supervisor.reconcile.reset_mock()
                supervisor.restart_all(config)
                self.assertEqual(supervisor.reconcile.call_count,1)
                self.assertEqual(supervisor.reconcile.call_args.kwargs, {'force_restart':True} if mode=='external' else {})

    def test_autostart_does_not_take_over_another_profile_or_installation(self):
        from flinteye_app import cli
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); first=home/'profile-a'; second=home/'profile-b'
            with patch('sys.platform','linux'), patch.object(Path,'home',return_value=home), \
                 patch.object(cli,'data_dir',return_value=first), patch.object(cli,'launch_command',return_value=['/first/FlintEye']):
                self.assertTrue(cli.enable_autostart())
                registration=cli._read_startup()
            for profile, command in [(second,['/first/FlintEye']),(first,['/second/FlintEye'])]:
                with patch('sys.platform','linux'), patch.object(Path,'home',return_value=home), \
                     patch.object(cli,'data_dir',return_value=profile), patch.object(cli,'launch_command',return_value=command):
                    self.assertFalse(cli.enable_autostart())
                    cli.disable_autostart()
                    self.assertEqual(cli._read_startup(),registration)
            with patch('sys.platform','linux'), patch.object(Path,'home',return_value=home):
                (cli.default_data_dir()/'autostart-owner.json').write_text('{invalid')
                self.assertFalse(cli._owns_startup(registration))

    def test_existing_instance_reopens_active_port_not_pending_saved_port(self):
        from flinteye_app.instance_control import InstanceControl, active_listener_port
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); control=InstanceControl(root,lambda:None,port=18765)
            try:
                self.assertEqual(active_listener_port(root,18080),18765)
                self.assertEqual(active_listener_port(root,19000),18765)
            finally: control.close()
            self.assertEqual(active_listener_port(root,19000),19000)

    def test_legacy_mac_bundle_id_requires_explicit_removal(self):
        from flinteye_app import cli
        import plistlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            registration=plistlib.dumps({'ProgramArguments':['/usr/bin/open','-b','community.flinteye','--args','--background']}).decode()
            with patch('sys.platform','darwin'), patch.object(cli,'data_dir',return_value=root), \
                 patch.object(cli,'default_data_dir',return_value=root):
                self.assertFalse(cli._owns_startup(registration))
                self.assertTrue(cli._owns_startup(registration,allow_legacy_bundle_id=True))

    def test_custom_profile_can_run_when_windows_discovery_index_is_unwritable(self):
        from flinteye_app.instance_control import InstanceControl
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); blocked=root/'blocked'; blocked.write_text('not a directory')
            with patch('sys.platform','win32'), patch('sys.frozen',True,create=True), \
                 patch('flinteye_app.flinteye_runtime.default_data_dir',return_value=blocked), self.assertLogs('flinteye_app.instance_control',level='WARNING'):
                control=InstanceControl(root,lambda:None)
            try:
                self.assertTrue(control.path.exists())
                self.assertIsNone(control.index)
            finally: control.close()

    def test_noop_media_update_does_not_interrupt_publishers(self):
        from flinteye_app.orchestrator_mediamtx_yaml import apply_mediamtx_yaml
        from flinteye_app.orchestrator_store import RuntimeStore
        from flinteye_app.cli import initialize
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runtime=initialize(root)
            store=RuntimeStore(env_file='',runtime_file=str(runtime),use_env=False)
            config=store.get_effective()
            apply_mediamtx_yaml(config,workspace_dir=tmp)
            callback=Mock()
            store.patch_runtime({'recording':{'show_previous':False,'playback_cache_delete_after':'1h'}})
            result=apply_mediamtx_yaml(store.get_effective(),workspace_dir=tmp,before_write=callback)
            self.assertFalse(result.changed)
            callback.assert_not_called()
