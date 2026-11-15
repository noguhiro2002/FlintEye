"""Non-sensitive build identity, also bundled in installed applications."""
from functools import lru_cache
import json
import re
from flinteye_app._version import VERSION, RELEASE_VERSION, RELEASE_CHANNEL
from flinteye_app.flinteye_runtime import application_dir


@lru_cache(maxsize=1)
def build_info() -> dict:
    commit = None
    dirty = None
    try:
        info = json.loads((application_dir() / 'build-info.json').read_text(encoding='utf-8'))
        if re.fullmatch(r'[0-9a-f]{40}', str(info.get('commit', ''))):
            commit = info['commit']
        dirty = info.get('dirty') is True
    except (OSError, ValueError, AttributeError):
        pass
    return {'version': VERSION, 'release': RELEASE_VERSION, 'channel': RELEASE_CHANNEL,
            'commit': commit, 'dirty': dirty}
