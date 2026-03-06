"""Tests for rrecall.cli — Click group structure."""

from __future__ import annotations

from click.testing import CliRunner

from rrecall.cli import main


def test_help_lists_subgroups():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("notes", "code", "costs"):
        assert cmd in result.output


def test_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_unknown_command_returns_error():
    result = CliRunner().invoke(main, ["doesnotexist"])
    assert result.exit_code != 0
