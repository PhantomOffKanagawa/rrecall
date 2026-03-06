"""PreCompact hook script — called by Claude Code before compaction.

Reads hook JSON from stdin, copies the transcript to a timestamped snapshot,
and updates the session registry. Must complete in <100ms and produce no stdout.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from rrecall.config import get_config_dir
from rrecall.hooks.session_registry import record_pre_compact, register_session
from rrecall.utils.logging import get_logger

logger = get_logger("hooks.pre_compact")


def _snapshot_dir() -> Path:
    d = get_config_dir() / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> None:
    """Entry point — reads hook payload from stdin."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            logger.debug("PreCompact: empty stdin, nothing to do")
            return

        payload = json.loads(raw)
        session_id = payload.get("session_id", "")
        transcript_path = payload.get("transcript_path", "")
        cwd = payload.get("cwd", "")

        if not session_id or not transcript_path:
            logger.warning("PreCompact: missing session_id or transcript_path")
            return

        transcript = Path(transcript_path)
        if not transcript.exists():
            logger.warning("PreCompact: transcript not found: %s", transcript_path)
            return

        # Register session if not already known
        register_session(session_id, cwd, transcript_path)

        # Copy transcript to timestamped snapshot
        ts = int(time.time())
        snapshot = _snapshot_dir() / f"{session_id}_{ts}.jsonl"
        shutil.copy2(transcript, snapshot)

        # Update registry
        record_pre_compact(session_id, str(snapshot))
        logger.info("PreCompact: snapshot saved -> %s", snapshot)

    except Exception:
        logger.exception("PreCompact hook failed")
        # Always exit 0 so we don't block Claude Code
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
