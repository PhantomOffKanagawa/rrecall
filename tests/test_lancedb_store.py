"""Tests for rrecall.vectordb.lancedb_store."""

from __future__ import annotations

import pytest

from rrecall.vectordb.lancedb_store import NOTES_SCHEMA, SearchResult, VectorStore

_ZERO_VEC = [0.0] * 384


@pytest.fixture()
def store(tmp_path):
    return VectorStore(db_path=tmp_path / "lancedb")


def test_create_and_reopen_table(store):
    t1 = store.create_or_open_table("t", NOTES_SCHEMA)
    t2 = store.create_or_open_table("t", NOTES_SCHEMA)
    assert t1.name == t2.name


def test_upsert_inserts_and_updates(store):
    store.create_or_open_table("t", NOTES_SCHEMA)
    store.upsert_chunks("t", [{"id": "1", "text": "hello", "source_file": "", "heading": "",
                               "content_hash": "", "session_id": "", "project": "", "tags": "", "chunk_index": 0,
                               "vector": _ZERO_VEC}])
    assert store.count("t") == 1

    store.upsert_chunks("t", [{"id": "1", "text": "updated", "source_file": "", "heading": "",
                               "content_hash": "", "session_id": "", "project": "", "tags": "", "chunk_index": 0,
                               "vector": _ZERO_VEC}])
    assert store.count("t") == 1


def test_delete_chunks(store):
    store.create_or_open_table("t", NOTES_SCHEMA)
    store.upsert_chunks("t", [
        {"id": "a", "text": "one", "source_file": "", "heading": "", "content_hash": "",
         "session_id": "", "project": "", "tags": "", "chunk_index": 0, "vector": _ZERO_VEC},
        {"id": "b", "text": "two", "source_file": "", "heading": "", "content_hash": "",
         "session_id": "", "project": "", "tags": "", "chunk_index": 1, "vector": _ZERO_VEC},
    ])
    store.delete_chunks("t", ["a"])
    assert store.count("t") == 1


def test_text_search(store):
    store.create_or_open_table("t", NOTES_SCHEMA)
    store.upsert_chunks("t", [
        {"id": "1", "text": "python programming language", "source_file": "a.md", "heading": "Intro",
         "content_hash": "", "session_id": "", "project": "", "tags": "", "chunk_index": 0, "vector": _ZERO_VEC},
        {"id": "2", "text": "rust systems language", "source_file": "b.md", "heading": "Intro",
         "content_hash": "", "session_id": "", "project": "", "tags": "", "chunk_index": 0, "vector": _ZERO_VEC},
    ])
    store.ensure_fts_index("t")
    results = store.text_search("t", "python", top_k=5)
    assert len(results) >= 1
    assert results[0].id == "1"
    assert isinstance(results[0], SearchResult)


def test_drop_table(store):
    store.create_or_open_table("t", NOTES_SCHEMA)
    store.drop_table("t")
    store.drop_table("nonexistent")  # should not raise


def test_empty_operations(store):
    store.create_or_open_table("t", NOTES_SCHEMA)
    store.upsert_chunks("t", [])  # no-op
    store.delete_chunks("t", [])  # no-op
