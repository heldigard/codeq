"""Optional tree-sitter body extraction for brace-langs.

When the `tree-sitter` + `tree-sitter-language-pack` packages are importable,
this module provides AST-exact body extraction for JS/TS/Java/Go/Rust. It is
tried BEFORE the brace-count heuristic in `_raw_body` / `_class_body`, and
degrades gracefully — when tree-sitter is absent the brace-count path runs
unchanged.

Why tree-sitter over the existing brace-count path: `_scan_braces` (in
`locators.py`) already skips strings, char literals, template literals, and
line/block comments. Its one residual blind spot is **regex literals containing
braces** (`const re = /a}b/`) — an unbalanced `}` inside a regex truncates the
body. tree-sitter's grammar parses regex literals correctly, so its span is
exact regardless of lexical ambiguity. It also removes the heuristic nature
entirely (true AST vs brace counting).

Usage:
    from codeq.shared.tree_sitter_extract import ts_available, ts_body
    if ts_available():
        body = ts_body(name, file, lang)  # None if not found / unsupported lang
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Iterator

# tree-sitter node types that DECLARE a function/method body, per language.
# Verified against tree-sitter-language-pack 1.12 (2026-07-04) by probing each
# grammar. `name` field types follow in `_NAME_FIELD_TYPES`.
_FUNC_NODE_TYPES: dict[str, frozenset[str]] = {
    "javascript": frozenset(
        {"function_declaration", "method_definition", "generator_function_declaration"}
    ),
    "typescript": frozenset(
        {"function_declaration", "method_definition", "generator_function_declaration"}
    ),
    "java": frozenset({"method_declaration", "constructor_declaration"}),
    "go": frozenset({"function_declaration", "method_declaration"}),
    "rust": frozenset({"function_item"}),
}

# tree-sitter node types that DECLARE a type (class/interface/struct/trait/enum).
_TYPE_NODE_TYPES: dict[str, frozenset[str]] = {
    "javascript": frozenset({"class_declaration"}),
    "typescript": frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "type_alias_declaration",
        }
    ),
    "java": frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
        }
    ),
    # Go wraps each type in a `type_spec` inside a `type_declaration`; match on
    # `type_spec` directly so its field_identifier name is reachable.
    "go": frozenset({"type_spec"}),
    "rust": frozenset({"struct_item", "enum_item", "trait_item"}),
}

# Node types that hold the DECLARED identifier (the symbol name). Differs per
# grammar: Go method/type names are `field_identifier`, TS/Java/Rust type
# names are `type_identifier`, most others are `identifier`.
_NAME_FIELD_TYPES = frozenset({"identifier", "type_identifier", "field_identifier"})

# Cache parsers per language (parsing is the hot path; language setup is not).
_parsers: dict[str, object] = {}


def ts_available() -> bool:
    """True when tree-sitter + the language pack are installed. Uses
    `importlib.util.find_spec` (not a try-import) so there is no unused-import
    artifact for the type-checker to flag on this optional-dep path."""
    return (
        importlib.util.find_spec("tree_sitter") is not None
        and importlib.util.find_spec("tree_sitter_language_pack") is not None
    )


def ts_body(name: str, file: str, lang: str, want_type: bool = False) -> str | None:
    """AST-exact body of symbol NAME in FILE for LANG, or None.

    Walks the parsed tree for a node whose type is in the language's function
    (or type, if `want_type`) set AND whose declared name equals NAME, then
    returns that node's source span. Returns None when tree-sitter is absent,
    the language is unsupported, the file is unreadable, or no matching node
    exists (caller falls back to the brace-count path)."""
    parser = _parser_for(lang)
    if parser is None:
        return None
    try:
        src = Path(file).read_bytes()
    except OSError:
        return None
    tree = parser.parse(src)
    types = (
        _TYPE_NODE_TYPES.get(lang, frozenset())
        if want_type
        else _FUNC_NODE_TYPES.get(lang, frozenset())
    )
    if not types:
        return None
    for node in _walk(tree.root_node):
        if node.type not in types:
            continue
        if _declared_name(node) == name:
            return src[node.start_byte : node.end_byte].decode("utf-8", "replace")
    return None


def _parser_for(lang: str) -> Any | None:
    """Cached tree-sitter Parser for LANG, or None if the language is not in
    the pack. Uses `Parser(get_language(lang))` (the tree-sitter 0.26 API);
    `get_parser` from the language pack returns an incompatible object."""
    if lang in _parsers:
        return _parsers[lang]
    p = _build_parser(lang)
    _parsers[lang] = p
    return p


def _build_parser(lang: str) -> Any | None:
    """Construct a Parser for LANG. Returns None on any setup failure (unknown
    lang, ABI mismatch) so the caller degrades to the brace-count path. `Any`
    because tree-sitter is an optional dep the type-checker may not resolve."""
    try:
        from tree_sitter import Parser
        from tree_sitter_language_pack import get_language

        return Parser(get_language(lang))
    except Exception:
        return None


def _walk(node: Any) -> Iterator[Any]:
    """Yield NODE then recurse into its children — a pre-order traversal."""
    yield node
    for child in node.children:
        yield from _walk(child)


def _declared_name(node: Any) -> str | None:
    """The declared identifier of a declaration NODE, or None.

    Searches direct children for a name-typed node. Handles Go's `type_spec`
    (whose name is a direct `field_identifier` child) and Java/TS/Rust types
    (`type_identifier`). Does NOT recurse — the name is always a direct child
    in every grammar probed."""
    for child in node.children:
        if child.type in _NAME_FIELD_TYPES:
            return child.text.decode("utf-8", "replace")
    return None
