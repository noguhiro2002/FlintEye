"""CI download recovery changes only the regional Ubuntu URI."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ci_apt', Path(__file__).resolve().parents[1]/'packaging/ci_apt.py')
ci_apt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_apt)


class MirrorTests(unittest.TestCase):
    def test_regional_mirror_is_replaced_without_changing_trust_or_suites(self):
        value = ('Types: deb\nURIs: http://us-east-2.ec2.archive.ubuntu.com/ubuntu/\n'
                 'Suites: noble noble-updates\nComponents: main universe\n'
                 'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n')
        self.assertEqual(ci_apt.rewrite_sources(value), value.replace(
            'http://us-east-2.ec2.archive.ubuntu.com/ubuntu/', 'https://archive.ubuntu.com/ubuntu/'))
        untouched = 'URIs: http://ports.ubuntu.com/ubuntu-ports\ndeb https://packages.microsoft.com/repos/code stable main\n'
        self.assertEqual(ci_apt.rewrite_sources(untouched), untouched)

    def test_no_system_changes_outside_github_actions(self):
        with patch.dict('os.environ', {'GITHUB_ACTIONS': 'false'}):
            with self.assertRaises(SystemExit): ci_apt.main()


if __name__ == '__main__': unittest.main()
