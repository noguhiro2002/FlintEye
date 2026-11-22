from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flinteye_app.orchestrator_models import RuntimeConfig


_TOP_LEVEL_SECTION_RE = re.compile(r"^[^\s#][^:]*:\s*$")
_ANY_PATH_HEADER_RE = re.compile(r"^\s{2}[^ #][^:]*:\s*$")
_PATH_KEY_RE_TEMPLATE = r"^\s{{4}}{key}\s*:\s*(.+?)\s*$"
_ORCHESTRATOR_RECORD_PATH_SUFFIX = "/%path/%Y-%m-%d/%H-%M-%S-%f"


@dataclass
class RecordingApplyResult:
    ok: bool
    changed: bool
    config_path: str | None = None
    backup_path: str | None = None
    record_root: str | None = None
    record_paths: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    message: str = ""


def _normalize_paths(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        clean = raw.strip().strip("/")
        if not clean or clean.lower().startswith(("__mv_input/", "__mv_buffer/")):
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _resolve_record_paths(config: RuntimeConfig) -> list[str]:
    paths = list(config.recording.record_paths)
    if config.recording.record_all_cameras is None:
        include_all_cameras = not paths
    else:
        include_all_cameras = bool(config.recording.record_all_cameras)

    if include_all_cameras:
        paths = [camera.path for camera in config.cameras]
        paths.extend(config.recording.record_paths)

    if config.recording.include_multiview:
        prefix = config.multiview.output_prefix or "multiview"
        for i in range(1, config.recording.multiview_max_count + 1):
            paths.append(f"{prefix}_{i}")
    from flinteye_app.camera_audio import LIVE_PREFIX

    return [path for path in _normalize_paths(paths) if not path.startswith(LIVE_PREFIX + "/")]


def _resolve_config_path(config: RuntimeConfig, workspace_dir: str) -> Path | None:
    if config.recording.config_path:
        return Path(config.recording.config_path).expanduser()

    for token in reversed(config.mediamtx.direct.command):
        lower = token.lower()
        if lower.endswith(".yml") or lower.endswith(".yaml"):
            return Path(token).expanduser()

    fallback = Path(workspace_dir) / "mediamtx" / "mediamtx.yml"
    if fallback.is_file():
        return fallback
    return None


def _find_section_end(lines: list[str], section_start: int) -> int:
    for i in range(section_start + 1, len(lines)):
        if _TOP_LEVEL_SECTION_RE.match(lines[i]):
            return i
    return len(lines)


def _ensure_paths_section(lines: list[str]) -> tuple[list[str], int, int]:
    for i, line in enumerate(lines):
        if re.match(r"^\s*paths:\s*$", line):
            return lines, i, _find_section_end(lines, i)
    if lines and lines[-1] != "":
        lines.append("")
    lines.append("paths:")
    idx = len(lines) - 1
    return lines, idx, len(lines)


def _format_yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./%+\-]+", text):
        return text
    return "'" + text.replace("'", "''") + "'"


def _extract_block_value(lines: list[str], *, block_start: int, block_end: int, key: str) -> str | None:
    pattern = re.compile(_PATH_KEY_RE_TEMPLATE.format(key=re.escape(key)))
    for i in range(block_start + 1, block_end):
        match = pattern.match(lines[i])
        if not match:
            continue
        raw_value = match.group(1).strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            return raw_value[1:-1]
        return raw_value
    return None


def _looks_like_orchestrator_record_path(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().replace("\\", "/")
    return normalized.endswith((_ORCHESTRATOR_RECORD_PATH_SUFFIX, _ORCHESTRATOR_RECORD_PATH_SUFFIX + "_%z"))


def _find_existing_orchestrator_recording_paths(lines: list[str]) -> set[str]:
    _, paths_index, paths_end = _ensure_paths_section(lines)
    out: set[str] = set()
    i = paths_index + 1
    while i < paths_end:
        if not _ANY_PATH_HEADER_RE.match(lines[i]):
            i += 1
            continue

        path_name = lines[i].strip()[:-1].strip().strip("/")
        block_end = paths_end
        for j in range(i + 1, paths_end):
            if _ANY_PATH_HEADER_RE.match(lines[j]):
                block_end = j
                break

        record_path_value = _extract_block_value(
            lines,
            block_start=i,
            block_end=block_end,
            key="recordPath",
        )
        if path_name and _looks_like_orchestrator_record_path(record_path_value):
            out.add(path_name)
        i = block_end
    return out


def _replace_or_insert_key(
    lines: list[str],
    *,
    block_start: int,
    block_end: int,
    key: str,
    value: Any,
) -> tuple[list[str], int, bool]:
    formatted_value = _format_yaml_value(value)
    line_value = f"    {key}: {formatted_value}"
    key_pattern = re.compile(rf"^\s{{4}}{re.escape(key)}\s*:")

    for i in range(block_start + 1, block_end):
        if key_pattern.match(lines[i]):
            if lines[i] != line_value:
                lines[i] = line_value
                return lines, block_end, True
            return lines, block_end, False

    lines.insert(block_end, line_value)
    return lines, block_end + 1, True


def _upsert_recording_for_path(
    lines: list[str],
    *,
    path_name: str,
    desired: dict[str, Any],
) -> tuple[list[str], bool, str]:
    lines, paths_index, paths_end = _ensure_paths_section(lines)
    path_pattern = re.compile(rf"^\s{{2}}{re.escape(path_name)}:\s*$")

    path_index = -1
    for i in range(paths_index + 1, paths_end):
        if path_pattern.match(lines[i]):
            path_index = i
            break

    if path_index < 0:
        if paths_end > 0 and lines[paths_end - 1] != "":
            lines.insert(paths_end, "")
            paths_end += 1
        new_block = [f"  {path_name}:"]
        for key, value in desired.items():
            new_block.append(f"    {key}: {_format_yaml_value(value)}")
        for offset, row in enumerate(new_block):
            lines.insert(paths_end + offset, row)
        return lines, True, "inserted"

    path_end = paths_end
    for i in range(path_index + 1, paths_end):
        if _ANY_PATH_HEADER_RE.match(lines[i]):
            path_end = i
            break

    changed = False
    for key, value in desired.items():
        lines, path_end, row_changed = _replace_or_insert_key(
            lines,
            block_start=path_index,
            block_end=path_end,
            key=key,
            value=value,
        )
        changed = changed or row_changed
    return lines, changed, "updated"


def apply_recording_config(config: RuntimeConfig, *, workspace_dir: str, before_write=None, event_session=None, data_dir=None) -> RecordingApplyResult:
    if not config.recording.auto_apply:
        return RecordingApplyResult(
            ok=True,
            changed=False,
            message="recording.auto_apply is disabled",
        )

    config_path = _resolve_config_path(config, workspace_dir)
    if config_path is None:
        return RecordingApplyResult(
            ok=False,
            changed=False,
            message="unable to resolve mediamtx config path",
        )
    if not config_path.is_file():
        return RecordingApplyResult(
            ok=False,
            changed=False,
            config_path=str(config_path),
            message=f"mediamtx config not found: {config_path}",
        )

    record_paths = _resolve_record_paths(config)

    desired: dict[str, Any] = {"record": bool(config.recording.enabled)}
    record_root = config.recording.record_root.strip().rstrip("/\\")
    if config.recording.enabled and record_paths:
        if not record_root:
            return RecordingApplyResult(
                ok=False,
                changed=False,
                config_path=str(config_path),
                message="record_root is empty",
            )
        normalized_root = record_root.replace("\\", "/")
        record_path_value = normalized_root + _ORCHESTRATOR_RECORD_PATH_SUFFIX
        if config.recording.managed_storage:
            record_path_value += "_%z"
        desired.update(
            {
                "recordPath": record_path_value,
                "recordFormat": config.recording.record_format,
                "recordPartDuration": config.recording.record_part_duration,
                "recordMaxPartSize": config.recording.record_max_part_size,
                "recordSegmentDuration": config.recording.record_segment_duration,
                "recordDeleteAfter": "0s" if config.recording.managed_storage else config.recording.record_delete_after,
            }
        )

    if config.recording.managed_storage:
        import os
        import shlex
        from flinteye_app.flinteye_runtime import launch_command
        profile = str(data_dir or os.environ.get("FLINTEYE_DATA_DIR", str(config_path.parent.resolve())))
        suffix = ["--recording-session", event_session] if event_session else []
        command = launch_command() + ["--segment-complete", profile] + suffix
        # MediaMTX uses go-shellquote.Split even on Windows, then exec.Command.
        # Windows CRT quoting would lose unquoted backslashes in executable paths.
        desired["runOnRecordSegmentComplete"] = shlex.join(command)
        desired["runOnRecordSegmentCreate"] = shlex.join(
            launch_command() + ["--segment-created", profile] + suffix)
    lines = config_path.read_text(encoding="utf-8").splitlines()
    existing_record_paths = _find_existing_orchestrator_recording_paths(lines)
    changed = False
    actions: list[str] = []
    pcm_paths = {camera.path for camera in config.cameras if camera.audio.enabled and camera.audio.codec == "pcm"}
    for path_name in record_paths:
        path_settings = {**desired, "recordFormat": "fmp4"} if config.recording.enabled and path_name in pcm_paths else desired
        lines, path_changed, action = _upsert_recording_for_path(
            lines,
            path_name=path_name,
            desired=path_settings,
        )
        changed = changed or path_changed
        actions.append(f"{action}:paths.{path_name}")

    stale_paths = sorted(existing_record_paths.difference(record_paths))
    for path_name in stale_paths:
        lines, path_changed, action = _upsert_recording_for_path(
            lines,
            path_name=path_name,
            desired={"record": False},
        )
        changed = changed or path_changed
        actions.append(f"{action}:paths.{path_name}:record=no")

    backup_path = config_path.with_suffix(config_path.suffix + ".bak")
    if changed:
        if before_write is not None:
            before_write()
        shutil.copy2(config_path, backup_path)
        out_text = "\n".join(lines)
        if lines and lines[-1] != "":
            out_text += "\n"
        config_path.write_text(out_text, encoding="utf-8")

    if config.recording.enabled and record_paths:
        try:
            Path(record_root).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return RecordingApplyResult(
                ok=False,
                changed=changed,
                config_path=str(config_path),
                backup_path=str(backup_path) if changed else None,
                record_root=record_root,
                record_paths=record_paths,
                actions=actions,
                message=f"failed to create record root '{record_root}': {e}",
            )

    message = "recording config applied"
    if not record_paths and not config.recording.enabled:
        message = "recording is disabled and there are no selected recording targets"
    elif not record_paths:
        message = "recording enabled but no recording targets are selected"

    return RecordingApplyResult(
        ok=True,
        changed=changed,
        config_path=str(config_path),
        backup_path=str(backup_path) if changed else None,
        record_root=record_root,
        record_paths=record_paths,
        actions=actions,
        message=message,
    )
