"""Evidence for installed-app checks; manual approval never means a passed GUI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import time

STAGES = ('install', 'integrity', 'os_launch', 'api_gui', 'quit', 'uninstall', 'retained_reinstall')
MANUAL_CASES = ('os-first-launch-approval', 'native-menus-and-permissions', 'physical-usb-and-lan')
BROWSER_CHECKS = {
    'browser-first-run-setup', 'real-api-build-identity-and-authentication',
    'GUI-register-two-real-synthetic-RTSP-sources-and-save', 'per-camera-audio-default-off-detection-enable-and-save',
    'all-six-main-screens', 'live-and-multiview-real-WebRTC-frame-progress',
    'recording-GUI-playback-and-download', 'viewer-login-and-real-API-write-denial',
    'GUI-stop-keeps-API-and-saved-settings-cannot-restart-monitoring', 'GUI-start-resumes-recording-before-normal-quit',
}
RETAINED_CHECKS = {'retained-administrator-login', 'real-api-build-identity-and-authentication',
                   'retained-config-audio-and-recording-inventory', 'all-six-main-screens'}


class Report:
    def __init__(self, output: Path, *, method: str, release: str, commit: str):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.data = {'schema': 1, 'release': release, 'commit': commit,
                     'platform': platform.system().lower(), 'cpu': platform.machine().lower(),
                     'runner': os.environ.get('FLINTEYE_QA_RUNNER', 'local'), 'os_version': platform.platform(),
                     'method': method, 'started_at': time.time(),
                     'stages': {name: {'status': 'not-run'} for name in STAGES},
                     'manual': {name: {'status': 'pending'} for name in MANUAL_CASES}}
        if os.environ.get('FLINTEYE_QA_DIAGNOSTIC') == '1':
            self.data.update(diagnostic_only=True, validation_commit=os.environ.get('GITHUB_SHA'))
        self.save()

    def stage(self, name: str, status: str, evidence: str) -> None:
        if name not in STAGES or status not in {'passed', 'failed', 'manual-required'} or not evidence.strip():
            raise ValueError('Invalid lifecycle result')
        if status == 'manual-required' and name != 'os_launch':
            raise ValueError('Only OS authorization may replace a launch with a manual requirement')
        self.data['stages'][name] = {'status': status, 'evidence': evidence}
        self.save()

    def save(self) -> None:
        stages = self.data['stages']
        self.data['complete'] = all(x['status'] == 'passed' for x in stages.values())
        if any(x['status'] == 'failed' for x in stages.values()):
            self.data['result'] = 'failed'
        elif self.data['complete']:
            self.data['result'] = 'passed'
        elif stages['os_launch']['status'] == 'manual-required':
            self.data['result'] = 'manual-required'
        else:
            self.data['result'] = 'incomplete'
        (self.output/'lifecycle.json').write_text(json.dumps(self.data, indent=2)+'\n', encoding='utf-8')


def validate(receipt: dict, *, release: str, commit: str) -> str:
    if receipt.get('diagnostic_only'):
        raise ValueError('Diagnostic installer rechecks cannot be used for publication')
    if receipt.get('schema') != 1 or receipt.get('release') != release or receipt.get('commit') != commit:
        raise ValueError('Lifecycle evidence belongs to another build')
    stages = receipt.get('stages', {})
    if set(stages) != set(STAGES):
        raise ValueError('Missing lifecycle stages')
    for name, item in stages.items():
        if item.get('status') not in {'passed', 'failed', 'not-run', 'manual-required'}:
            raise ValueError('Unknown lifecycle status')
        if item['status'] != 'not-run' and not item.get('evidence', '').strip():
            raise ValueError('Missing lifecycle evidence')
        if item['status'] == 'manual-required' and name != 'os_launch':
            raise ValueError('Manual OS approval must not hide a failed test')
    if any(x['status'] == 'failed' for x in stages.values()):
        raise ValueError('A lifecycle stage failed')
    complete = all(x['status'] == 'passed' for x in stages.values())
    if bool(receipt.get('complete')) != complete:
        raise ValueError('Incomplete GUI checks cannot be marked passed')
    if complete and receipt.get('result') == 'passed':
        return 'passed'
    if stages['os_launch']['status'] == 'manual-required' and receipt.get('result') == 'manual-required':
        # Unsigned macOS must still prove installation, integrity and removal.
        if receipt.get('platform') != 'darwin' or any(
            stages[name]['status'] != 'passed' for name in ('install', 'integrity', 'uninstall')
        ):
            raise ValueError('Missing checks around macOS approval requirement')
        if any(stages[name]['status'] != 'not-run' for name in ('api_gui', 'quit', 'retained_reinstall')):
            raise ValueError('Unexecuted macOS GUI stages must remain not-run')
        return 'manual-required'
    raise ValueError('Incomplete lifecycle evidence')


def required_matrix() -> set[tuple[str, str, str]]:
    cases = set()
    for arch in ('amd64', 'arm64'):
        linux = 'ubuntu-24.04' if arch == 'amd64' else 'ubuntu-24.04-arm'
        windows = 'windows-2022' if arch == 'amd64' else 'windows-11-arm'
        mac15 = 'macos-15-intel' if arch == 'amd64' else 'macos-15'
        mac26 = 'macos-26-intel' if arch == 'amd64' else 'macos-26'
        for method in ('source', 'windows-exe', 'windows-script'): cases.add((method, windows, arch))
        cases.add(('source', mac15, arch))
        for runner in (mac15, mac26):
            for method in ('macos-dmg', 'macos-script'): cases.add((method, runner, arch))
        for method in ('source', 'linux-deb', 'linux-deb-script', 'linux-rpm', 'linux-rpm-script',
                       'linux-systemd', 'compose', 'compose-development'):
            cases.add((method, linux, arch))
    return cases


def collect(directory: Path, *, release: str, commit: str) -> dict:
    """Missing runners, foreign commits and partial GUI checks cannot be green."""
    import hashlib
    results, keys = [], set()
    for path in sorted(directory.rglob('lifecycle.json')):
        if path.is_symlink(): raise ValueError('Symlink lifecycle receipt')
        receipt = json.loads(path.read_text())
        result = validate(receipt, release=release, commit=commit)
        arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(receipt.get('cpu'))
        key = (receipt['method'], receipt.get('runner'), arch)
        if key in keys: raise ValueError('Duplicate lifecycle case: '+str(key))
        if key not in required_matrix(): raise ValueError('Unexpected lifecycle case: '+str(key))
        expected_os = 'darwin' if key[1].startswith('macos') else 'windows' if key[1].startswith('windows') else 'linux'
        if receipt.get('platform') != expected_os: raise ValueError('Lifecycle ran on another platform')
        keys.add(key)
        proofs = {}
        if result == 'passed':
            for name in ('browser/browser.json', 'retained/browser.json'):
                proof_path = path.parent/name
                proof = json.loads(proof_path.read_text())
                if proof.get('result') != 'passed' or proof.get('apiMocked') is not False or not proof.get('realApiRequests'):
                    raise ValueError('Missing real API/browser evidence: '+str(key))
                if proof.get('identity', {}).get('release') != release or proof['identity'].get('commit') != commit:
                    raise ValueError('Browser tested another application build')
                expected_checks = BROWSER_CHECKS if name.startswith('browser/') else RETAINED_CHECKS
                if not expected_checks.issubset(proof.get('stages', [])) or proof['identity'].get('dirty') is not False:
                    raise ValueError('Incomplete browser checks or dirty application build')
                proofs[name] = hashlib.sha256(proof_path.read_bytes()).hexdigest()
            decoded = json.loads((path.parent/'decoded-recordings.json').read_text())
            if not isinstance(decoded, list) or not decoded: raise ValueError('No decoded recording evidence')
            if not (path.parent/'decode.log').is_file(): raise ValueError('No full recording decode log')
            audio = json.loads((path.parent/'recording-audio.json').read_text())
            if not audio.get('enabled_camera') or audio.get('disabled_camera') != []:
                raise ValueError('Missing per-camera recording audio evidence')
        else:
            evidence = (path.parent/'macos-trust.log').read_text().lower()
            from verify_macos import validate_policy_control, confirmed_approval_refusal
            if not confirmed_approval_refusal(evidence):
                raise ValueError('No explicit macOS approval refusal evidence')
            policy_path = path.parent/'macos-policy.json'
            policy = json.loads(policy_path.read_text())
            control_path = path.parent/'os-control/independent-policy-control.json'
            control = json.loads(control_path.read_text()) if control_path.is_file() else {}
            validate_policy_control(policy, control, receipt['os_version'])
            proofs['macos-policy.json'] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
            if control_path.is_file(): proofs['independent-policy-control.json'] = hashlib.sha256(control_path.read_bytes()).hexdigest()
        results.append({**receipt, 'proofs': proofs, 'receipt_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if missing := required_matrix()-keys:
        raise ValueError('Missing lifecycle cases: '+', '.join('/'.join(x) for x in sorted(missing)))
    return {'schema': 1, 'release': release, 'commit': commit, 'ci_cases': len(results),
            'passed': sum(x['result'] == 'passed' for x in results),
            'approval_required': sum(x['result'] == 'manual-required' for x in results),
            'physical_acceptance': 'pending', 'cases': results}
