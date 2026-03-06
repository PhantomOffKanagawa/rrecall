"""SessionEnd hook script — called by Claude Code when a session ends.

Reads hook JSON from stdin, does a quick duplicate/filter check, then forks
the heavy conversion work to a background process. Must complete in <100ms
and produce no stdout.
"""

from __future__ import annotations

import json
import subprocess
import sys

from rrecall.config import get_config
from rrecall.hooks.session_registry import is_duplicate, register_session
from rrecall.hooks.transcript_parser import parse_transcript
from rrecall.utils.hashing import content_hash
from rrecall.utils.logging import get_logger

logger = get_logger("hooks.session_end")


def run() -> None:
    """Core logic — reads hook payload from stdin. Does not call sys.exit."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            logger.debug("SessionEnd: empty stdin, nothing to do")
            return

        payload = json.loads(raw)
        session_id = payload.get("session_id", "")
        transcript_path = payload.get("transcript_path", "")
        cwd = payload.get("cwd", "")

        if not session_id or not transcript_path:
            logger.warning("SessionEnd: missing session_id or transcript_path")
            return

        from pathlib import Path

        transcript = Path(transcript_path)
        if not transcript.exists():
            logger.warning("SessionEnd: transcript not found: %s", transcript_path)
            return

        # Register session if not already known
        register_session(session_id, cwd, transcript_path)

        # Quick duplicate check — hash the whole file
        file_content = transcript.read_text(encoding="utf-8")
        t_hash = content_hash(file_content)
        if is_duplicate(session_id, t_hash):
            logger.info("SessionEnd: duplicate transcript for %s, skipping", session_id)
            return

        # Quick filter — check minimum message count
        config = get_config()
        if config.hooks.filtering.enabled:
            data = parse_transcript(transcript)
            if len(data.messages) < config.hooks.filtering.min_messages:
                logger.info(
                    "SessionEnd: session %s has %d messages (min %d), skipping",
                    session_id, len(data.messages), config.hooks.filtering.min_messages,
                )
                return

        # Fork heavy work to background
        subprocess.Popen(
            [
                sys.executable, "-m", "rrecall.hooks.finalize",
                "--session-id", session_id,
                "--transcript-path", transcript_path,
                "--cwd", cwd,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("SessionEnd: launched finalize for session %s", session_id)

    except Exception:
        logger.exception("SessionEnd hook failed")
        # Swallow — never block Claude Code


def main() -> None:
    """Entry point for ``python -m`` usage. Calls run() then exits 0."""
    run()
    sys.exit(0)


if __name__ == "__main__":
    main()
