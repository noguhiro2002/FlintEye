"""Ad-hoc bundle integrity is mandatory; Gatekeeper trust is reported separately."""
import json
from pathlib import Path
import subprocess


def verify_app(app: Path) -> None:
    subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)],
                   check=True, timeout=120)


def assess_gatekeeper(app: Path, receipt: Path) -> None:
    result = subprocess.run(['spctl', '--assess', '--type', 'execute', '--verbose=4', str(app)],
                            capture_output=True, text=True, timeout=120)
    report = {'signature_mode': 'ad-hoc', 'integrity': 'passed',
              'gatekeeper_accepted': result.returncode == 0,
              'assessment_exit_code': result.returncode,
              'assessment': (result.stdout + result.stderr).strip(),
              'notarized': False, 'quarantined_first_launch': 'requires real-device acceptance'}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: ad-hoc integrity. Gatekeeper: ' + ('accepted on this machine' if result.returncode == 0
          else 'not accepted; this preview has no Developer ID/notarization.'))
