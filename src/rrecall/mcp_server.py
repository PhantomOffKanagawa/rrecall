"""RRecall MCP Server — exposes notes and code search as tools for Claude Code."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from rrecall.utils.logging import get_logger

logger = get_logger("mcp_server")

mcp = FastMCP(
    "rrecall",
    instructions="Persistent, searchable memory for Claude Code — search notes and code.",
)

# ---------------------------------------------------------------------------
# Shared state — lazily initialized
# ---------------------------------------------------------------------------

_store = None
_embedder = None
_config = None


def _get_store():
    global _store
    if _store is None:
        from rrecall.vectordb.lancedb_store import VectorStore
        _store = VectorStore()
    return _store


def _get_config():
    global _config
    if _config is None:
        from rrecall.config import get_config
        _config = get_config()
    return _config


def _get_embedder():
    global _embedder
    if _embedder is None:
        from rrecall.embedding.base import get_provider
        _embedder = get_provider(_get_config())
    return _embedder


# ---------------------------------------------------------------------------
# Notes tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_notes(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    project: str | None = None,
    session_id: str | None = None,
    tags: str | None = None,
) -> str:
    """Search indexed Obsidian notes and session transcripts.

    Use this to find past conversations, decisions, debugging sessions, and notes.

    Args:
        query: Natural language search query.
        mode: Search mode — "text" (keyword), "vector" (semantic), or "hybrid" (both, recommended).
        top_k: Maximum number of results.
        project: Filter to a specific project name.
        session_id: Filter to a specific session ID.
        tags: Filter by tags (comma-separated).
    """
    from rrecall.notes.searcher import search

    embedder = _get_embedder() if mode in ("vector", "hybrid") else None
    results = search(
        _get_store(), query,
        top_k=top_k, mode=mode, project=project,
        session_id=session_id, tags=tags, embedder=embedder,
    )

    if not results:
        return "No results found."

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        lines.append(f"## Result {i} (score: {r.score:.4f})")
        lines.append(f"**File:** {r.source_file}")
        if r.heading:
            lines.append(f"**Section:** {r.heading}")
        lines.append("")
        lines.append(r.text[:500])
        if len(r.text) > 500:
            lines.append("...")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def list_recent_sessions(
    limit: int = 10,
    project: str | None = None,
) -> str:
    """List recent Claude Code sessions from the session registry.

    Args:
        limit: Maximum number of sessions to return.
        project: Filter to a specific project name.
    """
    from rrecall.hooks.session_registry import _read_registry

    registry = _read_registry()
    sessions = sorted(registry.values(), key=lambda s: s.get("started_at", ""), reverse=True)

    if project:
        # Filter by cwd containing the project name
        sessions = [s for s in sessions if project.lower() in s.get("cwd", "").lower()]

    sessions = sessions[:limit]

    if not sessions:
        return "No sessions found."

    lines: list[str] = []
    for s in sessions:
        sid = s.get("session_id", "unknown")
        status = s.get("status", "unknown")
        started = s.get("started_at", "unknown")
        cwd = s.get("cwd", "")
        md = s.get("markdown_path", "")
        lines.append(f"- **{sid}** ({status}) — {started}")
        if cwd:
            lines.append(f"  Directory: {cwd}")
        if md:
            lines.append(f"  File: {md}")
    return "\n".join(lines)


@mcp.tool()
def get_session(session_id: str) -> str:
    """Read the full markdown content of a specific session.

    Args:
        session_id: The session ID to retrieve.
    """
    from pathlib import Path

    from rrecall.hooks.session_registry import _read_registry

    registry = _read_registry()
    session = registry.get(session_id)
    if not session:
        return f"Session {session_id} not found."

    md_path = session.get("markdown_path", "")
    if not md_path or not Path(md_path).exists():
        return f"Markdown file not found for session {session_id}."

    content = Path(md_path).read_text(encoding="utf-8")
    # Truncate if very long
    if len(content) > 10000:
        return content[:10000] + "\n\n... (truncated, use search_notes for specific sections)"
    return content


# ---------------------------------------------------------------------------
# Code tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_code(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    language: str | None = None,
    chunk_type: str | None = None,
    repo_name: str | None = None,
) -> str:
    """Search indexed code repositories for functions, classes, and other code.

    Use this to find implementations, patterns, and code examples across indexed repos.

    Args:
        query: Natural language or code search query.
        mode: Search mode — "text" (keyword), "vector" (semantic), or "hybrid" (both, recommended).
        top_k: Maximum number of results.
        language: Filter by language (e.g. "python", "typescript", "csharp").
        chunk_type: Filter by type (e.g. "function", "class", "imports").
        repo_name: Filter by repository name.
    """
    from rrecall.code.searcher import search

    embedder = _get_embedder() if mode in ("vector", "hybrid") else None
    results = search(
        _get_store(), query,
        top_k=top_k, mode=mode, language=language,
        chunk_type=chunk_type, repo_name=repo_name, embedder=embedder,
    )

    if not results:
        return "No results found."

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        meta = r.metadata
        lang = meta.get("language", "")
        sym = meta.get("symbol_name", "")
        ctype = meta.get("chunk_type", "")
        sig = meta.get("signature", "")
        start = meta.get("start_line", "")
        end = meta.get("end_line", "")

        lines.append(f"## Result {i} (score: {r.score:.4f})")
        lines.append(f"**File:** {r.source_file}")
        info_parts = [p for p in [lang, ctype, sym] if p]
        if info_parts:
            lines.append(f"**{' | '.join(info_parts)}**")
        if sig:
            lines.append(f"Signature: `{sig}`")
        if start and end:
            lines.append(f"Lines: {start}-{end}")
        lines.append("")
        lines.append(f"```{lang}")
        lines.append(r.text[:1000])
        if len(r.text) > 1000:
            lines.append("// ... truncated")
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def find_similar_code(
    snippet: str,
    language: str | None = None,
    repo_name: str | None = None,
    top_k: int = 5,
) -> str:
    """Find code similar to a given snippet using semantic search.

    Args:
        snippet: The code snippet to find similar code for.
        language: Filter by language.
        repo_name: Filter by repository name.
        top_k: Maximum number of results.
    """
    from rrecall.code.searcher import find_similar

    results = find_similar(
        _get_store(), snippet, _get_embedder(),
        top_k=top_k, language=language, repo_name=repo_name,
    )

    if not results:
        return "No similar code found."

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        meta = r.metadata
        lang = meta.get("language", "")
        sym = meta.get("symbol_name", "")
        lines.append(f"## Similar {i} (distance: {r.score:.4f})")
        lines.append(f"**File:** {r.source_file}")
        if sym:
            lines.append(f"**Symbol:** {sym}")
        lines.append(f"```{lang}")
        lines.append(r.text[:1000])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_code_context(
    file_path: str,
    start_line: int = 1,
    end_line: int | None = None,
    context_lines: int = 10,
) -> str:
    """Read a section of a source file with surrounding context.

    Args:
        file_path: Path to the source file.
        start_line: Starting line number (1-based).
        end_line: Ending line number (defaults to start_line).
        context_lines: Number of context lines before and after.
    """
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    try:
        all_lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return f"Error reading file: {e}"

    if end_line is None:
        end_line = start_line

    ctx_start = max(0, start_line - 1 - context_lines)
    ctx_end = min(len(all_lines), end_line + context_lines)

    lines: list[str] = []
    lines.append(f"**{file_path}** (lines {ctx_start + 1}-{ctx_end})")
    lines.append("```")
    for i in range(ctx_start, ctx_end):
        marker = "→ " if start_line - 1 <= i < end_line else "  "
        lines.append(f"{marker}{i + 1:4d} | {all_lines[i]}")
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
