"""Assemble and verify the exact artifacts that will be tested and published."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

from release_lib import ARCHES, REPOSITORY, ROOT, digest, package_names, version, release_identity


def write_documentation(destination: Path) -> None:
    """Keep publication notes current, with reproducible bytes across both phases."""
    paths = [ROOT / name for name in ('README.md', 'README.ja.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')]
    paths += sorted((ROOT / 'docs').rglob('*.md'))
    paths += sorted((ROOT / '.github').glob('*.md'))
    paths += sorted(p for p in (ROOT / 'images').iterdir() if p.is_file())
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(paths):
            if path.is_symlink():
                raise ValueError(f'Documentation must not contain symlinks: {path}')
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def validate_publication_revision(build_commit: str, publication_commit: str, changed_paths: list[str]) -> None:
    """A tested binary can accompany newer distribution instructions, never newer app code."""
    if not all(re.fullmatch('[0-9a-f]{40}', value) for value in (build_commit, publication_commit)):
        raise ValueError('Expected full build and publication commit hashes')
    allowed = {'README.md', 'README.ja.md', 'compose.yaml',
               'packaging/release.py', 'packaging/publish_release.py',
               '.github/workflows/publish-release.yml', 'tests/test_release_packaging.py'}
    for name in changed_paths:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not (
            name in allowed or (name.startswith('docs/') and name.endswith('.md'))
        ):
            raise ValueError('Application/build inputs changed; rebuild before publication: ' + name)


def check_publication_revision(build_commit: str, publication_commit: str) -> None:
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', '--no-renames', '-z', build_commit, publication_commit], text=True)
    validate_publication_revision(build_commit, publication_commit, [p for p in changed.split('\0') if p])


def required_assets(v: str) -> set[str]:
    names = set(package_names(v))
    for arch in ARCHES:
        names.add(f'FlintEye-{v}-macos-{arch}-signature.json')
        for target in ('windows', 'macos', 'linux'):
            names.update([f'FlintEye-{v}-{target}-{arch}-sources.tar.gz',
                          f'FlintEye-{v}-{target}-{arch}-licenses.zip'])
        for kind in ('sources', 'notices', 'mediamtx-sources'):
            names.add(f'FlintEye-{v}-container-{arch}-{kind}.tar.gz')
    return names


def assemble(source: Path, destination: Path, commit: str) -> None:
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('A full source commit SHA is required')
    if destination.exists():
        raise ValueError('Use an empty output path; never mix artifacts from different builds')
    v = version()
    release_value, channel = release_identity()
    expected = required_assets(v) | {f'container-{arch}.tar.gz' for arch in ARCHES}
    found = {}
    for path in source.rglob('*'):
        if path.is_file() and path.name in expected:
            if path.is_symlink() or path.name in found or path.stat().st_size == 0:
                raise ValueError(f'Duplicate, empty or symlink artifact: {path.name}')
            found[path.name] = path
    if missing := expected - found.keys():
        raise ValueError('Missing artifacts: ' + ', '.join(sorted(missing)))
    public = destination / 'public'
    containers = destination / 'containers'
    public.mkdir(parents=True)
    containers.mkdir()
    for name, path in found.items():
        target = containers if name.startswith('container-') else public
        shutil.copy2(path, target / name)
    for name in ('install.sh', 'install.ps1'):
        text = (ROOT / 'packaging' / name).read_text().replace('@RELEASE_VERSION@', release_value)
        (public / name).write_text(text, encoding='utf-8', newline='\n')
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'compose.yaml'):
        shutil.copy2(ROOT / name, public / name)
    for name in ('ACCEPTANCE.md', 'ACCEPTANCE.ja.md'):
        text = (ROOT / 'docs' / name).read_text()
        text = re.sub(r'\]\(([^)\s]+\.md(?:#[^)\s]+)?)\)',
                      lambda m: f'](https://github.com/{REPOSITORY}/blob/{commit}/docs/{m[1]})', text)
        (public / name).write_text(text)
    write_documentation(public / 'documentation.zip')
    (public / 'RELEASE-NOTES.md').write_text(
        f'# FlintEye {v}\n\nSource commit: `{commit}`\n\n'
        'Desktop installers include Python, the browser UI, FFmpeg and MediaMTX.\n'
        'Quit FlintEye before upgrading. Settings and recordings are retained.\n'
        'Windows/macOS packages are unsigned. Follow the documented per-app OS confirmation.\n'
        'Source archives and notices below cover bundled third-party components.\n'
        'Read the installation, server and licensing guides in the repository before deployment.\n')
    (public / 'SHA256SUMS').write_text(''.join(
        f'{digest(path)}  {path.name}\n' for path in sorted(public.iterdir()) if path.is_file()))
    manifest = {'schema': 1, 'version': v, 'release_version': release_value, 'channel': channel, 'commit': commit,
                'run_id': os.environ.get('GITHUB_RUN_ID', 'local'),
                'files': {str(p.relative_to(destination)): digest(p)
                          for p in sorted(destination.rglob('*')) if p.is_file()}}
    (destination / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def verify(destination: Path, commit: str | None = None) -> dict:
    manifest = json.loads((destination / 'build-manifest.json').read_text())
    if manifest.get('schema') != 1 or manifest.get('version') != version():
        raise ValueError('Release manifest version does not match this checkout')
    if commit is not None and manifest.get('commit') != commit:
        raise ValueError('The tested artifacts belong to a different commit')
    files = manifest.get('files', {})
    actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*')
              if p.is_file() and p.name != 'build-manifest.json'}
    if actual != set(files):
        raise ValueError('Unexpected or missing files in the release bundle')
    required = {'public/' + name for name in required_assets(version())}
    required.update('containers/container-' + arch + '.tar.gz' for arch in ARCHES)
    required.update('public/' + name for name in ('install.sh', 'install.ps1', 'SHA256SUMS', 'compose.yaml', 'LICENSE', 'documentation.zip', 'ACCEPTANCE.ja.md'))
    if not required.issubset(files):
        raise ValueError('Incomplete release bundle')
    for name, expected in files.items():
        path = destination / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink():
            raise ValueError('Unsafe manifest path')
        if not re.fullmatch('[0-9a-f]{64}', expected) or digest(path) != expected:
            raise ValueError(f'Artifact checksum mismatch: {name}')
    sums = (destination / 'public/SHA256SUMS').read_text().splitlines()
    wanted = [f'{digest(p)}  {p.name}' for p in sorted((destination / 'public').iterdir()) if p.name != 'SHA256SUMS']
    if sums != wanted:
        raise ValueError('Public checksums do not cover the complete public asset set')
    return manifest


def validate_publish_context(repo: dict, run: dict, *, commit: str, enabled: bool,
                             tested: bool, licenses_reviewed: bool, ref: str, channel: str = 'stable') -> None:
    if repo.get('full_name') != REPOSITORY:
        raise ValueError('Publishing is restricted to the FlintEye repository')
    if channel == 'private-test':
        if repo.get('private') is not True or repo.get('visibility') != 'private':
            raise ValueError('Private testing requires a private repository')
    elif channel in {'stable', 'public-preview'}:
        if repo.get('private', True) or repo.get('visibility') != 'public':
            raise ValueError('Public publishing requires a public repository')
        if not (enabled and licenses_reviewed) or (channel == 'stable' and not tested):
            raise ValueError('Enable publishing and review licenses/sources; stable releases also require device acceptance')
    else:
        raise ValueError('Unknown publication channel')
    branch = repo['default_branch']
    if ref != 'refs/heads/' + branch:
        raise ValueError('Publish from the default branch only')
    if (run.get('path') != '.github/workflows/build-release.yml' or
        run.get('event') != 'workflow_dispatch' or run.get('conclusion') != 'success' or
        run.get('head_sha') != commit or run.get('head_branch') != branch or
        run.get('head_repository', {}).get('full_name') != REPOSITORY):
        raise ValueError('Select a successful manual Build release run for this exact default-branch commit')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['assemble', 'verify', 'guard', 'version'])
    parser.add_argument('--input', type=Path, default=Path('build-artifacts'))
    parser.add_argument('--output', type=Path, default=Path('release-bundle'))
    parser.add_argument('--commit', default=os.environ.get('GITHUB_SHA'))
    parser.add_argument('--run-id')
    parser.add_argument('--channel', choices=['private-test', 'public-preview', 'stable'], default='public-preview')
    args = parser.parse_args()
    if args.action == 'version':
        print(version())
    elif args.action == 'assemble':
        assemble(args.input, args.output, args.commit or '')
        verify(args.output, args.commit)
    elif args.action == 'verify':
        print(json.dumps(verify(args.output, args.commit), indent=2))
    elif args.action == 'guard':
        if not args.run_id or not args.run_id.isdigit():
            raise ValueError('A numeric build run ID is required')
        def api(endpoint):
            return json.loads(subprocess.check_output(['gh', 'api', endpoint], text=True))
        repo = api('repos/' + REPOSITORY)
        run = api(f'repos/{REPOSITORY}/actions/runs/{args.run_id}')
        build_commit = run['head_sha']
        check_publication_revision(build_commit, args.commit)
        validate_publish_context(repo, run, commit=build_commit,
            enabled=os.environ.get('PUBLIC_PREVIEW_ENABLED' if args.channel == 'public-preview' else 'PUBLIC_RELEASE_ENABLED') == 'true',
            tested=os.environ.get('DEVICE_TESTS_CONFIRMED') == 'true',
            licenses_reviewed=os.environ.get('LICENSE_REVIEW_CONFIRMED') == 'true',
            ref=os.environ.get('GITHUB_REF', ''), channel=args.channel)
        head = api(f'repos/{REPOSITORY}/commits/{repo["default_branch"]}')
        if head['sha'] != args.commit:
            raise ValueError('Default branch moved; rerun publication from its current commit')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write('build_commit=' + build_commit + '\n')
        print('Publication prerequisites verified; no remote state changed.')


if __name__ == '__main__':
    main()
