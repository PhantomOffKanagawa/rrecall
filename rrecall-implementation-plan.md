# RoboRecall — Step-by-Step Implementation Plan

Each step is a self-contained unit you can build and test before moving on. Steps within a phase can sometimes be parallelized, but the phases themselves are sequential — each builds on the last.

---

## Phase 0: Project Scaffold

### Step 0.1 — Initialize the project with uv

```bash
mkdir rrecall && cd rrecall
uv init --lib
```

Set up `pyproject.toml` with the project metadata, Python >=3.11, and the `rrecall` CLI entry point. Don't add all dependencies yet — add them as each step needs them.

Create the directory skeleton:

```
rrecall/
├── __init__.py
├── config.py
├── embedding/
├── vectordb/
├── hooks/
├── notes/
├── code/
│   └── chunkers/
├── mcp_server.py
└── utils/
```

Add empty `__init__.py` files everywhere. Create `config/rrecall.example.toml` with placeholder sections.

**Test:** `uv run python -c "import rrecall"` succeeds.

### Step 0.2 — Configuration system

Dependencies: `pydantic >= 2.0`, `tomli >= 2.0` (or `tomllib` on 3.11+)

Build `rrecall/config.py`:

- Pydantic model for the full config schema (all sections from the architecture doc)
- Load from `~/.rrecall/config.toml`, fall back to defaults
- Environment variable overrides for secrets (`RRECALL_OPENAI_API_KEY`)
- A `get_config()` singleton function
- Create `~/.rrecall/` directory on first run if it doesn't exist

**Test:** Write a unit test that loads the example config and validates it. Test that missing file uses defaults. Test env var override.

### Step 0.3 — Utilities: hashing + logging

Build `rrecall/utils/hashing.py`:
- `content_hash(text: str) -> str` — SHA-256 of content, returns `sha256:abcdef...`
- `file_hash(path: Path) -> str` — SHA-256 of file bytes

Build `rrecall/utils/logging.py`:
- Structured logger setup (JSON to file, human-readable to stderr)
- Log to `~/.rrecall/rrecall.log`
- Configurable level from config

**Test:** Hash a known string, verify deterministic. Logger writes to file.

---

## Phase 1: Hooks — Capture Conversations

### Step 1.1 — Transcript parser

Dependencies: none (just stdlib `json`)

Build `rrecall/hooks/transcript_parser.py`:

- `parse_transcript(jsonl_path: Path) -> TranscriptData` 
- Read the JSONL file line by line
- Extract the summary line (type: "summary")
- Extract user/assistant message pairs with timestamps
- Extract tool_use blocks (tool name, input summary, response summary)
- Handle malformed lines gracefully (skip with warning)
- Return a dataclass:

```python
@dataclass
class TranscriptMessage:
    role: str  # "user" or "assistant"
    timestamp: datetime | None
    text_content: str
    tool_uses: list[ToolUseBlock]

@dataclass
class TranscriptData:
    summary: str | None
    messages: list[TranscriptMessage]
    raw_line_hashes: set[str]  # For deduplication
```

**Test:** Create a sample JSONL file mimicking Claude Code's format. Parse it. Verify message count, summary extraction, tool_use handling. Test with malformed lines.

### Step 1.2 — Markdown converter

Dependencies: none

Build the second half of `rrecall/hooks/transcript_parser.py` (or a separate `markdown_converter.py`):

- `transcript_to_markdown(data: TranscriptData, metadata: SessionMetadata) -> str`
- Generates the Obsidian-compatible markdown from the architecture doc:
  - YAML frontmatter (session_id, project, cwd, timestamps, tags)
  - Summary section
  - Conversation section with `### User` / `### Assistant` headings
  - Tool uses as collapsible callouts (`> [!tool]- Bash: \`cmd\``)
- Project name derived from cwd (last path component)
- Handles pre-compact snapshots as a separate section at the end

**Test:** Feed the parsed TranscriptData from Step 1.1 into this. Verify the output is valid Markdown. Verify frontmatter parses correctly with a YAML library. Verify Obsidian callout syntax.

### Step 1.3 — Session registry

Dependencies: none (stdlib `json`, `filelock` or manual locking)

Build `rrecall/hooks/session_registry.py`:

- Reads/writes `~/.rrecall/sessions.json`
- `register_session(session_id, cwd, transcript_path) -> SessionEntry`
- `record_pre_compact(session_id, snapshot_path)`
- `record_session_end(session_id, transcript_hash, markdown_path)`
- `get_session(session_id) -> SessionEntry | None`
- `is_duplicate(session_id, transcript_hash) -> bool`
- File locking to prevent concurrent hook races (use `fcntl.flock` on Unix or a simple `.lock` file)

**Test:** Register a session. Record a pre-compact. Record session end. Verify JSON file contents. Test duplicate detection. Test concurrent access doesn't corrupt.

### Step 1.4 — PreCompact hook script

Build `rrecall/hooks/pre_compact.py`:

This is the actual script that Claude Code calls. It:

1. Reads JSON from stdin (`session_id`, `transcript_path`, `trigger`)
2. Copies the transcript JSONL to `~/.rrecall/snapshots/{session_id}_{timestamp}.jsonl`
3. Updates the session registry
4. Exits with code 0
5. Produces no stdout

The entire script should complete in <100ms (it's just a file copy + JSON update).

**Test:** Pipe sample hook JSON to the script. Verify snapshot file created. Verify registry updated. Time it — must be <100ms.

### Step 1.5 — SessionEnd hook script

Build `rrecall/hooks/session_end.py`:

1. Reads JSON from stdin (`session_id`, `transcript_path`, `reason`)
2. Quick-checks: is the session worth saving? (min messages from config, not a duplicate hash)
3. Forks the heavy work to a background process and exits immediately:
   ```python
   subprocess.Popen(
       [sys.executable, "-m", "rrecall.hooks.finalize", "--session-id", session_id],
       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       start_new_session=True
   )
   ```
4. Exits with code 0, no stdout

Build `rrecall/hooks/finalize.py` (the background worker):

1. Loads the current transcript + all pre-compact snapshots for this session
2. Merges and deduplicates messages (by line hash)
3. Converts to Markdown
4. Writes atomically to the Obsidian vault (write to `.tmp`, then `os.rename`)
5. If this session already has a markdown file (resumed session), appends the new content with a `## Resumed (timestamp)` separator
6. Updates the session registry with final state
7. Cleans up old snapshots for this session

**Test:** Full end-to-end: create a fake transcript, pipe SessionEnd input, wait for background process, verify Markdown file in vault. Test resumed session appending. Test duplicate rejection.

### Step 1.6 — Hook installer script

Build `scripts/install-hooks.sh` (and `.ps1` for PowerShell):

- Detects whether `.claude/settings.json` exists (project-level or user-level)
- Adds the PreCompact and SessionEnd hook entries if not already present
- Uses `jq` for JSON manipulation (or Python fallback)
- Backs up the existing settings file before modifying

The hook entries should look like:
```json
{
  "hooks": {
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "python -m rrecall.hooks.pre_compact"
      }]
    }],
    "SessionEnd": [{
      "hooks": [{
        "type": "command",
        "command": "python -m rrecall.hooks.session_end"
      }]
    }]
  }
}
```

**Test:** Run installer on a test settings file. Verify hooks added. Run again — verify no duplicates. Test with existing hooks present.

### Checkpoint: Manual Integration Test

At this point you should be able to:
1. Install hooks into Claude Code
2. Have a conversation, hit `/compact` or let auto-compact happen
3. End the session
4. Find a well-formatted Markdown file in your Obsidian vault

Do this manually 3-5 times with different scenarios: short session, long session, resumed session, multiple compactions.

---

## Phase 2: Notes Search — Full-Text

### Step 2.1 — CLI skeleton

Dependencies: `click >= 8.0`

Build `rrecall/cli.py`:

```python
@click.group()
def main(): ...

@main.group()
def notes(): ...

@main.group()
def code(): ...

@main.group()
def costs(): ...
```

Register as entry point in `pyproject.toml`. Verify `rrecall --help` works.

### Step 2.2 — Notes indexer (FTS only)

Dependencies: `lancedb >= 0.15`, `pyarrow >= 15.0`

Build `rrecall/vectordb/lancedb_store.py`:

- `VectorStore` class wrapping LanceDB
- `create_or_open_table(name, schema)` — creates table if not exists
- `upsert_chunks(table_name, chunks: list[dict])` — add/update by id
- `delete_chunks(table_name, ids: list[str])` — remove chunks
- `text_search(table_name, query, top_k, filters) -> list[SearchResult]` — FTS via LanceDB's Tantivy integration
- Schema for notes table (without vector column for now — add a dummy zero vector or make it optional)

Build `rrecall/notes/indexer.py`:

- Walk the Obsidian vault directory
- For each `.md` file:
  - Compute content hash, skip if unchanged
  - Parse frontmatter (extract tags, session_id, project, etc.)
  - Chunk by heading sections (split on `## ` and `### ` boundaries)
  - For conversation files: chunk by user/assistant exchange pairs
  - Prepend heading hierarchy as context to each chunk
  - Assign chunk IDs: `{file_hash}_{chunk_index}`
- Track indexed files in a `file_index` within the LanceDB metadata or a sidecar JSON
- Handle file deletions (remove chunks for files no longer present)

Build `rrecall/notes/searcher.py`:

- `search(query, space, mode, top_k) -> list[SearchResult]`
- For now, only `mode="text"` works (FTS)
- Apply space filters (conversations only, notes only, project filter)

Wire into CLI:
```bash
rrecall notes index          # Full re-index
rrecall notes index --file path  # Single file
rrecall notes search "query" --mode text --top-k 10
```

**Test:** Create a test vault with 5-10 markdown files (mix of conversations and notes). Index. Search. Verify results make sense. Test incremental re-index after changing a file.

---

## Phase 3: Embeddings

### Step 3.1 — Embedding provider abstraction

Build `rrecall/embedding/base.py`:

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    @abstractmethod
    def embed_query(self, query: str) -> list[float]: ...
    @property
    @abstractmethod
    def dimension(self) -> int: ...
    @property
    @abstractmethod
    def model_name(self) -> str: ...
```

Build factory function:
```python
def get_provider(config: Config) -> EmbeddingProvider:
    if config.embedding.provider == "local":
        return LocalOnnxProvider(...)
    elif config.embedding.provider == "openai":
        return OpenAIProvider(...)
```

### Step 3.2 — Local ONNX provider

Dependencies: `fastembed-gpu >= 0.4`

Build `rrecall/embedding/local_onnx.py`:

- Wraps FastEmbed's `TextEmbedding`
- Constructor: select model, detect GPU availability, fall back to CPU
- `embed_texts`: batch embed with progress callback for large batches
- `embed_query`: use `query_embed` (adds "query: " prefix for BGE models)
- Lazy model loading (don't load until first embed call)

**Test:** Embed a few strings. Verify vector dimension matches expected (384 for bge-small). Verify GPU is used when available (`nvidia-smi` shows memory usage). Benchmark: embed 1000 strings, measure time.

### Step 3.3 — OpenAI provider + cost tracking

Dependencies: `openai >= 1.0`, `tiktoken >= 0.7`

Build `rrecall/embedding/openai_provider.py`:

- Wraps OpenAI embeddings API
- Handles batching (OpenAI accepts up to 2048 inputs per request, but chunk to ~100 for reliability)
- Rate limit handling with exponential backoff

Build `rrecall/embedding/cost_tracker.py`:

- Append-only JSONL ledger at `~/.rrecall/cost_ledger.jsonl`
- `record(model, tokens, requests)` — appends a line
- `get_summary(period: "day" | "week" | "month") -> CostSummary` — reads and aggregates
- Pricing lookup from config

Wire into CLI:
```bash
rrecall costs show                  # Current month
rrecall costs show --period week    # This week
```

**Test:** Embed with OpenAI (requires API key). Verify cost ledger has entries. Verify cost calculation matches expected pricing.

### Step 3.4 — Vector search in notes

Update `rrecall/vectordb/lancedb_store.py`:

- `vector_search(table_name, vector, top_k, filters) -> list[SearchResult]`
- `hybrid_search(table_name, query_text, query_vector, top_k, filters)` — combines FTS + vector with Reciprocal Rank Fusion (RRF)

Update `rrecall/notes/indexer.py`:

- After chunking, embed all chunks via the configured provider
- Store vectors in the LanceDB notes table
- For incremental re-index: only embed changed chunks

Update `rrecall/notes/searcher.py`:

- `mode="vector"`: embed query, vector search
- `mode="hybrid"`: embed query, run both FTS and vector, fuse with RRF

Update CLI:
```bash
rrecall notes search "JWT refresh token implementation" --mode hybrid
```

**Test:** Index the test vault with embeddings. Search with vector mode. Verify semantic matches work (e.g., query "authentication" finds chunks about "login" and "JWT"). Compare hybrid vs. pure vector vs. pure text results.

### Step 3.5 — Embedding server (optional)

Dependencies: `uvicorn`, `fastapi` (or just `http.server` for simplicity)

Build `rrecall/embedding/server.py`:

- Lightweight HTTP server that loads the model once and serves embed requests
- Endpoint: `POST /embed` with `{"texts": [...], "mode": "document"|"query"}`
- Health check: `GET /health`
- Graceful shutdown on SIGTERM

Update the local ONNX provider:

- On init, try to connect to `http://localhost:{port}/health`
- If running, proxy all embed calls to the server
- If not running, load model in-process (with a logged tip about the server)

Wire into CLI:
```bash
rrecall serve --port 9876 --model BAAI/bge-small-en-v1.5
```

**Test:** Start server. Embed via CLI (verify it hits the server, not loading locally). Stop server. Embed again (verify fallback works). Benchmark: compare latency with and without server for a single query.

### Checkpoint: Notes Search Integration Test

At this point:
1. Hooks capture conversations to Obsidian vault
2. `rrecall notes index` builds FTS + vector index
3. `rrecall notes search` finds relevant conversations and notes
4. Embedding works both locally and via OpenAI with cost tracking

Test end-to-end: have a Claude Code conversation about a specific topic. End session. Index. Search for that topic. Verify it's found.

---

## Phase 4: Code Search

### Step 4.1 — Tree-sitter setup + language configs

Dependencies: `tree-sitter >= 0.23`, `tree-sitter-python`, `tree-sitter-c-sharp`, `tree-sitter-typescript`, `tree-sitter-html`, `tree-sitter-css`

Build `rrecall/code/chunkers/languages.py`:

- Language detection from file extension
- Map of language → tree-sitter grammar + configuration:

```python
LANGUAGE_CONFIGS = {
    "python": LanguageConfig(
        grammar=tree_sitter_python,
        top_level_nodes=["class_definition", "function_definition", "decorated_definition"],
        merge_nodes=["import_statement", "import_from_statement"],
        # ...
    ),
    "csharp": LanguageConfig(...),
    "typescript": LanguageConfig(...),
    # etc.
}
```

**Test:** Verify all five grammars load successfully. Parse a sample file in each language. Print the AST node types.

### Step 4.2 — AST chunker

Build `rrecall/code/chunkers/treesitter.py`:

Implement the cAST-inspired algorithm:

1. `parse_file(path, language) -> Tree`
2. `extract_chunks(tree, source_code, config) -> list[CodeChunk]`:
   - Walk top-level AST nodes
   - For each node: if size <= max_chunk_size, emit as chunk
   - If too large: recurse into children, split at child boundaries
   - Merge adjacent small nodes (imports, type aliases) up to min_chunk_size
   - Build context header for each chunk (file path, parent class/namespace, signature)
3. Extract metadata: symbol name, parent symbol, signature, chunk type

Start with **Python only**. Get the algorithm right on one language before generalizing.

**Test:** Chunk a real Python file with classes and functions. Verify each chunk is a semantically meaningful unit. Verify no chunks are too large or too small. Verify context headers are correct. Verify signatures are extracted.

### Step 4.3 — Remaining languages

Extend the chunker to handle C#, TypeScript, HTML, CSS:

- **C#**: Handle namespaces (include as context, don't chunk them as units), partial classes, using directives, properties, records
- **TypeScript**: Handle JSX/TSX nodes, type aliases, interfaces, `export default`
- **HTML**: Chunk by top-level elements with id/class attributes; extract `<script>` and `<style>` tags and sub-parse them with the appropriate grammar
- **CSS**: Chunk by rule sets and media queries; keep `@import` and `@font-face` as context

**Test:** For each language, take 2-3 real-world files and verify chunks are sensible. Edge cases: empty files, single-function files, files with only imports, very large classes.

### Step 4.4 — Code indexer

Build `rrecall/code/indexer.py`:

- `index_repo(repo_path, repo_name)`:
  - Walk files respecting `.gitignore` (via `pathspec`)
  - Skip binary files, very large files (>100KB), vendor directories
  - Detect language from extension
  - Chunk each file with the AST chunker
  - Embed all chunks
  - Store in LanceDB code table
  - Track file hashes for incremental updates
- `incremental_reindex(repo_path)`:
  - Compare current file hashes against stored hashes
  - Re-chunk and re-embed only changed files
  - Remove chunks for deleted files
- `index_repo_group(group_name)`:
  - Resolve group paths from config
  - Index each repo

Wire into CLI:
```bash
rrecall code index                           # Index current repo
rrecall code index --repo ~/work/my-project  # Specific repo
rrecall code index --space group:backend     # Repo group
rrecall code index --space all               # All configured repos
rrecall code reindex                         # Force full re-index
```

**Test:** Index a real repo. Verify chunk count is reasonable. Verify incremental re-index is fast when nothing changed. Modify a file, re-index, verify only that file's chunks updated.

### Step 4.5 — Code searcher

Build `rrecall/code/searcher.py`:

- Same pattern as notes searcher: vector, text, hybrid modes
- Additional filters: language, chunk_type, file_pattern, repo_name
- `find_similar(code_snippet_or_file_range)`: embed the snippet, vector search

Wire into CLI:
```bash
rrecall code search "database connection retry logic" --space current
rrecall code search "ConnectionPool" --mode text --language csharp
rrecall code search --similar-to src/auth.py:10-50
```

**Test:** Index a repo. Search for concepts that exist in the code. Verify semantic search works (e.g., "error handling" finds `try/except` blocks). Test language and chunk_type filters. Test `--similar-to`.

### Checkpoint: Code Search Integration Test

Index 2-3 real repos you work with. Search across them. Verify results are relevant and fast (<1 second for vector search). Compare results across search modes.

---

## Phase 5: Unified MCP Server

### Step 5.1 — MCP server skeleton

Dependencies: `mcp >= 1.0`

Build `rrecall/mcp_server.py`:

- Initialize the MCP server with the `mcp` SDK
- Load config
- Initialize the embedding provider (shared instance)
- Initialize LanceDB connection (shared instance)
- Register tool stubs that return placeholder responses

**Test:** Start the server. Connect with a test MCP client (or Claude Code). Verify tools are listed. Verify stubs respond.

### Step 5.2 — Wire notes tools

Implement the actual tool handlers by calling into `notes/searcher.py`:

- `search_notes(query, space, mode, top_k, project)` → calls searcher, formats results
- `list_recent_sessions(limit, project)` → queries session registry
- `get_session(session_id)` → reads the markdown file and returns content

Format results for Claude consumption: include file path, heading context, relevance score, and the chunk text. Keep it concise — Claude doesn't need the full document, just the relevant chunks.

**Test:** Start MCP server. Use it from Claude Code. Ask "search my notes for JWT" and verify it returns results.

### Step 5.3 — Wire code tools

Implement code tool handlers by calling into `code/searcher.py`:

- `search_code(query, space, mode, top_k, language, chunk_type, file_pattern)`
- `find_similar_code(code_snippet, file_path, line_range, space)`
- `get_code_context(file_path, start_line, end_line, context_lines)` → reads the actual file and returns surrounding context

**Test:** Use from Claude Code. Ask "find code related to database connections" and verify it returns real code chunks.

### Step 5.4 — SessionStart hook for context injection

Build a SessionStart hook that optionally injects relevant context:

- Read the current `cwd` to determine the project
- Query the notes index for the most recent session summary for this project
- Query the code index for a high-level overview of the repo
- Print to stdout (SessionStart stdout becomes context for Claude)

This is opt-in via config:
```toml
[hooks.session_start]
enabled = false
inject_last_session_summary = true
inject_repo_overview = false
```

**Test:** Enable. Start a new Claude Code session. Verify Claude mentions awareness of the previous session's context.

---

## Phase 6: Polish & Hardening

### Step 6.1 — Error handling pass

Go through every module and ensure:
- File I/O errors are caught and logged (don't crash hooks)
- Network errors (OpenAI, embedding server) have retries and fallbacks
- Corrupt database files are detected and offer recovery (`rrecall repair`)
- Config errors give clear messages pointing to the problematic field

### Step 6.2 — Cross-platform path handling

- Test on both Windows (native Python) and WSL
- Normalize all stored paths to POSIX format
- Handle `/mnt/c/...` ↔ `C:\...` conversion in config
- Verify Obsidian vault access works from both environments

### Step 6.3 — Performance profiling

- Profile initial indexing of a large repo (10k+ files)
- Profile search latency (target: <500ms for hybrid search)
- Profile hook execution time (target: <100ms)
- Optimize batch embedding sizes for your GPU
- Add `--verbose` flag that prints timing info

### Step 6.4 — Documentation

- README with quick start guide
- `rrecall --help` for all commands (Click handles this)
- Configuration reference (annotated example TOML)
- Troubleshooting guide (common issues: CUDA not detected, vault path wrong, hooks not firing)

---

## Phase 7: Optional Enhancements (pick as needed)

### Step 7.1 — Claude -p conversation filtering
### Step 7.2 — Claude -p summary generation
### Step 7.3 — File watcher daemon (`rrecall watch`)
### Step 7.4 — Embedding cache by content hash
### Step 7.5 — Multi-search (notes + code combined results)
### Step 7.6 — Session diff view (files modified per session)
### Step 7.7 — `rrecall export` for backup/portability

---

## Quick Reference: What to Build When

| Step | Module | Key File(s) | Depends On | Done |
|------|--------|-------------|------------|------|
| 0.1 | scaffold | `pyproject.toml` | nothing | [x] |
| 0.2 | config | `config.py` | 0.1 | [x] |
| 0.3 | utils | `hashing.py`, `logging.py` | 0.1 | [x] |
| 1.1 | hooks | `transcript_parser.py` | 0.3 | [x] |
| 1.2 | hooks | `markdown_converter.py` | 1.1 | [x] |
| 1.3 | hooks | `session_registry.py` | 0.2, 0.3 | [x] |
| 1.4 | hooks | `pre_compact.py` | 1.3 | [x] |
| 1.5 | hooks | `session_end.py`, `finalize.py` | 1.1-1.4 | [x] |
| 1.6 | scripts | `install-hooks.sh`, `install-hooks.ps1` | 1.4, 1.5 | [x] |
| 2.1 | cli | `cli.py` | 0.2 | [X] |
| 2.2 | notes | `indexer.py`, `searcher.py`, `lancedb_store.py` | 2.1, 0.3 | [X] |
| 3.1 | embedding | `base.py` | 0.2 | [X] |
| 3.2 | embedding | `local_onnx.py` | 3.1 | [ ] |
| 3.3 | embedding | `openai_provider.py`, `cost_tracker.py` | 3.1 | [ ] |
| 3.4 | notes | update `indexer.py`, `searcher.py` | 2.2, 3.1-3.2 | [ ] |
| 3.5 | embedding | `server.py` | 3.2 | [ ] |
| 4.1 | code | `languages.py` | 0.1 | [ ] |
| 4.2 | code | `treesitter.py` | 4.1 | [ ] |
| 4.3 | code | extend `treesitter.py` | 4.2 | [ ] |
| 4.4 | code | `indexer.py` | 4.2, 3.1, 2.2 (LanceDB) | [ ] |
| 4.5 | code | `searcher.py` | 4.4 | [ ] |
| 5.1 | mcp | `mcp_server.py` | 3.1 | [ ] |
| 5.2 | mcp | `mcp_server.py` | 5.1, 2.2 | [ ] |
| 5.3 | mcp | `mcp_server.py` | 5.1, 4.5 | [ ] |
| 5.4 | hooks | `session_start.py` | 5.2, 5.3 | [ ] |
