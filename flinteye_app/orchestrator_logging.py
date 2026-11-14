from __future__ import annotations

import glob
import logging
import os
import re
import threading
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from flinteye_app.orchestrator_models import RuntimeConfig


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_DURATION_FACTORS = {
    "ms": 0.001,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}


def parse_duration_to_seconds(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip().lower()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h|d)", text)
    if not match:
        raise ValueError(f"invalid duration: {value}")
    return float(match.group(1)) * _DURATION_FACTORS[match.group(2)]


def resolve_log_dir(config: RuntimeConfig, workspace_dir: str) -> Path:
    path = Path(config.logging.directory)
    if not path.is_absolute():
        path = Path(workspace_dir) / path
    return path.resolve()


def resolve_log_level(config: RuntimeConfig) -> int:
    return getattr(logging, config.logging.level.upper(), logging.ERROR)


def resolve_log_retention_seconds(config: RuntimeConfig) -> float | None:
    retention = config.logging.retention or config.recording.record_delete_after
    return parse_duration_to_seconds(retention)


def process_log_filename(process_key: str) -> str:
    if process_key.startswith("camera:"):
        name = process_key.split(":", 1)[1]
    elif process_key == "multiview":
        name = "multiview"
    elif process_key == "mediamtx:direct":
        name = "mediamtx"
    else:
        name = process_key.replace(":", "_")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "process"
    return f"{safe}.log"


def infer_line_level(line: str) -> int:
    text = line.strip()
    lowered = text.lower()
    # MediaMTX uses ERR/WRN/INF/DEB, including bare "ERR: ..." on startup.
    media_level = re.search(r"(?:^|\s)(ERR|WRN|INF|DEB)(?::|\s|$)", text)
    if media_level:
        return {"ERR": logging.ERROR, "WRN": logging.WARNING,
                "INF": logging.INFO, "DEB": logging.DEBUG}[media_level[1]]
    if "[critical]" in lowered or lowered.startswith("critical"):
        return logging.CRITICAL
    if "[error]" in lowered or lowered.startswith("error") or " error " in lowered:
        return logging.ERROR
    if "[warn]" in lowered or "[warning]" in lowered or lowered.startswith("warning"):
        return logging.WARNING
    if "[info]" in lowered or lowered.startswith("info"):
        return logging.INFO
    if "[debug]" in lowered or lowered.startswith("debug"):
        return logging.DEBUG
    return logging.INFO


class RetentionTimedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename: str, *, retention_seconds: float | None) -> None:
        self.retention_seconds = retention_seconds
        super().__init__(
            filename=filename,
            when="midnight",
            interval=1,
            backupCount=0,
            encoding="utf-8",
            utc=False,
        )
        self.cleanup_old_files()

    def doRollover(self) -> None:
        super().doRollover()
        self.cleanup_old_files()

    def cleanup_old_files(self) -> None:
        if not self.retention_seconds:
            return
        cutoff = time.time() - self.retention_seconds
        for path in glob.glob(self.baseFilename + "*"):
            if os.path.abspath(path) == os.path.abspath(self.baseFilename):
                continue
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                continue


class LogManager:
    def __init__(self, *, workspace_dir: str) -> None:
        self.workspace_dir = workspace_dir
        self._lock = threading.RLock()
        self._configured = False
        self._log_dir = Path(workspace_dir) / "logs"
        self._level = logging.ERROR
        self._retention_seconds: float | None = None
        self._root_handlers: list[logging.Handler] = []
        self._process_handlers: dict[str, logging.Handler] = {}

    def configure(self, config: RuntimeConfig) -> None:
        with self._lock:
            self._log_dir = resolve_log_dir(config, self.workspace_dir)
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._level = resolve_log_level(config)
            self._retention_seconds = resolve_log_retention_seconds(config)

            root_logger = logging.getLogger()
            root_logger.setLevel(self._level)
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

            formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
            file_handler = RetentionTimedRotatingFileHandler(
                str(self._log_dir / "orchestrator.log"),
                retention_seconds=self._retention_seconds,
            )
            file_handler.setLevel(self._level)
            file_handler.setFormatter(formatter)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(self._level)
            console_handler.setFormatter(formatter)

            root_logger.addHandler(file_handler)
            root_logger.addHandler(console_handler)
            self._root_handlers = [file_handler, console_handler]

            for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
                logger = logging.getLogger(logger_name)
                logger.handlers = []
                logger.propagate = True
                logger.setLevel(self._level)

            for process_key in list(self._process_handlers.keys()):
                self._configure_process_logger(process_key)

            self._configured = True

    def _configure_process_logger(self, process_key: str) -> logging.Logger:
        logger_name = f"orchestrator.process.{process_key.replace(':', '.')}"
        logger = logging.getLogger(logger_name)
        logger.propagate = False
        logger.setLevel(self._level)

        old_handler = self._process_handlers.get(process_key)
        if old_handler is not None:
            logger.removeHandler(old_handler)
            try:
                old_handler.close()
            except Exception:
                pass

        formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
        handler = RetentionTimedRotatingFileHandler(
            str(self._log_dir / process_log_filename(process_key)),
            retention_seconds=self._retention_seconds,
        )
        handler.setLevel(self._level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        self._process_handlers[process_key] = handler
        return logger

    def get_process_logger(self, process_key: str) -> logging.Logger:
        with self._lock:
            return self._configure_process_logger(process_key)

