"""Tests for rrecall.utils.hashing — content and file hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

from rrecall.utils.hashing import content_hash, file_hash


class TestContentHash:
    def test_deterministic(self):
        assert content_hash("hello") == content_hash("hello")

    def test_prefix(self):
        h = content_hash("test")
        assert h.startswith("sha256:")

    def test_hex_length(self):
        h = content_hash("test")
        hex_part = h.removeprefix("sha256:")
        assert len(hex_part) == 64  # SHA-256 produces 64 hex chars

    def test_different_inputs_differ(self):
        assert content_hash("a") != content_hash("b")

    def test_empty_string(self):
        h = content_hash("")
        expected = "sha256:" + hashlib.sha256(b"").hexdigest()
        assert h == expected

    def test_unicode(self):
        h = content_hash("héllo wörld 🌍")
        expected = "sha256:" + hashlib.sha256("héllo wörld 🌍".encode("utf-8")).hexdigest()
        assert h == expected

    def test_known_value(self):
        # Well-known SHA-256 of "hello world"
        h = content_hash("hello world")
        assert h == "sha256:b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


class TestFileHash:
    def test_matches_content_for_text(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        fh = file_hash(f)
        ch = content_hash("hello world")
        assert fh == ch

    def test_prefix(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"data")
        assert file_hash(f).startswith("sha256:")

    def test_deterministic(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"data")
        assert file_hash(f) == file_hash(f)

    def test_different_content_differs(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"aaa")
        f2.write_bytes(b"bbb")
        assert file_hash(f1) != file_hash(f2)

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        expected = "sha256:" + hashlib.sha256(b"").hexdigest()
        assert file_hash(f) == expected

    def test_binary_content(self, tmp_path: Path):
        f = tmp_path / "bin.dat"
        data = bytes(range(256))
        f.write_bytes(data)
        expected = "sha256:" + hashlib.sha256(data).hexdigest()
        assert file_hash(f) == expected

    def test_large_file(self, tmp_path: Path):
        """Ensure chunked reading works for files larger than the 8192-byte buffer."""
        f = tmp_path / "large.bin"
        data = b"x" * 100_000
        f.write_bytes(data)
        expected = "sha256:" + hashlib.sha256(data).hexdigest()
        assert file_hash(f) == expected

    def test_missing_file_raises(self, tmp_path: Path):
        import pytest

        with pytest.raises(FileNotFoundError):
            file_hash(tmp_path / "nonexistent.txt")
