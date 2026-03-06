"""Convert parsed transcript data to Obsidian-compatible Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from rrecall.hooks.transcript_parser import TranscriptData, TranscriptMessage


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

@dataclass
class SessionMetadata:
    session_id: str
    cwd: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    compactions: int = 0

    @property
    def project_name(self) -> str:
        """Derive project name from the last component of cwd."""
        return PurePosixPath(self.cwd).name or "unknown"


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def _yaml_escape(value: str) -> str:
    """Escape a string for YAML scalar value."""
    if any(c in value for c in ':{}\'"[]&*!|>%@`'):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _build_frontmatter(data: TranscriptData, meta: SessionMetadata) -> str:
    lines = ["---"]
    lines.append(f"session_id: {meta.session_id}")
    lines.append(f"project: {meta.project_name}")
    lines.append(f"cwd: {_yaml_escape(meta.cwd)}")

    if meta.started_at:
        lines.append(f"started: {meta.started_at.isoformat()}")
    if meta.ended_at:
        lines.append(f"ended: {meta.ended_at.isoformat()}")

    lines.append(f"compactions: {meta.compactions}")
    lines.append(f"tags: [claude-session, {meta.project_name}]")

    if data.summary:
        lines.append(f"summary: {_yaml_escape(data.summary)}")

    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conversation body
# ---------------------------------------------------------------------------

def _format_timestamp(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return f" ({ts.strftime('%H:%M:%S')})"


def _format_message(msg: TranscriptMessage) -> str:
    """Format a single message as Markdown."""
    parts: list[str] = []

    role_label = "User" if msg.role == "user" else "Assistant"
    heading = f"### {role_label}{_format_timestamp(msg.timestamp)}"
    parts.append(heading)

    if msg.text_content.strip():
        parts.append(msg.text_content.strip())

    for tool in msg.tool_uses:
        # Obsidian callout syntax — collapsible
        parts.append(f"> [!tool]- {tool.tool_name}: `{tool.input_summary}`")
        if tool.output_summary:
            # Indent output inside callout
            for line in tool.output_summary.split("\n"):
                parts.append(f"> {line}")

    return "\n".join(parts)


def _compute_duration(meta: SessionMetadata) -> str:
    if not meta.started_at or not meta.ended_at:
        return "unknown"
    delta = meta.ended_at - meta.started_at
    total_minutes = int(delta.total_seconds() / 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}m"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transcript_to_markdown(
    data: TranscriptData,
    metadata: SessionMetadata,
    *,
    pre_compact_messages: list[list[TranscriptMessage]] | None = None,
) -> str:
    """Convert parsed transcript data to Obsidian-compatible Markdown.

    Args:
        data: Parsed transcript data.
        metadata: Session metadata (id, cwd, timestamps).
        pre_compact_messages: Optional list of message lists from pre-compaction
            snapshots, each rendered as a separate section at the end.

    Returns:
        Complete Markdown string ready to write to a file.
    """
    sections: list[str] = []

    # --- Frontmatter ---
    sections.append(_build_frontmatter(data, metadata))
    sections.append("")

    # --- Title ---
    title = data.summary or f"Session {metadata.session_id}"
    # Truncate long summaries for the title
    if len(title) > 80:
        title = title[:77] + "..."
    sections.append(f"# Session: {title}")

    duration = _compute_duration(metadata)
    date_str = metadata.started_at.strftime("%Y-%m-%d") if metadata.started_at else "unknown"
    sections.append(
        f"**Date:** {date_str} | **Duration:** {duration} | **Project:** {metadata.project_name}"
    )
    sections.append("")

    # --- Summary ---
    if data.summary:
        sections.append("## Summary")
        sections.append(data.summary)
        sections.append("")

    # --- Conversation ---
    sections.append("---")
    sections.append("")
    sections.append("## Conversation")
    sections.append("")

    for msg in data.messages:
        sections.append(_format_message(msg))
        sections.append("")

    # --- Pre-compaction snapshots ---
    if pre_compact_messages:
        for i, snapshot_msgs in enumerate(pre_compact_messages, 1):
            sections.append("---")
            sections.append("")
            sections.append(f"## Pre-Compaction Snapshot {i}")
            sections.append("*(Content that was compacted, preserved for reference)*")
            sections.append("")
            for msg in snapshot_msgs:
                sections.append(_format_message(msg))
                sections.append("")

    return "\n".join(sections)


def resumed_section(
    data: TranscriptData,
    resumed_at: datetime | None = None,
) -> str:
    """Generate a Markdown section for a resumed session (appended to existing file).

    Args:
        data: Parsed transcript data from the resumed portion.
        resumed_at: When the session was resumed.

    Returns:
        Markdown string to append to the existing session file.
    """
    sections: list[str] = []
    ts_str = resumed_at.isoformat() if resumed_at else "unknown"

    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append(f"## Resumed ({ts_str})")
    sections.append("")

    for msg in data.messages:
        sections.append(_format_message(msg))
        sections.append("")

    return "\n".join(sections)
