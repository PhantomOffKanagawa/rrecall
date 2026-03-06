"""Parse Claude Code transcript JSONL into structured data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rrecall.utils.hashing import content_hash
from rrecall.utils.logging import get_logger

logger = get_logger("hooks.transcript_parser")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ToolUseBlock:
    tool_name: str
    input_summary: str
    output_summary: str = ""


@dataclass
class TranscriptMessage:
    role: str  # "user" or "assistant"
    timestamp: datetime | None
    text_content: str
    tool_uses: list[ToolUseBlock] = field(default_factory=list)


@dataclass
class TranscriptData:
    summary: str | None
    messages: list[TranscriptMessage]
    raw_line_hashes: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text for summaries."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _extract_text(content: list | str) -> str:
    """Extract plain text from a message's content field.

    Content can be a plain string or a list of content blocks
    (text, tool_use, tool_result, etc.).
    """
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _extract_tool_uses(content: list | str) -> list[ToolUseBlock]:
    """Extract tool_use blocks from a message's content field."""
    if isinstance(content, str):
        return []
    tools: list[ToolUseBlock] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "unknown")
            inp = block.get("input", {})
            # Summarise the input — for Bash it's the command, for others the first key
            if isinstance(inp, dict):
                if "command" in inp:
                    input_summary = _truncate(str(inp["command"]))
                elif "file_path" in inp:
                    input_summary = str(inp["file_path"])
                elif "query" in inp:
                    input_summary = _truncate(str(inp["query"]))
                else:
                    input_summary = _truncate(json.dumps(inp, default=str))
            else:
                input_summary = _truncate(str(inp))
            tools.append(ToolUseBlock(tool_name=name, input_summary=input_summary))
    return tools


def _extract_tool_results(content: list | str, existing_tools: list[ToolUseBlock]) -> None:
    """Fill in output_summary on existing tool_use blocks from tool_result blocks."""
    if isinstance(content, str):
        return
    tool_id_map: dict[str, ToolUseBlock] = {}
    # Build a map of tool_use_id -> ToolUseBlock from the content
    # (tool_results reference tool_use_id, but we may not have that linkage;
    #  fall back to positional matching)
    result_idx = 0
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            result_content = block.get("content", "")
            if isinstance(result_content, list):
                result_text = " ".join(
                    b.get("text", "") for b in result_content if isinstance(b, dict)
                )
            else:
                result_text = str(result_content)
            if result_idx < len(existing_tools):
                existing_tools[result_idx].output_summary = _truncate(result_text, 300)
            result_idx += 1


def _parse_timestamp(line_data: dict) -> datetime | None:
    """Try to extract a timestamp from a JSONL line."""
    for key in ("timestamp", "ts", "created_at"):
        if ts := line_data.get(key):
            try:
                if isinstance(ts, (int, float)):
                    return datetime.fromtimestamp(ts)
                return datetime.fromisoformat(str(ts))
            except (ValueError, OSError):
                pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_transcript(jsonl_path: Path) -> TranscriptData:
    """Parse a Claude Code transcript JSONL file into structured data.

    Args:
        jsonl_path: Path to the ``.jsonl`` transcript file.

    Returns:
        A :class:`TranscriptData` with summary, messages, and line hashes.
    """
    summary: str | None = None
    messages: list[TranscriptMessage] = []
    line_hashes: set[str] = set()

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Track line hash for deduplication
            line_hashes.add(content_hash(raw_line))

            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON on line %d of %s", line_num, jsonl_path)
                continue

            if not isinstance(data, dict):
                logger.warning("Skipping non-object JSON on line %d of %s", line_num, jsonl_path)
                continue

            line_type = data.get("type", "")

            # --- Summary line ---
            if line_type == "summary":
                summary = data.get("summary", "")
                continue

            # --- User / Assistant messages ---
            if line_type in ("user", "assistant"):
                msg = data.get("message", {})
                role = msg.get("role", line_type)
                content = msg.get("content", "")
                text = _extract_text(content)
                tool_uses = _extract_tool_uses(content)
                ts = _parse_timestamp(data)

                messages.append(TranscriptMessage(
                    role=role,
                    timestamp=ts,
                    text_content=text,
                    tool_uses=tool_uses,
                ))
                continue

            # --- tool_result as separate line (some formats) ---
            if line_type == "tool_result" and messages:
                content = data.get("content", "")
                _extract_tool_results(
                    [{"type": "tool_result", "content": content}],
                    messages[-1].tool_uses,
                )

    logger.debug(
        "Parsed %s: %d messages, summary=%s",
        jsonl_path, len(messages), summary is not None,
    )
    return TranscriptData(summary=summary, messages=messages, raw_line_hashes=line_hashes)
