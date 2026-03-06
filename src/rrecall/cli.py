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


if __name__ == "__main__":
    main()
