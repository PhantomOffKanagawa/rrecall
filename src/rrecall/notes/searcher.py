"""Notes searcher — full-text, vector, and hybrid search over indexed notes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rrecall.notes.indexer import TABLE_NAME
from rrecall.vectordb.lancedb_store import SearchResult, VectorStore

if TYPE_CHECKING:
    from rrecall.embedding.base import EmbeddingProvider

SUPPORTED_MODES = {"text", "vector", "hybrid"}


def _build_filter(
    project: str | None,
    session_id: str | None,
    tags: str | None,
) -> str | None:
    filters: list[str] = []
    if project:
        filters.append(f"project = '{project}'")
    if session_id:
        filters.append(f"session_id = '{session_id}'")
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                filters.append(f"tags LIKE '%{tag}%'")
    return " AND ".join(filters) if filters else None


def search(
    store: VectorStore,
    query: str,
    *,
    top_k: int = 10,
    mode: str = "text",
    project: str | None = None,
    session_id: str | None = None,
    tags: str | None = None,
    embedder: EmbeddingProvider | None = None,
) -> list[SearchResult]:
    """Search indexed notes.

    Args:
        store: The VectorStore instance.
        query: Search query string.
        top_k: Maximum results to return.
        mode: "text" (FTS), "vector" (ANN), or "hybrid" (RRF fusion).
        project: Filter to a specific project name.
        session_id: Filter to a specific session.
        tags: Filter by tag (comma-separated).
        embedder: Required for vector/hybrid modes.
    """
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported search mode: {mode!r}")

    if mode in ("vector", "hybrid") and embedder is None:
        raise ValueError(f"mode={mode!r} requires an embedder")

    filter_expr = _build_filter(project, session_id, tags)

    if mode == "text":
        return store.text_search(TABLE_NAME, query, top_k=top_k, filter_expr=filter_expr)

    query_vector = embedder.embed_query(query)  # type: ignore[union-attr]

    if mode == "vector":
        return store.vector_search(TABLE_NAME, query_vector, top_k=top_k, filter_expr=filter_expr)

    # hybrid
    return store.hybrid_search(TABLE_NAME, query, query_vector, top_k=top_k, filter_expr=filter_expr)
