"""Diagnose existing installer bytes without producing publishable evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from lifecycle_report import LINUX_USER_METHODS
from release_lib import ROOT, REPOSITORY, digest, release_identity


TARGETS = ('all', 'windows', 'macos', 'linux-user')


def validate_changes(paths, *, target='all'):
    allowed = {'packaging/recheck_installers.py', 'packaging/macos_ci_policy.py',
               'packaging/lifecycle.py', 'packaging/lifecycle_common.py', 'packaging/lifecycle_report.py',
               'packaging/verify_macos.py',
               'packaging/install.sh', 'packaging/install.ps1', 'frontend/tests/installed.mjs',
               '.github/workflows/recheck-installers.yml', 'tests/test_lifecycle.py',
               'tests/test_recheck_installers.py', 'README.md', 'README.ja.md'}
    if target == 'linux-user':
        allowed.update({
            'packaging/lifecycle_linux.py', 'packaging/LifecycleLinux.Dockerfile',
            'packaging/acceptance-1.2.0.json',  # Release metadata is bundled as documentation.
            '.github/workflows/build-release.yml', '.github/workflows/online-lifecycle.yml',
            'tests/test_install_staging.py', 'tests/test_release_packaging.py',
        })
    for name in paths:
        if Path(name).is_absolute() or '..' in Path(name).parts or (name not in allowed and not (name.startswith('docs/') and name.endswith('.md'))):
            raise ValueError('Rebuild after changes to application/build inputs: '+name)


def matrix(target):
    cases = []
    for arch in ('amd64', 'arm64'):
        if target == 'linux-user':
            runner = 'ubuntu-24.04' if arch == 'amd64' else 'ubuntu-24.04-arm'
            cases += [dict(runner=runner, os='linux', arch=arch, method=method) for method in LINUX_USER_METHODS]
        if target in ('all', 'windows'):
            runner = 'windows-2022' if arch == 'amd64' else 'windows-11-arm'
            cases += [dict(runner=runner, os='windows', arch=arch, method=m) for m in ('windows-exe', 'windows-script')]
        if target in ('all', 'macos'):
            runners = ('macos-15-intel', 'macos-26-intel') if arch == 'amd64' else ('macos-15', 'macos-26')
            cases += [dict(runner=r, os='macos', arch=arch, method=m) for r in runners for m in ('macos-dmg', 'macos-script')]
    return {'include': cases}


def overlay(directory: Path, commit: str):
    build = json.loads((directory/'validation-build.json').read_text())
    release, _ = release_identity()
    if build.get('commit') != commit or build.get('release') != release:
        raise ValueError('Original installer provenance mismatch')
    sums = {}
    for line in (directory/'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        if Path(name).name != name or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Unsafe artifact checksum entry')
        if digest(directory/name) != expected: raise ValueError('Original artifact changed: '+name)
        sums[name] = expected
    original = dict(sums)
    for name in ('install.sh', 'install.ps1'):
        (directory/name).write_text((ROOT/'packaging'/name).read_text().replace('@RELEASE_VERSION@', release), newline='\n')
        sums[name] = digest(directory/name)
    (directory/'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name, value in sums.items()))
    (directory/'diagnostic-inputs.json').write_text(json.dumps({'diagnostic_only': True, 'application_commit': commit,
        'validation_commit': os.environ.get('GITHUB_SHA'), 'original_checksums': original,
        'diagnostic_checksums': sums}, indent=2)+'\n')


def preflight(run_id: str, target: str):
    if not re.fullmatch('[0-9]{1,16}', run_id): raise ValueError('Expected numeric build run ID')
    def api(path): return json.loads(subprocess.check_output(['gh', 'api', path], text=True))
    run = api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    commit = run['head_sha']
    if (run['status'] != 'completed' or run.get('path') != '.github/workflows/build-release.yml'
            or run.get('head_branch') != 'main' or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or not re.fullmatch('[0-9a-f]{40}', commit)):
        raise ValueError('Expected a completed main-branch Build release run from this repository')
    jobs = api(f'repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100')['jobs']
    builder, count = ('linux', 2) if target == 'linux-user' else ('desktop', 4)
    builds = [j for j in jobs if j['name'].startswith(builder+' (')]
    if len(builds) != count or any(j['conclusion'] != 'success' for j in builds):
        raise ValueError(f'All {count} original {builder} builders must have passed')
    subprocess.run(['git', 'merge-base', '--is-ancestor', commit, 'HEAD'], cwd=ROOT, check=True)
    changed = subprocess.check_output(['git', 'diff', '--name-only', commit, 'HEAD'], cwd=ROOT, text=True).splitlines()
    validate_changes(changed, target=target)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write('build_commit='+commit+'\n')
        f.write('matrix='+json.dumps(matrix(target), separators=(',', ':'))+'\n')
    print('Diagnostic only: reusing verified installers from '+commit+'; no release output is permitted.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id')
    parser.add_argument('--target', choices=TARGETS, default='all')
    parser.add_argument('--overlay', type=Path)
    parser.add_argument('--commit')
    args = parser.parse_args()
    if args.overlay:
        overlay(args.overlay, args.commit)
    else:
        preflight(args.run_id, args.target)
