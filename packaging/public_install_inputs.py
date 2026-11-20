"""Fetch anonymous public download bytes and verify the published provenance."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from urllib.request import Request, urlopen

from release_lib import REPOSITORY, digest, release_identity, version


def download(url: str, target: Path) -> None:
    request = Request(url, headers={'User-Agent': 'FlintEye-public-install-QA'})
    # No token, cookies, alternate server or TLS-verification override.
    with urlopen(request, timeout=90) as stream, target.open('wb') as output:
        if not stream.geturl().startswith('https://'): raise ValueError('Refusing a non-HTTPS redirect')
        size = 0
        while block := stream.read(1024*1024):
            size += len(block)
            if size > 400*1024*1024: raise ValueError('Unexpectedly large public installer')
            output.write(block)


def validate_manifest(manifest: dict, *, release: str, commit: str) -> None:
    if manifest.get('schema') != 1 or manifest.get('tag') != 'v'+release or manifest.get('commit') != commit:
        raise ValueError('Public release belongs to another application/commit')
    if manifest.get('image') != f'ghcr.io/noguhiro2002/flinteye:{release}':
        raise ValueError('Unexpected public image')


def verify_public_tag(release: str, commit: str) -> None:
    # Check the public Git ref without depending on a runner's shared REST API quota.
    ref = f'refs/tags/v{release}'
    peeled = ref + '^{}'
    output = subprocess.check_output(
        ['git', '-c', 'credential.helper=', '-c', 'http.extraHeader=', '-c', 'http.https://github.com/.extraHeader=',
         'ls-remote', '--exit-code', f'https://github.com/{REPOSITORY}.git', ref, peeled],
        text=True, timeout=60, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    refs = {}
    for line in output.splitlines():
        revision, separator, name = line.partition('\t')
        if (not separator or name not in (ref, peeled) or name in refs
                or not re.fullmatch('[0-9a-f]{40}', revision)):
            raise ValueError('Invalid public Git tag response')
        refs[name] = revision
    if ref not in refs or refs.get(peeled, refs[ref]) != commit:
        raise ValueError('Public tag points to another commit')


def prepare(directory: Path, *, release: str, commit: str, rpm: bool = False, container: bool = False) -> None:
    if release != release_identity()[0] or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Select this checkout\'s exact release and full build commit')
    if directory.exists(): raise ValueError('Use a new public-download directory')
    directory.mkdir(parents=True)
    base = f'https://github.com/{REPOSITORY}/releases/download/v{release}/'
    for name in ('SHA256SUMS', 'distribution-manifest.json'):
        download(base+name, directory/name)
    sums = {}
    for line in (directory/'SHA256SUMS').read_text().splitlines():
        checksum, name = line.split('  ', 1)
        if name in sums or '/' in name or '\\' in name or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise ValueError('Invalid public checksum list')
        sums[name] = checksum
    if sums.get('distribution-manifest.json') != digest(directory/'distribution-manifest.json'):
        raise ValueError('Public distribution manifest checksum mismatch')
    manifest = json.loads((directory/'distribution-manifest.json').read_text())
    validate_manifest(manifest, release=release, commit=commit)
    verify_public_tag(release, commit)
    if not re.fullmatch('sha256:[0-9a-f]{64}', manifest.get('container_digest', '')):
        raise ValueError('Missing published multi-architecture digest')
    arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'amd64'
    target = 'windows' if sys.platform == 'win32' else 'macos' if sys.platform == 'darwin' else 'linux'
    suffix = '-setup.exe' if target == 'windows' else '.dmg' if target == 'macos' else '.rpm' if rpm else '.deb'
    package = f'FlintEye-{version()}-{target}-{arch}{suffix}'
    script = 'install.ps1' if target == 'windows' else 'install.sh'
    for name in (() if container else (package, script)):
        download(base+name, directory/name)
        if digest(directory/name) != sums.get(name) or digest(directory/name) != manifest.get('files', {}).get(name, {}).get('sha256'):
            raise ValueError('Published asset differs from its checksums/provenance')
    if not container:
        (directory/'validation-build.json').write_text(json.dumps({'release': release, 'commit': commit,
            'version': version(), 'packages': {package: sums[package]}, 'origin': 'anonymous published release'}))
    (directory/'public-download.json').write_text(json.dumps({'release': release, 'commit': commit, 'anonymous': True,
        'base': base, 'package_sha256': sums.get(package), 'script_sha256': sums.get(script),
        'container_digest': manifest.get('container_digest')}, indent=2)+'\n')


def verify_image(directory: Path, image: str, *, release: str, commit: str) -> None:
    manifest = json.loads((directory/'distribution-manifest.json').read_text())
    validate_manifest(manifest, release=release, commit=commit)
    if image != manifest['image']: raise ValueError('Unexpected image reference')
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]
    expected = 'ghcr.io/noguhiro2002/flinteye@'+manifest['container_digest']
    if expected not in info.get('RepoDigests', []): raise ValueError('Public image digest mismatch')
    arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'amd64'
    if info.get('Architecture') != arch: raise ValueError('Public image architecture mismatch')
    if info['Config']['Labels'].get('org.opencontainers.image.revision') != commit: raise ValueError('Public image source mismatch')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--rpm', action='store_true')
    parser.add_argument('--container', action='store_true')
    parser.add_argument('--verify-image')
    args = parser.parse_args()
    if args.verify_image: verify_image(args.output, args.verify_image, release=args.release, commit=args.commit)
    else: prepare(args.output, release=args.release, commit=args.commit, rpm=args.rpm, container=args.container)
