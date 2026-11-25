import contextlib
import io
import os
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

import yaml

from tools import verify_before_push as verify


class VerificationContractTests(unittest.TestCase):
    def test_ci_runs_the_same_required_groups_as_the_local_gate(self):
        workflow = yaml.load((verify.ROOT / ".github/workflows/check.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertTrue({"push", "pull_request", "workflow_dispatch", "workflow_call"} <= workflow["on"].keys())
        job = workflow["jobs"]["tests"]
        self.assertNotIn("if", job)
        self.assertNotEqual(job.get("continue-on-error"), "true")
        steps = job["steps"]
        ci_groups = []
        for step in steps:
            invocation = [
                line.strip() for line in step.get("run", "").splitlines()
                if "tools/verify_before_push.py" in line
            ]
            if invocation:
                self.assertNotIn("if", step)
                self.assertNotEqual(step.get("continue-on-error"), "true")
                self.assertNotIn("set +e", step["run"])
                self.assertEqual(len(invocation), 1)
                group = re.fullmatch(r"python tools/verify_before_push\.py --group ([\w-]+)", invocation[0])
                self.assertIsNotNone(group, f"CI must propagate the result of {invocation[0]}")
                ci_groups.append(group[1])
        required = ["backend", "documentation", "frontend", "settings", "browsers", "dependency-audit", "containers"]
        self.assertEqual(ci_groups, required)
        self.assertEqual(list(verify.GROUPS), required)
        release = yaml.load((verify.ROOT / ".github/workflows/build-release.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertTrue(any(job.get("uses") == "./.github/workflows/check.yml" for job in release["jobs"].values()))
        self.assertIn("packaging/LinuxBuilder.Dockerfile", release["on"]["push"]["paths"])

    def test_default_gate_executes_real_checks_not_only_inventory(self):
        commands = []

        def capture(*command, **kwargs):
            commands.append((command, kwargs.get("cwd"), (kwargs.get("env") or {}).get("FLINTEYE_BROWSER"),
                             Path(kwargs["stdin"].name).name if kwargs.get("stdin") else None))

        with patch.object(verify, "run", side_effect=capture), patch.object(verify, "git_output", return_value=b"commit"), \
             patch.dict(os.environ, {"FLINTEYE_VENDOR_CACHE": ""}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(verify.main([]), 0)

        calls = [command for command, _, _, _ in commands]
        self.assertIn((verify.sys.executable, "tools/audit_api_coverage.py", "--require-all-operations",
                       "--require-permitted-behavior", "--output", "dist/api-coverage-audit"), calls)
        self.assertIn((verify.sys.executable, "packaging/check_docs.py"), calls)
        for script in ("install.sh", "build_vendor.sh", "smoke_bundle.sh"):
            self.assertIn(("bash", "-n", f"packaging/{script}"), calls)
        self.assertIn((("npm", "test"), verify.FRONTEND, "chromium", None), commands)
        self.assertIn(("node", "tests/settings-inventory.mjs"), calls)
        self.assertIn((verify.sys.executable, "packaging/qa_settings.py", "dist/settings-coverage"), calls)
        for engine in ("firefox", "webkit"):
            for test in ("monitoring", "setup", "recordings", "config-revision", "dialog", "navigation", "preview10"):
                self.assertIn((("node", f"tests/{test}.mjs"), verify.FRONTEND, engine, None), commands)
        self.assertIn(("npm", "run", "audit"), calls)
        self.assertIn(("docker", "build", "--build-arg", "FLINTEYE_REVISION=commit", "-t", "flinteye:check", "."), calls)
        self.assertEqual(
            [source for command, _, _, source in commands if command[:2] == ("docker", "run")],
            ["smoke_container.py", "smoke_private_input.py", "smoke_storage_faults.py"],
        )
        self.assertTrue(any("packaging/smoke_compose.py" in command for command in calls))

    def test_failure_or_missing_tool_keeps_gate_red_and_reports_pending(self):
        for error in (subprocess.CalledProcessError(9, "backend"), FileNotFoundError("missing required tool")):
            with self.subTest(error=error), patch.object(verify, "run", side_effect=error) as run, \
                 contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(verify.main([]), 1)
                self.assertEqual(run.call_count, 1)
                self.assertIn("backend failed", stderr.getvalue())
                self.assertIn("Pending groups: documentation", stderr.getvalue())
                self.assertNotIn("passed", stdout.getvalue())

    def test_targeted_rerun_does_not_claim_full_verification(self):
        with patch.object(verify, "check_group") as group, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(verify.main(["--group", "settings"]), 0)
            group.assert_called_once_with("settings")
            self.assertIn("Targeted check", output.getvalue())
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            verify.main(["--group", "unrecognized"])
        self.assertEqual(raised.exception.code, 2)

    def test_vendor_cache_keeps_the_same_container_tests(self):
        with patch.object(verify, "run") as run, patch.object(verify, "git_output", return_value=b"commit"), \
             patch.dict(os.environ, {"FLINTEYE_VENDOR_CACHE": "/verified-downloads"}):
            verify.check_containers()
        self.assertEqual(run.call_args_list[0].args[:4],
                         ("docker", "build", "--build-context", "vendor-downloads=/verified-downloads"))
        self.assertEqual(len(run.call_args_list), 5)

    def test_frontend_build_cannot_silently_modify_tracked_sources(self):
        with patch.object(verify, "run") as run, patch.object(verify, "git_output", side_effect=[b"before", b"after"]):
            with self.assertRaisesRegex(ValueError, "modified tracked frontend"):
                verify.check_frontend()
            run.assert_called_once_with("npm", "run", "build", cwd=verify.FRONTEND)
