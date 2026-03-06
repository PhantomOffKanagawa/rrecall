"""RRecall CLI — persistent, searchable memory for Claude Code."""

from __future__ import annotations

import click


@click.group()
@click.version_option(package_name="rrecall")
def main() -> None:
    """RRecall — persistent, searchable memory for Claude Code."""


@main.group()
def notes() -> None:
    """Search and manage Obsidian session notes."""


@notes.command()
@click.option("--file", "file_path", type=click.Path(exists=True), help="Index a single file.")
@click.option("--force", is_flag=True, help="Re-index all files even if unchanged.")
def index(file_path: str | None, force: bool) -> None:
    """Index the Obsidian vault for full-text search."""
    from pathlib import Path

    from rrecall.config import get_config
    from rrecall.notes.indexer import index_file, index_vault
    from rrecall.vectordb.lancedb_store import VectorStore

    store = VectorStore()
    config = get_config()

    if file_path:
        n = index_file(store, Path(file_path), config)
        click.echo(f"Indexed {n} chunks from {file_path}")
    else:
        files, chunks, removed = index_vault(store, config, force=force)
        click.echo(f"Indexed {files} files ({chunks} chunks), removed {removed} stale files.")


@notes.command()
@click.argument("query")
@click.option("--mode", default="text", type=click.Choice(["text"]), help="Search mode.")
@click.option("--top-k", default=10, type=int, help="Max results.")
@click.option("--project", default=None, help="Filter by project.")
@click.option("--session-id", default=None, help="Filter by session ID.")
@click.option("--tags", default=None, help="Filter by tags (comma-separated).")
def search(query: str, mode: str, top_k: int, project: str | None, session_id: str | None, tags: str | None) -> None:
    """Search indexed notes."""
    from rrecall.notes.searcher import search as do_search
    from rrecall.vectordb.lancedb_store import VectorStore

    store = VectorStore()
    results = do_search(store, query, top_k=top_k, mode=mode, project=project, session_id=session_id, tags=tags)

    if not results:
        click.echo("No results found.")
        return

    for i, r in enumerate(results, 1):
        click.echo(f"\n--- Result {i} (score: {r.score:.4f}) ---")
        click.echo(f"File: {r.source_file}")
        if r.heading:
            click.echo(f"Section: {r.heading}")
        # Show first 200 chars of text
        preview = r.text[:200].replace("\n", " ")
        if len(r.text) > 200:
            preview += "..."
        click.echo(preview)


@main.group()
def code() -> None:
    """Search and index code for semantic retrieval."""


@main.group()
def costs() -> None:
    """View token usage and cost estimates."""


# ---------------------------------------------------------------------------
# Hooks — called by Claude Code, read JSON from stdin
# ---------------------------------------------------------------------------

@main.group()
def hooks() -> None:
    """Hook entry points called by Claude Code (reads JSON from stdin)."""


@hooks.command("pre-compact")
def hooks_pre_compact() -> None:
    """PreCompact hook — snapshots transcript before compaction."""
    from rrecall.hooks.pre_compact import run
    run()


@hooks.command("session-end")
def hooks_session_end() -> None:
    """SessionEnd hook — triggers transcript conversion to Markdown."""
    from rrecall.hooks.session_end import run
    run()


if __name__ == "__main__":
    main()
