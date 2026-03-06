"""Notes indexer — walks the Obsidian vault, chunks markdown, and indexes into LanceDB."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rrecall.config import RrecallConfig, get_config, get_config_dir
from rrecall.embedding.base import EmbeddingProvider
from rrecall.utils.hashing import file_hash
from rrecall.utils.logging import get_logger
from rrecall.vectordb.lancedb_store import VectorStore, notes_schema

logger = get_logger("notes.indexer")

TABLE_NAME = "notes"
_INDEX_FILE = "notes_file_index.json"


@dataclass
class ChunkInfo:
    """A single chunk extracted from a markdown file."""
    id: str
    source_file: str
    heading: str
    text: str
    chunk_index: int
    session_id: str = ""
    project: str = ""
    tags: str = ""


@dataclass
class _Frontmatter:
    """Parsed YAML frontmatter from a markdown file."""
    session_id: str = ""
    project: str = ""
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _parse_frontmatter(text: str) -> tuple[_Frontmatter, str]:
    """Extract YAML frontmatter from markdown text.

    Returns (frontmatter, body_without_frontmatter).
    """
    fm = _Frontmatter()
    if not text.startswith("---"):
        return fm, text

    end = text.find("\n---", 3)
    if end == -1:
        return fm, text

    yaml_block = text[4:end].strip()
    body = text[end + 4:].lstrip("\n")

    # Simple key: value parsing (no full YAML library needed)
    for line in yaml_block.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")

        fm.raw[key] = val
        if key == "session_id":
            fm.session_id = val
        elif key == "project":
            fm.project = val
        elif key == "tags":
            # tags can be [tag1, tag2] or comma-separated
            val_clean = val.strip("[]")
            fm.tags = [t.strip().strip("#") for t in val_clean.split(",") if t.strip()]

    return fm, body


def _chunk_by_headings(body: str, source_file: str, fm: _Frontmatter) -> list[ChunkInfo]:
    """Split markdown body into chunks at heading boundaries."""
    # Split on ## and ### headings
    heading_pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)

    chunks: list[ChunkInfo] = []
    positions: list[tuple[int, str]] = []

    for m in heading_pattern.finditer(body):
        positions.append((m.start(), m.group(2).strip()))

    if not positions:
        # No headings — treat entire body as one chunk
        text = body.strip()
        if text:
            fh = file_hash(Path(source_file)) if Path(source_file).exists() else source_file
            chunks.append(ChunkInfo(
                id=f"{fh}_0",
                source_file=source_file,
                heading="",
                text=text,
                chunk_index=0,
                session_id=fm.session_id,
                project=fm.project,
                tags=",".join(fm.tags),
            ))
        return chunks

    # Content before first heading
    pre_heading = body[:positions[0][0]].strip()
    fh = file_hash(Path(source_file)) if Path(source_file).exists() else source_file

    if pre_heading:
        chunks.append(ChunkInfo(
            id=f"{fh}_0",
            source_file=source_file,
            heading="(preamble)",
            text=pre_heading,
            chunk_index=0,
            session_id=fm.session_id,
            project=fm.project,
            tags=",".join(fm.tags),
        ))

    for i, (start, heading) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        text = body[start:end].strip()
        if text:
            chunk_idx = len(chunks)
            chunks.append(ChunkInfo(
                id=f"{fh}_{chunk_idx}",
                source_file=source_file,
                heading=heading,
                text=text,
                chunk_index=chunk_idx,
                session_id=fm.session_id,
                project=fm.project,
                tags=",".join(fm.tags),
            ))

    return chunks


def _load_file_index() -> dict[str, str]:
    """Load the file index (path -> content_hash) from disk."""
    idx_path = get_config_dir() / _INDEX_FILE
    if idx_path.exists():
        return json.loads(idx_path.read_text(encoding="utf-8"))
    return {}


def _save_file_index(index: dict[str, str]) -> None:
    """Persist the file index to disk."""
    idx_path = get_config_dir() / _INDEX_FILE
    tmp = idx_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
    tmp.rename(idx_path)


def _should_include(path: Path, config: RrecallConfig) -> bool:
    """Check if a file matches include/exclude patterns."""
    name = path.name
    rel = str(path)
    for pattern in config.notes.exclude_patterns:
        if path.match(pattern) or Path(rel).match(pattern):
            return False
    for pattern in config.notes.include_patterns:
        if path.match(pattern):
            return True
    return False


def _collect_vault_files(config: RrecallConfig) -> list[Path]:
    """Walk the vault directory and return matching markdown files."""
    vault = config.general.vault_path
    if not vault.exists():
        logger.warning("Vault path does not exist: %s", vault)
        return []
    files = []
    for p in vault.rglob("*"):
        if p.is_file() and _should_include(p, config):
            files.append(p)
    return sorted(files)


def index_file(
    store: VectorStore,
    file_path: Path,
    config: RrecallConfig | None = None,
    embedder: EmbeddingProvider | None = None,
) -> int:
    """Index a single markdown file. Returns the number of chunks indexed."""
    if config is None:
        config = get_config()

    text = file_path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    chunks = _chunk_by_headings(body, str(file_path), fm)

    if not chunks:
        return 0

    # Compute embeddings if a provider is given
    vectors: list[list[float]] | None = None
    if embedder is not None:
        vectors = embedder.embed_texts([c.text for c in chunks])

    dim = embedder.dimension if embedder else 384
    schema = notes_schema(dim)
    store.create_or_open_table(TABLE_NAME, schema)

    fh = file_hash(file_path)
    records = []
    for i, c in enumerate(chunks):
        rec: dict[str, Any] = {
            "id": c.id,
            "source_file": c.source_file,
            "heading": c.heading,
            "text": c.text,
            "content_hash": fh,
            "session_id": c.session_id,
            "project": c.project,
            "tags": c.tags,
            "chunk_index": c.chunk_index,
            "vector": vectors[i] if vectors else [0.0] * dim,
        }
        records.append(rec)

    store.upsert_chunks(TABLE_NAME, records)
    return len(records)


def index_vault(
    store: VectorStore,
    config: RrecallConfig | None = None,
    force: bool = False,
    embedder: EmbeddingProvider | None = None,
) -> tuple[int, int, int]:
    """Index the entire vault. Returns (files_indexed, chunks_added, files_removed)."""
    if config is None:
        config = get_config()

    file_index = _load_file_index()
    files = _collect_vault_files(config)

    dim = embedder.dimension if embedder else 384
    schema = notes_schema(dim)
    store.create_or_open_table(TABLE_NAME, schema)

    files_indexed = 0
    chunks_added = 0

    current_paths = set()
    to_index: list[tuple[Path, str, str]] = []
    for f in files:
        fpath = str(f)
        current_paths.add(fpath)
        fh = file_hash(f)
        if force or file_index.get(fpath) != fh:
            to_index.append((f, fpath, fh))

    import click
    skipped = len(files) - len(to_index)
    if skipped and to_index:
        click.echo(f"Skipping {skipped} unchanged files, indexing {len(to_index)}...")

    with click.progressbar(to_index, label="Indexing",
                           item_show_func=lambda p: str(p[0].name) if p else "") as bar:
        for f, fpath, fh in bar:
            n = index_file(store, f, config, embedder=embedder)
            chunks_added += n
            files_indexed += 1
            file_index[fpath] = fh

    # Handle deletions — remove chunks for files no longer present
    files_removed = 0
    stale = set(file_index.keys()) - current_paths
    for fpath in stale:
        old_hash = file_index.pop(fpath)
        # Chunks have IDs prefixed with the file hash
        # We need to delete by source_file
        try:
            table = store._db.open_table(TABLE_NAME)
            escaped = fpath.replace("'", "''")
            table.delete(f"source_file = '{escaped}'")
            files_removed += 1
        except Exception as e:
            logger.warning("Failed to remove chunks for %s: %s", fpath, e)

    _save_file_index(file_index)

    # Rebuild FTS index after changes
    if files_indexed > 0 or files_removed > 0:
        store.ensure_fts_index(TABLE_NAME)

    return files_indexed, chunks_added, files_removed
