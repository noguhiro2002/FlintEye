"""Compare macOS policy assessment with a tiny independent, harmless app.

Assessment only: never launch this control, change protection settings, remove
quarantine, or use its result to approve a FlintEye application test.
"""
import argparse
import json
from pathlib import Path
import platform
import plistlib
import subprocess
import tempfile
import time


def assess(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    report = {'purpose': 'Independent CI OS-policy diagnostic; not an application acceptance test',
              'os': platform.platform()}
    with tempfile.TemporaryDirectory(prefix='FlintEye policy control ') as directory:
        root = Path(directory); app = root/'PolicyControl.app'; contents = app/'Contents'
        (contents/'MacOS').mkdir(parents=True)
        (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'PolicyControl',
            'CFBundleIdentifier': 'community.flinteye.ci-policy-control', 'CFBundleName': 'PolicyControl',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '1.0', 'CFBundleVersion': '1',
            'LSMinimumSystemVersion': '14.0'}))
        source = root/'main.c'; source.write_text('int main(void) { return 0; }\n')
        for command in (['clang', str(source), '-o', str(contents/'MacOS/PolicyControl')],
                        ['codesign', '--force', '--sign', '-', str(app)],
                        ['xattr', '-w', 'com.apple.quarantine', f'0083;{int(time.time()):x};FlintEyePolicyControl;', str(app)]):
            subprocess.run(command, capture_output=True, text=True, check=True, timeout=90)
        for key, command in [('spctl', ['spctl', '--assess', '--type', 'execute', '--verbose=4', str(app)]),
                             ('distribution', ['/usr/bin/syspolicy_check', 'distribution', str(app)])]:
            try:
                r = subprocess.run(command, capture_output=True, text=True, timeout=120)
                report[key] = {'exit_code': r.returncode, 'output': r.stdout+r.stderr}
            except subprocess.TimeoutExpired:
                report[key] = {'timeout': True}
    (output/'independent-policy-control.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Recorded independent OS scanner result; no security setting or application approval changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    assess(parser.parse_args().output)
