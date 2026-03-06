# RoboRecall — Architecture & Design Document

**Project Codename:** `rrecall` (RoboRecall)
**Target Platform:** Windows 11 + WSL2, NVIDIA RTX 2000 Ada (8GB VRAM)
**Languages:** Python (primary), Shell scripts (hooks)

---

## Executive Summary

rrecall is a three-part toolset that gives Claude Code persistent, searchable memory across sessions by capturing conversations into an Obsidian vault and providing fast semantic search over both notes and code repositories. It consists of:

1. **Hooks** — `PreCompact` and `SessionEnd` hooks that convert JSONL transcripts to Obsidian-compatible Markdown and trigger re-indexing
2. **Notes Search** — A CLI + MCP server for full-text and vector search across the Obsidian vault (conversations, notes, docs)
3. **Code Search** — A CLI + MCP server for AST-aware, language-intelligent vector search across one or many code repositories

All embedding can run fully local (ONNX + GPU) or via OpenAI's API with cost tracking.

---

## 1. Project Structure

```
rrecall/
├── pyproject.toml                  # Single Python package, uv-managed
├── README.md
├── rrecall/
│   ├── __init__.py
│   ├── config.py                   # Central config (TOML-based)
│   ├── embedding/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract EmbeddingProvider
│   │   ├── local_onnx.py           # FastEmbed / ONNX Runtime + CUDA
│   │   ├── openai_provider.py      # OpenAI text-embedding-3-small/large
│   │   ├── cost_tracker.py         # Token counting + cost ledger
│   │   └── server.py               # Optional long-running embedding server (HTTP)
│   ├── vectordb/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract VectorStore
│   │   ├── lancedb_store.py        # LanceDB (embedded, no server)
│   │   └── migrations.py           # Schema versioning
│   ├── hooks/
│   │   ├── __init__.py
│   │   ├── session_end.py          # SessionEnd hook script
│   │   ├── pre_compact.py          # PreCompact hook script
│   │   ├── transcript_parser.py    # JSONL → Markdown converter
│   │   ├── session_registry.py     # Tracks session state, prevents dupes
│   │   └── summarizer.py           # Optional: claude -p summary
│   ├── notes/
│   │   ├── __init__.py
│   │   ├── indexer.py              # Vault file walker + chunker
│   │   ├── searcher.py             # Hybrid search (FTS + vector)
│   │   └── cli.py                  # CLI entry point
│   ├── code/
│   │   ├── __init__.py
│   │   ├── indexer.py              # Repo walker + AST chunker
│   │   ├── chunkers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # Abstract CodeChunker
│   │   │   ├── treesitter.py       # Tree-sitter AST chunking (cAST-style)
│   │   │   └── languages.py        # Language-specific configs
│   │   ├── searcher.py             # Hybrid search (FTS + vector)
│   │   └── cli.py                  # CLI entry point
│   ├── mcp_server.py               # Unified MCP server (notes + code + shared embedding)
│   └── utils/
│       ├── __init__.py
│       ├── file_watcher.py         # inotify/ReadDirectoryChanges watcher
│       ├── hashing.py              # Content hashing for change detection
│       └── logging.py              # Structured logging
├── scripts/
│   ├── install-hooks.sh            # Installs hooks into .claude/settings.json
│   ├── install-hooks.ps1           # PowerShell variant
│   └── start-embedding-server.sh   # Launches persistent embedding server
├── tests/
│   └── ...
└── config/
    └── rrecall.example.toml      # Example configuration
```

---

## 2. Hooks System — Detailed Design

### 2.1 Hook Lifecycle & Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                   Claude Code Session                    │
│                                                         │
│  ┌──────────┐     ┌──────────────┐     ┌─────────────┐ │
│  │ Working  │────>│ PreCompact   │────>│ Compacted   │ │
│  │ Session  │     │ Hook fires   │     │ Session     │ │
│  └──────────┘     └──────┬───────┘     └──────┬──────┘ │
│                          │                     │        │
│                   ┌──────▼───────┐      ┌──────▼──────┐ │
│                   │ Save full    │      │ SessionEnd  │ │
│                   │ transcript   │      │ Hook fires  │ │
│                   │ snapshot     │      │             │ │
│                   └──────────────┘      └──────┬──────┘ │
│                                                │        │
└────────────────────────────────────────────────┼────────┘
                                                 │
                              ┌──────────────────▼──────────────────┐
                              │          Hook Script                 │
                              │  1. Read transcript JSONL            │
                              │  2. Merge with any pre-compact snap  │
                              │  3. Convert to Markdown              │
                              │  4. Write/append to Obsidian vault   │
                              │  5. Queue async re-index             │
                              └─────────────────────────────────────┘
```

### 2.2 Session Tracking & Deduplication

**Session Registry** (`~/.rrecall/sessions.json`):

```json
{
  "abc123": {
    "session_id": "abc123",
    "cwd": "/home/user/project",
    "started_at": "2026-03-05T10:00:00Z",
    "pre_compact_snapshots": [
      "~/.rrecall/snapshots/abc123_1709640000.jsonl"
    ],
    "last_transcript_hash": "sha256:...",
    "markdown_path": "vault/Claude Sessions/2026-03-05_abc123_project-name.md",
    "status": "active"
  }
}
```

**Key behaviors:**

- **PreCompact hook** copies the full transcript JSONL to a timestamped snapshot file *before* compaction destroys it. This runs synchronously but is just a file copy — fast and non-blocking.
- **SessionEnd hook** reads the current transcript, merges it with any pre-compact snapshots for that session_id, deduplicates messages by their JSONL line hashes, and produces the final Markdown.
- **Resume handling**: When `SessionStart` fires with `source: "resume"`, the registry marks that session as continued. The SessionEnd hook appends new content rather than overwriting.
- **Idempotency**: The transcript hash is stored; if SessionEnd fires twice with the same content, no duplicate write occurs.

### 2.3 Preventing Infinite Loops

Hooks must never trigger Claude Code to do more work:

- All hook scripts exit with code `0` (success, no blocking)
- No stdout is produced (stdout on SessionEnd/PreCompact is shown in transcript view but not to Claude)
- The re-indexing is queued to a background process via a Unix socket/named pipe — the hook script itself returns immediately
- A lockfile (`~/.rrecall/hook.lock`) with PID prevents concurrent hook executions from racing

### 2.4 Preventing Delays

- **PreCompact**: Copy transcript file only (~1-50ms). No parsing, no embedding.
- **SessionEnd**: Fork a background process for Markdown conversion + indexing. The hook script itself exits in <100ms.
- Pattern: `nohup python -m rrecall.hooks.finalize --session-id $SESSION_ID &>/dev/null &`

### 2.5 JSONL → Markdown Conversion

The transcript JSONL contains lines with structures like:

```json
{"type": "summary", "summary": "...", "leafUuid": "..."}
{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "..."}]}}
{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "..."}, {"type": "tool_use", ...}]}}
```

The converter produces Obsidian-compatible Markdown:

```markdown
---
session_id: abc123
project: my-project
cwd: /home/user/my-project
started: 2026-03-05T10:00:00Z
ended: 2026-03-05T11:30:00Z
compactions: 2
tags: [claude-session, my-project]
summary: "Refactored authentication module to use JWT tokens..."
---

# Session: Refactored Authentication Module
**Date:** 2026-03-05 | **Duration:** 1h 30m | **Project:** my-project

## Summary
Refactored authentication module to use JWT tokens...

---

## Conversation

### User (10:00:12)
Can you help me refactor the auth module to use JWT?

### Assistant (10:00:45)
I'll help you refactor the authentication module...

> [!tool]- Bash: `cat src/auth.py`
> (tool output collapsed)

### User (10:15:22)
Looks good, but can we add refresh token support?

...

---

## Pre-Compaction Snapshot 1 (10:45:00)
*(Content that was compacted, preserved for reference)*

### User (10:20:00)
...
```

### 2.6 Optional Features

**Conversation Filtering (worth-tracking decision):**

```toml
[hooks.filtering]
enabled = true
# Skip sessions shorter than N messages
min_messages = 3
# Skip sessions shorter than N seconds
min_duration_seconds = 30
# Use claude -p to decide (costs tokens but smart)
use_llm_filter = false
llm_filter_prompt = "Given this conversation summary, is this worth archiving? Respond YES or NO."
```

When `use_llm_filter = true`, the SessionEnd background process runs:
```bash
echo "$SUMMARY" | claude -p "Is this conversation worth archiving for future reference? It should have meaningful technical content, decisions, or problem-solving. Respond with only YES or NO." --max-tokens 3
```

**Summary Generation:**

```toml
[hooks.summary]
enabled = true
# "transcript" = use the summary from the JSONL first line
# "claude" = generate via claude -p
# "both" = use transcript summary, enhance with claude -p
strategy = "transcript"
```

---

## 3. Notes Search — Detailed Design

### 3.1 Indexing Pipeline

```
Obsidian Vault
     │
     ▼
┌─────────────┐    ┌──────────────┐    ┌────────────────┐
│ File Walker  │───>│ Chunker      │───>│ Embedding      │
│ (.md files)  │    │ (by heading, │    │ Provider       │
│ + hash check │    │  paragraph,  │    │ (local/OpenAI) │
│              │    │  frontmatter)│    │                │
└─────────────┘    └──────────────┘    └───────┬────────┘
                                               │
                                        ┌──────▼──────┐
                                        │  LanceDB    │
                                        │  (vectors + │
                                        │   FTS index) │
                                        └─────────────┘
```

**Chunking Strategy for Notes:**

- Parse Markdown into AST (using `markdown-it` or `mistune`)
- Chunk by heading sections (H1, H2, H3 boundaries)
- Frontmatter becomes metadata on every chunk from that file
- For conversation files: each user/assistant exchange pair is a chunk
- Overlap: include the heading hierarchy as a prefix to each chunk for context
- Max chunk size: ~512 tokens (configurable)

**Search Spaces:**

| Space | Description | Filter |
|-------|-------------|--------|
| `vault` | Everything in the Obsidian vault | No filter |
| `conversations` | Only Claude session transcripts | `tags contains "claude-session"` |
| `notes` | Everything except conversations | `tags not contains "claude-session"` |
| `project:NAME` | Conversations + notes tagged with project | `project == NAME` |

### 3.2 Incremental Indexing

- Maintain a `file_index.json` mapping filepath → `{hash, last_indexed, chunk_ids[]}`
- On re-index: walk vault, compute content hashes, skip unchanged files
- Changed files: delete old chunks from LanceDB, re-chunk, re-embed, insert
- Deleted files: remove chunks from LanceDB
- Typical re-index of 1 changed file: <2 seconds

### 3.3 Search Interface

**CLI:**
```bash
# Vector search across whole vault
rrecall notes search "how did we implement JWT refresh tokens" --space vault --top-k 10

# Full-text search in conversations only
rrecall notes search "JWT" --space conversations --mode text --top-k 20

# Hybrid search (vector + FTS, RRF fusion)
rrecall notes search "authentication refactor" --space project:my-app --mode hybrid
```

**MCP Server Tools:**

```json
{
  "tools": [
    {
      "name": "search_notes",
      "description": "Search Obsidian vault notes and Claude Code conversation history using semantic or text search",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "space": {"type": "string", "enum": ["vault", "conversations", "notes"], "default": "vault"},
          "mode": {"type": "string", "enum": ["vector", "text", "hybrid"], "default": "hybrid"},
          "top_k": {"type": "integer", "default": 5},
          "project": {"type": "string", "description": "Filter to a specific project"}
        },
        "required": ["query"]
      }
    },
    {
      "name": "list_recent_sessions",
      "description": "List recent Claude Code sessions with summaries",
      "inputSchema": {
        "type": "object",
        "properties": {
          "limit": {"type": "integer", "default": 10},
          "project": {"type": "string"}
        }
      }
    },
    {
      "name": "get_session",
      "description": "Retrieve the full content of a specific Claude Code session",
      "inputSchema": {
        "type": "object",
        "properties": {
          "session_id": {"type": "string"}
        },
        "required": ["session_id"]
      }
    }
  ]
}
```

---

## 4. Code Search — Detailed Design

### 4.1 AST-Aware Code Chunking

Rather than naive line-splitting, rrecall uses Tree-sitter to parse code into ASTs and extract semantically meaningful chunks.

**Chunking Algorithm (cAST-inspired):**

1. Parse file with Tree-sitter into AST
2. Walk top-level nodes: classes, functions, interfaces, enums, imports
3. For each node:
   - If it fits within `max_chunk_size` (default 1500 chars): emit as a single chunk
   - If too large: recursively split at child boundaries (methods within a class, statements within a function)
   - Merge adjacent small siblings (imports, type aliases) up to `min_chunk_size`
4. Prepend context header to each chunk: file path, parent class/namespace, function signature

**Language-Specific Configurations:**

| Language | Tree-sitter Grammar | Top-Level Nodes | Special Handling |
|----------|-------------------|-----------------|------------------|
| C# | `tree-sitter-c-sharp` | namespace, class, interface, enum, record, method | Preserve `using` directives as context; handle partial classes by including class name in chunk metadata |
| Python | `tree-sitter-python` | class, function, decorated_definition | Include decorators with their function; docstrings as separate searchable metadata |
| TypeScript | `tree-sitter-typescript` | class, function, interface, type_alias, enum | Handle `.tsx` with JSX nodes; preserve type annotations |
| HTML | `tree-sitter-html` | element (with id/class attrs) | Chunk by component-level elements; extract `<script>` and `<style>` for sub-parsing |
| CSS | `tree-sitter-css` | rule_set, media_query, keyframes | Group related selectors; preserve media query context |

**Chunk Metadata Schema:**

```python
@dataclass
class CodeChunk:
    content: str              # The actual code
    file_path: str            # Relative path within repo
    repo_name: str            # Repository identifier
    language: str             # Detected language
    chunk_type: str           # "function", "class", "method", "module_level", etc.
    symbol_name: str | None   # e.g., "UserService.authenticate"
    parent_symbol: str | None # e.g., "UserService"
    start_line: int
    end_line: int
    context_header: str       # "// File: src/auth/service.ts\n// Class: UserService"
    signature: str | None     # e.g., "async authenticate(token: string): Promise<User>"
    content_hash: str         # For change detection
```

### 4.2 Search Spaces

```toml
[code.repos]
# Define repo groups
[code.repos.current]
# Auto-detected from cwd — no config needed

[code.repos.all]
paths = [
  "~/projects",
  "~/work",
]
scan_depth = 2  # How deep to look for .git directories

[code.repos.groups.backend]
paths = [
  "~/work/api-service",
  "~/work/auth-service",
  "~/work/shared-lib",
]

[code.repos.groups.frontend]
paths = [
  "~/work/web-app",
  "~/work/component-library",
]
```

**Search space resolution:**

| CLI Flag | Behavior |
|----------|----------|
| `--space current` | Index/search only the repo at `cwd` (or `--repo path`) |
| `--space all` | All configured repo paths |
| `--space group:backend` | Only repos in the "backend" group |
| `--space repo:/path/to/repo` | A specific repo by path |

### 4.3 Indexing Strategy

**Initial Index:**
- Walk repo respecting `.gitignore` (using `pathspec` library)
- Parse each supported file with Tree-sitter
- Chunk → embed → store in LanceDB
- Store file hashes for incremental updates
- For a 50k-line repo: ~30-60 seconds with local GPU, ~10-20 seconds with OpenAI

**Incremental Re-index:**
- Use `git diff --name-only HEAD~1` or content hashing to find changed files
- Re-chunk and re-embed only changed files
- Triggered by hooks or manually via CLI
- Typical incremental: <5 seconds

**Background Index Daemon (optional):**
```bash
# Start a file watcher that auto-reindexes on save
rrecall code watch --space current
# Uses inotify (Linux/WSL) or ReadDirectoryChangesW (Windows)
```

### 4.4 Search Interface

**CLI:**
```bash
# Semantic search in current repo
rrecall code search "error handling for database connections" --space current

# Text search across a repo group
rrecall code search "ConnectionPool" --space group:backend --mode text

# Find similar code to a specific function
rrecall code search --similar-to src/auth/service.ts:42-67 --space all
```

**MCP Server Tools:**

```json
{
  "tools": [
    {
      "name": "search_code",
      "description": "Semantic and text search across code repositories",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "space": {"type": "string", "default": "current"},
          "mode": {"type": "string", "enum": ["vector", "text", "hybrid"], "default": "hybrid"},
          "top_k": {"type": "integer", "default": 5},
          "language": {"type": "string", "description": "Filter by language"},
          "chunk_type": {"type": "string", "description": "Filter: function, class, method, etc."},
          "file_pattern": {"type": "string", "description": "Glob pattern for file paths"}
        },
        "required": ["query"]
      }
    },
    {
      "name": "find_similar_code",
      "description": "Find code similar to a given snippet or file range",
      "inputSchema": {
        "type": "object",
        "properties": {
          "code_snippet": {"type": "string"},
          "file_path": {"type": "string"},
          "line_range": {"type": "string", "description": "e.g., '42-67'"},
          "space": {"type": "string", "default": "current"}
        }
      }
    },
    {
      "name": "get_code_context",
      "description": "Get the full file context around a search result",
      "inputSchema": {
        "type": "object",
        "properties": {
          "file_path": {"type": "string"},
          "start_line": {"type": "integer"},
          "end_line": {"type": "integer"},
          "context_lines": {"type": "integer", "default": 20}
        },
        "required": ["file_path"]
      }
    }
  ]
}
```

---

## 5. Embedding System — Detailed Design

### 5.1 Provider Architecture

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of vectors."""
        ...

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Embed a single query (may use different prefix/instruction)."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
```

### 5.2 Local ONNX Provider

**Recommended Model:** `BAAI/bge-small-en-v1.5` (33M params, 384 dimensions, ONNX-quantized)

- Why: excellent accuracy-to-speed ratio, well-supported ONNX format, small enough to load in <1 second, fits easily in 8GB VRAM alongside other work
- Alternative for higher accuracy: `BAAI/bge-base-en-v1.5` (110M params, 768 dims)
- Code-specific alternative: `Salesforce/codet5p-110m-embedding` (110M params, 256 dims, trained on code)

**Implementation via FastEmbed:**

```python
from fastembed import TextEmbedding

class LocalOnnxProvider(EmbeddingProvider):
    def __init__(self, model_name="BAAI/bge-small-en-v1.5", use_gpu=True):
        providers = ["CUDAExecutionProvider"] if use_gpu else ["CPUExecutionProvider"]
        self.model = TextEmbedding(model_name=model_name, providers=providers)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [e.tolist() for e in self.model.embed(texts)]

    def embed_query(self, query: str) -> list[float]:
        # BGE models benefit from "query: " prefix for retrieval
        return list(self.model.query_embed(query))[0].tolist()
```

**Embedding Server Mode (optional, for avoiding model reload latency):**

A lightweight HTTP server that keeps the model loaded in memory:

```bash
rrecall embedding-server start --port 9876 --model BAAI/bge-small-en-v1.5 --gpu
```

Exposes a simple endpoint:
```
POST /embed  {"texts": ["..."], "mode": "document"|"query"}
→ {"vectors": [[...], ...], "model": "...", "dimension": 384}
```

The CLI and MCP servers connect to this instead of loading the model themselves. Falls back to direct loading if the server isn't running.

### 5.3 OpenAI Provider

```python
class OpenAIProvider(EmbeddingProvider):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.cost_tracker = CostTracker()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(input=texts, model=self.model)
        tokens_used = response.usage.total_tokens
        self.cost_tracker.record(self.model, tokens_used, len(texts))
        return [item.embedding for item in response.data]
```

### 5.4 Cost Tracking

```python
# ~/.rrecall/cost_ledger.jsonl
{"timestamp": "2026-03-05T10:00:00Z", "model": "text-embedding-3-small", "tokens": 15234, "requests": 12, "estimated_cost_usd": 0.000304}
{"timestamp": "2026-03-05T11:00:00Z", "model": "text-embedding-3-small", "tokens": 8901, "requests": 7, "estimated_cost_usd": 0.000178}
```

**CLI cost report:**
```bash
rrecall costs show --period month
# Output:
# March 2026 OpenAI Embedding Costs
# ──────────────────────────────────
# Model                    Tokens      Requests    Cost (USD)
# text-embedding-3-small   1,234,567   892         $0.025
# text-embedding-3-large   0           0           $0.000
# ──────────────────────────────────
# Total:                                           $0.025
```

Pricing table (kept in config, user-updatable):
```toml
[embedding.openai.pricing]
"text-embedding-3-small" = 0.00002  # per 1k tokens
"text-embedding-3-large" = 0.00013  # per 1k tokens
```

---

## 6. Vector Storage — LanceDB

**Why LanceDB:**
- Embedded (no server process), single-file database
- Native vector search with IVF-PQ indexing
- Full-text search built in (Tantivy-based)
- Python-native, works on Windows and WSL
- Handles millions of vectors easily
- Supports filtering during search (metadata filters)

**Schema:**

```python
# Notes table
notes_schema = pa.schema([
    pa.field("id", pa.string()),           # chunk_id
    pa.field("file_path", pa.string()),
    pa.field("file_name", pa.string()),
    pa.field("heading_path", pa.string()), # "H1 > H2 > H3"
    pa.field("content", pa.string()),
    pa.field("chunk_index", pa.int32()),
    pa.field("source_type", pa.string()),  # "conversation", "note", "doc"
    pa.field("project", pa.string()),
    pa.field("session_id", pa.string()),   # null for non-conversation files
    pa.field("timestamp", pa.timestamp("us")),
    pa.field("tags", pa.list_(pa.string())),
    pa.field("content_hash", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), list_size=384)),
])

# Code table
code_schema = pa.schema([
    pa.field("id", pa.string()),
    pa.field("file_path", pa.string()),
    pa.field("repo_name", pa.string()),
    pa.field("language", pa.string()),
    pa.field("chunk_type", pa.string()),
    pa.field("symbol_name", pa.string()),
    pa.field("parent_symbol", pa.string()),
    pa.field("signature", pa.string()),
    pa.field("content", pa.string()),
    pa.field("context_header", pa.string()),
    pa.field("start_line", pa.int32()),
    pa.field("end_line", pa.int32()),
    pa.field("content_hash", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), list_size=384)),
])
```

**Database Location:**
```
~/.rrecall/
├── db/
│   ├── notes.lance/          # LanceDB notes table
│   └── code.lance/           # LanceDB code table
├── sessions.json             # Session registry
├── cost_ledger.jsonl         # OpenAI cost tracking
├── snapshots/                # Pre-compact transcript backups
│   └── abc123_1709640000.jsonl
└── config.toml               # User configuration
```

---

## 7. Configuration

```toml
# ~/.rrecall/config.toml

[general]
obsidian_vault = "~/Obsidian/MyVault"
session_subfolder = "Claude Sessions"    # Subfolder within vault
log_level = "info"

[embedding]
# "local" or "openai"
provider = "local"

[embedding.local]
model = "BAAI/bge-small-en-v1.5"
use_gpu = true
# If true, connect to a running embedding server instead of loading model in-process
use_server = false
server_url = "http://localhost:9876"

[embedding.openai]
# API key can also be set via RRECALL_OPENAI_API_KEY env var
api_key = ""
model = "text-embedding-3-small"

[embedding.openai.pricing]
"text-embedding-3-small" = 0.00002
"text-embedding-3-large" = 0.00013

[hooks]
enabled = true

[hooks.filtering]
enabled = true
min_messages = 3
min_duration_seconds = 30
use_llm_filter = false

[hooks.summary]
enabled = true
strategy = "transcript"  # "transcript", "claude", "both"

[notes]
# File patterns to index (beyond .md)
include_patterns = ["*.md"]
exclude_patterns = ["*.excalidraw.md", ".obsidian/*", ".trash/*"]
chunk_max_tokens = 512
chunk_overlap_tokens = 50

[code]
chunk_max_chars = 1500
chunk_min_chars = 100
chunk_overlap_lines = 3

[code.repos.all]
paths = ["~/projects", "~/work"]
scan_depth = 2

# Example repo group
# [code.repos.groups.backend]
# paths = ["~/work/api", "~/work/auth"]
```

---

## 8. MCP Server Configuration

Both MCP servers are registered in Claude Code's settings:

```json
{
  "mcpServers": {
    "rrecall": {
      "command": "python",
      "args": ["-m", "rrecall.mcp_server"],
      "env": {
        "RRECALL_CONFIG": "~/.rrecall/config.toml"
      }
    }
  }
}
```

The unified server loads the embedding model once on startup and exposes all tools (`search_notes`, `list_recent_sessions`, `get_session`, `search_code`, `find_similar_code`, `get_code_context`) through a single process.

---

## 9. Open Questions & Decisions Needed

### Architecture Decisions

1. **Single vs. dual embedding models for code?**
   - Option A: Use one general model (bge-small) for both notes and code — simpler, single model load
   - Option B: Use a code-specific model (codet5p-110m-embedding) for code and bge-small for notes — potentially better code retrieval, but two models to manage
   - **Recommendation:** Start with Option A. Code-trained models show marginal improvement over general models for retrieval tasks. Switch later if quality is insufficient.

2. **LanceDB vs. Qdrant (embedded mode) vs. SQLite + faiss?**
   - LanceDB: simplest setup, good enough performance, built-in FTS
   - Qdrant: more mature vector search, but requires a server process even in embedded mode
   - SQLite + faiss: most control, but more code to maintain
   - **Recommendation:** LanceDB for v1. Migrate if needed.

3. **Python vs. Rust/Go for the CLI?**
   - Python: faster to build, easier embedding model integration, uv makes dependency management clean
   - Rust: faster startup, smaller binary, but harder ONNX integration
   - **Recommendation:** Python with uv for v1. The embedding server amortizes startup cost.

4. **Separate MCP servers vs. unified?**
   - Separate: clear separation of concerns, can restart independently
   - Unified: single process, shared embedding model in memory
   - **Decision: Unified.** The embedding model is the expensive shared resource. One MCP server exposes both `search_notes` and `search_code` tool families.

### Feature Questions

5. **Should the embedding server be required or optional?**
   - Making it optional (with in-process fallback) is more flexible but means the first search in a session has a cold-start delay of ~2-5 seconds for model loading.
   - Making it required means better UX but another process to manage.
   - **Recommendation:** Optional with strong encouragement. Detect if running and use it; fall back to in-process with a "tip: run rrecall serve for faster searches" message.

6. **How to handle Obsidian vault syncing conflicts?**
   - If the vault is synced (Obsidian Sync, Git, etc.), concurrent writes could conflict.
   - **Recommendation:** Write session files atomically (write to temp, rename). Use session_id in filename to avoid conflicts. Include a `.gitignore` pattern suggestion for snapshot files.

7. **Should code indexing happen on every SessionEnd, or only on explicit trigger?**
   - On every SessionEnd: always up-to-date but potentially slow
   - On explicit trigger: user controls when, but might forget
   - **Recommendation:** Hybrid — SessionEnd queues a "notes re-index" (fast, just the new markdown file). Code re-index only on explicit `rrecall code reindex` or via file watcher daemon.

8. **Cross-platform path handling (Windows vs WSL)?**
   - Hooks in Claude Code may run in either context
   - Obsidian vault may be on Windows filesystem accessed from WSL via `/mnt/c/...`
   - **Recommendation:** Normalize all paths using `pathlib.Path` and store as POSIX paths in the database. Config supports both Windows and POSIX paths. The installer detects the environment.

### Additional Features to Consider

9. **Graph relationships between sessions**: Track which sessions reference files modified in other sessions, enabling "related sessions" queries.

10. **Embedding cache**: Cache embeddings by content hash so re-indexing unchanged content across repos doesn't re-embed.

11. **Export/backup**: CLI command to export the full database as a portable archive.

12. **Session diff view**: Show what files were created/modified/deleted in a session (from tool_use events in the transcript).

13. **Conversation threading**: If a session was resumed multiple times, show the conversation thread with clear markers for each resumption.

14. **Tag suggestions**: Use the session content to auto-suggest Obsidian tags beyond just the project name.

15. **Multi-model search**: Query both notes and code simultaneously with a single search, ranking results together.

---

## 10. Implementation Roadmap

### Phase 1: Core Hooks + Basic Notes Search (1-2 weeks)
- [ ] JSONL transcript parser
- [ ] PreCompact + SessionEnd hooks with session registry
- [ ] Markdown converter with Obsidian frontmatter
- [ ] Basic notes indexer (FTS only, no embeddings)
- [ ] CLI: `rrecall notes search` with text mode
- [ ] Hook installer script

### Phase 2: Embedding + Vector Search (1-2 weeks)
- [ ] Embedding provider abstraction
- [ ] Local ONNX provider (FastEmbed + CUDA)
- [ ] OpenAI provider + cost tracking
- [ ] LanceDB integration
- [ ] Hybrid search (FTS + vector, RRF fusion)
- [ ] Embedding server (optional daemon)

### Phase 3: Code Search (1-2 weeks)
- [ ] Tree-sitter AST chunking for C#, Python, TypeScript, HTML, CSS
- [ ] Code indexer with incremental updates
- [ ] Code search CLI
- [ ] Repo group configuration

### Phase 4: MCP Servers + Polish (1 week)
- [ ] Notes MCP server
- [ ] Code MCP server
- [ ] SessionStart hook for injecting relevant context
- [ ] Configuration validation and error messages
- [ ] Documentation

### Phase 5: Optional Enhancements (ongoing)
- [ ] Claude -p conversation filtering
- [ ] Claude -p summary generation
- [ ] File watcher daemon for auto-reindex
- [ ] Cross-platform installer (Windows + WSL detection)
- [ ] Embedding cache by content hash
- [ ] Multi-model search across notes + code

---

## 11. Dependencies

```toml
[project]
name = "rrecall"
requires-python = ">=3.11"

[project.dependencies]
# Core
click = ">=8.0"          # CLI framework
tomli = ">=2.0"          # TOML config parsing
pydantic = ">=2.0"       # Config/data validation

# Embedding
fastembed-gpu = ">=0.4"  # ONNX embedding with CUDA
openai = ">=1.0"         # OpenAI API client
tiktoken = ">=0.7"       # Token counting for cost tracking

# Vector DB
lancedb = ">=0.15"       # Embedded vector database
pyarrow = ">=15.0"       # Arrow tables for LanceDB

# Code parsing
tree-sitter = ">=0.23"   # AST parsing
tree-sitter-python = "*"
tree-sitter-c-sharp = "*"
tree-sitter-typescript = "*"
tree-sitter-html = "*"
tree-sitter-css = "*"

# Markdown
mistune = ">=3.0"        # Markdown parsing

# MCP
mcp = ">=1.0"            # Model Context Protocol SDK

# Utilities
pathspec = ">=0.12"      # .gitignore pattern matching
watchdog = ">=4.0"       # File system watching (cross-platform)

[project.scripts]
rrecall = "rrecall.cli:main"
```

---

## 12. RTX 2000 Ada GPU Considerations

The RTX 2000 Ada Laptop GPU has 8GB VRAM and uses the Ada Lovelace architecture (CUDA compute capability 8.9).

**ONNX Runtime configuration:**
- Use `onnxruntime-gpu` with CUDA 12.x
- For Hugging Face TEI (Text Embeddings Inference), build with `candle-cuda` (supports Turing and above, which includes Ada)
- The `bge-small-en-v1.5` model uses ~200MB VRAM — leaves plenty of room for other work
- Even `bge-base-en-v1.5` at ~500MB VRAM is comfortable

**Batch sizing:** With 8GB VRAM and bge-small, you can embed batches of 256+ texts simultaneously. For initial indexing of large repos, this means high throughput (~5000+ embeddings/second).

**WSL2 GPU passthrough:** CUDA works in WSL2 natively on Windows 11 with the NVIDIA GPU driver installed on the Windows side. No separate driver needed in WSL. Verify with `nvidia-smi` from within WSL.
