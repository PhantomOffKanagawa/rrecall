---
description: "Search and index notes and code using rrecall — persistent memory for Claude Code. Use when the user wants to search past sessions, index their vault or code, check embedding costs, or query their knowledge base. ALSO use when the user's request implies continuing previous work, references something done before, asks to 'pick up where we left off', mentions a previous session, or when the task clearly requires context from prior conversations."
allowed-tools:
  - Bash
  - Read
---

# RRecall — Persistent Memory for Claude Code

RRecall indexes Obsidian notes (including Claude Code session transcripts) and code repositories into a local vector database for full-text and semantic search.

## Auto-Context Pickup

When the user's message suggests they are continuing previous work or need context from past sessions, **proactively search for relevant context before starting the task.** Trigger signals include:

- References to previous work ("we did X before", "last time", "continue with", "pick up where we left off")
- Mentioning something that was done in a past session ("the config we set up", "that bug fix")
- Asking about project history or decisions
- Starting a task on a codebase where prior sessions exist

### Context Retrieval Procedure

1. Construct a search query from the user's topic, task description, or project name.
2. Run parallel searches with JSON output:

```bash
rrecall notes search "QUERY" --mode hybrid --top-k 5 --json
rrecall code search "QUERY" --mode hybrid --top-k 5 --json
```

3. If the current directory maps to a project, add a project-scoped search:

```bash
rrecall notes search "QUERY" --mode hybrid --top-k 5 --project PROJECT_NAME --json
```

4. Review results. If a session note looks highly relevant, read the full markdown file from the `file` field for complete context.
5. Summarize actionable context — previous decisions, solutions, unfinished work, relevant code — then proceed with the task.

## Slash Command

The `/recall [query]` command is available for explicit context retrieval.

## CLI Reference

### Notes

**Index:**
```bash
rrecall notes index                    # Index all notes with embeddings
rrecall notes index --no-embed         # FTS only
rrecall notes index --file PATH        # Single file
rrecall notes index --force            # Re-index everything
```

**Search:**
```bash
rrecall notes search "QUERY" --mode hybrid --top-k 10 --json
rrecall notes search "QUERY" --project PROJECT --json
rrecall notes search "QUERY" --session-id ID --json
rrecall notes search "QUERY" --tags "tag1,tag2" --json
```

### Code

**Index:**
```bash
rrecall code index                     # Index all configured paths
rrecall code index --dir ~/projects/X  # Specific directory
rrecall code index --force             # Force re-index
```

**Search:**
```bash
rrecall code search "QUERY" --mode hybrid --top-k 10 --json
rrecall code search "QUERY" --language python --json
rrecall code search "QUERY" --chunk-type function --json
rrecall code search "QUERY" --repo REPO --json
```

### Backfill

```bash
rrecall hooks backfill --dry-run       # Preview what would be processed
rrecall hooks backfill                 # Process all unprocessed sessions
rrecall hooks backfill --force         # Re-process everything
```

### Costs

```bash
rrecall costs show                     # This month's embedding costs
rrecall costs show --period day        # Today's costs
```

## Guidelines

- Always use `--json` for structured output — parse the results programmatically.
- Use `--mode hybrid` for best search quality (keyword + semantic).
- Index before searching if the user hasn't indexed yet.
- Configuration: `~/.rrecall/config.toml`. Repo paths: `[code.repos.all]`.
- The embedding model loads lazily on first use.
