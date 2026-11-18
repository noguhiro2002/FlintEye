"""Put the exact installer scripts beside each OS's Actions packages for QA."""
import argparse
import json
from pathlib import Path
import re

from release_lib import ROOT, digest, release_identity, version


def prepare(directory: Path, commit: str) -> None:
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('A full source commit SHA is required')
    packages = sorted(p for p in directory.glob('FlintEye-*') if p.is_file())
    if not any(p.suffix in {'.dmg', '.exe', '.deb', '.rpm'} for p in packages):
        raise ValueError('No native installer in the validation directory')
    release, channel = release_identity()
    for name in ('install.sh', 'install.ps1'):
        text = (ROOT / 'packaging' / name).read_text().replace('@RELEASE_VERSION@', release)
        (directory / name).write_text(text, encoding='utf-8', newline='\n')
    (directory / 'validation-build.json').write_text(json.dumps({
        'version': version(), 'release': release, 'channel': channel, 'commit': commit,
        'purpose': 'Local-artifact installation testing; physical-device acceptance pending',
        'packages': {p.name: digest(p) for p in packages},
    }, indent=2) + '\n')
    files = packages + [directory / name for name in ('install.sh', 'install.ps1', 'validation-build.json')]
    (directory / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in sorted(files)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=ROOT / 'dist')
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    prepare(args.directory, args.commit)
