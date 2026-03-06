"""Tests for the transcript parser."""

import json
import tempfile
from pathlib import Path

from rrecall.hooks.transcript_parser import parse_transcript


def _write_jsonl(lines: list[dict]) -> Path:
    """Write JSONL lines to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for line in lines:
        tmp.write(json.dumps(line) + "\n")
    tmp.close()
    return Path(tmp.name)


SAMPLE_LINES = [
    {"type": "summary", "summary": "Refactored auth module to use JWT", "leafUuid": "abc123"},
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Can you help me refactor the auth module?"}],
        },
        "timestamp": "2026-03-05T10:00:12Z",
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll help you refactor the auth module."},
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "cat src/auth.py"},
                },
            ],
        },
        "timestamp": "2026-03-05T10:00:45Z",
    },
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Looks good, add refresh token support."}],
        },
        "timestamp": "2026-03-05T10:15:22Z",
    },
]


def test_parse_basic():
    path = _write_jsonl(SAMPLE_LINES)
    result = parse_transcript(path)

    assert result.summary == "Refactored auth module to use JWT"
    assert len(result.messages) == 3
    assert result.messages[0].role == "user"
    assert "refactor the auth module" in result.messages[0].text_content
    assert result.messages[1].role == "assistant"
    assert len(result.messages[1].tool_uses) == 1
    assert result.messages[1].tool_uses[0].tool_name == "Bash"
    assert result.messages[1].tool_uses[0].input_summary == "cat src/auth.py"
    Path(path).unlink()


def test_parse_timestamps():
    path = _write_jsonl(SAMPLE_LINES)
    result = parse_transcript(path)

    assert result.messages[0].timestamp is not None
    assert result.messages[0].timestamp.hour == 10
    assert result.messages[0].timestamp.minute == 0
    Path(path).unlink()


def test_line_hashes_unique():
    path = _write_jsonl(SAMPLE_LINES)
    result = parse_transcript(path)

    # 4 non-empty lines -> 4 unique hashes
    assert len(result.raw_line_hashes) == 4
    Path(path).unlink()


def test_malformed_lines():
    lines = [
        {"type": "summary", "summary": "Test summary"},
        "this is not valid json {{{",  # will be written as raw string
        {"type": "user", "message": {"role": "user", "content": "Hello"}},
    ]
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    tmp.write(json.dumps(lines[0]) + "\n")
    tmp.write("this is not valid json {{{\n")  # malformed
    tmp.write(json.dumps(lines[2]) + "\n")
    tmp.close()
    path = Path(tmp.name)

    result = parse_transcript(path)
    assert result.summary == "Test summary"
    assert len(result.messages) == 1  # malformed line skipped
    assert result.messages[0].text_content == "Hello"
    path.unlink()


def test_empty_file():
    path = _write_jsonl([])
    result = parse_transcript(path)
    assert result.summary is None
    assert len(result.messages) == 0
    Path(path).unlink()


def test_string_content():
    """Messages with plain string content instead of list of blocks."""
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Simple string message"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "Simple reply"}},
    ]
    path = _write_jsonl(lines)
    result = parse_transcript(path)
    assert len(result.messages) == 2
    assert result.messages[0].text_content == "Simple string message"
    assert result.messages[1].text_content == "Simple reply"
    Path(path).unlink()
