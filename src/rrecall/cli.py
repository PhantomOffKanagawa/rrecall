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
