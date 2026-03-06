"""Tests for rrecall.code.indexer."""

from __future__ import annotations

from pathlib import Path

import pytest

from rrecall.code.indexer import collect_repo_files, index_repo
from rrecall.vectordb.lancedb_store import VectorStore


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def repo(tmp_path):
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    _write(repo_dir / "main.py", "def hello():\n    return 'world'\n")
    _write(repo_dir / "utils.py", "import os\n\ndef helper():\n    pass\n")
    _write(repo_dir / "readme.md", "# My Repo\n")
    _write(repo_dir / "data.bin", b"\x00\x01\x02".decode("latin-1"))
    _write(repo_dir / "node_modules" / "pkg.py", "x = 1\n")
    return repo_dir


@pytest.fixture()
def store(tmp_path):
    return VectorStore(db_path=tmp_path / "lancedb")


def test_collect_repo_files(repo):
    files = collect_repo_files(repo)
    names = {f.name for f in files}
    assert "main.py" in names
    assert "utils.py" in names
    # Excluded:
    assert "readme.md" not in names  # not a supported language
    assert "data.bin" not in names  # binary
    assert "pkg.py" not in names  # node_modules


def test_collect_respects_gitignore(repo):
    (repo / ".gitignore").write_text("utils.py\n")
    files = collect_repo_files(repo)
    names = {f.name for f in files}
    assert "main.py" in names
    assert "utils.py" not in names


def test_index_repo(repo, store, tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path / "config"))
    import rrecall.config as cfg
    cfg._config = None

    files, chunks = index_repo(store, repo, repo_name="myrepo")
    assert files == 2
    assert chunks >= 2
    assert store.count("code") >= 2


def test_index_repo_incremental(repo, store, tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path / "config"))
    import rrecall.config as cfg
    cfg._config = None

    index_repo(store, repo, repo_name="myrepo")

    # Re-index without changes — should skip
    files2, chunks2 = index_repo(store, repo, repo_name="myrepo")
    assert files2 == 0
    assert chunks2 == 0


def test_index_repo_detects_change(repo, store, tmp_path, monkeypatch):
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path / "config"))
    import rrecall.config as cfg
    cfg._config = None

    index_repo(store, repo, repo_name="myrepo")

    # Modify a file
    (repo / "main.py").write_text("def hello():\n    return 'changed'\n")
    files, chunks = index_repo(store, repo, repo_name="myrepo")
    assert files == 1
    assert chunks >= 1
