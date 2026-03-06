"""Shared fixtures for rrecall tests."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture()
def tmp_config_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for use as RRECALL_CONFIG_DIR."""
    d = tmp_path / "rrecall_config"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove RRECALL_* env vars so tests don't leak state."""
    for key in list(os.environ):
        if key.startswith("RRECALL_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _reset_config_singleton() -> Generator[None, None, None]:
    """Reset the config module singleton between tests."""
    import rrecall.config as cfg_mod

    yield
    cfg_mod._config = None


@pytest.fixture(autouse=True)
def _reset_logging() -> Generator[None, None, None]:
    """Clear rrecall logger handlers between tests so setup_logging runs fresh."""
    yield
    logger = logging.getLogger("rrecall")
    logger.handlers.clear()
    logger.setLevel(logging.WARNING)
