"""Tests for rrecall.code.chunkers.treesitter."""

from __future__ import annotations

from pathlib import Path

from rrecall.code.chunkers.treesitter import chunk_file, extract_chunks, parse_file


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


SAMPLE_PYTHON = '''\
import os
import sys
from pathlib import Path

class MyClass:
    """A sample class."""

    def method_one(self):
        return 1

    def method_two(self, x: int) -> int:
        return x * 2

def standalone_function(a, b):
    """Add two numbers."""
    return a + b

CONSTANT = 42
'''

LARGE_CLASS = '''\
class BigClass:
    """ + ("x" * 2000) + """

    def small_method(self):
        pass
'''


def test_chunk_python_file(tmp_path):
    f = _write(tmp_path, "sample.py", SAMPLE_PYTHON)
    chunks = chunk_file(f)
    assert len(chunks) >= 3  # imports, class, function

    types = [c.chunk_type for c in chunks]
    assert "imports" in types
    assert "class" in types
    assert "function" in types


def test_import_merging(tmp_path):
    f = _write(tmp_path, "sample.py", SAMPLE_PYTHON)
    chunks = chunk_file(f)
    import_chunks = [c for c in chunks if c.chunk_type == "imports"]
    # All 3 import lines should be merged into one chunk
    assert len(import_chunks) == 1
    assert "import os" in import_chunks[0].text
    assert "from pathlib" in import_chunks[0].text


def test_signature_extraction(tmp_path):
    f = _write(tmp_path, "sample.py", SAMPLE_PYTHON)
    chunks = chunk_file(f)
    func_chunks = [c for c in chunks if c.symbol_name == "standalone_function"]
    assert len(func_chunks) == 1
    assert "def standalone_function(a, b):" in func_chunks[0].signature


def test_symbol_names(tmp_path):
    f = _write(tmp_path, "sample.py", SAMPLE_PYTHON)
    chunks = chunk_file(f)
    names = {c.symbol_name for c in chunks if c.symbol_name}
    assert "MyClass" in names
    assert "standalone_function" in names


def test_line_numbers(tmp_path):
    f = _write(tmp_path, "sample.py", SAMPLE_PYTHON)
    chunks = chunk_file(f)
    for c in chunks:
        assert c.start_line >= 1
        assert c.end_line >= c.start_line


def test_context_header(tmp_path):
    f = _write(tmp_path, "sample.py", SAMPLE_PYTHON)
    chunks = chunk_file(f)
    class_chunk = [c for c in chunks if c.symbol_name == "MyClass"][0]
    assert str(f) in class_chunk.context_header


def test_large_node_splitting(tmp_path):
    # A class body larger than max_chars should be split
    big = "class BigClass:\n" + "\n".join(
        f"    def method_{i}(self):\n        return {i}\n" for i in range(50)
    )
    f = _write(tmp_path, "big.py", big)
    chunks = chunk_file(f, max_chars=500)
    assert len(chunks) > 1


def test_unsupported_file_returns_empty(tmp_path):
    f = _write(tmp_path, "readme.md", "# Hello")
    assert chunk_file(f) == []


def test_empty_file(tmp_path):
    f = _write(tmp_path, "empty.py", "")
    assert chunk_file(f) == []


def test_decorated_function(tmp_path):
    code = "@staticmethod\ndef decorated():\n    pass\n"
    f = _write(tmp_path, "dec.py", code)
    chunks = chunk_file(f)
    assert len(chunks) >= 1
    assert chunks[0].symbol_name == "decorated"
    assert chunks[0].chunk_type == "function"
