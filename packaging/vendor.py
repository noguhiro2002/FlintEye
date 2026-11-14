"""Fetch verified source archives, prepare MediaMTX, and retain redistribution material."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import http.client
import ssl
import urllib.error
import urllib.request
import zipfile

from release_lib import ROOT, digest

LOCK = json.loads((ROOT / 'packaging/vendor-lock.json').read_text())
VENDOR = ROOT / 'vendor'


def fetch(url: str, target: Path, expected: str) -> Path:
    if not url.startswith('https://'):
        raise ValueError('Refusing a non-HTTPS download')
    if target.exists() and digest(target) == expected:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        temporary = None
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                if not response.url.startswith('https://'):
                    raise ValueError('Refusing a non-HTTPS download')
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.',
                                                 suffix='.partial', delete=False) as stream:
                    temporary = Path(stream.name)
                    shutil.copyfileobj(response, stream)
            if digest(temporary) != expected:
                raise ValueError(f'Checksum mismatch: {target.name}')
            temporary.replace(target)
            return target
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
            reason = getattr(error, 'reason', error)
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise
            if isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise RuntimeError(
                    f'Could not download {target.name} after 3 attempts: {reason}. '
                    'Check network/proxy access, or use the verified source-cache procedure '
                    'in docs/DOCKER.md. TLS verification and SHA-256 checks remain required.'
                ) from error
            print(f'Download interrupted for {target.name}; retrying ({attempt+2}/3)', flush=True)
            time.sleep(2 ** attempt)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def media_cache(directory: Path, source_archive: Path | None = None) -> None:
    """Prepare the three pinned downloads needed by the Docker MediaMTX build.

    A release's container-*-mediamtx-sources.tar.gz can supply them without a
    network request. Only selected files are read; no archive paths are extracted.
    """
    directory.mkdir(parents=True, exist_ok=True)

    def obtain(item: dict) -> Path:
        target = directory / item['filename']
        if source_archive is None:
            return fetch(item['url'], target, item['sha256'])
        with tarfile.open(source_archive) as archive:
            names = {f'vendor/downloads/{target.name}', f'downloads/{target.name}'}
            matches = [m for m in archive if m.name in names and m.isfile()]
            if len(matches) != 1:
                raise ValueError(f'Source archive must contain exactly one download: {target.name}')
            temporary = None
            try:
                with archive.extractfile(matches[0]) as source, tempfile.NamedTemporaryFile(
                    dir=directory, prefix=target.name+'.', suffix='.partial', delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    shutil.copyfileobj(source, stream)
                if digest(temporary) != item['sha256']:
                    raise ValueError(f'Checksum mismatch: {target.name}')
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return target

    media = obtain(LOCK['sources']['mediamtx'])
    with tarfile.open(media) as archive:
        def text_file(suffix: str) -> str:
            members = [m for m in archive.getmembers() if m.name.endswith(suffix) and m.isfile()]
            if len(members) != 1 or members[0].size > 1024:
                raise ValueError('Unexpected pinned MediaMTX HLS metadata')
            return archive.extractfile(members[0]).read().decode('utf-8').strip()
        hls_version = text_file('/internal/servers/hls/hlsjsdownloader/VERSION')
        hls_hash = text_file('/internal/servers/hls/hlsjsdownloader/HASH')
    license_info = LOCK['assets']['hls_license']
    if hls_version != license_info['version']:
        raise ValueError('Pinned HLS source and license versions differ')
    obtain({'url': f'https://github.com/video-dev/hls.js/releases/download/{hls_version}/release.zip',
            'filename': f'hls-{hls_version}.zip', 'sha256': hls_hash})
    obtain(license_info)
    print(f'Verified MediaMTX download cache: {directory.resolve()}')


def source(name: str) -> Path:
    item = LOCK['sources'][name]
    archive = fetch(item['url'], VENDOR / 'downloads' / item['filename'], item['sha256'])
    destination = VENDOR / 'src' / name
    if destination.exists():
        return destination
    temporary = VENDOR / 'src' / ('.extract-' + name)
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(archive) as stream:
            stream.extractall(temporary, filter='data')
        children = list(temporary.iterdir())
        if len(children) != 1 or not children[0].is_dir():
            raise ValueError(f'Unexpected source archive layout: {name}')
        children[0].rename(destination)
    finally:
        shutil.rmtree(temporary)
    return destination


def mediamtx() -> None:
    tree = source('mediamtx')
    # FlintEye supports USB/IP inputs. Exclude the unrelated, precompiled native
    # CSI-camera helper so all bundled executable code comes from our source build.
    rpi = tree / 'internal/staticsources/rpicamera'
    for path in rpi.glob('*.go'):
        text = path.read_text()
        if 'flinteye_no_rpicamera' in text:
            continue
        if path.name == 'source_other.go':
            text = text.replace('//go:build !linux || (!arm && !arm64)',
                                '//go:build flinteye_no_rpicamera || !linux || (!arm && !arm64)')
        elif path.name != 'downloader.go' and ('_arm' in path.name):
            lines = text.splitlines()
            if lines and lines[0].startswith('//go:build '):
                lines[0] = '//go:build !flinteye_no_rpicamera && (' + lines[0][11:] + ')'
            else:
                lines = ['//go:build !flinteye_no_rpicamera', '', *lines]
            text = '\n'.join(lines) + '\n'
        path.write_text(text)
    (tree / 'FLINTEYE-MODIFICATIONS.txt').write_text(
        'FlintEye build: adds the flinteye_no_rpicamera build tag to disable the\n'
        'precompiled Raspberry Pi CSI helper. USB/IP inputs remain available.\n'
        'VERSION is supplied from the verified source archive version.\n')
    (tree / 'internal/core/VERSION').write_text('v' + LOCK['sources']['mediamtx']['version'])
    hls = tree / 'internal/servers/hls'
    hls_version = (hls / 'hlsjsdownloader/VERSION').read_text().strip()
    expected = (hls / 'hlsjsdownloader/HASH').read_text().strip()
    archive = fetch(f'https://github.com/video-dev/hls.js/releases/download/{hls_version}/release.zip',
                    VENDOR / 'downloads' / f'hls-{hls_version}.zip', expected)
    with zipfile.ZipFile(archive) as stream:
        (hls / 'hls.min.js').write_bytes(stream.read('dist/hls.min.js'))
    license_info = LOCK['assets']['hls_license']
    if license_info['version'] != hls_version:
        raise ValueError('Update the pinned HLS license when updating MediaMTX')
    license_file = fetch(license_info['url'], VENDOR / 'downloads' / license_info['filename'], license_info['sha256'])
    hls_notices = VENDOR / 'licenses/hls.js'
    hls_notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(license_file, hls_notices / 'LICENSE')
    # Downloads are created with private temporary-file permissions. Installed
    # third-party notices must also be readable by users other than the builder.
    (hls_notices / 'LICENSE').chmod(0o644)
    env = {**os.environ, 'CGO_ENABLED': '0'}
    subprocess.run(['go', 'mod', 'download'], cwd=tree, env=env, check=True)
    subprocess.run(['go', 'mod', 'verify'], cwd=tree, env=env, check=True)
    subprocess.run(['go', 'mod', 'vendor'], cwd=tree, env=env, check=True)
    (VENDOR / 'bin').mkdir(parents=True, exist_ok=True)
    output = VENDOR / 'bin' / ('mediamtx.exe' if os.name == 'nt' else 'mediamtx')
    subprocess.run(['go', 'build', '-mod=vendor', '-trimpath', '-buildvcs=false',
                    '-tags=flinteye_no_rpicamera', '-o', str(output), '.'], cwd=tree, env=env, check=True)


def collect_notices() -> None:
    notices = VENDOR / 'licenses'
    notices.mkdir(exist_ok=True)
    for component in (VENDOR / 'src').iterdir():
        if not component.is_dir():
            continue
        for path in component.rglob('*'):
            if path.is_file() and path.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'FTL.', 'PATENTS')):
                target = notices / component.name / path.relative_to(component)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)


def finish() -> None:
    collect_notices()
    shutil.copy2(ROOT / 'packaging/vendor-lock.json', VENDOR / 'vendor-lock.json')
    ffmpeg = VENDOR / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    configuration = subprocess.check_output([str(ffmpeg), '-hide_banner', '-buildconf'], text=True, stderr=subprocess.STDOUT)
    if '--enable-nonfree' in configuration:
        raise ValueError('Non-redistributable FFmpeg configuration')
    (VENDOR / 'ffmpeg-buildconf.txt').write_text(configuration)
    (VENDOR / 'THIRD_PARTY_NOTICES.txt').write_text(
        'FlintEye native dependencies\n\n'
        'FFmpeg with libx264: GPL; see licenses/ffmpeg and licenses/x264.\n'
        'MediaMTX: MIT. FreeType and HarfBuzz retain their own licenses.\n'
        'MediaMTX excludes its native Raspberry Pi CSI helper; see source modifications.\n'
        'Exact versions and source hashes: vendor-lock.json. Build configuration: ffmpeg-buildconf.txt.\n'
        'Corresponding sources, patches and build recipes accompany each release.\n'
        'FlintEye restrictions do not apply to third-party components.\n')
    with tarfile.open(VENDOR / 'corresponding-source.tar.gz', 'w:gz') as archive:
        for name in ('src', 'downloads', 'vendor-lock.json', 'ffmpeg-buildconf.txt', 'THIRD_PARTY_NOTICES.txt'):
            archive.add(VENDOR / name, arcname=name)
        archive.add(ROOT / 'flinteye_app/_version.py', arcname='flinteye-build/flinteye_app/_version.py')
        archive.add(ROOT / 'packaging', arcname='flinteye-build/packaging',
                    filter=lambda info: None if '__pycache__' in info.name else info)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['fetch', 'mediamtx', 'notices', 'finish', 'media-cache'])
    parser.add_argument('names', nargs='*')
    parser.add_argument('--cache-dir', type=Path, default=VENDOR / 'downloads')
    parser.add_argument('--from-source-archive', type=Path)
    args = parser.parse_args()
    if args.action == 'media-cache':
        media_cache(args.cache_dir, args.from_source_archive)
    elif args.action == 'fetch':
        for name in args.names or LOCK['sources']:
            print(source(name))
    elif args.action == 'mediamtx':
        mediamtx()
    elif args.action == 'notices':
        collect_notices()
    else:
        finish()


if __name__ == '__main__':
    main()
