"""Tests for the pre_compact hook."""

import io
import json
import sys

import pytest
from pathlib import Path

from rrecall.hooks.pre_compact import main
from rrecall.hooks.session_registry import get_session


@pytest.fixture(autouse=True)
def tmp_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))


def _make_transcript(tmp_path: Path) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"type": "summary", "summary": "Test session"}) + "\n"
        + json.dumps({"type": "user", "message": {"role": "user", "content": "Hello"}}) + "\n",
        encoding="utf-8",
    )
    return transcript


def test_valid_payload_creates_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))
    transcript = _make_transcript(tmp_path)
    payload = json.dumps({
        "session_id": "sess-001",
        "transcript_path": str(transcript),
        "cwd": "/home/user/project",
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    snapshots_dir = tmp_path / "snapshots"
    snapshot_files = list(snapshots_dir.glob("sess-001_*.jsonl"))
    assert len(snapshot_files) == 1


def test_valid_payload_updates_registry(tmp_path, monkeypatch):
    transcript = _make_transcript(tmp_path)
    payload = json.dumps({
        "session_id": "sess-002",
        "transcript_path": str(transcript),
        "cwd": "/home/user/project",
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    entry = get_session("sess-002")
    assert entry is not None
    assert len(entry.pre_compact_snapshots) == 1


def test_empty_stdin_exits_cleanly(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_missing_transcript_path_exits_cleanly(monkeypatch):
    payload = json.dumps({"session_id": "sess-003", "cwd": "/home/user/project"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_nonexistent_transcript_exits_cleanly(monkeypatch):
    payload = json.dumps({
        "session_id": "sess-004",
        "transcript_path": "/does/not/exist.jsonl",
        "cwd": "/home/user/project",
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_malformed_json_stdin_exits_cleanly(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{not valid json"))

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
