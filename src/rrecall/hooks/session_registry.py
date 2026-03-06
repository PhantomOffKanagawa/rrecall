"""Session registry — tracks hook state and prevents duplicates.

Stores session metadata in ``~/.rrecall/sessions.json`` with file locking
to prevent concurrent hook races.
"""

from __future__ import annotations

import fcntl
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rrecall.config import get_config_dir
from rrecall.utils.logging import get_logger

logger = get_logger("hooks.session_registry")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SessionEntry:
    session_id: str
    cwd: str
    started_at: str  # ISO format
    last_transcript_hash: str = ""
    markdown_path: str = ""
    status: str = "active"  # active, completed


# ---------------------------------------------------------------------------
# File-locked JSON store
# ---------------------------------------------------------------------------

def _registry_path() -> Path:
    return get_config_dir() / "sessions.json"


def _lock_path() -> Path:
    return get_config_dir() / "sessions.lock"


class _RegistryLock:
    """Context manager for file-based locking."""

    def __init__(self) -> None:
        self._lock_file = _lock_path()
        self._fd: int | None = None

    def __enter__(self) -> _RegistryLock:
        self._lock_file.touch(exist_ok=True)
        self._fd = open(self._lock_file, "w")
        # Non-blocking attempt first, then blocking with timeout
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            # Wait up to 5 seconds
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (BlockingIOError, OSError):
                    time.sleep(0.05)
            else:
                fcntl.flock(self._fd, fcntl.LOCK_EX)  # final blocking attempt
        return self

    def __exit__(self, *exc) -> None:
        if self._fd:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None


def _read_registry() -> dict[str, dict]:
    path = _registry_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Corrupt sessions.json, starting fresh: %s", e)
        return {}


def _write_registry(data: dict[str, dict]) -> None:
    path = _registry_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.rename(path)


def _entry_from_dict(d: dict) -> SessionEntry:
    return SessionEntry(
        session_id=d.get("session_id", ""),
        cwd=d.get("cwd", ""),
        started_at=d.get("started_at", ""),
        last_transcript_hash=d.get("last_transcript_hash", ""),
        markdown_path=d.get("markdown_path", ""),
        status=d.get("status", "active"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_session(session_id: str, cwd: str, transcript_path: str = "") -> SessionEntry:
    """Register a new session or return the existing one."""
    with _RegistryLock():
        registry = _read_registry()

        if session_id in registry:
            logger.debug("Session %s already registered", session_id)
            return _entry_from_dict(registry[session_id])

        entry = SessionEntry(
            session_id=session_id,
            cwd=cwd,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        registry[session_id] = asdict(entry)
        _write_registry(registry)
        logger.info("Registered session %s (cwd=%s)", session_id, cwd)
        return entry


def record_session_end(session_id: str, transcript_hash: str, markdown_path: str) -> None:
    """Record session end with final transcript hash and markdown path."""
    with _RegistryLock():
        registry = _read_registry()
        if session_id not in registry:
            logger.warning("record_session_end: session %s not found", session_id)
            return

        registry[session_id]["last_transcript_hash"] = transcript_hash
        registry[session_id]["markdown_path"] = markdown_path
        registry[session_id]["status"] = "completed"
        _write_registry(registry)
        logger.info("Session %s completed -> %s", session_id, markdown_path)


def get_session(session_id: str) -> SessionEntry | None:
    """Get a session entry by ID (no lock needed for reads)."""
    registry = _read_registry()
    if session_id in registry:
        return _entry_from_dict(registry[session_id])
    return None


def is_duplicate(session_id: str, transcript_hash: str) -> bool:
    """Check if this transcript has already been processed for this session."""
    entry = get_session(session_id)
    if entry is None:
        return False
    return entry.last_transcript_hash == transcript_hash and transcript_hash != ""
