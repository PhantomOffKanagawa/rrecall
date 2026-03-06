"""Tests for rrecall.notes.searcher."""

from __future__ import annotations

import pytest

from rrecall.notes.indexer import TABLE_NAME
from rrecall.notes.searcher import search
from rrecall.vectordb.lancedb_store import NOTES_SCHEMA, VectorStore


@pytest.fixture()
def store(tmp_path):
    s = VectorStore(db_path=tmp_path / "lancedb")
    s.create_or_open_table(TABLE_NAME, NOTES_SCHEMA)
    s.upsert_chunks(TABLE_NAME, [
        {"id": "1", "text": "python asyncio event loop", "source_file": "a.md", "heading": "Async",
         "content_hash": "", "session_id": "s1", "project": "backend", "tags": "python,async", "chunk_index": 0},
        {"id": "2", "text": "rust ownership borrow checker", "source_file": "b.md", "heading": "Memory",
         "content_hash": "", "session_id": "s2", "project": "systems", "tags": "rust", "chunk_index": 0},
    ])
    s.ensure_fts_index(TABLE_NAME)
    return s


def test_search_returns_results(store):
    results = search(store, "python")
    assert len(results) >= 1
    assert results[0].id == "1"


def test_search_project_filter(store):
    results = search(store, "python", project="systems")
    # python is in project "backend", filtering to "systems" should exclude it
    ids = [r.id for r in results]
    assert "1" not in ids


def test_unsupported_mode_raises(store):
    with pytest.raises(ValueError, match="Unsupported search mode"):
        search(store, "query", mode="vector")
