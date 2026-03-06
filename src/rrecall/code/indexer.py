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


_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              "vendor", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache"}


def discover_dirs(paths: list[str], scan_depth: int) -> list[Path]:
    """Find project directories under the given paths.

    Walks each configured path and returns its immediate subdirectories
    (the "project" level). Each project is then indexed separately so that
    per-project .gitignore files are respected.

    If a configured path has no subdirectories with indexable files,
    the path itself is included.
    """
    dirs: list[Path] = []
    for raw in paths:
        base = Path(raw).expanduser().resolve()
        if not base.is_dir():
            logger.warning("Configured path does not exist: %s", base)
            continue
        # Collect subdirectories at depth 1 (project level)
        found_any = False
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.name not in _SKIP_DIRS and not child.name.startswith("."):
                dirs.append(child)
                found_any = True
        if not found_any:
            dirs.append(base)
    return dirs


def index_paths(
    store: VectorStore,
    config: RrecallConfig | None = None,
    embedder: EmbeddingProvider | None = None,
    force: bool = False,
) -> tuple[int, int, int]:
    """Discover and index all directories under configured paths. Returns (dirs, files, chunks)."""
    if config is None:
        config = get_config()
    repos_cfg = config.code.repos.all
    dirs = discover_dirs(repos_cfg.paths, repos_cfg.scan_depth)
    logger.info("Discovered %d directories under %s", len(dirs), repos_cfg.paths)

    total_files = 0
    total_chunks = 0
    for dir_path in dirs:
        files, chunks = index_repo(store, dir_path, config=config, embedder=embedder, force=force)
        logger.info("  %s: %d files, %d chunks", dir_path.name, files, chunks)
        total_files += files
        total_chunks += chunks

    return len(dirs), total_files, total_chunks


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

    files: list[Path] = []
    for p in repo_path.rglob("*"):
        if not p.is_file():
            continue
        # Skip files in ignored directories
        parts = p.relative_to(repo_path).parts
        if any(part in _SKIP_DIRS for part in parts):
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

    # Determine which files need indexing
    to_index: list[tuple[Path, str, str]] = []  # (path, fpath, file_hash)
    for f in files:
        fpath = str(f)
        current_paths.add(fpath)
        fh = file_hash(f)
        if force or file_index.get(fpath) != fh:
            to_index.append((f, fpath, fh))
        else:
            pass  # unchanged, skip

    import click
    skipped = len(files) - len(to_index)
    if skipped and to_index:
        click.echo(f"Skipping {skipped} unchanged files, indexing {len(to_index)}...")

    if to_index:
        # Phase 1: Chunk all files (fast, no I/O beyond reading source)
        # Each entry: (fpath, fh, list_of_chunks)
        file_chunks: list[tuple[str, str, list]] = []
        with click.progressbar(to_index, label="Chunking",
                               item_show_func=lambda p: str(p[0].name) if p else "") as bar:
            for f, fpath, fh in bar:
                chunks = chunk_file(f, max_chars=code_cfg.chunk_max_chars, min_chars=code_cfg.chunk_min_chars)
                file_chunks.append((fpath, fh, chunks))

        # Phase 2: Batch embed all chunks at once
        all_texts: list[str] = []
        for fpath, fh, chunks in file_chunks:
            for c in chunks:
                text = f"{c.context_header}\n{c.text}" if c.context_header else c.text
                all_texts.append(text)

        all_vectors: list[list[float]] | None = None
        if embedder is not None and all_texts:
            click.echo(f"Embedding {len(all_texts)} chunks...")
            all_vectors = embedder.embed_texts(all_texts)

        # Phase 3: Build records and upsert in batches
        vec_idx = 0
        all_records: list[dict[str, Any]] = []
        delete_paths: list[str] = []

        for fpath, fh, chunks in file_chunks:
            if not chunks:
                file_index[fpath] = fh
                vec_idx += len(chunks)  # 0, but consistent
                continue

            delete_paths.append(fpath)
            for i, c in enumerate(chunks):
                all_records.append({
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
                    "vector": all_vectors[vec_idx] if all_vectors else [0.0] * dim,
                })
                vec_idx += 1

            files_indexed += 1
            file_index[fpath] = fh

        # Bulk delete old chunks for changed files
        if delete_paths:
            try:
                table = store._db.open_table(TABLE_NAME)
                conditions = " OR ".join(
                    f"source_file = '{p.replace(chr(39), chr(39)+chr(39))}'" for p in delete_paths
                )
                table.delete(conditions)
            except Exception:
                pass

        # Bulk upsert in batches of 5000 records
        BATCH_SIZE = 5000
        if all_records:
            with click.progressbar(range(0, len(all_records), BATCH_SIZE),
                                   label="Writing ", length=len(all_records) // BATCH_SIZE + 1) as bar:
                for start in bar:
                    batch = all_records[start:start + BATCH_SIZE]
                    store.upsert_chunks(TABLE_NAME, batch)
            chunks_added = len(all_records)

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
