"""Compare published releases without mistaking previews for stable updates."""
from __future__ import annotations

import re

RELEASES = 'https://github.com/noguhiro2002/FlintEye/releases'


def release_key(value: str):
    match = re.fullmatch(r'v?([0-9]+)\.([0-9]+)\.([0-9]+)(?:-preview\.([1-9][0-9]{0,5}))?', value)
    if not match:
        return None
    major, minor, patch, preview = match.groups()
    return (int(major), int(minor), int(patch), int(preview is None), int(preview or 0))


def update_result(releases: list[dict], *, current: str, current_release: str, channel: str) -> dict:
    result = {'current': current, 'current_release': current_release, 'channel': channel,
              'available': False, 'url': RELEASES}
    if channel == 'source':
        return {**result, 'message': 'Source checkout: update from the repository. Public installers are being prepared.'}
    candidates = []
    for release in releases:
        tag = release.get('tag_name', '')
        key = release_key(tag) if isinstance(tag, str) else None
        if release.get('draft') or key is None:
            continue
        preview = key[3] == 0
        if bool(release.get('prerelease')) != preview or (channel == 'stable' and preview):
            continue
        candidates.append((key, tag))
    if not candidates:
        return {**result, 'message': 'No published release is available for this update channel yet.'}
    key, tag = max(candidates)
    current_key = release_key(current_release)
    return {**result, 'available': current_key is not None and key > current_key,
            'version': tag, 'url': RELEASES+'/tag/'+tag}
