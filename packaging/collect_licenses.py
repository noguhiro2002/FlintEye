"""Collect installed Python/npm license files and inventories for the bundle."""
from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def license_document(item: Path, source: Path, declared: set[str] | None = None) -> bool:
    """Select notice documents, never test extensions named e.g. copying*.so."""
    if any(part.lower().endswith('.dsym') for part in item.parts):
        return False
    if source.suffix.lower() in {'.so', '.dll', '.dylib', '.exe', '.pyd', '.py', '.pyc', '.o', '.a', '.lib'}:
        return False
    metadata_license = any(part.endswith('.dist-info') and index + 1 < len(item.parts)
                           and item.parts[index + 1] == 'licenses' for index, part in enumerate(item.parts))
    named = re.match(r'^(licen[cs]e|copying|copyright|notice)(?:$|[._-])', source.name, re.I)
    if not (metadata_license or named or item.as_posix() in (declared or set())) or not source.is_file():
        return False
    data = source.read_bytes()
    # License texts can contain non-ASCII characters, but never NULs or object code.
    if b'\0' in data or data[:4] in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe') or data[:2] == b'MZ':
        return False
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        return False
    return True


def collect(destination: Path) -> None:
    # This directory contains only generated runtime notices. A rebuild must not
    # retain files accepted by an older collector; vendor sources live elsewhere.
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata['Name']
        inventory.append({'ecosystem': 'python', 'name': name, 'version': dist.version,
                          'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', '')})
        declared = set(dist.metadata.get_all('License-File') or [])
        for item in dist.files or []:
            source = Path(dist.locate_file(item))
            if license_document(Path(item), source, declared):
                target = destination / 'python' / name / Path(*[p for p in item.parts if p not in ('..', '.')])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for package in (ROOT / 'frontend/node_modules').rglob('package.json'):
        if package.parent.name == 'node_modules':
            continue
        try:
            metadata = json.loads(package.read_text())
        except (ValueError, UnicodeError):
            continue
        if not metadata.get('name') or not metadata.get('version'):
            continue
        inventory.append({'ecosystem': 'npm', 'name': metadata['name'], 'version': metadata['version'],
                          'license': metadata.get('license', '')})
        for source in package.parent.iterdir():
            if license_document(Path(source.name), source):
                target = destination / 'npm' / package.parent.relative_to(ROOT / 'frontend/node_modules') / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    # Retain the interpreter's own installed license where provided.
    for source in [Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE',
                   Path(sys.base_prefix) / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'LICENSE.txt']:
        if source.is_file():
            shutil.copy2(source, destination / 'CPython-LICENSE.txt')
            break
    # PyInstaller's Tcl/Tk data hooks do not necessarily copy the distro's
    # separate license directory. Preserve the notices for native runtime libs.
    if sys.platform.startswith('linux'):
        for name in ('tcl', 'tk', 'openssl-libs', 'openssl', 'libffi', 'libX11', 'libXft',
                     'libXext', 'libXrender', 'libXScrnSaver', 'libXau', 'libXdmcp', 'libxcb',
                     'fontconfig', 'freetype', 'libpng', 'expat', 'zlib', 'bzip2-libs',
                     'xz-libs', 'libstdc++', 'libgcc'):
            source = Path('/usr/share/licenses') / name
            if source.is_dir():
                shutil.copytree(source, destination / 'system' / name, dirs_exist_ok=True)
            # Rocky puts Tcl/Tk's license.terms in /usr/share/doc, not licenses.
            documentation = Path('/usr/share/doc') / name
            if documentation.is_dir():
                for source in documentation.rglob('*'):
                    if source.is_file() and source.name.lower().startswith(('license', 'copying', 'copyright', 'notice')):
                        target = destination / 'system' / name / source.relative_to(documentation)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
    interpreter_roots = [Path(sys.base_prefix) / directory for directory in ('tcl', 'Resources')]
    for pattern in ('tcl*', 'tk*'):
        interpreter_roots.extend((Path(sys.base_prefix) / 'lib').glob(pattern))
    try:
        import tkinter
        tcl_library = Path(tkinter.Tcl().eval('info library'))
        interpreter_roots.extend((tcl_library, tcl_library.parent / ('tk' + str(tkinter.TkVersion))))
    except (ImportError, RuntimeError):
        pass  # Headless container Python need not include Tcl/Tk.
    for base in interpreter_roots:
        if base.is_dir():
            for source in base.rglob('*'):
                if source.is_file() and source.name.lower().startswith(('license', 'copying')):
                    target = destination / 'interpreter' / base.name / source.relative_to(base)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (destination / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')


if __name__ == '__main__':
    collect(Path(sys.argv[1]))
