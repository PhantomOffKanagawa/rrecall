"""Tests for rrecall.utils.logging — setup, formatters, child loggers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from rrecall.utils.logging import setup_logging, get_logger


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path: Path):
        setup_logging(log_dir=tmp_path)
        log_file = tmp_path / "rrecall.log"
        assert log_file.exists()

    def test_returns_rrecall_logger(self, tmp_path: Path):
        logger = setup_logging(log_dir=tmp_path)
        assert logger.name == "rrecall"

    def test_sets_level(self, tmp_path: Path):
        logger = setup_logging(level="debug", log_dir=tmp_path)
        assert logger.level == logging.DEBUG

    def test_sets_level_case_insensitive(self, tmp_path: Path):
        logger = setup_logging(level="WARNING", log_dir=tmp_path)
        assert logger.level == logging.WARNING

    def test_has_two_handlers(self, tmp_path: Path):
        logger = setup_logging(log_dir=tmp_path)
        assert len(logger.handlers) == 2

    def test_idempotent(self, tmp_path: Path):
        """Calling setup_logging twice doesn't add duplicate handlers."""
        l1 = setup_logging(log_dir=tmp_path)
        handler_count = len(l1.handlers)
        l2 = setup_logging(log_dir=tmp_path)
        assert l1 is l2
        assert len(l2.handlers) == handler_count


class TestJSONFormatter:
    def test_log_file_contains_valid_json(self, tmp_path: Path):
        logger = setup_logging(level="info", log_dir=tmp_path)
        logger.info("test message")

        log_file = tmp_path / "rrecall.log"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["msg"] == "test message"
        assert entry["level"] == "INFO"
        assert entry["logger"] == "rrecall"
        assert "ts" in entry

    def test_json_ts_is_iso_format(self, tmp_path: Path):
        logger = setup_logging(level="info", log_dir=tmp_path)
        logger.info("ts check")

        log_file = tmp_path / "rrecall.log"
        entry = json.loads(log_file.read_text().strip().splitlines()[0])
        ts = entry["ts"]
        # Should parse as ISO datetime with timezone
        from datetime import datetime

        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None

    def test_json_exception_field(self, tmp_path: Path):
        logger = setup_logging(level="info", log_dir=tmp_path)
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("caught error")

        log_file = tmp_path / "rrecall.log"
        entry = json.loads(log_file.read_text().strip().splitlines()[0])
        assert "exception" in entry
        assert "ValueError" in entry["exception"]
        assert "boom" in entry["exception"]

    def test_multiple_messages(self, tmp_path: Path):
        logger = setup_logging(level="debug", log_dir=tmp_path)
        logger.debug("one")
        logger.info("two")
        logger.warning("three")

        log_file = tmp_path / "rrecall.log"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 3
        levels = [json.loads(line)["level"] for line in lines]
        assert levels == ["DEBUG", "INFO", "WARNING"]


class TestHumanFormatter:
    def test_stderr_format(self, tmp_path: Path, capsys):
        logger = setup_logging(level="info", log_dir=tmp_path)
        logger.info("hello from test")

        captured = capsys.readouterr()
        # Human formatter writes to stderr
        assert "[I]" in captured.err
        assert "hello from test" in captured.err

    def test_stderr_shows_time(self, tmp_path: Path, capsys):
        logger = setup_logging(level="info", log_dir=tmp_path)
        logger.info("time check")

        captured = capsys.readouterr()
        # Format is HH:MM:SS [X] msg — should have colons from time
        parts = captured.err.strip().split()
        assert ":" in parts[0]  # time field


class TestGetLogger:
    def test_returns_child_logger(self, tmp_path: Path):
        setup_logging(log_dir=tmp_path)
        child = get_logger("hooks")
        assert child.name == "rrecall.hooks"

    def test_child_writes_to_same_file(self, tmp_path: Path):
        setup_logging(level="info", log_dir=tmp_path)
        child = get_logger("notes")
        child.info("child message")

        log_file = tmp_path / "rrecall.log"
        entry = json.loads(log_file.read_text().strip().splitlines()[0])
        assert entry["logger"] == "rrecall.notes"
        assert entry["msg"] == "child message"

    def test_none_returns_root(self, tmp_path: Path):
        setup_logging(log_dir=tmp_path)
        root = get_logger(None)
        assert root.name == "rrecall"

    def test_auto_initializes_if_no_handlers(self, tmp_path: Path, monkeypatch):
        """get_logger should call setup_logging if handlers haven't been set."""
        monkeypatch.setenv("RRECALL_CONFIG_DIR", str(tmp_path))
        logger = get_logger("auto")
        assert logger.name == "rrecall.auto"
        # Parent should have handlers now
        assert len(logging.getLogger("rrecall").handlers) > 0

    def test_level_filtering(self, tmp_path: Path):
        setup_logging(level="warning", log_dir=tmp_path)
        logger = get_logger("filtered")
        logger.debug("should not appear")
        logger.info("should not appear either")
        logger.warning("should appear")

        log_file = tmp_path / "rrecall.log"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["level"] == "WARNING"
