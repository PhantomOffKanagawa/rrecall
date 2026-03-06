"""Code indexer — walks repos, chunks source files, and indexes into LanceDB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pathspec
import pyarrow as pa

from rrecall.code.chunkers.languages import EXTENSION_MAP, detect_language
from rrecall.code.chunkers.treesitter import chunk_file
from rrecall.config import CodeConfig, RrecallConfig, get_config, get_config_dir
from rrecall.embedding.base import EmbeddingProvider
from rrecall.utils.hashing import file_hash
from rrecall.utils.logging import get_logger
from rrecall.vectordb.lancedb_store import EMBEDDING_DIM, VectorStore

logger = get_logger("code.indexer")

TABLE_NAME = "code"
_INDEX_FILE = "code_file_index.json"

MAX_FILE_SIZE = 100_000  # 100 KB


def code_schema(dim: int = EMBEDDING_DIM) -> pa.Schema:
    return pa.schema([
        pa.field("id", pa.utf8(), nullable=False),
        pa.field("source_file", pa.utf8()),
        pa.field("repo_name", pa.utf8()),
        pa.field("language", pa.utf8()),
        pa.field("chunk_type", pa.utf8()),
        pa.field("symbol_name", pa.utf8()),
        pa.field("parent_symbol", pa.utf8()),
        pa.field("signature", pa.utf8()),
        pa.field("text", pa.utf8()),
        pa.field("context_header", pa.utf8()),
        pa.field("content_hash", pa.utf8()),
        pa.field("start_line", pa.int32()),
        pa.field("end_line", pa.int32()),
        pa.field("chunk_index", pa.int32()),
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ])


def _load_file_index() -> dict[str, str]:
    idx_path = get_config_dir() / _INDEX_FILE
    if idx_path.exists():
        return json.loads(idx_path.read_text(encoding="utf-8"))
    return {}


def _save_file_index(index: dict[str, str]) -> None:
    idx_path = get_config_dir() / _INDEX_FILE
    tmp = idx_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
    tmp.rename(idx_path)


def _load_gitignore(repo_path: Path) -> pathspec.PathSpec | None:
    gi = repo_path / ".gitignore"
    if gi.exists():
        return pathspec.PathSpec.from_lines("gitignore", gi.read_text().splitlines())
    return None


def _is_binary(path: Path) -> bool:
    """Quick heuristic: check first 8KB for null bytes."""
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except OSError:
        return True


def collect_repo_files(repo_path: Path) -> list[Path]:
    """Walk a repo directory, respecting .gitignore, skipping binaries and large files."""
    gitignore = _load_gitignore(repo_path)
    # Always skip these directories
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv",
                 "vendor", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache"}

    files: list[Path] = []
    for p in repo_path.rglob("*"):
        if not p.is_file():
            continue
        # Skip files in ignored directories
        parts = p.relative_to(repo_path).parts
        if any(part in skip_dirs for part in parts):
            continue
        # Check language support
        if detect_language(p) is None:
            continue
        # Check gitignore
        rel = str(p.relative_to(repo_path))
        if gitignore and gitignore.match_file(rel):
            continue
        # Skip large or binary files
        try:
            if p.stat().st_size > MAX_FILE_SIZE:
                continue
        except OSError:
            continue
        if _is_binary(p):
            continue
        files.append(p)

    return sorted(files)


def index_repo(
    store: VectorStore,
    repo_path: Path,
    repo_name: str | None = None,
    config: RrecallConfig | None = None,
    embedder: EmbeddingProvider | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Index a single repo. Returns (files_indexed, chunks_added)."""
    if config is None:
        config = get_config()
    if repo_name is None:
        repo_name = repo_path.name

    code_cfg = config.code
    dim = embedder.dimension if embedder else EMBEDDING_DIM
    schema = code_schema(dim)
    store.create_or_open_table(TABLE_NAME, schema)

    file_index = _load_file_index()
    files = collect_repo_files(repo_path)

    files_indexed = 0
    chunks_added = 0
    current_paths: set[str] = set()

    for f in files:
        fpath = str(f)
        current_paths.add(fpath)
        fh = file_hash(f)

        if not force and file_index.get(fpath) == fh:
            continue

        chunks = chunk_file(f, max_chars=code_cfg.chunk_max_chars, min_chars=code_cfg.chunk_min_chars)
        if not chunks:
            file_index[fpath] = fh
            continue

        # Embed if provider given
        vectors: list[list[float]] | None = None
        if embedder is not None:
            texts = [f"{c.context_header}\n{c.text}" if c.context_header else c.text for c in chunks]
            vectors = embedder.embed_texts(texts)

        records: list[dict[str, Any]] = []
        for i, c in enumerate(chunks):
            records.append({
                "id": f"{fh}_{i}",
                "source_file": c.file_path,
                "repo_name": repo_name,
                "language": c.language,
                "chunk_type": c.chunk_type,
                "symbol_name": c.symbol_name,
                "parent_symbol": c.parent_symbol,
                "signature": c.signature,
                "text": c.text,
                "context_header": c.context_header,
                "content_hash": fh,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "chunk_index": i,
                "vector": vectors[i] if vectors else [0.0] * dim,
            })

        # Remove old chunks for this file before upserting
        try:
            escaped = fpath.replace("'", "''")
            table = store._db.open_table(TABLE_NAME)
            table.delete(f"source_file = '{escaped}'")
        except Exception:
            pass

        store.upsert_chunks(TABLE_NAME, records)
        chunks_added += len(records)
        files_indexed += 1
        file_index[fpath] = fh

    # Remove stale files (deleted from repo)
    repo_prefix = str(repo_path)
    stale = {k for k in file_index if k.startswith(repo_prefix)} - current_paths
    for fpath in stale:
        file_index.pop(fpath)
        try:
            escaped = fpath.replace("'", "''")
            table = store._db.open_table(TABLE_NAME)
            table.delete(f"source_file = '{escaped}'")
        except Exception as e:
            logger.warning("Failed to remove chunks for %s: %s", fpath, e)

    _save_file_index(file_index)

    if files_indexed > 0 or stale:
        try:
            store.ensure_fts_index(TABLE_NAME, column="text")
        except Exception as e:
            logger.warning("FTS index creation failed: %s", e)

    return files_indexed, chunks_added
