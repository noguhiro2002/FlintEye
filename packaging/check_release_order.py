"""Stable ordering ignores testing tags, even when a preview is GitHub Latest."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys


def check_order(current: str, releases: list[dict]) -> None:
    if not re.fullmatch(r'\d+\.\d+\.\d+', current):
        raise ValueError('Expected stable X.Y.Z version')
    for release in releases:
        tag = release.get('tag_name', '')
        if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
            continue
        if tuple(map(int, current.split('.'))) <= tuple(map(int, tag[1:].split('.'))):
            raise ValueError('New stable version must be newer than all existing stable releases')


if __name__ == '__main__':
    pages = json.loads(subprocess.check_output([
        'gh', 'api', '--paginate', '--slurp', f'repos/{os.environ["GITHUB_REPOSITORY"]}/releases?per_page=100'], text=True))
    check_order(sys.argv[1], [release for page in pages for release in page])
