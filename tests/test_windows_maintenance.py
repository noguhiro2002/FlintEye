"""Firewall lifecycle metadata, with no elevation or real Firewall access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flinteye_app import windows_maintenance as maintenance


class FirewallOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.global_root = self.root/'global'
        self.bundle = self.root/'program/_internal'
        self.bundle.mkdir(parents=True)
        self.profiles = [self.global_root, self.root/'custom profile']
        self.config = SimpleNamespace(network=SimpleNamespace(enabled=True,
            address='192.168.1.10', allowed_subnets=['192.168.1.0/24']), api=SimpleNamespace(port=18080))
        self.calls = []
        self.request_paths = []
        for name, value in (('_require_windows', None), ('application_dir', self.bundle),
                            ('default_data_dir', self.global_root)):
            context = patch.object(maintenance, name, return_value=value)
            context.start(); self.addCleanup(context.stop)
        runner = patch.object(maintenance.subprocess, 'run', side_effect=self.execute)
        self.runner = runner.start()
        self.addCleanup(runner.stop)

    def execute(self, command, **kwargs):
        request = Path(command[command.index('-Request')+1])
        payload = json.loads(request.read_text())
        self.request_paths.append(request)
        self.calls.append(payload)
        if payload['action'] == 'apply':
            self.assertTrue(maintenance._inventory(Path(payload['application']), payload['id']).is_file(),
                            'Ownership must exist before an elevated change begins')
        return SimpleNamespace(returncode=0)

    def receipt(self, root):
        return json.loads((root/'firewall-owner.json').read_text())

    def test_all_profiles_are_discoverable_and_other_installations_are_preserved(self):
        for root in self.profiles:
            maintenance.manage_firewall(root, self.config, 'apply')
        other = self.root/'other installation/_internal'
        other.mkdir(parents=True)
        foreign_profile = self.root/'foreign profile'
        with patch.object(maintenance, 'application_dir', return_value=other):
            maintenance.manage_firewall(foreign_profile, self.config, 'apply')
        self.assertEqual(len(maintenance._owned_inventory(maintenance._programs()[0])), 2)
        maintenance.remove_installation_firewall()
        self.assertEqual(self.calls[-1]['action'], 'remove-installation')
        for root in self.profiles:
            self.assertFalse(self.receipt(root)['applied'])
        self.assertTrue(self.receipt(foreign_profile)['applied'])
        self.assertEqual(len(list((maintenance._maintenance_dir()/'firewall-installations').glob('*.json'))), 1)
        self.assertEqual(len(self.request_paths), len(set(self.request_paths)))
        self.assertTrue(all(not path.exists() for path in self.request_paths))

    def test_failed_apply_remains_discoverable_without_leaking_request_files(self):
        root = self.profiles[1]
        def fail(command, **kwargs):
            self.execute(command, **kwargs)
            raise subprocess.CalledProcessError(1, command)
        self.runner.side_effect = fail
        with self.assertRaises(subprocess.CalledProcessError):
            maintenance.manage_firewall(root, self.config, 'apply')
        self.assertEqual(len(maintenance._owned_inventory(maintenance._programs()[0])), 1)
        self.assertFalse((root/'firewall-owner.json').exists())
        self.assertTrue(all(not path.exists() for path in self.request_paths))

    def test_deleted_profile_does_not_hide_rules_or_get_recreated(self):
        root = self.profiles[1]
        maintenance.manage_firewall(root, self.config, 'apply')
        shutil.rmtree(root)
        maintenance.remove_installation_firewall()
        self.assertFalse(root.exists())
        self.assertFalse(maintenance._owned_inventory(maintenance._programs()[0]))

    def test_default_data_deletion_does_not_erase_other_profile_ownership(self):
        for root in self.profiles:
            maintenance.manage_firewall(root, self.config, 'apply')
        shutil.rmtree(self.global_root)
        self.assertEqual(len(maintenance._owned_inventory(maintenance._programs()[0])), 2)
        maintenance.remove_installation_firewall()
        self.assertFalse(self.global_root.exists())
        self.assertFalse(self.receipt(self.profiles[1])['applied'])

    def test_cli_cleanup_does_not_initialize_or_lock_a_camera_profile(self):
        from flinteye_app import cli
        unused = self.root/'unused profile'
        with patch.object(cli.sys, 'argv', ['FlintEye', '--headless', '--data-dir', str(unused), '--remove-installation-firewall-rules']), \
             patch.object(cli, 'initialize') as initialize, \
             patch.object(maintenance, 'remove_installation_firewall') as remove, patch.dict(os.environ):
            self.assertEqual(cli.main(), 0)
            remove.assert_called_once_with()
            initialize.assert_not_called()
        self.assertFalse(unused.exists())

    def test_refused_removal_retains_inventory_and_receipts_for_retry(self):
        root = self.profiles[1]
        maintenance.manage_firewall(root, self.config, 'apply')
        self.runner.side_effect = subprocess.CalledProcessError(2, ['synthetic cancelled elevation'])
        with self.assertRaises(subprocess.CalledProcessError):
            maintenance.remove_installation_firewall()
        self.assertTrue(self.receipt(root)['applied'])
        self.assertEqual(len(maintenance._owned_inventory(maintenance._programs()[0])), 1)

    def test_profile_removal_does_not_forget_other_profiles(self):
        for root in self.profiles:
            maintenance.manage_firewall(root, self.config, 'apply')
        maintenance.manage_firewall(self.profiles[0], self.config, 'remove')
        self.assertFalse(self.receipt(self.profiles[0])['applied'])
        remaining = maintenance._owned_inventory(maintenance._programs()[0])
        self.assertEqual([record['profile'] for _, record in remaining], [str(self.profiles[1])])

    def test_concurrent_installation_operation_is_rejected_before_elevation(self):
        with maintenance._operation(maintenance._programs()[0]):
            with self.assertRaisesRegex(ValueError, 'in progress'):
                maintenance.manage_firewall(self.profiles[1], self.config, 'apply')
        self.runner.assert_not_called()

    def test_corrupt_inventory_stops_cleanup_before_elevation(self):
        root = self.profiles[1]
        maintenance.manage_firewall(root, self.config, 'apply')
        entry = maintenance._owned_inventory(maintenance._programs()[0])[0][0]
        entry.write_text('incomplete metadata')
        calls = len(self.calls)
        with self.assertRaises(ValueError):
            maintenance.remove_installation_firewall()
        self.assertEqual(len(self.calls), calls)
        self.assertTrue(self.receipt(root)['applied'])


if __name__ == '__main__':
    unittest.main()
