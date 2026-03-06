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
@click.option("--embed/--no-embed", default=True, help="Compute embeddings (default: on).")
def index(file_path: str | None, force: bool, embed: bool) -> None:
    """Index the Obsidian vault for full-text and vector search."""
    from pathlib import Path

    from rrecall.config import get_config
    from rrecall.notes.indexer import index_file, index_vault
    from rrecall.vectordb.lancedb_store import VectorStore

    store = VectorStore()
    config = get_config()
    embedder = None
    if embed:
        from rrecall.embedding.base import get_provider
        embedder = get_provider(config)

    if file_path:
        n = index_file(store, Path(file_path), config, embedder=embedder)
        click.echo(f"Indexed {n} chunks from {file_path}")
    else:
        files, chunks, removed = index_vault(store, config, force=force, embedder=embedder)
        click.echo(f"Indexed {files} files ({chunks} chunks), removed {removed} stale files.")


@notes.command()
@click.argument("query")
@click.option("--mode", default="text", type=click.Choice(["text", "vector", "hybrid"]), help="Search mode.")
@click.option("--top-k", default=10, type=int, help="Max results.")
@click.option("--project", default=None, help="Filter by project.")
@click.option("--session-id", default=None, help="Filter by session ID.")
@click.option("--tags", default=None, help="Filter by tags (comma-separated).")
@click.option("--json", "output_json", is_flag=True, help="Output results as JSON.")
def search(query: str, mode: str, top_k: int, project: str | None, session_id: str | None, tags: str | None, output_json: bool) -> None:
    """Search indexed notes."""
    from rrecall.notes.searcher import search as do_search
    from rrecall.vectordb.lancedb_store import VectorStore

    store = VectorStore()
    embedder = None
    if mode in ("vector", "hybrid"):
        from rrecall.config import get_config
        from rrecall.embedding.base import get_provider
        embedder = get_provider(get_config())

    results = do_search(store, query, top_k=top_k, mode=mode, project=project, session_id=session_id, tags=tags, embedder=embedder)

    if output_json:
        import json
        out = [
            {
                "file": r.source_file,
                "heading": r.heading,
                "score": r.score,
                "text": r.text,
                **{k: v for k, v in r.metadata.items() if k not in ("vector",)},
            }
            for r in results
        ]
        click.echo(json.dumps(out, indent=2))
        return

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


@code.command("index")
@click.option("--dir", "dir_path", type=click.Path(exists=True), default=None, help="Index a specific directory instead of configured paths.")
@click.option("--force", is_flag=True, help="Re-index all files even if unchanged.")
@click.option("--embed/--no-embed", default=True, help="Compute embeddings (default: on).")
def code_index(dir_path: str | None, force: bool, embed: bool) -> None:
    """Index code for search. By default indexes all configured paths."""
    from pathlib import Path

    from rrecall.config import get_config
    from rrecall.vectordb.lancedb_store import VectorStore

    store = VectorStore()
    config = get_config()
    embedder = None
    if embed:
        from rrecall.embedding.base import get_provider
        embedder = get_provider(config)

    if dir_path:
        from rrecall.code.indexer import index_repo
        path = Path(dir_path).resolve()
        files, chunks = index_repo(store, path, config=config, embedder=embedder, force=force)
        click.echo(f"Indexed {files} files ({chunks} chunks) from {path.name}")
    else:
        from rrecall.code.indexer import index_paths
        dirs, files, chunks = index_paths(store, config=config, embedder=embedder, force=force)
        click.echo(f"Scanned {dirs} directories, indexed {files} files ({chunks} chunks)")


@code.command("search")
@click.argument("query")
@click.option("--mode", default="text", type=click.Choice(["text", "vector", "hybrid"]), help="Search mode.")
@click.option("--top-k", default=10, type=int, help="Max results.")
@click.option("--language", default=None, help="Filter by language.")
@click.option("--chunk-type", default=None, help="Filter by chunk type (function, class, imports).")
@click.option("--repo", "repo_name", default=None, help="Filter by repo name.")
@click.option("--json", "output_json", is_flag=True, help="Output results as JSON.")
def code_search(query: str, mode: str, top_k: int, language: str | None, chunk_type: str | None, repo_name: str | None, output_json: bool) -> None:
    """Search indexed code."""
    from rrecall.code.searcher import search as do_search
    from rrecall.vectordb.lancedb_store import VectorStore

    store = VectorStore()
    embedder = None
    if mode in ("vector", "hybrid"):
        from rrecall.config import get_config
        from rrecall.embedding.base import get_provider
        embedder = get_provider(get_config())

    results = do_search(store, query, top_k=top_k, mode=mode, language=language,
                        chunk_type=chunk_type, repo_name=repo_name, embedder=embedder)

    if output_json:
        import json
        out = [
            {
                "file": r.source_file,
                "start_line": r.metadata.get("start_line"),
                "end_line": r.metadata.get("end_line"),
                "score": r.score,
                "language": r.metadata.get("language", ""),
                "chunk_type": r.metadata.get("chunk_type", ""),
                "symbol_name": r.metadata.get("symbol_name", ""),
                "signature": r.metadata.get("signature", ""),
                "text": r.text,
            }
            for r in results
        ]
        click.echo(json.dumps(out, indent=2))
        return

    if not results:
        click.echo("No results found.")
        return

    for i, r in enumerate(results, 1):
        click.echo(f"\n--- Result {i} (score: {r.score:.4f}) ---")
        meta = r.metadata
        loc = r.source_file
        if meta.get("start_line"):
            loc += f":{meta['start_line']}"
            if meta.get("end_line") and meta["end_line"] != meta["start_line"]:
                loc += f"-{meta['end_line']}"
        click.echo(f"File: {loc}")
        parts = []
        if meta.get("language"):
            parts.append(meta["language"])
        if meta.get("symbol_name"):
            parts.append(meta["symbol_name"])
        if meta.get("chunk_type"):
            parts.append(meta["chunk_type"])
        if parts:
            click.echo(f"  {' | '.join(parts)}")
        preview = r.text[:300].rstrip()
        if len(r.text) > 300:
            preview += "\n..."
        click.echo(preview)


@main.group()
def costs() -> None:
    """View token usage and cost estimates."""


@costs.command("show")
@click.option("--period", default="month", type=click.Choice(["day", "week", "month"]), help="Time period.")
def costs_show(period: str) -> None:
    """Show embedding cost summary."""
    from rrecall.embedding.cost_tracker import get_summary

    s = get_summary(period)
    if s.entries == 0:
        click.echo(f"No API usage in the last {period}.")
        return
    click.echo(f"Period: last {period} ({s.entries} entries)")
    click.echo(f"Tokens: {s.total_tokens:,}")
    click.echo(f"Requests: {s.total_requests:,}")
    click.echo(f"Est. cost: ${s.total_cost:.6f}")


@main.command()
def serve() -> None:
    """Start the MCP server (stdio transport)."""
    from rrecall.mcp_server import main as mcp_main
    mcp_main()


# ---------------------------------------------------------------------------
# Hooks — called by Claude Code, read JSON from stdin
# ---------------------------------------------------------------------------

@main.group()
def hooks() -> None:
    """Hook entry points called by Claude Code (reads JSON from stdin)."""


@hooks.command("session-end")
def hooks_session_end() -> None:
    """SessionEnd hook — triggers transcript conversion to Markdown and indexes."""
    from rrecall.hooks.session_end import run
    run()


@hooks.command("stop")
def hooks_stop() -> None:
    """Stop hook — updates Markdown after each turn (no indexing)."""
    from rrecall.hooks.session_end import run
    run(no_index=True)


@hooks.command("backfill")
@click.option("--dry-run", is_flag=True, help="Show what would be processed without doing it.")
@click.option("--force", is_flag=True, help="Re-process already completed sessions.")
@click.option("--min-messages", default=None, type=int, help="Override minimum message count filter.")
def hooks_backfill(dry_run: bool, force: bool, min_messages: int | None) -> None:
    """Retroactively run session-end processing on all previous conversations."""
    from rrecall.hooks.backfill import backfill

    label = "[dry-run] " if dry_run else ""
    click.echo(f"{label}Scanning for unprocessed Claude Code sessions...")

    processed, skipped, failed = backfill(
        dry_run=dry_run, force=force, min_messages=min_messages,
    )

    click.echo(f"\n{label}Done: {processed} processed, {skipped} skipped, {failed} failed.")


if __name__ == "__main__":
    main()
