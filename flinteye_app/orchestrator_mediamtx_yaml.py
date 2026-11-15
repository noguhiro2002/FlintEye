from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flinteye_app.orchestrator_models import RuntimeConfig
from flinteye_app.orchestrator_recording import RecordingApplyResult, apply_recording_config


_TOP_LEVEL_SECTION_RE = re.compile(r"^[^\s#][^:]*:\s*$")
_PATH_HEADER_RE = re.compile(r"^\s{2}[^ #][^:]*:\s*$")
_SAFE_TEXT_RE = re.compile(r"^[A-Za-z0-9_./%+\-]+$")


@dataclass
class ManagedApplyResult:
    ok: bool
    changed: bool
    config_path: str | None = None
    backup_path: str | None = None
    actions: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class MediamtxYamlApplyResult:
    ok: bool
    changed: bool
    recording: RecordingApplyResult
    managed: ManagedApplyResult
    message: str = ""


def resolve_mediamtx_config_path(config: RuntimeConfig, workspace_dir: str) -> Path | None:
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


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _SAFE_TEXT_RE.fullmatch(text):
        return text
    return "'" + text.replace("'", "''") + "'"


def _yaml_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    return _yaml_scalar(value)


def _upsert_top_level(lines: list[str], key: str, value: Any) -> tuple[list[str], bool, str]:
    line_value = f"{key}: {_yaml_value(value)}"
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for i, line in enumerate(lines):
        if pattern.match(line):
            if lines[i] == line_value:
                return lines, False, "unchanged"
            lines[i] = line_value
            return lines, True, "updated"

    insert_idx = len(lines)
    for section_name in ("pathDefaults:", "paths:"):
        for i, line in enumerate(lines):
            if line.strip() == section_name:
                insert_idx = i
                break
        if insert_idx != len(lines):
            break

    if insert_idx > 0 and lines[insert_idx - 1] != "":
        lines.insert(insert_idx, "")
        insert_idx += 1
    lines.insert(insert_idx, line_value)
    return lines, True, "inserted"


def _replace_or_insert_path_key(
    lines: list[str],
    *,
    block_start: int,
    block_end: int,
    key: str,
    value: Any,
) -> tuple[list[str], int, bool]:
    line_value = f"    {key}: {_yaml_value(value)}"
    key_pattern = re.compile(rf"^\s{{4}}{re.escape(key)}\s*:")
    for i in range(block_start + 1, block_end):
        if key_pattern.match(lines[i]):
            if lines[i] == line_value:
                return lines, block_end, False
            lines[i] = line_value
            return lines, block_end, True

    lines.insert(block_end, line_value)
    return lines, block_end + 1, True


def _upsert_path_settings(
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

        block = [f"  {path_name}:"]
        for key, value in desired.items():
            block.append(f"    {key}: {_yaml_value(value)}")
        for offset, row in enumerate(block):
            lines.insert(paths_end + offset, row)
        return lines, True, "inserted"

    path_end = paths_end
    for i in range(path_index + 1, paths_end):
        if _PATH_HEADER_RE.match(lines[i]):
            path_end = i
            break

    changed = False
    for key, value in desired.items():
        lines, path_end, row_changed = _replace_or_insert_path_key(
            lines,
            block_start=path_index,
            block_end=path_end,
            key=key,
            value=value,
        )
        changed = changed or row_changed
    return lines, changed, "updated"


def _normalize_api_bind_host(host: str) -> str:
    normalized = host.strip()
    if normalized.lower() == "localhost":
        return "127.0.0.1"
    return normalized


def _format_socket_address(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _resolve_auto_managed_globals(config: RuntimeConfig) -> dict[str, Any]:
    multiview = config.multiview
    if not multiview.enabled or multiview.source_mode not in {"api", "hybrid"}:
        return {}

    api_url = multiview.mtx_api_url.strip()
    if not api_url:
        return {}

    parsed = urlparse(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {}

    host = _normalize_api_bind_host(parsed.hostname)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return {
        "api": True,
        "apiAddress": _format_socket_address(host, port),
        "apiEncryption": parsed.scheme == "https",
    }


def apply_managed_mediamtx_config(config: RuntimeConfig, *, workspace_dir: str, before_write=None) -> ManagedApplyResult:
    managed = config.mediamtx.managed
    auto_global = _resolve_auto_managed_globals(config)
    if not managed.enabled and not auto_global:
        return ManagedApplyResult(ok=True, changed=False, message="mediamtx.managed is disabled")
    desired_global = dict(managed.global_) if managed.enabled else {}
    desired_global.update(auto_global)
    desired_paths = managed.paths if managed.enabled else {}

    if not desired_global and not desired_paths:
        return ManagedApplyResult(ok=True, changed=False, message="no managed keys to apply")

    config_path = resolve_mediamtx_config_path(config, workspace_dir)
    if config_path is None:
        return ManagedApplyResult(ok=False, changed=False, message="unable to resolve mediamtx config path")
    if not config_path.is_file():
        return ManagedApplyResult(
            ok=False,
            changed=False,
            config_path=str(config_path),
            message=f"mediamtx config not found: {config_path}",
        )

    lines = config_path.read_text(encoding="utf-8").splitlines()
    changed = False
    actions: list[str] = []

    for key, value in desired_global.items():
        lines, row_changed, action = _upsert_top_level(lines, key, value)
        changed = changed or row_changed
        actions.append(f"{action}:global.{key}")

    for path_name, settings in desired_paths.items():
        normalized = path_name.strip().strip("/")
        if not normalized:
            continue
        lines, row_changed, action = _upsert_path_settings(lines, path_name=normalized, desired=settings)
        changed = changed or row_changed
        actions.append(f"{action}:paths.{normalized}")

    backup_path = config_path.with_suffix(config_path.suffix + ".bak")
    if changed:
        if before_write is not None:
            before_write()
        shutil.copy2(config_path, backup_path)
        out_text = "\n".join(lines)
        if lines and lines[-1] != "":
            out_text += "\n"
        config_path.write_text(out_text, encoding="utf-8")

    return ManagedApplyResult(
        ok=True,
        changed=changed,
        config_path=str(config_path),
        backup_path=str(backup_path) if changed else None,
        actions=actions,
        message="managed mediamtx config applied",
    )


def apply_mediamtx_yaml(config: RuntimeConfig, *, workspace_dir: str, before_write=None, event_session=None, data_dir=None) -> MediamtxYamlApplyResult:
    recording = apply_recording_config(config, workspace_dir=workspace_dir, before_write=before_write,
                                       event_session=event_session, data_dir=data_dir)
    managed = apply_managed_mediamtx_config(config, workspace_dir=workspace_dir, before_write=before_write)
    ok = recording.ok and managed.ok
    changed = recording.changed or managed.changed
    if not ok:
        parts = []
        if not recording.ok:
            parts.append(f"recording: {recording.message}")
        if not managed.ok:
            parts.append(f"managed: {managed.message}")
        message = "; ".join(parts)
    else:
        message = "mediamtx config applied"
    return MediamtxYamlApplyResult(
        ok=ok,
        changed=changed,
        recording=recording,
        managed=managed,
        message=message,
    )
