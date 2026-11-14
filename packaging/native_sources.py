"""Retain exact Rocky source RPMs for system libraries copied into a Linux bundle."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from release_lib import digest


def collect(bundle: Path, destination: Path, notices: Path) -> None:
    if not shutil.which('rpm') or not shutil.which('dnf'):
        raise RuntimeError('Build Linux release packages in the documented Rocky builder')
    destination.mkdir(parents=True, exist_ok=True)
    notices.mkdir(parents=True, exist_ok=True)
    system_libraries: dict[str, list[Path]] = {}
    for line in subprocess.check_output(['ldconfig', '-p'], text=True).splitlines():
        match = re.search(r'=> (/.+)$', line)
        if match:
            path = Path(match.group(1))
            system_libraries.setdefault(path.name, []).append(path)
            if path.resolve().name != path.name:
                system_libraries.setdefault(path.resolve().name, []).append(path)
    packages = {}
    inventory = []
    for library in sorted(bundle.rglob('*.so*')):
        if not library.is_file() or library.is_symlink():
            continue
        for original in system_libraries.get(library.name, []):
            if not original.is_file() or digest(original) != digest(library):
                continue
            record = subprocess.check_output(
                ['rpm', '-qf', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{SOURCERPM}', str(original.resolve())], text=True)
            name, version, source_rpm = record.split('\t')
            if not source_rpm.endswith('.src.rpm'):
                raise RuntimeError(f'Missing source package for {name}')
            packages[name] = {'version': version, 'source_rpm': source_rpm}
            inventory.append({'file': str(library.relative_to(bundle)), 'sha256': digest(library),
                              'package': name, 'version': version, 'source_rpm': source_rpm})
            break
    if not packages:
        raise RuntimeError('No system libraries found in the native bundle')
    for name, item in sorted(packages.items()):
        source_file = destination / item['source_rpm']
        if not source_file.exists():
            subprocess.run(['dnf', 'download', '--source', '--downloaddir', str(destination),
                            f'{name}-{item["version"]}'], check=True)
        if not source_file.is_file():
            raise RuntimeError(f'Exact corresponding source not downloaded: {source_file.name}')
        subprocess.run(['rpm', '--checksig', str(source_file)], check=True)
        paths = subprocess.check_output(['rpm', '-ql', name], text=True).splitlines()
        for entry in paths:
            source = Path(entry)
            if source.is_file() and (entry.startswith('/usr/share/licenses/') or
                    source.name.lower().startswith(('license', 'copying', 'copyright', 'notice'))):
                target = notices / name / source.relative_to('/')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    manifest = json.dumps(inventory, indent=2) + '\n'
    (destination / 'system-libraries.json').write_text(manifest)
    (notices / 'system-libraries.json').write_text(manifest)
    (destination / 'README.txt').write_text(
        'Exact source RPMs for Rocky Linux shared libraries copied into this bundle.\n'
        'Each SRPM contains upstream sources, patches and the RPM spec build recipe.\n'
        'Use rpm2cpio FILE.src.rpm | cpio -idmv in a new directory to inspect them,\n'
        'or rpmbuild --rebuild FILE.src.rpm on the matching Rocky release.\n'
        'System library versions and binary hashes are recorded in system-libraries.json.\n'
        'The accompanying media-sources.tar.gz contains the FFmpeg/MediaMTX and\n'
        'CPython source trees, downloads and FlintEye build scripts.\n')
