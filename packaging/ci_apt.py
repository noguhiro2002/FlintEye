"""Avoid slow regional EC2 mirrors on disposable Ubuntu Actions runners."""
from __future__ import annotations

import os
from pathlib import Path
import re


def rewrite_sources(text: str) -> str:
    # Preserve suites, components, Signed-By and all non-Ubuntu repositories.
    return re.sub(r'https?://[a-z0-9.-]+\.ec2\.archive\.ubuntu\.com/ubuntu(?=[/\s]|$)',
                  'https://archive.ubuntu.com/ubuntu', text)


def main() -> None:
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.geteuid() != 0:
        raise SystemExit('This helper runs only as root on a disposable GitHub Actions runner')
    sources = [Path('/etc/apt/sources.list')]
    sources += list(Path('/etc/apt/sources.list.d').glob('*.sources'))
    sources += list(Path('/etc/apt/sources.list.d').glob('*.list'))
    changed = 0
    for path in sources:
        if not path.is_file() or path.is_symlink(): continue
        old = path.read_text()
        new = rewrite_sources(old)
        if old != new:
            path.write_text(new)
            changed += 1
    Path('/etc/apt/apt.conf.d/80-flinteye-ci-network').write_text(
        'Acquire::Retries "3";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n')
    print(f'CI: {changed} regional Ubuntu mirror file(s) switched to official HTTPS; package signature checks unchanged')


if __name__ == '__main__': main()
