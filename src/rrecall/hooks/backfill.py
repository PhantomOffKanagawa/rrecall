"""Backfill — retroactively run session-end finalize on all previous conversations.

Scans ~/.claude/projects/ for transcript JSONL files, skips already-processed
sessions, and runs the finalize logic on each one.
"""

from __future__ import annotations

import json
from pathlib import Path

from rrecall.config import get_config
from rrecall.hooks.finalize import finalize
from rrecall.hooks.session_registry import get_session, register_session
from rrecall.hooks.transcript_parser import parse_transcript
from rrecall.utils.hashing import content_hash
from rrecall.utils.logging import get_logger

logger = get_logger("hooks.backfill")

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _extract_cwd_from_transcript(jsonl_path: Path) -> str | None:
    """Read the first few lines of a transcript to extract the cwd field."""
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("cwd"):
                    return data["cwd"]
    except OSError:
        pass
    return None


def discover_transcripts() -> list[tuple[str, Path, str]]:
    """Discover all Claude Code session transcripts.

    Returns:
        List of (session_id, transcript_path, cwd) tuples.
    """
    if not CLAUDE_PROJECTS_DIR.exists():
        return []

    results: list[tuple[str, Path, str]] = []
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            session_id = jsonl_file.stem
            # Skip files that don't look like UUIDs
            if len(session_id) != 36 or session_id.count("-") != 4:
                continue
            cwd = _extract_cwd_from_transcript(jsonl_file)
            if cwd:
                results.append((session_id, jsonl_file, cwd))

    return results


def backfill(*, dry_run: bool = False, force: bool = False,
             min_messages: int | None = None) -> tuple[int, int, int]:
    """Run finalize on all unprocessed past sessions.

    Args:
        dry_run: If True, only report what would be done.
        force: If True, re-process even already-completed sessions.
        min_messages: Override minimum message count filter (None = use config).

    Returns:
        Tuple of (processed, skipped, failed) counts.
    """
    config = get_config()
    transcripts = discover_transcripts()
    min_msg = min_messages if min_messages is not None else (
        config.hooks.filtering.min_messages if config.hooks.filtering.enabled else 0
    )

    processed = 0
    skipped = 0
    failed = 0

    for session_id, transcript_path, cwd in transcripts:
        # Check if already processed
        entry = get_session(session_id)
        if entry and entry.status == "completed" and not force:
            skipped += 1
            continue

        # Quick filter on message count
        try:
            data = parse_transcript(transcript_path)
        except Exception as e:
            logger.warning("Failed to parse %s: %s", transcript_path, e)
            failed += 1
            continue

        if len(data.messages) < min_msg:
            logger.debug(
                "Skipping %s: %d messages (min %d)",
                session_id[:8], len(data.messages), min_msg,
            )
            skipped += 1
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would process %s (%d messages, cwd=%s)",
                session_id[:8], len(data.messages), cwd,
            )
            processed += 1
            continue

        # Register and finalize
        try:
            register_session(session_id, cwd, str(transcript_path))
            finalize(session_id, str(transcript_path), cwd)
            processed += 1
            logger.info("Processed %s (%d messages)", session_id[:8], len(data.messages))
        except Exception as e:
            logger.warning("Failed to finalize %s: %s", session_id[:8], e)
            failed += 1

    return processed, skipped, failed
