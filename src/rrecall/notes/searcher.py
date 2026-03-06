"""Notes searcher — full-text search over indexed Obsidian vault notes."""

from __future__ import annotations

from rrecall.notes.indexer import TABLE_NAME
from rrecall.vectordb.lancedb_store import SearchResult, VectorStore


def search(
    store: VectorStore,
    query: str,
    *,
    top_k: int = 10,
    mode: str = "text",
    project: str | None = None,
    session_id: str | None = None,
    tags: str | None = None,
) -> list[SearchResult]:
    """Search indexed notes.

    Args:
        store: The VectorStore instance.
        query: Search query string.
        top_k: Maximum results to return.
        mode: Search mode — only "text" (FTS) supported for now.
        project: Filter to a specific project name.
        session_id: Filter to a specific session.
        tags: Filter by tag (comma-separated).

    Returns:
        List of SearchResult ordered by relevance.
    """
    if mode != "text":
        raise ValueError(f"Unsupported search mode: {mode!r} (only 'text' supported)")

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

    filter_expr = " AND ".join(filters) if filters else None

    return store.text_search(TABLE_NAME, query, top_k=top_k, filter_expr=filter_expr)
