"""Structured logging setup for rrecall."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


class _JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class _HumanFormatter(logging.Formatter):
    """Concise human-readable format for stderr."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S")
        return f"{ts} [{record.levelname[0]}] {record.getMessage()}"


def setup_logging(
    *,
    level: str = "info",
    log_dir: Path | None = None,
) -> logging.Logger:
    """Configure the ``rrecall`` logger.

    - JSON to ``<log_dir>/rrecall.log``
    - Human-readable to stderr
    """
    logger = logging.getLogger("rrecall")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # stderr handler — human-readable
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(_HumanFormatter())
    logger.addHandler(stderr_handler)

    # file handler — JSON
    if log_dir is None:
        from rrecall.config import get_config_dir
        log_dir = get_config_dir()

    log_file = log_dir / "rrecall.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(_JSONFormatter())
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the ``rrecall`` namespace."""
    base = logging.getLogger("rrecall")
    if not base.handlers:
        setup_logging()
    if name:
        return base.getChild(name)
    return base
