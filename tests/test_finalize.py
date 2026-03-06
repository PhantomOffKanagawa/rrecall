"""Tests for the finalize background worker."""

import json

import pytest
from pathlib import Path

from rrecall.hooks.finalize import finalize
from rrecall.hooks.session_registry import register_session, get_session


@pytest.fixture(autouse=True)
def env_setup(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    vault_dir = tmp_path / "vault"
    config_dir.mkdir()
    vault_dir.mkdir()
    monkeypatch.setenv("RRECALL_CONFIG_DIR", str(config_dir))

    config_path = config_dir / "config.toml"
    config_path.write_text(
        f'[general]\nobsidian_vault = "{vault_dir}"\nsession_subfolder = "Claude Sessions"\n\n'
        f'[hooks.filtering]\nenabled = false\n',
        encoding="utf-8",
    )

    import rrecall.config as cfg_mod
    cfg_mod._config = None

    yield {"config_dir": config_dir, "vault_dir": vault_dir}

    cfg_mod._config = None


def _make_transcript(path: Path, messages=None, summary="Test session"):
    lines = [{"type": "summary", "summary": summary}]
    if messages is None:
        messages = [
            {"type": "user", "message": {"role": "user", "content": "Hello"}, "timestamp": "2026-03-05T10:00:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": "Hi there"}, "timestamp": "2026-03-05T10:01:00Z"},
            {"type": "user", "message": {"role": "user", "content": "Help me"}, "timestamp": "2026-03-05T10:05:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": "Sure thing"}, "timestamp": "2026-03-05T10:10:00Z"},
        ]
    lines.extend(messages)
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def test_basic_finalize_creates_markdown_file(tmp_path, env_setup):
    vault_dir = env_setup["vault_dir"]
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript(transcript)

    finalize("sess-basic", str(transcript), "/home/user/myproject")

    session_dir = vault_dir / "Claude Sessions"
    md_files = list(session_dir.glob("*.md"))
    assert len(md_files) == 1


def test_basic_finalize_file_contains_frontmatter_and_conversation(tmp_path, env_setup):
    vault_dir = env_setup["vault_dir"]
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript(transcript)

    finalize("sess-content", str(transcript), "/home/user/myproject")

    session_dir = vault_dir / "Claude Sessions"
    md_file = list(session_dir.glob("*.md"))[0]
    content = md_file.read_text(encoding="utf-8")

    assert "session_id: sess-content" in content
    assert "## Conversation" in content
    assert "Hello" in content
    assert "Hi there" in content


def test_output_file_naming(tmp_path, env_setup):
    vault_dir = env_setup["vault_dir"]
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript(transcript)

    finalize("sess-naming", str(transcript), "/home/user/myproject")

    session_dir = vault_dir / "Claude Sessions"
    md_files = list(session_dir.glob("*.md"))
    assert len(md_files) == 1
    filename = md_files[0].name
    assert filename.startswith("2026-03-05_sess-nam")
    assert "myproject" in filename
    assert filename.endswith(".md")


def test_session_registry_updated_to_completed(tmp_path, env_setup):
    register_session("sess-registry", "/home/user/myproject")
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript(transcript)

    finalize("sess-registry", str(transcript), "/home/user/myproject")

    entry = get_session("sess-registry")
    assert entry is not None
    assert entry.status == "completed"
    assert entry.markdown_path != ""


def test_resumed_session_appends_section(tmp_path, env_setup):
    vault_dir = env_setup["vault_dir"]
    register_session("sess-resume", "/home/user/myproject")
    transcript1 = tmp_path / "transcript1.jsonl"
    _make_transcript(transcript1)

    finalize("sess-resume", str(transcript1), "/home/user/myproject")

    session_dir = vault_dir / "Claude Sessions"
    md_files = list(session_dir.glob("*.md"))
    assert len(md_files) == 1
    original_path = md_files[0]

    transcript2 = tmp_path / "transcript2.jsonl"
    _make_transcript(transcript2, messages=[
        {"type": "user", "message": {"role": "user", "content": "New question"}, "timestamp": "2026-03-05T11:00:00Z"},
        {"type": "assistant", "message": {"role": "assistant", "content": "New answer"}, "timestamp": "2026-03-05T11:01:00Z"},
    ])

    finalize("sess-resume", str(transcript2), "/home/user/myproject")

    content = original_path.read_text(encoding="utf-8")
    assert "## Resumed" in content
    assert "New question" in content
    assert "New answer" in content


def test_nonexistent_transcript_does_not_crash(tmp_path):
    finalize("sess-missing", "/does/not/exist.jsonl", "/home/user/myproject")
