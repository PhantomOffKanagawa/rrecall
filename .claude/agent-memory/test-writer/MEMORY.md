# Test Writer Memory — rrecall

## Project Test Conventions

- **Framework:** pytest (configured in `pyproject.toml`)
- **Runner:** `uv run pytest tests/ -v`
- **Style:** flat functions (no class grouping), `test_<behavior>` naming
- **Assertions:** plain `assert`, no extra assertion libraries
- **File layout:** `tests/test_<module_name>.py` alongside production code in `src/rrecall/`

## Key Patterns

- Temporary files: use `tempfile.NamedTemporaryFile` or `tmp_path` fixture; always clean up with `.unlink()`
- Config dir isolation: monkeypatch `RRECALL_CONFIG_DIR` env var to `str(tmp_path)` for any test touching session registry or config dir
- `autouse=True` fixture pattern for mandatory env isolation (session registry tests)
- `sys.stdin` mocking: `monkeypatch.setattr("sys.stdin", io.StringIO(payload))`
- `main()` functions that call `sys.exit(0)`: catch with `pytest.raises(SystemExit)` and check `.code == 0`

## Important Source Paths

- `src/rrecall/config.py` — `get_config_dir()` reads `RRECALL_CONFIG_DIR` env var
- `src/rrecall/hooks/transcript_parser.py` — `TranscriptData`, `TranscriptMessage`, `ToolUseBlock`
- `src/rrecall/hooks/markdown_converter.py` — `transcript_to_markdown()`, `resumed_section()`, `SessionMetadata`
- `src/rrecall/hooks/session_registry.py` — file-locked JSON store at `{config_dir}/sessions.json`
- `src/rrecall/hooks/pre_compact.py` — stdin hook, always exits with `sys.exit(0)`

## Gotchas

- Do NOT introspect `monkeypatch._patches` — it's a private API that doesn't exist; use `tmp_path` directly or re-call `monkeypatch.setenv` to get the path
- `record_session_end` silently no-ops if session not already registered (no auto-create)
- `record_pre_compact` auto-creates the session entry if not found
- `is_duplicate` returns `False` for empty string hash even if stored hash is also empty
