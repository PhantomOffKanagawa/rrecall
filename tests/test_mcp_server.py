"""Tests for rrecall.mcp_server tools."""

from __future__ import annotations

import json

import pytest

from rrecall.mcp_server import (
    get_code_context,
    get_session,
    list_recent_sessions,
    search_code,
    search_notes,
)


@pytest.fixture(autouse=True)
def _reset_globals(tmp_path, monkeypatch):
    """Reset shared state and point config dir to tmp."""
    import rrecall.mcp_server as srv
    import rrecall.config as cfg

    srv._store = None
    srv._embedder = None
    srv._config = None
    cfg._config = None
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path / "config"))


@pytest.fixture()
def indexed_notes(tmp_path, monkeypatch):
    """Set up a store with indexed notes."""
    from rrecall.notes.indexer import TABLE_NAME
    from rrecall.vectordb.lancedb_store import NOTES_SCHEMA, VectorStore

    import rrecall.mcp_server as srv

    db_path = tmp_path / "config" / "lancedb"
    store = VectorStore(db_path=db_path)
    store.create_or_open_table(TABLE_NAME, NOTES_SCHEMA)
    store.upsert_chunks(TABLE_NAME, [
        {"id": "n1", "text": "JWT refresh token implementation details", "source_file": "session.md",
         "heading": "Auth", "content_hash": "", "session_id": "s1", "project": "backend",
         "tags": "auth,jwt", "chunk_index": 0, "vector": [0.0] * 384},
    ])
    store.ensure_fts_index(TABLE_NAME)
    srv._store = store
    return store


@pytest.fixture()
def indexed_code(tmp_path, monkeypatch):
    """Set up a store with indexed code."""
    from rrecall.code.indexer import TABLE_NAME, code_schema
    from rrecall.vectordb.lancedb_store import VectorStore

    import rrecall.mcp_server as srv

    db_path = tmp_path / "config" / "lancedb"
    store = srv._store or VectorStore(db_path=db_path)
    store.create_or_open_table(TABLE_NAME, code_schema())
    store.upsert_chunks(TABLE_NAME, [
        {"id": "c1", "text": "def connect_db(url):\n    return Database(url)",
         "source_file": "db.py", "repo_name": "myapp", "language": "python",
         "chunk_type": "function", "symbol_name": "connect_db", "parent_symbol": "",
         "signature": "def connect_db(url):", "context_header": "",
         "content_hash": "", "start_line": 1, "end_line": 2, "chunk_index": 0,
         "vector": [0.0] * 384},
    ])
    store.ensure_fts_index(TABLE_NAME)
    srv._store = store
    return store


def test_search_notes_returns_results(indexed_notes):
    result = search_notes("JWT", mode="text")
    assert "JWT" in result
    assert "session.md" in result


def test_search_notes_no_results(indexed_notes):
    result = search_notes("nonexistent_query_xyz", mode="text")
    assert "No results" in result


def test_search_code_returns_results(indexed_code):
    result = search_code("connect_db", mode="text")
    assert "connect_db" in result
    assert "db.py" in result


def test_search_code_no_results(indexed_code):
    result = search_code("nonexistent_query_xyz", mode="text")
    assert "No results" in result


def test_list_recent_sessions_empty(tmp_path):
    result = list_recent_sessions()
    assert "No sessions" in result


def test_list_recent_sessions_with_data(tmp_path):
    registry_dir = tmp_path / "config"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "sess1": {
            "session_id": "sess1",
            "cwd": "/home/user/project",
            "started_at": "2026-01-01T00:00:00",
            "status": "completed",
            "markdown_path": "/vault/sess1.md",
        }
    }
    (registry_dir / "sessions.json").write_text(json.dumps(registry))
    result = list_recent_sessions()
    assert "sess1" in result
    assert "completed" in result


def test_get_session_not_found(tmp_path):
    result = get_session("nonexistent")
    assert "not found" in result


def test_get_code_context(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    result = get_code_context(str(f), start_line=2, end_line=3, context_lines=1)
    assert "line1" in result
    assert "line4" in result
    assert "→" in result  # marker on lines 2-3


def test_get_code_context_missing_file():
    result = get_code_context("/nonexistent/file.py")
    assert "not found" in result
