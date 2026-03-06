"""Tests for the session registry."""

import json

import pytest

from rrecall.hooks.session_registry import (
    get_session,
    is_duplicate,
    record_session_end,
    register_session,
)


@pytest.fixture(autouse=True)
def tmp_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))


def test_register_session_creates_entry():
    entry = register_session("sess-001", "/home/user/project")
    assert entry.session_id == "sess-001"
    assert entry.cwd == "/home/user/project"
    assert entry.status == "active"


def test_register_session_second_call_returns_existing():
    first = register_session("sess-001", "/home/user/project")
    second = register_session("sess-001", "/different/path")
    assert second.session_id == first.session_id
    assert second.cwd == "/home/user/project"


def test_record_session_end_sets_completed_status():
    register_session("sess-001", "/home/user/project")
    record_session_end("sess-001", "abc123hash", "/vault/session.md")

    entry = get_session("sess-001")
    assert entry.status == "completed"
    assert entry.last_transcript_hash == "abc123hash"
    assert entry.markdown_path == "/vault/session.md"


def test_get_session_returns_none_for_unknown():
    assert get_session("no-such-session") is None


def test_is_duplicate_returns_true_when_hash_matches():
    register_session("sess-001", "/home/user/project")
    record_session_end("sess-001", "myhash", "/vault/session.md")
    assert is_duplicate("sess-001", "myhash") is True


def test_is_duplicate_returns_false_when_hash_differs():
    register_session("sess-001", "/home/user/project")
    record_session_end("sess-001", "myhash", "/vault/session.md")
    assert is_duplicate("sess-001", "otherhash") is False


def test_is_duplicate_returns_false_for_unknown_session():
    assert is_duplicate("no-such-session", "somehash") is False


def test_is_duplicate_returns_false_for_empty_hash():
    register_session("sess-001", "/home/user/project")
    assert is_duplicate("sess-001", "") is False


def test_registry_persists_across_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))
    register_session("sess-persist", "/home/user/project")
    record_session_end("sess-persist", "hash99", "/vault/out.md")

    registry_file = tmp_path / "sessions.json"
    raw = json.loads(registry_file.read_text())
    assert "sess-persist" in raw
    assert raw["sess-persist"]["status"] == "completed"
    assert raw["sess-persist"]["last_transcript_hash"] == "hash99"
