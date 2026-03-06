# Robo Recall (rrecall)

> [!warning] This is in large part "vibe-coded" and partially untested \
> All code has been given a glance but only ~50% has been heavily reviewed and features such as the OpenAI endpoint haven't been tested. \
> This is partially a proof of concept I intend to move forward into a more reliable product. \
> Automated testing and certain practices have been used to try and keep this as reliable and portable as possible but it needs more thorough manual testing. \
> Should you use this, please add any Github issues as such issues arise. I am also more than open to feedback so please leave it :) .

Persistent, searchable memory for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Captures conversations into an Obsidian vault and provides semantic search over notes and code.

## What it does

- **Session capture** — Claude Code hooks automatically convert transcripts to Markdown in your Obsidian vault after each turn and at session end
- **Notes search** — Full-text, vector, and hybrid search over your vault
- **Code search** — AST-aware code chunking (Python, TypeScript, C#, CSS, HTML) with semantic search via tree-sitter
- **MCP server** — Exposes search tools directly to Claude Code via the Model Context Protocol
- **Local-first** — Runs embeddings locally with FastEmbed (GPU/CPU), or optionally via OpenAI API with cost tracking

## Install

```bash
uv tool install rrecall
```

## Setup

1. Copy the example config:
```bash
mkdir -p ~/.rrecall
cp config/rrecall.example.toml ~/.rrecall/config.toml
# Edit ~/.rrecall/config.toml — set your vault path
```

2. Install Claude Code hooks:
```bash
bash scripts/install-hooks.sh        # Linux/macOS
# pwsh scripts/install-hooks.ps1    # Windows
```

This registers two hooks:
- **Stop** — updates the session Markdown after each assistant turn
- **SessionEnd** — final write + auto-indexes into the search database

3. Index your existing vault and code:
```bash
rrecall notes index
rrecall code index
```

## Usage

### CLI

```bash
# Search notes
rrecall notes search "authentication flow"
rrecall notes search "auth" --mode hybrid --top-k 5
rrecall notes search "auth" --json   # LLM-friendly output

# Search code
rrecall code search "error handling"
rrecall code search "database" --language python --json

# Backfill past sessions
rrecall hooks backfill --dry-run
rrecall hooks backfill

# Check embedding costs (OpenAI provider only)
rrecall costs show --period month
```

### MCP Server

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "rrecall": {
      "command": "rrecall-mcp"
    }
  }
}
```

This gives Claude Code access to `search_notes`, `search_code`, `find_similar_code`, `get_code_context`, `list_recent_sessions`, and `get_session` tools.

## Configuration

See [`config/rrecall.example.toml`](config/rrecall.example.toml) for all options. Key settings:

| Setting | Default | Description |
|---|---|---|
| `general.obsidian_vault` | `~/Obsidian/MyVault` | Path to your Obsidian vault |
| `embedding.provider` | `local` | `local` (FastEmbed) or `openai` |
| `hooks.auto_index` | `true` | Auto-index notes after session ends |
| `code.repos.all.paths` | `["~/code"]` | Directories to scan for code |

Environment variable overrides: `RRECALL_OBSIDIAN_VAULT`, `RRECALL_OPENAI_API_KEY`, `RRECALL_LOG_LEVEL`.

## Development

```bash
git clone https://github.com/PhantomOffKanagawa/rrecall.git
cd rrecall
uv sync --group dev
uv run pytest
```

> **Note:** The PowerShell install script (`install-hooks.ps1`) is tested with PowerShell Core (pwsh 7) on Linux. It targets Windows PowerShell 5.1 compatibility but this is not verified in CI.

## To-Dos
- [ ] Cover empty file case for `/scripts/install-hooks.*`
- [ ] Show success in response on hook
- [ ] Add options to create and link Project or JIRA Card pages for better Graph View Linking
- [ ] Add option for tool use responses
- [ ] Add better loading indicator
- [ ] Limit OOM errors but ensure speed
- [ ] Test OpenAI option

## License

MIT
