"""Background finalize worker — converts transcript to Markdown and writes to vault.

Launched by the SessionEnd hook as a detached subprocess. Does the heavy work:
1. Load transcript + pre-compact snapshots
2. Merge and deduplicate messages
3. Convert to Markdown
4. Write atomically to the Obsidian vault
5. Update session registry
6. Clean up snapshots
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rrecall.config import get_config
from rrecall.hooks.markdown_converter import (
    SessionMetadata,
    resumed_section,
    transcript_to_markdown,
)
from rrecall.hooks.session_registry import (
    get_session,
    record_session_end,
)
from rrecall.hooks.transcript_parser import (
    TranscriptMessage,
    parse_transcript,
)
from rrecall.utils.hashing import content_hash
from rrecall.utils.logging import get_logger

logger = get_logger("hooks.finalize")


def _merge_messages(
    current: list[TranscriptMessage],
    snapshots: list[list[TranscriptMessage]],
    seen_hashes: set[str],
) -> tuple[list[TranscriptMessage], list[list[TranscriptMessage]]]:
    """Deduplicate messages across current transcript and pre-compact snapshots.

    Returns:
        Tuple of (main messages, pre-compact message lists for archival sections).
    """
    # The current transcript's messages are the "canonical" ones.
    # Pre-compact snapshots contain messages that were compacted away —
    # we keep them in separate sections for reference.
    # Dedup within each snapshot against `seen_hashes`.

    deduped_snapshots: list[list[TranscriptMessage]] = []
    for snapshot_msgs in snapshots:
        unique: list[TranscriptMessage] = []
        for msg in snapshot_msgs:
            h = content_hash(msg.text_content)
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique.append(msg)
        if unique:
            deduped_snapshots.append(unique)

    return current, deduped_snapshots


def _build_vault_path(config, session_id: str, project_name: str, started_at: datetime) -> Path:
    """Build the output path in the Obsidian vault."""
    vault = config.general.vault_path
    session_dir = vault / config.general.session_subfolder
    session_dir.mkdir(parents=True, exist_ok=True)

    date_str = started_at.strftime("%Y-%m-%d")
    safe_project = project_name.replace(" ", "-").replace("/", "-")
    filename = f"{date_str}_{session_id[:8]}_{safe_project}.md"
    return session_dir / filename


def finalize(session_id: str, transcript_path: str, cwd: str) -> None:
    """Main finalize logic."""
    config = get_config()
    transcript = Path(transcript_path)

    if not transcript.exists():
        logger.error("Finalize: transcript not found: %s", transcript_path)
        return

    # Parse current transcript
    data = parse_transcript(transcript)

    # Load pre-compact snapshots
    entry = get_session(session_id)
    snapshot_message_lists: list[list[TranscriptMessage]] = []
    if entry and entry.pre_compact_snapshots:
        for snap_path in entry.pre_compact_snapshots:
            snap = Path(snap_path)
            if snap.exists():
                snap_data = parse_transcript(snap)
                snapshot_message_lists.append(snap_data.messages)

    # Merge and deduplicate
    main_messages, pre_compact = _merge_messages(
        data.messages,
        snapshot_message_lists,
        set(data.raw_line_hashes),
    )

    # Build metadata
    now = datetime.now(timezone.utc)
    started = data.messages[0].timestamp if data.messages and data.messages[0].timestamp else now
    ended = data.messages[-1].timestamp if data.messages and data.messages[-1].timestamp else now

    metadata = SessionMetadata(
        session_id=session_id,
        cwd=cwd,
        started_at=started,
        ended_at=ended,
        compactions=len(pre_compact),
    )

    # Check for resumed session — if markdown already exists, append
    vault_path = _build_vault_path(config, session_id, metadata.project_name, started)

    if entry and entry.markdown_path and Path(entry.markdown_path).exists():
        # Resumed session — append
        resumed_md = resumed_section(data, resumed_at=now)
        existing_path = Path(entry.markdown_path)

        tmp_path = existing_path.with_suffix(".tmp")
        existing_content = existing_path.read_text(encoding="utf-8")
        tmp_path.write_text(existing_content + resumed_md, encoding="utf-8")
        tmp_path.rename(existing_path)

        vault_path = existing_path
        logger.info("Finalize: appended resumed content to %s", existing_path)
    else:
        # New session — write full markdown
        markdown = transcript_to_markdown(data, metadata, pre_compact_messages=pre_compact)

        tmp_path = vault_path.with_suffix(".tmp")
        tmp_path.write_text(markdown, encoding="utf-8")
        tmp_path.rename(vault_path)
        logger.info("Finalize: wrote %s", vault_path)

    # Update registry
    file_content = transcript.read_text(encoding="utf-8")
    t_hash = content_hash(file_content)
    record_session_end(session_id, t_hash, str(vault_path))

    # Clean up snapshots
    if entry and entry.pre_compact_snapshots:
        for snap_path in entry.pre_compact_snapshots:
            snap = Path(snap_path)
            if snap.exists():
                try:
                    snap.unlink()
                    logger.debug("Cleaned up snapshot: %s", snap_path)
                except OSError as e:
                    logger.warning("Failed to clean up snapshot %s: %s", snap_path, e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize a Claude Code session")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--transcript-path", required=True)
    parser.add_argument("--cwd", default="")
    args = parser.parse_args()

    try:
        finalize(args.session_id, args.transcript_path, args.cwd)
    except Exception:
        logger.exception("Finalize failed for session %s", args.session_id)
        sys.exit(1)


if __name__ == "__main__":
    main()
