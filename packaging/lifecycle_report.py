"""Evidence for installed-app checks; manual approval never means a passed GUI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import time

STAGES = ('install', 'integrity', 'os_launch', 'api_gui', 'quit', 'uninstall', 'retained_reinstall')
LINUX_USER_METHODS = ('linux-deb-user-script', 'linux-rpm-user-script')
MANUAL_CASES = ('os-first-launch-approval', 'native-menus-and-permissions', 'physical-usb-and-lan')
BROWSER_CHECKS = {
    'browser-first-run-setup', 'real-api-build-identity-and-authentication',
    'GUI-register-two-cameras-and-save', 'per-camera-audio-default-off-detection-enable-and-save',
    'both-live-cameras-show-their-own-marker', 'all-six-main-screens', 'live-and-multiview-real-WebRTC-frame-progress',
    'recording-GUI-playback-and-download', 'viewer-login-and-real-API-write-denial',
    'multiview-shows-both-camera-markers', 'GUI-remove-and-readd-camera-keeps-other-publisher',
    'GUI-stop-keeps-API-and-saved-settings-cannot-restart-monitoring', 'GUI-start-resumes-recording-before-normal-quit',
}
RETAINED_CHECKS = {'retained-administrator-login', 'real-api-build-identity-and-authentication',
                   'retained-config-audio-and-recording-inventory', 'all-six-main-screens'}
NEW_BROWSER_CHECKS = {'GUI-settings-save-and-effective-values', 'GUI-ONVIF-inspect-and-PTZ-movement',
                      'GUI-camera-rename-preserves-stream-and-recordings', 'GUI-rejects-duplicate-and-migrates-paths'}
NEW_RETAINED_CHECKS = {'retained-branding-rename-and-PTZ'}
EVENT_BROWSER_CHECKS = {'GUI-event-settings-and-equipment-API-archive-playback-and-download'}
EVENT_RETAINED_CHECKS = {'retained-event-recording-settings-and-playback'}


def requires_preview_7_checks(release: str) -> bool:
    return _requires_preview_checks(release, 7)


def requires_preview_8_checks(release: str) -> bool:
    return _requires_preview_checks(release, 8)


def _requires_preview_checks(release: str, number: int) -> bool:
    version, _, preview = release.partition('-preview.')
    return tuple(map(int, version.split('.'))) > (1, 2, 0) or (
        version == '1.2.0' and (not preview or int(preview) >= number))


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
        for method in ('source', 'linux-deb', 'linux-deb-script', 'linux-rpm', 'linux-rpm-script', *LINUX_USER_METHODS,
                       'linux-systemd', 'compose', 'compose-development'):
            cases.add((method, linux, arch))
    return cases


def collect(directory: Path, *, release: str, commit: str) -> dict:
    """Missing runners, foreign commits and partial GUI checks cannot be green."""
    import hashlib
    results, keys = [], set()
    for path in sorted(directory.rglob('lifecycle.json')):
        if path.is_symlink(): raise ValueError('Symlink lifecycle receipt')
        receipt = json.loads(path.read_text(encoding='utf-8'))
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
                proof = json.loads(proof_path.read_text(encoding='utf-8'))
                if proof.get('result') != 'passed' or proof.get('apiMocked') is not False or not proof.get('realApiRequests'):
                    raise ValueError('Missing real API/browser evidence: '+str(key))
                if proof.get('identity', {}).get('release') != release or proof['identity'].get('commit') != commit:
                    raise ValueError('Browser tested another application build')
                expected_checks = BROWSER_CHECKS if name.startswith('browser/') else RETAINED_CHECKS
                if requires_preview_7_checks(release):
                    expected_checks = expected_checks | (NEW_BROWSER_CHECKS if name.startswith('browser/') else NEW_RETAINED_CHECKS)
                if requires_preview_8_checks(release):
                    expected_checks = expected_checks | (EVENT_BROWSER_CHECKS if name.startswith('browser/') else EVENT_RETAINED_CHECKS)
                if name.startswith('browser/') and key[0] == 'source' and expected_os == 'linux':
                    expected_checks = expected_checks | {'synthetic-USB-and-IP-live-multiview-and-removal',
                                                        'desktop-browser-one-use-setup-handoff'}
                if not expected_checks.issubset(proof.get('stages', [])) or proof['identity'].get('dirty') is not False:
                    raise ValueError('Incomplete browser checks or dirty application build')
                proofs[name] = hashlib.sha256(proof_path.read_bytes()).hexdigest()
            if requires_preview_7_checks(release):
                onvif = path.parent/'fixture/onvif-operations.json'
                requests = json.loads(onvif.read_text(encoding='utf-8'))
                for operation in ('ContinuousMove', 'Stop'):
                    if not any(row['endpoint'] == 'ptz' and row['operation'] == operation
                               and row['profile'] == 'qa-main' for row in requests):
                        raise ValueError(f'Missing real ONVIF {operation} evidence for {key}')
                proofs['fixture/onvif-operations.json'] = hashlib.sha256(onvif.read_bytes()).hexdigest()
            decoded = json.loads((path.parent/'decoded-recordings.json').read_text(encoding='utf-8'))
            if not isinstance(decoded, list) or not decoded: raise ValueError('No decoded recording evidence')
            sources = {Path(name).parts[:2] for name in decoded}
            if sources != {('recordings', name) for name in ('qa-camera-1', 'qa-camera-2', 'multiview_1')}:
                raise ValueError('Missing or unexpected decoded recording sources')
            selection = json.loads((path.parent/'browser/download-selection.json').read_text(encoding='utf-8'))
            filename = selection.get('savedName')
            selected = 'recordings/' + selection['relativePath']
            if filename not in {'recording-download.mp4', 'recording-download.ts'} or selected not in decoded:
                raise ValueError('Browser selected an unknown recording')
            retained = json.loads((path.parent/'retained-files.json').read_text(encoding='utf-8'))
            original_hashes = {name.replace(chr(92), '/'): value for name, value in retained.items()}
            from release_lib import digest
            download_hash = digest(path.parent/'browser'/filename)
            if download_hash != original_hashes.get(selected):
                raise ValueError('Downloaded bytes differ from selected original recording')
            proofs['browser/'+filename] = download_hash
            if requires_preview_8_checks(release):
                event = json.loads((path.parent/'browser/event-selection.json').read_text(encoding='utf-8'))
                if not re.fullmatch(r'[0-9a-f]{32}', event['event_id']) or type(event['clip_index']) is not int or event['clip_index'] < 0:
                    raise ValueError('Invalid event recording selection')
                archived = f"event-recordings/{event['event_id']}/{event['clip_index']}.mp4"
                archive_hash = digest(path.parent/'browser/event-download.mp4')
                if archive_hash != original_hashes.get(archived):
                    raise ValueError('Event download differs from the preserved archive')
                proofs['browser/event-download.mp4'] = archive_hash
            if not (path.parent/'decode.log').is_file(): raise ValueError('No full recording decode log')
            audio = json.loads((path.parent/'recording-audio.json').read_text(encoding='utf-8'))
            if not audio.get('enabled_camera') or audio.get('disabled_camera') != []:
                raise ValueError('Missing per-camera recording audio evidence')
        else:
            evidence = (path.parent/'macos-trust.log').read_text(encoding='utf-8').lower()
            from verify_macos import validate_policy_control, confirmed_approval_refusal
            if not confirmed_approval_refusal(evidence):
                raise ValueError('No explicit macOS approval refusal evidence')
            policy_path = path.parent/'macos-policy.json'
            policy = json.loads(policy_path.read_text(encoding='utf-8'))
            control_path = path.parent/'os-control/independent-policy-control.json'
            control = json.loads(control_path.read_text(encoding='utf-8')) if control_path.is_file() else {}
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
