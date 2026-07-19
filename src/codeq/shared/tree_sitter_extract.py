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

import bisect
import importlib.util
import re
from pathlib import Path
from typing import Any, Iterator, cast

from codeq.shared.config import EXT_LANG

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
            # `src` is bytes; node byte offsets are typed Any (optional dep)
            # but bytes.__getitem__(slice[Any, Any]) returns bytes, so .decode
            # is correctly inferred to return str here. No cast needed.
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
            # child.text is bytes at runtime but typed as Any (optional dep).
            # Cast to silence mypy --no-any-return without losing precision
            # for the consumer (str | None is the declared return).
            text = cast(bytes, child.text)
            return text.decode("utf-8", "replace")
    return None


# ---------------------------------------------------------------------------
# Reference filtering — drop lexical hits inside comments / string literals
# ---------------------------------------------------------------------------

# tree-sitter node types that are COMMENT or STRING CONTAINERS per language.
# Verified empirically against tree-sitter-language-pack 1.12.5 (2026-07-18)
# by probing each grammar with NAME placed in line/block comment, string, and
# template literals. Only the CONTAINER node is listed: its byte range covers
# the match, so child fragment nodes (string_fragment / string_content / ...)
# need not be enumerated.
_COMMENT_STRING_NODE_TYPES: dict[str, frozenset[str]] = {
    "javascript": frozenset({"comment", "string", "template_string"}),
    "typescript": frozenset({"comment", "string", "template_string"}),
    "java": frozenset({"line_comment", "block_comment", "string_literal"}),
    "go": frozenset(
        {"comment", "interpreted_string_literal", "raw_string_literal", "rune_literal"}
    ),
    "rust": frozenset(
        {
            "line_comment",
            "block_comment",
            "string_literal",
            "raw_string_literal",
            "char_literal",
        }
    ),
}


def ts_filter_refs(name: str, ref_lines: list[str], lang: str) -> list[str]:
    """Drop REF_LINES whose symbol hit is inside a comment or string literal.

    Groups lines by source file, parses each once with tree-sitter, and keeps a
    line only when some word-boundary occurrence of NAME on it is NOT inside a
    comment/string node's byte range. Returns REF_LINES unchanged when
    tree-sitter is absent, the language has no comment/string table (python
    uses the AST path already; bash has no tree-sitter integration), or a file
    fails to read/parse — graceful, never worse than the lexical input.

    Why FILTER (not re-derive) refs from tree-sitter: identifier-vs-property-
    key classification varies per grammar, and a from-scratch walker risks
    losing member-access true positives (`obj.foo`). Filtering lexical output
    can only drop false positives (comment / string mentions), never true ones.
    """
    if not ref_lines or not ts_available():
        return ref_lines
    name_b = name.encode("utf-8")
    rx = re.compile(rb"\b" + re.escape(name_b) + rb"\b")
    cache: dict[str, set[int] | None] = {}
    out: list[str] = []
    for rl in ref_lines:
        m = re.match(r"^(.*?):(\d+):(.*)$", rl)
        if not m:
            out.append(rl)
            continue
        file, line_no = m.group(1), int(m.group(2))
        if file not in cache:
            cache[file] = _code_lines_for(name_b, rx, file, lang)
        code_lines = cache[file]
        if code_lines is None or line_no in code_lines:
            out.append(rl)
    return out


def _code_lines_for(
    name_b: bytes,
    rx: re.Pattern[bytes],
    file: str,
    lang_hint: str,
) -> set[int] | None:
    """1-based line numbers where NAME occurs as real code in FILE, or None
    when the file cannot be classified so the caller passes its lines through
    unchanged rather than silently dropping them.

    LANG_HINT is the caller's explicit language (may be "" — the CLI `refs`
    path passes lang=None for a mixed tree); when empty, the language is
    inferred from FILE's extension so each hit file is parsed with the
    matching grammar."""
    lang = lang_hint or _lang_of_file(file)
    if lang is None or lang not in _COMMENT_STRING_NODE_TYPES:
        return None  # python (AST path) / bash / unknown ext → passthrough
    try:
        src = Path(file).read_bytes()
    except OSError:
        return None
    parser = _parser_for(lang)
    if parser is None:
        return None
    bad_types = _COMMENT_STRING_NODE_TYPES[lang]
    tree = parser.parse(src)
    bad_ranges = _comment_string_ranges(tree.root_node, bad_types)
    line_starts = _line_starts(src)
    code_lines: set[int] = set()
    for m in rx.finditer(src):
        off = m.start()
        if any(s <= off < e for s, e in bad_ranges):
            continue
        code_lines.add(bisect.bisect_right(line_starts, off))
    return code_lines


def _lang_of_file(file: str) -> str | None:
    """tree-sitter lang for FILE from its extension, or None when unknown.
    Used to classify each hit file individually when the caller has no
    explicit language (the `refs` CLI path passes lang=None for mixed trees)."""
    ext = Path(file).suffix.lstrip(".")
    return EXT_LANG.get(ext)


def _comment_string_ranges(
    root: Any, bad_types: frozenset[str]
) -> list[tuple[int, int]]:
    """Byte [start, end) ranges of every comment/string node under ROOT.
    Descends only into non-bad nodes — a string's children are all inside its
    range, so pruning at the container avoids redundant inner ranges."""
    ranges: list[tuple[int, int]] = []
    stack: list[Any] = [root]
    while stack:
        n = stack.pop()
        if n.type in bad_types:
            ranges.append((n.start_byte, n.end_byte))
        else:
            stack.extend(n.children)
    return ranges


def _line_starts(src: bytes) -> list[int]:
    """Cumulative byte offset of the start of each line (line 1 starts at 0).
    `bisect_right(starts, offset)` yields the 1-based line number of OFFSET.
    Iterates bytes directly so a trailing no-newline line is handled correctly."""
    starts = [0]
    for i, b in enumerate(src):
        if b == 0x0A:  # newline
            starts.append(i + 1)
    return starts
