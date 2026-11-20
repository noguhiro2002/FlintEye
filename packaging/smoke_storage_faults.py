"""Run in the QA container with an empty, bounded 8 MiB recording tmpfs."""
import errno
from pathlib import Path
import shutil
import tempfile

from flinteye_app.cli import initialize
from flinteye_app.flinteye_storage import cleanup, storage_problem
from flinteye_app.orchestrator_store import RuntimeStore
from flinteye_app.recording_events import file_evidence, record_event, summary


volume = Path('/qa-recordings')
if (not volume.is_mount() or not 0 < shutil.disk_usage(volume).total <= 8 * 1024**2
        or any(volume.iterdir()) or not any(line.split()[4] == str(volume) and ' - tmpfs ' in line
                                            for line in Path('/proc/self/mountinfo').read_text().splitlines())):
    raise RuntimeError('Expected a dedicated empty tmpfs capped at 8 MiB')

with tempfile.TemporaryDirectory() as directory:
    profile = Path(directory)
    store = RuntimeStore(env_file='', runtime_file=str(initialize(profile)), use_env=False)
    root = volume/'recordings'
    root.mkdir()
    store.patch_runtime({'recording': {'record_root': str(root), 'min_free_bytes': 500_000,
                                       'max_bytes': 100_000_000, 'managed_storage': True, 'enabled': True}})
    config = store.get_effective()
    clips = root/'fixture'/'2026-01-01'
    clips.mkdir(parents=True)
    sentinel = root/'personal.txt'
    sentinel.write_bytes(b'unrelated file')
    completed = clips/'completed.ts'
    completed.write_bytes(b'x'*1024**2)
    record_event(profile, completed, complete=True, session='before-restart')
    interrupted = clips/'active.ts'
    record_event(profile, interrupted, complete=False, session='before-restart')
    try:
        with interrupted.open('wb', buffering=0) as partial:
            for _ in range(10):
                partial.write(b'y'*1024**2)
    except OSError as error:
        if error.errno != errno.ENOSPC:
            raise
    else:
        raise AssertionError('Missing ENOSPC from the bounded volume')
    assert storage_problem(config) and 'free disk space' in storage_problem(config)
    assert not file_evidence(profile, [interrupted])[str(interrupted)]['is_stable']
    partial_size = interrupted.stat().st_size
    assert cleanup(profile, config, directory) == 1 and not completed.exists()
    assert interrupted.stat().st_size == partial_size and partial_size > 0
    assert cleanup(profile, config, directory) == 0
    assert storage_problem(config) is None

    detached = volume/'detached'
    root.rename(detached)
    assert storage_problem(config) and 'unavailable' in storage_problem(config)
    assert cleanup(profile, config, directory) == 0 and not root.exists()
    detached.rename(root)
    reopened = RuntimeStore(env_file='', runtime_file=str(profile/'runtime.json'), use_env=False)
    assert storage_problem(reopened.get_effective()) is None
    recovered = clips/'recovered.ts'
    recovered.write_bytes(b'new segment')
    record_event(profile, recovered, complete=True, session='after-restart')
    evidence = file_evidence(profile, [interrupted, recovered])
    assert evidence[str(recovered)]['is_stable'] and not evidence[str(interrupted)]['is_stable']
    assert summary(profile, 'after-restart')['previous_incomplete_segments'] == 1
    assert sentinel.read_bytes() == b'unrelated file'
    print('PASS: ENOSPC, cleanup, unavailable root, remount and durable completion state')
