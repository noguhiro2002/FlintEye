"""Build the constrained cryptography package natively on Windows ARM64.

PyPI does not provide a win_arm64 wheel for the constrained 50.0.2 release.
Build against verified, private static OpenSSL sources rather than relying on
an unrelated x64 OpenSSL installation or weakening the TLS implementation.
The normal dependency-install step must follow this helper.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from release_lib import ROOT, binary_architecture, digest
from vendor import LOCK, VENDOR, source


def msvc_environment() -> dict[str, str]:
    locator = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    installation = subprocess.check_output([str(locator), '-latest', '-products', '*',
        '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.ARM64',
        '-property', 'installationPath'], text=True).strip()
    developer = Path(installation) / 'Common7/Tools/VsDevCmd.bat'
    if not installation or not developer.is_file():
        raise RuntimeError('Install Visual Studio C++ ARM64 build tools before building cryptography.')
    if any(c in str(developer) for c in '\r\n"%&|^'):
        raise ValueError('Unsupported Visual Studio command path')
    # Read the compiler environment in memory. Never log or write its contents:
    # the inherited environment can contain CI credentials.
    comspec = os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe')
    if any(c in comspec for c in '\r\n"%&|^'):
        raise ValueError('Unsupported command processor path')
    for host in ('arm64', 'amd64'):
        # Pass a complete cmd command line. list2cmdline's backslash-escaped
        # quotes follow C runtime rules, not cmd.exe's batch-path syntax.
        command = f'"{comspec}" /d /u /s /c "call "{developer}" -no_logo -arch=arm64 -host_arch={host} >nul && set"'
        result = subprocess.run(command, check=False, capture_output=True,
                                encoding='utf-16-le', errors='replace')
        if result.returncode:
            continue
        env = os.environ.copy()
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            if separator and key:
                env[key.upper()] = value
        if env.get('VSCMD_ARG_TGT_ARCH', '').lower() == 'arm64':
            return env
    raise RuntimeError('Visual Studio could not initialize an ARM64 compiler environment. Check the installed C++ ARM64 tools and Windows SDK.')


def main() -> None:
    if sys.platform != 'win32' or platform.machine().lower() not in {'arm64', 'aarch64'}:
        raise RuntimeError('Run this helper with native Windows ARM64 Python.')
    env = msvc_environment()
    candidates = [Path(r'C:\Strawberry\perl\bin\perl.exe')]
    if found := shutil.which('perl', path=env.get('PATH')):
        candidates.append(Path(found))
    perl = next((path for path in candidates if path.is_file() and
        subprocess.check_output([str(path), '-e', 'print $^O'], env=env, text=True).strip() == 'MSWin32'), None)
    if perl is None:
        raise RuntimeError('Install native Strawberry Perl; MSYS Perl cannot build MSVC OpenSSL.')
    for tool in ('cl.exe', 'nmake.exe', 'rustc.exe', 'cargo.exe'):
        if not shutil.which(tool, path=env.get('PATH')):
            raise RuntimeError(f'Missing native build tool: {tool}')
    tree = source('openssl')
    build = VENDOR / 'build/openssl-arm64'
    prefix = (VENDOR / 'openssl-arm64').resolve()
    if build.exists() or prefix.exists() or (VENDOR/'crypto-wheels').exists():
        raise RuntimeError('Use a fresh checkout, or remove generated vendor/build/openssl-arm64, vendor/openssl-arm64 and vendor/crypto-wheels before retrying.')
    build.mkdir(parents=True)
    configure = [str(perl), str(tree / 'Configure'), 'VC-WIN64-ARM',
        'no-shared', 'no-asm', 'no-tests', 'no-makedepend',
        '--prefix=' + str(prefix), '--openssldir=' + str(prefix / 'ssl')]
    subprocess.run(configure, cwd=build, env=env, check=True)
    for target in ('build_libs', 'install_dev'):
        subprocess.run(['nmake.exe', '/nologo', target], cwd=build, env=env, check=True)
    libraries = [path.parent for path in prefix.rglob('libcrypto.lib') if (path.parent/'libssl.lib').is_file()]
    if len(libraries) != 1:
        raise RuntimeError('Expected one installed native OpenSSL static library pair')
    env.update(OPENSSL_DIR=str(prefix), OPENSSL_STATIC='1',
               OPENSSL_LIB_DIR=str(libraries[0]), OPENSSL_INCLUDE_DIR=str(prefix/'include'))
    constrained = (ROOT / 'packaging/constraints.txt').read_text()
    package = re.search(r'^cryptography==[^\s;]+$', constrained, re.M)
    if not package:
        raise ValueError('Pin the exact cryptography version in packaging/constraints.txt')
    wheels = VENDOR / 'crypto-wheels'
    wheels.mkdir(exist_ok=False)
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-cache-dir',
        '--no-binary=cryptography', '-c', str(ROOT/'packaging/constraints.txt'),
        '--wheel-dir', str(wheels), package[0]], cwd=ROOT, env=env, check=True)
    built = list(wheels.glob('cryptography-*-win_arm64.whl'))
    if len(built) != 1:
        raise RuntimeError('Expected exactly one native ARM64 cryptography wheel')
    wheel = built[0]
    with zipfile.ZipFile(wheel) as archive, tempfile.TemporaryDirectory() as temporary:
        bindings = [name for name in archive.namelist() if name.endswith('.pyd')]
        if not bindings:
            raise RuntimeError('The cryptography wheel has no native bindings')
        for name in bindings:
            binary = Path(temporary) / Path(name).name
            binary.write_bytes(archive.read(name))
            if binary_architecture(binary) != 'arm64':
                raise RuntimeError('Cryptography contains a binding for a different CPU')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)],
        env=env, check=True)
    notices = VENDOR / 'licenses/openssl'
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tree / 'LICENSE.txt', notices / 'LICENSE.txt')
    (notices/'FlintEye-build.json').write_text(json.dumps({
        'openssl': LOCK['sources']['openssl'], 'configure': configure[2:],
        'cryptography': package[0], 'wheel': wheel.name, 'sha256': digest(wheel),
        'rust': subprocess.check_output(['rustc.exe', '--version'], env=env, text=True).strip(),
        'linkage': 'static', 'architecture': 'arm64',
        'msvc_host': env.get('VSCMD_ARG_HOST_ARCH')}, indent=2)+'\n')
    print('Verified native ARM64 cryptography installed; OpenSSL sources/notices retained.')


if __name__ == '__main__':
    main()
