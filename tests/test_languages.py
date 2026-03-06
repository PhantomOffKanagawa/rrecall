"""Tests for rrecall.code.chunkers.languages."""

from __future__ import annotations

from rrecall.code.chunkers.languages import (
    detect_language,
    get_config,
    get_configs,
    get_parser,
)


def test_all_grammars_load():
    configs = get_configs()
    assert set(configs.keys()) == {"python", "csharp", "typescript", "tsx", "html", "css"}


def test_detect_language():
    assert detect_language("foo.py") == "python"
    assert detect_language("bar.cs") == "csharp"
    assert detect_language("baz.ts") == "typescript"
    assert detect_language("qux.tsx") == "tsx"
    assert detect_language("index.html") == "html"
    assert detect_language("style.css") == "css"
    assert detect_language("readme.md") is None


def test_get_parser_parses_python():
    parser = get_parser("python")
    assert parser is not None
    tree = parser.parse(b"def hello(): pass")
    root = tree.root_node
    assert root.type == "module"
    assert any(c.type == "function_definition" for c in root.children)


def test_get_parser_parses_csharp():
    parser = get_parser("csharp")
    assert parser is not None
    tree = parser.parse(b"class Foo { void Bar() {} }")
    assert tree.root_node.type == "compilation_unit"


def test_get_parser_parses_typescript():
    parser = get_parser("typescript")
    assert parser is not None
    tree = parser.parse(b"function greet(name: string): void {}")
    assert tree.root_node.type == "program"


def test_get_parser_parses_html():
    parser = get_parser("html")
    assert parser is not None
    tree = parser.parse(b"<div>hello</div>")
    assert tree.root_node.type == "document"


def test_get_parser_parses_css():
    parser = get_parser("css")
    assert parser is not None
    tree = parser.parse(b"body { color: red; }")
    assert tree.root_node.type == "stylesheet"


def test_get_parser_unknown_returns_none():
    assert get_parser("brainfuck") is None


def test_python_config_has_expected_nodes():
    cfg = get_config("python")
    assert cfg is not None
    assert "function_definition" in cfg.top_level_nodes
    assert "import_statement" in cfg.merge_nodes
