"""AST-based code chunker using tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter as ts

from rrecall.code.chunkers.languages import (
    LanguageConfig,
    detect_language,
    get_config,
    get_parser,
)


@dataclass
class CodeChunk:
    """A semantically meaningful code chunk."""
    text: str
    file_path: str
    language: str
    chunk_type: str  # "function", "class", "imports", "other"
    symbol_name: str = ""
    parent_symbol: str = ""
    signature: str = ""
    start_line: int = 0
    end_line: int = 0
    context_header: str = ""


def parse_file(path: Path, language: str | None = None) -> tuple[ts.Tree, bytes, str] | None:
    """Parse a file and return (tree, source_bytes, language).

    Returns None if language is unsupported.
    """
    if language is None:
        language = detect_language(path)
    if language is None:
        return None
    parser = get_parser(language)
    if parser is None:
        return None
    source = path.read_bytes()
    tree = parser.parse(source)
    return tree, source, language


def _node_text(node: ts.Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _node_size(node: ts.Node) -> int:
    return node.end_byte - node.start_byte


def _extract_signature(node: ts.Node, source: bytes, language: str) -> str:
    """Extract the signature line(s) from a definition node."""
    text = _node_text(node, source)
    # For Python: first line up to the colon
    if language == "python":
        for line in text.splitlines():
            line = line.strip()
            if line.endswith(":"):
                return line
            if line.endswith(":\\"):
                return line[:-1]
        return text.splitlines()[0] if text else ""
    # For other languages: first line up to opening brace
    first_line = text.split("{")[0].strip() if "{" in text else text.splitlines()[0]
    return first_line


def _classify_node(node: ts.Node, config: LanguageConfig) -> str:
    """Classify a node as function, class, imports, or other."""
    ntype = node.type
    if ntype in config.merge_nodes:
        return "imports"
    if "class" in ntype or "struct" in ntype or "interface" in ntype:
        return "class"
    if "function" in ntype or "method" in ntype:
        return "function"
    if ntype == "decorated_definition":
        # Look at the inner node
        for child in node.children:
            if "class" in child.type:
                return "class"
            if "function" in child.type or "definition" in child.type:
                return "function"
    return "other"


def _symbol_name(node: ts.Node, source: bytes) -> str:
    """Extract the symbol name from a definition node."""
    # Look for a 'name' or 'identifier' child
    for child in node.children:
        if child.type in ("identifier", "name", "property_identifier"):
            return _node_text(child, source)
    # For decorated definitions, recurse into the inner definition
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type != "decorator":
                name = _symbol_name(child, source)
                if name:
                    return name
    return ""


def _build_context_header(file_path: str, parent_symbol: str, signature: str) -> str:
    """Build a context header for a chunk."""
    parts = [f"# {file_path}"]
    if parent_symbol:
        parts.append(f"# in {parent_symbol}")
    if signature:
        parts.append(signature)
    return "\n".join(parts)


def _split_large_node(
    node: ts.Node,
    source: bytes,
    language: str,
    config: LanguageConfig,
    max_chars: int,
    file_path: str,
    parent_symbol: str,
) -> list[CodeChunk]:
    """Recursively split a node that exceeds max_chars."""
    chunks: list[CodeChunk] = []
    # Emit the signature/header as its own small chunk, then split children
    for child in node.children:
        child_text = _node_text(child, source)
        if not child_text.strip():
            continue
        if _node_size(child) <= max_chars:
            sig = _extract_signature(child, source, language)
            name = _symbol_name(child, source)
            ctype = _classify_node(child, config)
            header = _build_context_header(file_path, parent_symbol, sig)
            chunks.append(CodeChunk(
                text=child_text,
                file_path=file_path,
                language=language,
                chunk_type=ctype,
                symbol_name=name,
                parent_symbol=parent_symbol,
                signature=sig,
                start_line=child.start_point.row + 1,
                end_line=child.end_point.row + 1,
                context_header=header,
            ))
        else:
            child_name = _symbol_name(child, source) or parent_symbol
            chunks.extend(_split_large_node(
                child, source, language, config, max_chars, file_path, child_name,
            ))
    return chunks


def extract_chunks(
    tree: ts.Tree,
    source: bytes,
    language: str,
    file_path: str = "",
    max_chars: int = 1500,
    min_chars: int = 100,
) -> list[CodeChunk]:
    """Extract code chunks from a parsed tree.

    Algorithm:
    1. Walk top-level nodes
    2. Small mergeable nodes (imports) get merged together
    3. Nodes within max_chars become a single chunk
    4. Nodes exceeding max_chars get recursively split at child boundaries
    """
    config = get_config(language)
    if config is None:
        return []

    root = tree.root_node
    chunks: list[CodeChunk] = []
    merge_buffer: list[ts.Node] = []
    merge_size = 0

    def _flush_merge_buffer() -> None:
        nonlocal merge_buffer, merge_size
        if not merge_buffer:
            return
        text = "\n".join(_node_text(n, source) for n in merge_buffer)
        chunks.append(CodeChunk(
            text=text,
            file_path=file_path,
            language=language,
            chunk_type="imports",
            start_line=merge_buffer[0].start_point.row + 1,
            end_line=merge_buffer[-1].end_point.row + 1,
            context_header=_build_context_header(file_path, "", ""),
        ))
        merge_buffer = []
        merge_size = 0

    for child in root.children:
        ntype = child.type
        text = _node_text(child, source)
        if not text.strip():
            continue

        # Mergeable nodes (imports, using directives, etc.)
        if ntype in config.merge_nodes:
            if merge_size + _node_size(child) > max_chars:
                _flush_merge_buffer()
            merge_buffer.append(child)
            merge_size += _node_size(child)
            continue

        # Flush any pending merge buffer before non-mergeable nodes
        _flush_merge_buffer()

        # Context nodes (e.g. namespaces) — recurse into their children
        if ntype in config.context_nodes:
            ctx_name = _symbol_name(child, source)
            for grandchild in child.children:
                gc_text = _node_text(grandchild, source)
                if not gc_text.strip():
                    continue
                if grandchild.type in config.top_level_nodes:
                    if _node_size(grandchild) <= max_chars:
                        sig = _extract_signature(grandchild, source, language)
                        name = _symbol_name(grandchild, source)
                        ctype = _classify_node(grandchild, config)
                        header = _build_context_header(file_path, ctx_name, sig)
                        chunks.append(CodeChunk(
                            text=gc_text,
                            file_path=file_path,
                            language=language,
                            chunk_type=ctype,
                            symbol_name=name,
                            parent_symbol=ctx_name,
                            signature=sig,
                            start_line=grandchild.start_point.row + 1,
                            end_line=grandchild.end_point.row + 1,
                            context_header=header,
                        ))
                    else:
                        chunks.extend(_split_large_node(
                            grandchild, source, language, config, max_chars,
                            file_path, ctx_name,
                        ))
            continue

        # Top-level or other nodes
        size = _node_size(child)
        if size <= max_chars:
            sig = _extract_signature(child, source, language) if ntype in config.top_level_nodes else ""
            name = _symbol_name(child, source)
            ctype = _classify_node(child, config)
            header = _build_context_header(file_path, "", sig)
            chunks.append(CodeChunk(
                text=text,
                file_path=file_path,
                language=language,
                chunk_type=ctype,
                symbol_name=name,
                signature=sig,
                start_line=child.start_point.row + 1,
                end_line=child.end_point.row + 1,
                context_header=header,
            ))
        else:
            name = _symbol_name(child, source)
            chunks.extend(_split_large_node(
                child, source, language, config, max_chars, file_path, name,
            ))

    # Final flush
    _flush_merge_buffer()

    return chunks


def chunk_file(
    path: Path,
    max_chars: int = 1500,
    min_chars: int = 100,
    language: str | None = None,
) -> list[CodeChunk]:
    """Parse and chunk a file in one call."""
    result = parse_file(path, language)
    if result is None:
        return []
    tree, source, lang = result
    return extract_chunks(tree, source, lang, file_path=str(path), max_chars=max_chars, min_chars=min_chars)
