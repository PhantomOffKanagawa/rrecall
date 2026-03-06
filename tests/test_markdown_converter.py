"""Tests for the markdown converter."""

from datetime import datetime, timezone

import pytest

from rrecall.hooks.transcript_parser import TranscriptData, TranscriptMessage, ToolUseBlock
from rrecall.hooks.markdown_converter import transcript_to_markdown, resumed_section, SessionMetadata


def _make_data(summary="Test session summary", messages=None):
    if messages is None:
        messages = [
            TranscriptMessage(role="user", timestamp=None, text_content="Hello"),
            TranscriptMessage(role="assistant", timestamp=None, text_content="Hi there"),
        ]
    return TranscriptData(summary=summary, messages=messages)


def _make_meta(
    session_id="sess-001",
    cwd="/home/user/my-project",
    started_at=None,
    ended_at=None,
):
    return SessionMetadata(
        session_id=session_id,
        cwd=cwd,
        started_at=started_at,
        ended_at=ended_at,
    )


def test_output_has_yaml_frontmatter():
    md = transcript_to_markdown(_make_data(), _make_meta())
    lines = md.splitlines()
    assert lines[0] == "---"
    closing = lines.index("---", 1)
    assert closing > 1


def test_output_has_summary_section():
    md = transcript_to_markdown(_make_data(), _make_meta())
    assert "## Summary" in md
    assert "Test session summary" in md


def test_output_has_conversation_section():
    md = transcript_to_markdown(_make_data(), _make_meta())
    assert "## Conversation" in md


def test_frontmatter_contains_session_id():
    md = transcript_to_markdown(_make_data(), _make_meta(session_id="my-session-42"))
    frontmatter = md.split("---")[1]
    assert "session_id: my-session-42" in frontmatter


def test_frontmatter_contains_project():
    md = transcript_to_markdown(_make_data(), _make_meta(cwd="/home/user/my-project"))
    frontmatter = md.split("---")[1]
    assert "project: my-project" in frontmatter


def test_frontmatter_contains_cwd():
    md = transcript_to_markdown(_make_data(), _make_meta(cwd="/home/user/my-project"))
    frontmatter = md.split("---")[1]
    assert "/home/user/my-project" in frontmatter


def test_frontmatter_contains_claude_session_tag():
    md = transcript_to_markdown(_make_data(), _make_meta())
    frontmatter = md.split("---")[1]
    assert "claude-session" in frontmatter


def test_frontmatter_contains_project_tag():
    md = transcript_to_markdown(_make_data(), _make_meta(cwd="/home/user/my-project"))
    frontmatter = md.split("---")[1]
    assert "my-project" in frontmatter


def test_frontmatter_contains_summary():
    md = transcript_to_markdown(_make_data(summary="Refactored auth"), _make_meta())
    frontmatter = md.split("---")[1]
    assert "Refactored auth" in frontmatter


def test_tool_use_renders_as_obsidian_callout():
    tool = ToolUseBlock(tool_name="Bash", input_summary="cat src/auth.py")
    msg = TranscriptMessage(role="assistant", timestamp=None, text_content="", tool_uses=[tool])
    data = TranscriptData(summary="x", messages=[msg])
    md = transcript_to_markdown(data, _make_meta())
    assert "> [!tool]- Bash: `cat src/auth.py`" in md


def test_resumed_section_heading():
    ts = datetime(2026, 3, 5, 14, 30, 0, tzinfo=timezone.utc)
    data = TranscriptData(summary=None, messages=[])
    result = resumed_section(data, resumed_at=ts)
    assert "## Resumed (" in result
    assert "2026-03-05" in result


def test_resumed_section_without_timestamp():
    data = TranscriptData(summary=None, messages=[])
    result = resumed_section(data, resumed_at=None)
    assert "## Resumed (unknown)" in result


def test_session_metadata_project_name():
    meta = SessionMetadata(session_id="x", cwd="/home/user/my-project")
    assert meta.project_name == "my-project"


def test_session_metadata_project_name_nested_path():
    meta = SessionMetadata(session_id="x", cwd="/work/org/team/repo")
    assert meta.project_name == "repo"


def test_duration_90_minutes():
    started = datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 3, 5, 11, 30, 0, tzinfo=timezone.utc)
    meta = _make_meta(started_at=started, ended_at=ended)
    md = transcript_to_markdown(_make_data(), meta)
    assert "1h 30m" in md


def test_duration_under_one_hour():
    started = datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 3, 5, 10, 45, 0, tzinfo=timezone.utc)
    meta = _make_meta(started_at=started, ended_at=ended)
    md = transcript_to_markdown(_make_data(), meta)
    assert "45m" in md


def test_duration_unknown_when_no_timestamps():
    md = transcript_to_markdown(_make_data(), _make_meta())
    assert "unknown" in md
