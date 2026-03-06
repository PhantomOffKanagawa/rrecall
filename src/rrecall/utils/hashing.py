"""Content hashing for change detection and deduplication."""

from __future__ import annotations

import hashlib
from pathlib import Path


def content_hash(text: str) -> str:
    """SHA-256 hash of a string, returned as ``sha256:<hex>``."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def file_hash(path: Path) -> str:
    """SHA-256 hash of a file's bytes, returned as ``sha256:<hex>``."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"
