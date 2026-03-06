"""Background finalize worker — converts transcript to Markdown and writes to vault.

Launched by the SessionEnd hook as a detached subprocess. Does the heavy work:
1. Parse the transcript JSONL (which already contains all messages, including pre-compaction)
2. Convert to Markdown
3. Write atomically to the Obsidian vault
4. Update session registry
"""

from __future__ import annotations

import argparse
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
from rrecall.hooks.transcript_parser import parse_transcript
from rrecall.utils.hashing import content_hash
from rrecall.utils.logging import get_logger

logger = get_logger("hooks.finalize")


def _build_vault_path(config, session_id: str, project_name: str, started_at: datetime) -> Path:
    """Build the output path in the Obsidian vault."""
    vault = config.general.vault_path
    session_dir = vault / config.general.session_subfolder
    session_dir.mkdir(parents=True, exist_ok=True)

    date_str = started_at.strftime("%Y-%m-%d")
    safe_project = project_name.replace(" ", "-").replace("/", "-")
    filename = f"{date_str}_{session_id[:8]}_{safe_project}.md"
    return session_dir / filename


def finalize(session_id: str, transcript_path: str, cwd: str, *, auto_index: bool = True) -> None:
    """Main finalize logic."""
    config = get_config()
    transcript = Path(transcript_path)

    if not transcript.exists():
        logger.error("Finalize: transcript not found: %s", transcript_path)
        return

    # Parse transcript — it already contains all messages including pre-compaction
    data = parse_transcript(transcript)

    entry = get_session(session_id)

    # Build metadata
    now = datetime.now(timezone.utc)
    started = data.messages[0].timestamp if data.messages and data.messages[0].timestamp else now
    ended = data.messages[-1].timestamp if data.messages and data.messages[-1].timestamp else now

    metadata = SessionMetadata(
        session_id=session_id,
        cwd=cwd,
        started_at=started,
        ended_at=ended,
    )

    # Check for resumed session — if markdown already exists, append
    vault_path = _build_vault_path(config, session_id, metadata.project_name, started)

    if entry and entry.markdown_path and Path(entry.markdown_path).exists():
        # Resumed session — append new messages
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
        markdown = transcript_to_markdown(data, metadata)

        tmp_path = vault_path.with_suffix(".tmp")
        tmp_path.write_text(markdown, encoding="utf-8")
        tmp_path.rename(vault_path)
        logger.info("Finalize: wrote %s", vault_path)

    # Update registry
    file_content = transcript.read_text(encoding="utf-8")
    t_hash = content_hash(file_content)
    record_session_end(session_id, t_hash, str(vault_path))

    # Auto-index the written markdown file
    if auto_index and config.hooks.auto_index:
        try:
            from rrecall.embedding.base import get_provider
            from rrecall.notes.indexer import index_file
            from rrecall.vectordb.lancedb_store import VectorStore

            store = VectorStore()
            embedder = get_provider(config)
            n = index_file(store, vault_path, config, embedder=embedder)
            logger.info("Finalize: auto-indexed %d chunks from %s", n, vault_path.name)
        except Exception as e:
            logger.warning("Finalize: auto-index failed: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize a Claude Code session")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--transcript-path", required=True)
    parser.add_argument("--cwd", default="")
    parser.add_argument("--no-index", action="store_true", help="Skip auto-indexing")
    args = parser.parse_args()

    try:
        finalize(args.session_id, args.transcript_path, args.cwd, auto_index=not args.no_index)
    except Exception:
        logger.exception("Finalize failed for session %s", args.session_id)
        sys.exit(1)


if __name__ == "__main__":
    main()
