"""LanceDB-backed vector/FTS store for rrecall."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

from rrecall.config import get_config_dir
from rrecall.utils.logging import get_logger

logger = get_logger("vectordb.lancedb_store")

EMBEDDING_DIM = 384  # Default for bge-small-en-v1.5

# Schema for the notes table
NOTES_SCHEMA = pa.schema([
    pa.field("id", pa.utf8(), nullable=False),
    pa.field("source_file", pa.utf8()),
    pa.field("heading", pa.utf8()),
    pa.field("text", pa.utf8()),
    pa.field("content_hash", pa.utf8()),
    pa.field("session_id", pa.utf8()),
    pa.field("project", pa.utf8()),
    pa.field("tags", pa.utf8()),  # comma-separated
    pa.field("chunk_index", pa.int32()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
])


def notes_schema(dim: int = EMBEDDING_DIM) -> pa.Schema:
    """Build the notes schema with a custom vector dimension."""
    if dim == EMBEDDING_DIM:
        return NOTES_SCHEMA
    fields = [f for f in NOTES_SCHEMA if f.name != "vector"]
    fields.append(pa.field("vector", pa.list_(pa.float32(), dim)))
    return pa.schema(fields)


@dataclass
class SearchResult:
    """A single search result from the store."""
    id: str
    text: str
    score: float
    source_file: str = ""
    heading: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore:
    """Wrapper around a local LanceDB database."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = get_config_dir() / "lancedb"
        db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(db_path))
        self._db_path = db_path

    def _table_exists(self, name: str) -> bool:
        """Check if a table exists in the database."""
        result = self._db.list_tables()
        # list_tables() may return a ListTablesResponse or a plain list
        tables = result.tables if hasattr(result, "tables") else result
        return name in tables

    def create_or_open_table(self, name: str, schema: pa.Schema) -> lancedb.table.Table:
        """Open an existing table or create it with the given schema.

        If the existing table's schema doesn't match (e.g. missing vector column),
        the table is dropped and recreated.
        """
        if self._table_exists(name):
            table = self._db.open_table(name)
            existing_names = {f.name for f in table.schema}
            required_names = {f.name for f in schema}
            if required_names - existing_names:
                logger.info("Schema mismatch for table %s, recreating (new columns: %s)",
                            name, required_names - existing_names)
                self._db.drop_table(name)
                return self._db.create_table(name, schema=schema)
            return table
        return self._db.create_table(name, schema=schema)

    def upsert_chunks(self, table_name: str, chunks: list[dict[str, Any]]) -> None:
        """Add or update chunks by id."""
        if not chunks:
            return
        table = self._db.open_table(table_name)
        table.merge_insert("id") \
            .when_matched_update_all() \
            .when_not_matched_insert_all() \
            .execute(chunks)

    def delete_chunks(self, table_name: str, ids: list[str]) -> None:
        """Remove chunks by id."""
        if not ids:
            return
        table = self._db.open_table(table_name)
        # LanceDB uses SQL-like filter expressions
        id_list = ", ".join(f"'{i}'" for i in ids)
        table.delete(f"id IN ({id_list})")

    def text_search(
        self,
        table_name: str,
        query: str,
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Full-text search via LanceDB's Tantivy FTS index."""
        table = self._db.open_table(table_name)
        search = table.search(query, query_type="fts").limit(top_k)
        if filter_expr:
            search = search.where(filter_expr)
        try:
            rows = search.to_list()
        except Exception as e:
            # FTS index may not exist yet
            logger.warning("FTS search failed (index may not exist): %s", e)
            return []

        results = []
        for row in rows:
            results.append(SearchResult(
                id=row.get("id", ""),
                text=row.get("text", ""),
                score=row.get("_score", 0.0),
                source_file=row.get("source_file", ""),
                heading=row.get("heading", ""),
                metadata={
                    k: v for k, v in row.items()
                    if k not in {"id", "text", "_score", "source_file", "heading"}
                },
            ))
        return results

    def vector_search(
        self,
        table_name: str,
        query_vector: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """ANN vector search via LanceDB."""
        table = self._db.open_table(table_name)
        search = table.search(query_vector, query_type="vector").limit(top_k)
        if filter_expr:
            search = search.where(filter_expr)
        rows = search.to_list()
        return [
            SearchResult(
                id=row.get("id", ""),
                text=row.get("text", ""),
                score=row.get("_distance", 0.0),
                source_file=row.get("source_file", ""),
                heading=row.get("heading", ""),
                metadata={k: v for k, v in row.items()
                          if k not in {"id", "text", "_distance", "source_file", "heading", "vector"}},
            )
            for row in rows
        ]

    def hybrid_search(
        self,
        table_name: str,
        query_text: str,
        query_vector: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
        rrf_k: int = 60,
    ) -> list[SearchResult]:
        """Hybrid FTS + vector search fused with Reciprocal Rank Fusion (RRF)."""
        fts_results = self.text_search(table_name, query_text, top_k=top_k, filter_expr=filter_expr)
        vec_results = self.vector_search(table_name, query_vector, top_k=top_k, filter_expr=filter_expr)

        # RRF: score(d) = sum(1 / (k + rank_i)) across result lists
        scores: dict[str, float] = {}
        result_map: dict[str, SearchResult] = {}

        for rank, r in enumerate(fts_results):
            scores[r.id] = scores.get(r.id, 0.0) + 1.0 / (rrf_k + rank + 1)
            result_map[r.id] = r

        for rank, r in enumerate(vec_results):
            scores[r.id] = scores.get(r.id, 0.0) + 1.0 / (rrf_k + rank + 1)
            if r.id not in result_map:
                result_map[r.id] = r

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [
            SearchResult(
                id=rid,
                text=result_map[rid].text,
                score=score,
                source_file=result_map[rid].source_file,
                heading=result_map[rid].heading,
                metadata=result_map[rid].metadata,
            )
            for rid, score in ranked
        ]

    def ensure_fts_index(self, table_name: str, column: str = "text") -> None:
        """Create or replace the FTS index on a table."""
        table = self._db.open_table(table_name)
        table.create_fts_index(column, replace=True)

    def count(self, table_name: str) -> int:
        """Return the number of rows in a table."""
        table = self._db.open_table(table_name)
        return table.count_rows()

    def drop_table(self, table_name: str) -> None:
        """Drop a table if it exists."""
        if self._table_exists(table_name):
            self._db.drop_table(table_name)
