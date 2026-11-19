"""Avoid slow regional EC2 mirrors on disposable Ubuntu Actions runners."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re


def rewrite_sources(text: str, *, architecture: str = 'amd64') -> str:
    # Preserve suites, components, Signed-By and all non-Ubuntu repositories.
    records = re.split(r'(\n\s*\n)', text)
    for index, record in enumerate(records):
        security = bool(re.search(r'^Suites:.*\b[\w.-]+-security\b', record, re.M))
        base = ('https://ports.ubuntu.com/ubuntu-ports' if architecture == 'arm64' else
                'https://security.ubuntu.com/ubuntu' if security else 'https://archive.ubuntu.com/ubuntu')
        record = re.sub(r'mirror\+file:/etc/apt/apt-mirrors\.txt(?=[/\s]|$)', base, record)
        records[index] = re.sub(r'https?://[a-z0-9.-]+\.ec2\.archive\.ubuntu\.com/ubuntu(?=[/\s]|$)', base, record)
    return ''.join(records)


def main() -> None:
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.geteuid() != 0:
        raise SystemExit('This helper runs only as root on a disposable GitHub Actions runner')
    sources = [Path('/etc/apt/sources.list')]
    sources += list(Path('/etc/apt/sources.list.d').glob('*.sources'))
    sources += list(Path('/etc/apt/sources.list.d').glob('*.list'))
    changed = 0
    architecture = 'arm64' if platform.machine().lower() in {'aarch64', 'arm64'} else 'amd64'
    for path in sources:
        if not path.is_file() or path.is_symlink(): continue
        old = path.read_text()
        new = rewrite_sources(old, architecture=architecture)
        if old != new:
            path.write_text(new)
            changed += 1
    Path('/etc/apt/apt.conf.d/80-flinteye-ci-network').write_text(
        'Acquire::Retries "3";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n')
    print(f'CI: {changed} regional Ubuntu mirror file(s) switched to official HTTPS; package signature checks unchanged')


if __name__ == '__main__': main()
