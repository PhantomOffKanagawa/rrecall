"""Tests for the session_end hook."""

import io
import json
import sys

import pytest
from pathlib import Path

from rrecall.hooks.session_end import main
from rrecall.hooks.session_registry import register_session, record_session_end
from rrecall.utils.hashing import content_hash


@pytest.fixture(autouse=True)
def tmp_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))


def _make_transcript(tmp_path: Path, num_messages: int = 4) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    lines = [{"type": "summary", "summary": "Test session"}]
    for i in range(num_messages):
        role = "user" if i % 2 == 0 else "assistant"
        lines.append({
            "type": role,
            "message": {"role": role, "content": f"Message {i}"},
            "timestamp": "2026-03-05T10:00:00Z",
        })
    with open(transcript, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return transcript


def test_empty_stdin_exits_cleanly(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_missing_session_id_exits_cleanly(tmp_path, monkeypatch):
    transcript = _make_transcript(tmp_path)
    payload = json.dumps({"transcript_path": str(transcript), "cwd": "/home/user/project"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_missing_transcript_path_exits_cleanly(monkeypatch):
    payload = json.dumps({"session_id": "sess-001", "cwd": "/home/user/project"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_nonexistent_transcript_exits_cleanly(monkeypatch):
    payload = json.dumps({
        "session_id": "sess-001",
        "transcript_path": "/does/not/exist.jsonl",
        "cwd": "/home/user/project",
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_duplicate_transcript_skips_processing(tmp_path, monkeypatch):
    transcript = _make_transcript(tmp_path)
    file_content = transcript.read_text(encoding="utf-8")
    t_hash = content_hash(file_content)

    register_session("sess-dup", "/home/user/project")
    record_session_end("sess-dup", t_hash, "/vault/session.md")

    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: calls.append(args))

    payload = json.dumps({
        "session_id": "sess-dup",
        "transcript_path": str(transcript),
        "cwd": "/home/user/project",
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert len(calls) == 0


def test_too_few_messages_skips_processing(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[hooks.filtering]\nenabled = true\nmin_messages = 5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))

    transcript = _make_transcript(tmp_path, num_messages=2)

    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: calls.append(args))

    payload = json.dumps({
        "session_id": "sess-short",
        "transcript_path": str(transcript),
        "cwd": "/home/user/project",
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert len(calls) == 0


def test_valid_session_launches_finalize_subprocess(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[hooks.filtering]\nenabled = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))

    transcript = _make_transcript(tmp_path)

    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: calls.append(args))

    payload = json.dumps({
        "session_id": "sess-valid",
        "transcript_path": str(transcript),
        "cwd": "/home/user/project",
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert len(calls) == 1
    assert "rrecall.hooks.finalize" in calls[0]
