"""Code searcher — full-text, vector, and hybrid search over indexed code."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rrecall.code.indexer import TABLE_NAME
from rrecall.vectordb.lancedb_store import SearchResult, VectorStore

if TYPE_CHECKING:
    from rrecall.embedding.base import EmbeddingProvider

SUPPORTED_MODES = {"text", "vector", "hybrid"}


def _build_filter(
    language: str | None,
    chunk_type: str | None,
    repo_name: str | None,
) -> str | None:
    filters: list[str] = []
    if language:
        filters.append(f"language = '{language}'")
    if chunk_type:
        filters.append(f"chunk_type = '{chunk_type}'")
    if repo_name:
        filters.append(f"repo_name = '{repo_name}'")
    return " AND ".join(filters) if filters else None


def search(
    store: VectorStore,
    query: str,
    *,
    top_k: int = 10,
    mode: str = "text",
    language: str | None = None,
    chunk_type: str | None = None,
    repo_name: str | None = None,
    embedder: EmbeddingProvider | None = None,
) -> list[SearchResult]:
    """Search indexed code.

    Args:
        store: The VectorStore instance.
        query: Search query string.
        top_k: Maximum results to return.
        mode: "text" (FTS), "vector" (ANN), or "hybrid" (RRF fusion).
        language: Filter by language (e.g. "python", "typescript").
        chunk_type: Filter by chunk type (e.g. "function", "class").
        repo_name: Filter by repository name.
        embedder: Required for vector/hybrid modes.
    """
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported search mode: {mode!r}")

    if mode in ("vector", "hybrid") and embedder is None:
        raise ValueError(f"mode={mode!r} requires an embedder")

    filter_expr = _build_filter(language, chunk_type, repo_name)

    if mode == "text":
        return store.text_search(TABLE_NAME, query, top_k=top_k, filter_expr=filter_expr)

    query_vector = embedder.embed_query(query)  # type: ignore[union-attr]

    if mode == "vector":
        return store.vector_search(TABLE_NAME, query_vector, top_k=top_k, filter_expr=filter_expr)

    return store.hybrid_search(TABLE_NAME, query, query_vector, top_k=top_k, filter_expr=filter_expr)


def find_similar(
    store: VectorStore,
    snippet: str,
    embedder: EmbeddingProvider,
    *,
    top_k: int = 10,
    language: str | None = None,
    repo_name: str | None = None,
) -> list[SearchResult]:
    """Find code similar to a given snippet via vector search."""
    query_vector = embedder.embed_query(snippet)
    filter_expr = _build_filter(language, chunk_type=None, repo_name=repo_name)
    return store.vector_search(TABLE_NAME, query_vector, top_k=top_k, filter_expr=filter_expr)
