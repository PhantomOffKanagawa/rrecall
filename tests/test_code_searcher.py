"""Tests for rrecall.code.searcher."""

from __future__ import annotations

import pytest

from rrecall.code.indexer import TABLE_NAME, code_schema
from rrecall.code.searcher import search
from rrecall.vectordb.lancedb_store import VectorStore

_ZERO_VEC = [0.0] * 384


@pytest.fixture()
def store(tmp_path):
    s = VectorStore(db_path=tmp_path / "lancedb")
    s.create_or_open_table(TABLE_NAME, code_schema())
    s.upsert_chunks(TABLE_NAME, [
        {"id": "1", "text": "def authenticate_user(username, password):\n    return check_db(username, password)",
         "source_file": "auth.py", "repo_name": "backend", "language": "python",
         "chunk_type": "function", "symbol_name": "authenticate_user", "parent_symbol": "",
         "signature": "def authenticate_user(username, password):", "context_header": "",
         "content_hash": "", "start_line": 1, "end_line": 2, "chunk_index": 0, "vector": _ZERO_VEC},
        {"id": "2", "text": "export class UserController {\n    async getUser(req, res) {}\n}",
         "source_file": "user.ts", "repo_name": "frontend", "language": "typescript",
         "chunk_type": "class", "symbol_name": "UserController", "parent_symbol": "",
         "signature": "export class UserController", "context_header": "",
         "content_hash": "", "start_line": 1, "end_line": 3, "chunk_index": 0, "vector": _ZERO_VEC},
    ])
    s.ensure_fts_index(TABLE_NAME)
    return s


def test_search_returns_results(store):
    results = search(store, "authenticate")
    assert len(results) >= 1
    assert results[0].id == "1"


def test_search_language_filter(store):
    results = search(store, "UserController", language="typescript")
    ids = {r.id for r in results}
    assert "2" in ids
    assert "1" not in ids


def test_search_chunk_type_filter(store):
    results = search(store, "getUser", chunk_type="class")
    ids = {r.id for r in results}
    assert "2" in ids


def test_search_repo_filter(store):
    results = search(store, "authenticate", repo_name="backend")
    ids = {r.id for r in results}
    assert "1" in ids
    assert "2" not in ids


def test_unsupported_mode_raises(store):
    with pytest.raises(ValueError, match="Unsupported search mode"):
        search(store, "query", mode="magic")


def test_vector_mode_requires_embedder(store):
    with pytest.raises(ValueError, match="requires an embedder"):
        search(store, "query", mode="vector")
