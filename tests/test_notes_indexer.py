"""Tests for rrecall.notes.indexer."""

from __future__ import annotations

from pathlib import Path

import pytest

from rrecall.notes.indexer import (
    _chunk_by_headings,
    _Frontmatter,
    _parse_frontmatter,
    index_file,
    index_vault,
)
from rrecall.vectordb.lancedb_store import VectorStore


@pytest.fixture()
def store(tmp_path):
    return VectorStore(db_path=tmp_path / "lancedb")


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("RRECALL_OBSIDIAN_VAULT", str(vault_dir))
    # Reset config singleton
    import rrecall.config as cfg
    cfg._config = None
    return vault_dir


def _write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- Frontmatter parsing ---

def test_parse_frontmatter_extracts_fields():
    text = "---\nsession_id: abc123\nproject: myproj\ntags: [coding, debug]\n---\n\n## Body"
    fm, body = _parse_frontmatter(text)
    assert fm.session_id == "abc123"
    assert fm.project == "myproj"
    assert fm.tags == ["coding", "debug"]
    assert "## Body" in body


def test_parse_frontmatter_no_frontmatter():
    fm, body = _parse_frontmatter("Just a plain file.")
    assert fm.session_id == ""
    assert body == "Just a plain file."


# --- Chunking ---

def test_chunk_by_headings_splits_on_headings(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("## Section A\nContent A\n\n## Section B\nContent B\n")
    chunks = _chunk_by_headings(md.read_text(), str(md), _Frontmatter())
    assert len(chunks) == 2
    assert chunks[0].heading == "Section A"
    assert chunks[1].heading == "Section B"


def test_chunk_by_headings_no_headings(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("Just plain content with no headings.")
    chunks = _chunk_by_headings(md.read_text(), str(md), _Frontmatter())
    assert len(chunks) == 1
    assert chunks[0].heading == ""


# --- Indexing ---

def test_index_file(tmp_path, store):
    md = _write_md(tmp_path / "note.md", "---\nproject: test\n---\n\n## Hello\nWorld\n")
    n = index_file(store, md)
    assert n == 1
    assert store.count("notes") == 1


def test_index_vault_incremental(vault, store, tmp_path, monkeypatch):
    _write_md(vault / "a.md", "## First\nContent one\n")
    _write_md(vault / "b.md", "## Second\nContent two\n")

    files, chunks, removed = index_vault(store, force=True)
    assert files == 2
    assert chunks == 2

    # Re-index without changes — should skip
    files2, chunks2, _ = index_vault(store)
    assert files2 == 0
    assert chunks2 == 0


def test_index_vault_handles_deletion(vault, store, tmp_path, monkeypatch):
    md = _write_md(vault / "temp.md", "## Temp\nWill be deleted\n")
    index_vault(store, force=True)
    assert store.count("notes") == 1

    md.unlink()
    _, _, removed = index_vault(store)
    assert removed == 1
