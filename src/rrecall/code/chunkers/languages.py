"""Tree-sitter language detection and configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter as ts


@dataclass
class LanguageConfig:
    """Configuration for how to chunk a specific language."""
    language: ts.Language
    top_level_nodes: list[str]
    merge_nodes: list[str] = field(default_factory=list)
    context_nodes: list[str] = field(default_factory=list)


def _load_configs() -> dict[str, LanguageConfig]:
    """Build the language config map. Lazy-loaded to avoid import cost."""
    import tree_sitter_c_sharp as ts_csharp
    import tree_sitter_css as ts_css
    import tree_sitter_html as ts_html
    import tree_sitter_python as ts_python
    import tree_sitter_typescript as ts_typescript

    return {
        "python": LanguageConfig(
            language=ts.Language(ts_python.language()),
            top_level_nodes=[
                "class_definition", "function_definition", "decorated_definition",
            ],
            merge_nodes=["import_statement", "import_from_statement"],
        ),
        "csharp": LanguageConfig(
            language=ts.Language(ts_csharp.language()),
            top_level_nodes=[
                "class_declaration", "struct_declaration", "interface_declaration",
                "enum_declaration", "record_declaration", "method_declaration",
                "property_declaration",
            ],
            merge_nodes=["using_directive"],
            context_nodes=["namespace_declaration"],
        ),
        "typescript": LanguageConfig(
            language=ts.Language(ts_typescript.language_typescript()),
            top_level_nodes=[
                "class_declaration", "function_declaration", "lexical_declaration",
                "export_statement", "interface_declaration", "type_alias_declaration",
            ],
            merge_nodes=["import_statement"],
        ),
        "tsx": LanguageConfig(
            language=ts.Language(ts_typescript.language_tsx()),
            top_level_nodes=[
                "class_declaration", "function_declaration", "lexical_declaration",
                "export_statement", "interface_declaration", "type_alias_declaration",
            ],
            merge_nodes=["import_statement"],
        ),
        "html": LanguageConfig(
            language=ts.Language(ts_html.language()),
            top_level_nodes=["element", "script_element", "style_element"],
            merge_nodes=["doctype"],
        ),
        "css": LanguageConfig(
            language=ts.Language(ts_css.language()),
            top_level_nodes=["rule_set", "media_statement", "keyframes_statement"],
            merge_nodes=["import_statement", "charset_statement"],
        ),
    }


_configs: dict[str, LanguageConfig] | None = None


def get_configs() -> dict[str, LanguageConfig]:
    """Return the language config map, loading on first call."""
    global _configs
    if _configs is None:
        _configs = _load_configs()
    return _configs


# Extension → language name
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".cs": "csharp",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
}


def detect_language(path: Path | str) -> str | None:
    """Detect language from file extension. Returns None if unsupported."""
    suffix = Path(path).suffix.lower()
    return EXTENSION_MAP.get(suffix)


def get_config(language: str) -> LanguageConfig | None:
    """Get the config for a language name."""
    return get_configs().get(language)


def get_parser(language: str) -> ts.Parser | None:
    """Create a parser for the given language."""
    cfg = get_config(language)
    if cfg is None:
        return None
    parser = ts.Parser(cfg.language)
    return parser
