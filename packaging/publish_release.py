"""Distribute verified archives without rebuilding or changing visibility."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from release import verify, validate_publish_context, check_publication_revision, write_documentation
from release_lib import ARCHES, IMAGE, REPOSITORY, ROOT, digest, version
from check_release_order import check_order


DOCKER_MANIFEST = 'application/vnd.docker.distribution.manifest.v2+json'
OCI_MANIFEST = 'application/vnd.oci.image.manifest.v1+json'


def run(*command: str) -> str:
    return subprocess.check_output(command, text=True).strip()


def api(endpoint: str, *, missing: bool = False):
    result = subprocess.run(['gh', 'api', endpoint], text=True, capture_output=True)
    if result.returncode:
        if missing and 'HTTP 404' in result.stderr:
            return None
        raise RuntimeError(f'GitHub API failed for {endpoint}: {result.stderr.strip()}')
    return json.loads(result.stdout)


def find_release(tag: str) -> dict | None:
    # The tag endpoint returns published releases only, even for a maintainer.
    pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
                           f'repos/{REPOSITORY}/releases?per_page=100'))
    matches = [item for page in pages for item in page if item['tag_name'] == tag]
    if len(matches) > 1:
        raise ValueError('Multiple releases use the requested tag; resolve the ambiguity first')
    return matches[0] if matches else None


def release_version(channel: str, number: str) -> str:
    if channel == 'stable':
        return version()
    if channel not in {'private-test', 'public-preview'} or not re.fullmatch(r'[1-9][0-9]{0,5}', number):
        raise ValueError('Expected a preview channel with a positive preview number, or stable')
    return version() + '-preview.' + number


def check_visibility(channel: str, *, require_package: bool = False, staging: bool = False) -> dict | None:
    repository = api('repos/' + REPOSITORY)
    expected = 'private' if channel == 'private-test' else 'public'
    if repository.get('visibility') != expected or repository.get('private') != (expected == 'private'):
        raise ValueError('Repository visibility does not match the selected channel')
    package = api('users/' + REPOSITORY.split('/')[0] + '/packages/container/flinteye', missing=True)
    if package is None:
        if require_package:
            raise ValueError('Cannot verify the uploaded GHCR package')
    else:
        allowed = {expected, 'private'} if staging else {expected}
        if package.get('visibility') not in allowed:
            raise ValueError('GHCR visibility does not match the selected channel')
        if require_package and (package.get('repository') or {}).get('full_name') != REPOSITORY:
            raise ValueError('GHCR package is not linked to this repository')
    return package


def link_release_documentation(text: str, revision: str) -> str:
    return re.sub(r'\]\(([\w.-][\w./-]*\.md(?:#[^)\s]+)?)\)',
                  rf'](https://github.com/{REPOSITORY}/blob/{revision}/docs/\1)', text)


def prepare(bundle: Path, output: Path, commit: str, run_id: str, channel: str, number: str,
            *, tested: bool = False, publication_commit: str | None = None) -> dict:
    manifest = verify(bundle, commit)
    if str(manifest['run_id']) != run_id:
        raise ValueError('Build manifest run ID differs from the selected run')
    if output.exists():
        raise ValueError('Use an empty distribution directory')
    image_version = release_version(channel, number)
    if channel in {'public-preview', 'stable'}:
        expected_channel = 'preview' if channel == 'public-preview' else 'stable'
        if manifest.get('release_version') != image_version or manifest.get('channel') != expected_channel:
            raise ValueError('Build a new bundle with the matching embedded release version/channel')
    tag = 'v' + image_version
    output.mkdir(parents=True)
    excluded = {'SHA256SUMS', 'RELEASE-NOTES.md'}
    if channel == 'private-test':
        excluded |= {'install.sh', 'install.ps1'}
    for source in (bundle / 'public').iterdir():
        if source.name not in excluded:
            shutil.copy2(source, output / source.name)
    if channel != 'private-test':
        for name in ('install.sh', 'install.ps1'):
            text = (ROOT / 'packaging' / name).read_text().replace('@RELEASE_VERSION@', image_version)
            (output / name).write_text(text, encoding='utf-8', newline='\n')
    shutil.copy2(bundle / 'build-manifest.json', output / 'build-manifest.json')
    write_documentation(output / 'documentation.zip',
                        release=image_version if channel == 'public-preview' else None)
    for language in ('', '.ja'):
        name = 'ACCEPTANCE' + language + '.md'
        text = link_release_documentation((ROOT / 'docs' / name).read_text(), publication_commit or commit)
        (output / name).write_text(text)
    # The attached Compose pins this distribution, even for a later preview number.
    compose = (ROOT / 'compose.yaml').read_text()
    compose = re.sub(r'ghcr\.io/noguhiro2002/flinteye:[\w.-]+', IMAGE + ':' + image_version, compose)
    (output / 'compose.yaml').write_text(compose)
    desktop_compose = re.sub(r'ghcr\.io/noguhiro2002/flinteye:[\w.-]+', IMAGE + ':' + image_version, (ROOT/'deploy/compose.desktop.yaml').read_text())
    (output/'compose.desktop.yaml').write_text(desktop_compose)
    for language in ('en', 'ja'):
        source = ROOT / 'docs' / ('RELEASE_NOTES.md' if language == 'en' else 'RELEASE_NOTES.ja.md')
        text = source.read_text()
        status = ('Private testing — real-device validation in progress' if language == 'en' else '検証版・実機検証中') if channel == 'private-test' else ('Stable release' if language == 'en' else '正式版')
        validation = ('Automated checks passed. This repository and its container package remain private. This is not a public stable release.' if language == 'en' else '自動検証済みです。リポジトリとコンテナは非公開を維持しています。一般公開・正式版への昇格は行っていません。') if channel == 'private-test' else ''
        if channel == 'public-preview':
            status = 'UNDER DEVELOPMENT — Public preview' if language == 'en' else 'UNDER DEVELOPMENT — Public preview'
            validation = ('This is a public development preview, not a stable release. Automated checks and the required Windows x64, M1 Mac and Linux x64 device checks have been confirmed. Other hardware combinations still require real-device validation.' if language == 'en' else 'これはパブリック開発プレビューであり、安定版リリースではありません。自動チェックおよび必須のWindows x64、M1 Mac、Linux x64デバイスチェックは確認済みです。その他のハードウェアの組み合わせについては、引き続き実機での検証が必要です。')
            if not tested:
                validation = ('Automated package checks passed. This development preview is published for installation-path and physical-device testing. Real-device acceptance is still in progress; this is not a stable release.' if language == 'en' else '自動パッケージチェックが合格しました。この開発プレビューは、配布URLからのインストールおよび実機テスト用に公開されています。実機での受け入れテストは現在も進行中であるため、安定版ではありません。')
        for key, value in {'TAG':tag, 'STATUS':status, 'VERSION':version(), 'COMMIT':commit,
                           'RUN_ID':run_id, 'IMAGE_VERSION':image_version, 'VALIDATION':validation}.items():
            text = text.replace('@' + key + '@', value)
        if re.search(r'@[A-Z_]+@', text):
            raise ValueError('Unresolved release note placeholder')
        text = text.replace('](RELEASE_NOTES.ja.md)', '](https://github.com/' + REPOSITORY + '/releases/download/' + tag + '/RELEASE-NOTES.ja.md)')
        text = text.replace('](RELEASE_NOTES.md)', '](https://github.com/' + REPOSITORY + '/releases/download/' + tag + '/RELEASE-NOTES.en.md)')
        text = link_release_documentation(text, publication_commit or commit)
        (output / f'RELEASE-NOTES.{language}.md').write_text(text)
    return {'schema':1, 'channel':channel, 'tag':tag, 'application_version':version(),
            'commit':commit, 'build_run_id':run_id, 'build_manifest_sha256':digest(bundle/'build-manifest.json'),
            'image':IMAGE+':'+image_version, 'device_acceptance_pending':not tested,
            'publication_commit':publication_commit or commit}


def finalize(output: Path, metadata: dict) -> None:
    metadata['files'] = {p.name: {'size':p.stat().st_size, 'sha256':digest(p)}
                         for p in sorted(output.iterdir()) if p.name not in ('distribution-manifest.json','SHA256SUMS')}
    (output / 'distribution-manifest.json').write_text(json.dumps(metadata, indent=2)+'\n')
    (output / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in sorted(output.iterdir()) if p.name != 'SHA256SUMS'))


def verify_remote_assets(release_id: int, output: Path) -> None:
    expected = {p.name: p for p in output.iterdir()}
    # Asset digests may take a short time to become visible after upload.
    for attempt in range(6):
        pages = json.loads(run('gh','api','--paginate','--slurp',f'repos/{REPOSITORY}/releases/{release_id}/assets?per_page=100'))
        actual = {asset['name']:asset for page in pages for asset in page}
        if set(actual) == set(expected) and all(
            actual[name]['size'] == path.stat().st_size and actual[name].get('digest') == 'sha256:'+digest(path)
            for name,path in expected.items()):
            return
        if attempt < 5:
            time.sleep(5)
    raise ValueError('Uploaded asset names, sizes or SHA-256 digests do not match')


def registry_descriptor(reference: str, *, missing: bool = False) -> dict | None:
    result = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', reference,
                             '--format', '{{json .Manifest}}'], capture_output=True, text=True)
    if result.returncode:
        if missing and any(term in result.stderr.lower() for term in ('not found', 'manifest unknown')):
            return None
        raise RuntimeError(f'Cannot inspect image {reference}: {result.stderr.strip()}')
    descriptor = json.loads(result.stdout)
    if not re.fullmatch('sha256:[0-9a-f]{64}', descriptor.get('digest', '')):
        raise ValueError(f'Invalid registry image digest: {reference}')
    return descriptor


def architecture_receipt(tag: str, descriptor: dict, image_id: str) -> dict:
    if descriptor.get('mediaType') not in (DOCKER_MANIFEST, OCI_MANIFEST):
        raise ValueError(f'Architecture tag does not address a single image: {tag}')
    reference = IMAGE + '@' + descriptor['digest']
    manifest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', reference, '--raw'))
    # Docker image IDs are config digests, which also bind the uncompressed layers.
    if manifest.get('config', {}).get('digest') != image_id:
        raise ValueError(f'Architecture tag does not match the tested image ID: {tag}')
    return {'tag': tag, 'digest': descriptor['digest'], 'image_id': image_id}


def verify_container_receipt(metadata: dict, commit: str) -> None:
    architecture_images = metadata['container_architectures']
    if set(architecture_images) != set(ARCHES):
        raise ValueError('Incomplete container architecture receipt')
    reference = IMAGE + '@' + metadata['container_digest']
    index = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', reference, '--raw'))
    manifests = index.get('manifests', [])
    platforms = {m['platform']['architecture']: m for m in manifests}
    if len(manifests) != len(ARCHES) or set(platforms) != set(ARCHES):
        raise ValueError('Wrong container platforms')
    for arch in ARCHES:
        item = architecture_images[arch]
        if not re.fullmatch('sha256:[0-9a-f]{64}', item['digest']) or platforms[arch]['digest'] != item['digest'] or platforms[arch]['platform']['os'] != 'linux':
            raise ValueError('Container receipt platform/digest mismatch')
        config = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', IMAGE+'@'+item['digest'], '--format', '{{json .Image}}'))
        labels = config['config']['Labels']
        if config['architecture'] != arch or labels.get('org.opencontainers.image.revision') != commit or labels.get('org.opencontainers.image.version') != version() or labels.get('org.opencontainers.image.source') != 'https://github.com/'+REPOSITORY:
            raise ValueError('Container receipt source/version mismatch')
        if item['tag'] != metadata['image']+'-'+arch or registry_descriptor(item['tag'])['digest'] != item['digest']:
            raise ValueError('Versioned architecture tag changed')
    if registry_descriptor(metadata['image'])['digest'] != metadata['container_digest']:
        raise ValueError('Versioned image tag changed')


def distribute_containers(bundle: Path, metadata: dict, commit: str, *, has_package: bool) -> None:
    image = metadata['image']
    tags = {arch: image + '-' + arch for arch in ARCHES}
    descriptors = {
        arch: registry_descriptor(tag, missing=True) if has_package else None
        for arch, tag in tags.items()
    }
    index = registry_descriptor(image, missing=True) if has_package else None
    if index is not None and any(descriptor is None for descriptor in descriptors.values()):
        raise ValueError('Existing multi-architecture tag has missing architecture tags')
    if has_package and metadata['channel'] == 'private-test' and registry_descriptor(IMAGE + ':latest', missing=True):
        raise ValueError('Image tag already exists: ' + IMAGE + ':latest')

    image_ids = {}
    architecture_images = {}
    for arch, tag in tags.items():
        subprocess.run(['docker', 'load', '--input', str(bundle / 'containers' / f'container-{arch}.tar.gz')], check=True)
        local = 'flinteye:release-' + arch
        info = json.loads(run('docker', 'image', 'inspect', local))[0]
        labels = info['Config']['Labels']
        if (info['Architecture'] != arch or info['Os'] != 'linux'
                or labels.get('org.opencontainers.image.revision') != commit
                or labels.get('org.opencontainers.image.version') != version()
                or labels.get('org.opencontainers.image.source') != 'https://github.com/' + REPOSITORY):
            raise ValueError('Loaded container identity does not match the tested source and CPU')
        image_ids[arch] = info['Id']
        if descriptors[arch] is not None:
            architecture_images[arch] = architecture_receipt(tag, descriptors[arch], info['Id'])

    for arch, tag in tags.items():
        if arch in architecture_images:
            continue
        subprocess.run(['docker', 'tag', 'flinteye:release-' + arch, tag], check=True)
        subprocess.run(['docker', 'push', '--platform', 'linux/' + arch, tag], check=True)
        descriptors[arch] = registry_descriptor(tag)
        architecture_images[arch] = architecture_receipt(tag, descriptors[arch], image_ids[arch])

    if index is None:
        command = ['docker', 'buildx', 'imagetools', 'create']
        # Buildx uses a Docker manifest list when every source is a Docker manifest.
        if any(descriptor['mediaType'] == OCI_MANIFEST for descriptor in descriptors.values()):
            description = ('FlintEye UNDER DEVELOPMENT; public preview' if metadata['channel'] == 'public-preview'
                           else 'FlintEye camera monitoring and recording')
            url = 'https://github.com/' + REPOSITORY
            command.extend([
                '--annotation', 'index:org.opencontainers.image.description=' + description,
                '--annotation', 'index:org.opencontainers.image.source=' + url,
                '--annotation', 'index:org.opencontainers.image.documentation=' + url
                + '/blob/' + metadata['publication_commit'] + '/docs/DOCKER.md',
            ])
        references = [IMAGE + '@' + architecture_images[arch]['digest'] for arch in ARCHES]
        subprocess.run([*command, '-t', image, *references], check=True)
        index = registry_descriptor(image)

    metadata['container_architectures'] = architecture_images
    metadata['container_digest'] = index['digest']
    verify_container_receipt(metadata, commit)


def finish_publication(args, metadata: dict, commit: str) -> None:
    tag = metadata['tag']
    release = find_release(tag)
    if not release or not release.get('draft') or release.get('target_commitish') != commit:
        raise ValueError('Only the verified draft for this exact commit can be published')
    verify_container_receipt(metadata, commit)
    check_visibility(args.channel, require_package=True)
    verify_remote_assets(release['id'], args.output)
    preview = args.channel == 'public-preview'
    subprocess.run(['gh', 'release', 'edit', tag, '--repo', REPOSITORY, '--draft=false',
                    '--prerelease='+str(preview).lower(), '--latest='+str(not preview).lower()], check=True)
    published = api(f'repos/{REPOSITORY}/releases/tags/{tag}')
    if published['draft'] or published['prerelease'] != preview:
        raise ValueError('Published release has the wrong development/stable status')
    if not preview and api(f'repos/{REPOSITORY}/releases/latest')['id'] != release['id']:
        raise ValueError('Release did not become normal Latest')
    reference = api(f'repos/{REPOSITORY}/git/ref/tags/{tag}')['object']
    if reference['type'] == 'tag':
        reference = api(f'repos/{REPOSITORY}/git/tags/{reference["sha"]}')['object']
    if reference['type'] != 'commit' or reference['sha'] != commit:
        raise ValueError('Release tag does not point at the tested commit')
    if args.channel == 'stable':
        subprocess.run(['docker','buildx','imagetools','create','-t',IMAGE+':latest',IMAGE+'@'+metadata['container_digest']],check=True)
    print(json.dumps({'release':published['html_url'],'package':IMAGE,'container_digest':metadata['container_digest'],'verified_assets':len(list(args.output.iterdir()))},indent=2))


def publish(args) -> None:
    publication_commit = os.environ['GITHUB_SHA']
    repo = api('repos/'+REPOSITORY)
    build = api(f'repos/{REPOSITORY}/actions/runs/{args.run_id}')
    commit = build['head_sha']
    if args.channel in {'public-preview', 'stable'}:
        from release import check_development_acceptance
        check_development_acceptance(commit, channel=args.channel,
                                     tested=os.environ.get('DEVICE_TESTS_CONFIRMED') == 'true')
    check_publication_revision(commit, publication_commit)
    flag = 'PUBLIC_PREVIEW_ENABLED' if args.channel == 'public-preview' else 'PUBLIC_RELEASE_ENABLED'
    validate_publish_context(repo, build, commit=commit, ref=os.environ['GITHUB_REF'], channel=args.channel,
                             enabled=os.environ.get(flag)=='true',
                             tested=os.environ.get('DEVICE_TESTS_CONFIRMED')=='true',
                             licenses_reviewed=os.environ.get('LICENSE_REVIEW_CONFIRMED')=='true')
    if api(f'repos/{REPOSITORY}/commits/{repo["default_branch"]}')['sha'] != publication_commit:
        raise ValueError('Default branch moved; rerun publication from its current commit')
    package = check_visibility(args.channel, staging=args.phase == 'prepare')
    metadata = prepare(args.bundle, args.output, commit, args.run_id, args.channel, args.preview_number,
                       tested=os.environ.get('DEVICE_TESTS_CONFIRMED')=='true', publication_commit=publication_commit)
    tag, image = metadata['tag'], metadata['image']
    if args.phase == 'publish':
        remote = args.output.parent / (args.output.name+'-receipt')
        remote.mkdir()
        subprocess.run(['gh','release','download',tag,'--repo',REPOSITORY,'--pattern','distribution-manifest.json','--dir',str(remote)],check=True)
        receipt = json.loads((remote/'distribution-manifest.json').read_text())
        if any(receipt.get(key) != value for key,value in metadata.items()):
            raise ValueError('Draft receipt is for a different source, build, channel or version')
        for key in ('container_architectures','container_digest'):
            metadata[key] = receipt[key]
        if not re.fullmatch('sha256:[0-9a-f]{64}', metadata['container_digest']):
            raise ValueError('Invalid container digest in draft')
        finalize(args.output,metadata)
        finish_publication(args,metadata,commit)
        return
    if find_release(tag) or api(f'repos/{REPOSITORY}/git/ref/tags/{tag}', missing=True):
        raise ValueError('Release or tag already exists; never overwrite it')
    if args.channel == 'stable':
        pages=json.loads(run('gh','api','--paginate','--slurp',f'repos/{REPOSITORY}/releases?per_page=100'))
        check_order(version(), [r for page in pages for r in page])
    distribute_containers(args.bundle, metadata, commit, has_package=package is not None)
    check_visibility(args.channel,require_package=True,staging=True)
    finalize(args.output,metadata)
    body=args.output.parent/(args.output.name+'-body.md')
    body.write_text((args.output/'RELEASE-NOTES.en.md').read_text()+'\n---\n\n'+(args.output/'RELEASE-NOTES.ja.md').read_text())
    title=f'FlintEye {tag} — UNDER DEVELOPMENT' if args.channel=='public-preview' else f'FlintEye {tag} — '+('Private testing' if args.channel=='private-test' else 'Stable release')
    subprocess.run(['gh','release','create',tag,'--repo',REPOSITORY,'--target',commit,'--draft','--title',title,'--notes-file',str(body),*[str(p) for p in sorted(args.output.iterdir())]],check=True)
    release_id=json.loads(run('gh','release','view',tag,'--repo',REPOSITORY,'--json','databaseId'))['databaseId']
    verify_remote_assets(release_id,args.output)
    print(json.dumps({'draft':tag,'container_digest':metadata['container_digest'],
                      'next':'Confirm package visibility, then rerun phase=publish with the same commit and build run.'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel',choices=['private-test','public-preview','stable'],required=True)
    parser.add_argument('--phase',choices=['prepare','publish'],default='prepare')
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--preview-number',default='1')
    parser.add_argument('--bundle',type=Path,default=Path('release-bundle'))
    parser.add_argument('--output',type=Path,default=Path('distribution'))
    args=parser.parse_args()
    if not args.run_id.isdigit():
        raise ValueError('Expected numeric build run ID')
    publish(args)
