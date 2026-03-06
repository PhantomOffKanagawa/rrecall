"""Tests for scripts/install-hooks.sh."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parents[1] / "scripts" / "install-hooks.sh")


def run_install(tmp_path: Path, *, scope: str = "project", cwd: Path | None = None) -> subprocess.CompletedProcess:
    args = ["bash", SCRIPT]
    if scope == "project":
        args.append("--project")
    return subprocess.run(
        args,
        cwd=str(cwd or tmp_path),
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )


def settings_path(tmp_path: Path, scope: str = "project") -> Path:
    if scope == "user":
        return tmp_path / ".claude" / "settings.json"
    return tmp_path / ".claude" / "settings.json"


def load_settings(tmp_path: Path, scope: str = "project") -> dict:
    return json.loads(settings_path(tmp_path, scope).read_text())


def test_fresh_install_creates_settings(tmp_path: Path):
    result = run_install(tmp_path)
    assert result.returncode == 0
    settings = load_settings(tmp_path)
    assert "hooks" in settings
    assert len(settings["hooks"]["PreCompact"]) == 1
    assert len(settings["hooks"]["SessionEnd"]) == 1
    assert settings["hooks"]["PreCompact"][0]["hooks"][0]["command"] == "rrecall hooks pre-compact"
    assert settings["hooks"]["SessionEnd"][0]["hooks"][0]["command"] == "rrecall hooks session-end"


def test_preserves_existing_settings(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = {"env": {"FOO": "bar"}, "permissions": {"allow": ["Read"]}}
    (claude_dir / "settings.json").write_text(json.dumps(existing))

    result = run_install(tmp_path)
    assert result.returncode == 0
    settings = load_settings(tmp_path)
    assert settings["env"] == {"FOO": "bar"}
    assert settings["permissions"] == {"allow": ["Read"]}
    assert "hooks" in settings


def test_creates_backup(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text('{"existing": true}')

    run_install(tmp_path)
    backups = list(claude_dir.glob("settings.json.bak.*"))
    assert len(backups) == 1


def test_no_duplicate_hooks_on_rerun(tmp_path: Path):
    run_install(tmp_path)
    run_install(tmp_path)
    settings = load_settings(tmp_path)
    assert len(settings["hooks"]["PreCompact"]) == 1
    assert len(settings["hooks"]["SessionEnd"]) == 1


def test_preserves_existing_hooks(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = {
        "hooks": {
            "PreToolUse": [{"hooks": [{"type": "command", "command": "echo hi"}]}]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(existing))

    run_install(tmp_path)
    settings = load_settings(tmp_path)
    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert "PreCompact" in settings["hooks"]
    assert "SessionEnd" in settings["hooks"]


def test_user_scope(tmp_path: Path):
    result = run_install(tmp_path, scope="user")
    assert result.returncode == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "hooks" in settings


def test_output_messages(tmp_path: Path):
    result = run_install(tmp_path)
    assert "rrecall hooks installed" in result.stdout
    assert "PreCompact" in result.stdout
    assert "SessionEnd" in result.stdout


def test_no_backup_on_fresh_install(tmp_path: Path):
    run_install(tmp_path)
    claude_dir = tmp_path / ".claude"
    backups = list(claude_dir.glob("settings.json.bak.*"))
    assert len(backups) == 0


def test_backup_contains_original_content(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    original = {"customSetting": True}
    (claude_dir / "settings.json").write_text(json.dumps(original))

    run_install(tmp_path)
    backups = list(claude_dir.glob("settings.json.bak.*"))
    assert json.loads(backups[0].read_text()) == original


def test_project_scope_writes_to_project_dir(tmp_path: Path):
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    result = run_install(tmp_path, scope="project", cwd=project_dir)
    assert result.returncode == 0
    project_settings = project_dir / ".claude" / "settings.json"
    assert project_settings.exists()
    settings = json.loads(project_settings.read_text())
    assert "PreCompact" in settings["hooks"]


def test_project_scope_does_not_write_to_home(tmp_path: Path):
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    run_install(tmp_path, scope="project", cwd=project_dir)
    assert not (tmp_path / ".claude" / "settings.json").exists()
