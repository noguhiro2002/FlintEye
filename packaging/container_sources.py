"""Run as root in a disposable copy of the tested image; export media sources."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def package_owner(output: str) -> str | None:
    # dpkg-query may prepend "diversion by ... from/to" lines. Only actual
    # package ownership records have this syntax, including multiarch suffixes.
    for line in output.splitlines():
        if match := re.match(r'^([a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?): /', line):
            return match.group(1)
    return None


def main() -> None:
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=True)
    # Derive the exact Debian source package versions from the tested FFmpeg's
    # dependency closure, before installing source-retrieval tools.
    binaries = {'/usr/bin/ffmpeg', '/usr/bin/ffprobe'}
    for binary in tuple(binaries):
        output = subprocess.check_output(['ldd', binary], text=True)
        binaries.update(re.findall(r'(/[^\s]+)', output))
    packages = set()
    for binary in sorted(binaries):
        owner = None
        candidates = [binary, str(Path(binary).resolve())]
        if binary.startswith('/lib/'):
            candidates.append('/usr' + binary)
        for candidate in candidates:
            result = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True)
            if result.returncode == 0:
                owner = package_owner(result.stdout)
                if owner:
                    break
        if owner is None:
            raise RuntimeError(f'Cannot identify binary owner: {binary}')
        spec = subprocess.check_output(['dpkg-query', '-W', '-f=${source:Package}=${source:Version}', owner], text=True)
        packages.add(spec)
    inventory = subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n'], text=True)
    (destination / 'debian-packages.txt').write_text(inventory)
    sources = Path('/etc/apt/sources.list.d/debian.sources')
    sources.write_text(sources.read_text().replace('Types: deb\n', 'Types: deb deb-src\n'))
    subprocess.run(['apt-get', 'update'], check=True)
    subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', 'dpkg-dev'], check=True)
    with tempfile.TemporaryDirectory(prefix='flinteye-sources-') as temporary:
        directory = Path(temporary)
        subprocess.run(['apt-get', 'source', '--download-only', *sorted(packages)], cwd=directory, check=True)
        (directory / 'README.txt').write_text(
            'Exact Debian source archives for FFmpeg/FFprobe and their linked libraries.\n'
            'Extract each .dsc using dpkg-source -x; debian/rules records the distro build recipe.\n'
            'The package versions were read from the tested release image.\n' + '\n'.join(sorted(packages)) + '\n')
        shutil.copy2(destination / 'debian-packages.txt', directory)
        with tarfile.open(destination / 'container-sources.tar.gz', 'w:gz') as archive:
            archive.add(directory, arcname='debian-media-sources')
    with tarfile.open(destination / 'container-notices.tar.gz', 'w:gz') as archive:
        for path in Path('/usr/share/doc').glob('*/copyright'):
            archive.add(path, arcname=str(path.relative_to('/')))
        archive.add('/opt/flinteye/licenses', arcname='flinteye/licenses')
        archive.add('/opt/flinteye/LICENSE', arcname='flinteye/LICENSE')
        archive.add('/opt/flinteye/THIRD_PARTY_NOTICES.md', arcname='flinteye/THIRD_PARTY_NOTICES.md')


if __name__ == '__main__':
    main()
