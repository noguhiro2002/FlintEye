"""Run the Settings form against the real API in a stopped, disposable profile."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from lifecycle import owned_profile
from lifecycle_common import ROOT, request_quit, seed_runtime, stop_process, wait_http


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='flinteye-settings-qa-') as directory:
        profile = Path(directory)/'profile'
        owned_profile(profile)
        port = seed_runtime(profile, str(profile), 'unused-qa-command')
        (profile/'monitoring.json').write_text(json.dumps({
            'desired_running': False, 'resume_on_startup': False, 'clean_stop': True}))
        (profile/'alternate recordings').mkdir()
        args = [sys.executable, str(ROOT/'flinteye.py'), '--headless', '--disable-lan', '--data-dir', str(profile)]
        with (output/'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(args, cwd=directory, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                url = f'http://127.0.0.1:{port}'
                wait_http(url, process, seconds=30)
                subprocess.run(['node', str(ROOT/'frontend/tests/settings-roundtrip.mjs'), url, str(profile), str(output)],
                               check=True, timeout=240)
                request_quit(profile, process)
            finally:
                if process.poll() is None:
                    stop_process(process)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
