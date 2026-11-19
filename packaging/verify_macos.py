"""Ad-hoc bundle integrity is mandatory; Gatekeeper trust is reported separately."""
import json
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
from release_lib import release_identity

THREAT_TERMS = ('malware detected', 'identified as malware', 'known malware', 'malicious software detected',
                'killing container due to rules engine deny')


def confirmed_approval_refusal(evidence: str) -> bool:
    text = evidence.lower()
    return not any(term in text for term in THREAT_TERMS) and any(term in text for term in (
        'adhoc signed or signed by an unknown certificate chain', 'gatekeeper denial breadcrumb', 'gatekeeper rejection'))


def validate_policy_control(policy: dict, control: dict, os_version: str) -> None:
    """An app-specific scanner error must not be excused as ordinary consent."""
    from macos_ci_policy import CONTROL_SOURCE, CONTROL_ID
    text = policy.get('system_policy', {}).get('output', '')
    if 'Internal Xprotect Error' not in text:
        return
    if any(term in text.lower() for term in THREAT_TERMS):
        raise RuntimeError('OS assessment reports a threat; investigate before distribution')
    if (control.get('os') != os_version or control.get('bundle_id') != CONTROL_ID
            or control.get('source_sha256') != hashlib.sha256(CONTROL_SOURCE.encode()).hexdigest()
            or control.get('distribution', {}).get('exit_code') != policy['system_policy'].get('exit_code')
            or text.strip().replace('FlintEye.app', 'PolicyControl.app') != control.get('distribution', {}).get('output', '').strip()):
        raise RuntimeError('App-specific or unconfirmed XProtect error; independent control did not reproduce it')


def verify_structure(app: Path) -> None:
    """Catch missing launch targets and external/broken links before signing tests."""
    root = app.resolve(strict=True)
    metadata = plistlib.loads((root/'Contents/Info.plist').read_bytes())
    if metadata.get('CFBundleExecutable') != 'FlintEye' or metadata.get('CFBundlePackageType') != 'APPL':
        raise RuntimeError('Invalid macOS executable declaration')
    executable = root/'Contents/MacOS/FlintEye'
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError('Bundle executable is missing or not executable')
    for path in root.rglob('*'):
        if path.is_symlink():
            try:
                path.resolve(strict=True).relative_to(root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(f'Broken, cyclic or outside-bundle link: {path.relative_to(root)}') from exc


def verify_icon(app: Path) -> None:
    contents = app / 'Contents'
    metadata = plistlib.loads((contents / 'Info.plist').read_bytes())
    icon = contents / 'Resources/flinteye.icns'
    source = Path(__file__).resolve().parents[1] / 'images/icons/flinteye.icns'
    if metadata.get('CFBundleIconFile') != icon.name or not icon.is_file():
        raise RuntimeError('The app bundle must refer to its FlintEye icon')
    if icon.read_bytes() != source.read_bytes():
        raise RuntimeError('The app bundle icon differs from the FlintEye symbol')
    if metadata.get('FlintEyeReleaseVersion') != release_identity()[0]:
        raise RuntimeError('The app bundle does not identify this exact preview')
    if metadata.get('CFBundleDisplayName') != 'FlintEye':
        raise RuntimeError('The app bundle must use the FlintEye display name')


def verify_app(app: Path) -> None:
    verify_structure(app)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)],
                   check=True, timeout=120)
    verify_icon(app)


def assess_gatekeeper(app: Path, receipt: Path) -> None:
    result = subprocess.run(['spctl', '--assess', '--type', 'execute', '--verbose=4', str(app)],
                            capture_output=True, text=True, timeout=120)
    report = {'signature_mode': 'ad-hoc', 'integrity': 'passed',
              'gatekeeper_accepted': result.returncode == 0,
              'assessment_exit_code': result.returncode,
              'assessment': (result.stdout + result.stderr).strip(),
              'notarized': False, 'quarantined_first_launch': 'requires real-device acceptance',
              'os_launch': 'not-tested-by-signature-check', 'api_gui': 'not-tested-by-signature-check'}
    policy = subprocess.run(['/usr/bin/syspolicy_check', 'distribution', str(app)],
                            capture_output=True, text=True, timeout=120)
    report['system_policy'] = {'exit_code': policy.returncode, 'output': (policy.stdout+policy.stderr).strip()}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: ad-hoc integrity. Gatekeeper: ' + ('accepted on this machine' if result.returncode == 0
          else 'not accepted; this preview has no Developer ID/notarization.'))
