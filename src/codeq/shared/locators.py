from __future__ import annotations

import re
from pathlib import Path

from codeq.shared.config import CTAGS, _METHOD_LOCATOR, _RESERVED_KEYWORDS
from codeq.shared.core import _parse_ctags_line, lang_of, run

def _regex_locate_method(file: str, name: str, lang: str) -> int | None:
    """Regex-based fallback locator for brace-lang class methods when ctags
    misses them. Returns the 1-based line of the first signature match
    (preferring indented / in-class hits over top-level hits), or None."""
    pat_tpl = _METHOD_LOCATOR.get(lang)
    if not pat_tpl:
        return None
    rx = re.compile(pat_tpl.format(name=re.escape(name)), re.MULTILINE)
    try:
        text = Path(file).read_text(errors="replace")
    except OSError:
        return None
    indented_hit: int | None = None
    lines = text.splitlines()
    for m in rx.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        if line_no - 1 < len(lines) and lines[line_no - 1].startswith((" ", "\t")):
            return line_no  # class body — preferred
        if indented_hit is None:
            indented_hit = line_no
    return indented_hit

def _regex_outline_methods(file: str, lang: str, skip_names: set[str]) -> list[tuple[int, str, str]]:
    """Regex sweep that finds all method signatures in a brace-lang file (used
    by outline when ctags misses them due to the generic-arg-field bug).
    Returns [(line, kind='method', name), ...] — does NOT include names in
    `skip_names` (used to avoid duplicating entries ctags DID return).

    Discriminates real method declarations from in-method function calls via
    two signal checks on the match line + immediate next lines:
      1. Return-type annotation IMMEDIATELY after the closing `)`: `): Word`
      2. Access modifier at the start of the line: `protected`/`private`/etc.
         OR `async <Name>` (typed async method shorthand).
    A bare `effect(() => {` call site has neither, so it's filtered out.
    """
    if lang not in ("typescript", "javascript", "java"):
        return []
    if lang in ("typescript", "javascript"):
        rx = re.compile(
            r"^[ \t]*(?:export\s+)?(?:async\s+)?"
            r"(?:\s*(?:public|private|protected|static|abstract|override|readonly|async)\s+)*"
            r"\*?\s*([A-Za-z_$][\w$]*)\s*(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*\(",
            re.MULTILINE,
        )
    else:  # java
        rx = re.compile(
            r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:\s*(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)*"
            r"(?:<[^>]+>\s+)?[\w<>\[\],?\s]+?\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*\(",
            re.MULTILINE,
        )
    try:
        text = Path(file).read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    return_re = re.compile(r"\)\s*:\s*[A-Za-z_$]")
    modifier_re = re.compile(
        r"^[ \t]*(?:public|private|protected|static|abstract|readonly)\s+"
    )
    async_re = re.compile(r"^[ \t]*async\s+[A-Za-z_$][\w$]*\s*\(")
    for m in rx.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        if line_no - 1 >= len(lines):
            continue
        line = lines[line_no - 1]
        if _brace_depth_before_line(lines, line_no) != 1:
            continue
        name = m.group(1)
        if name in _RESERVED_KEYWORDS:
            continue
        if name in skip_names:
            continue
        # Discrimination: real declaration has either a return-type annotation
        # immediately after the closing `)`, OR an access modifier at line-start,
        # OR an `async <Name>` shorthand. A plain function call has neither.
        sig_window = "\n".join(lines[line_no - 1:line_no + 4])
        is_decl = (
            return_re.search(sig_window) is not None
            or modifier_re.match(line) is not None
            or async_re.match(line) is not None
        )
        if not is_decl:
            continue
        skip_names.add(name)
        out.append((line_no, "method", name))
    return out


def _brace_depth_before_line(lines: list[str], line_no: int) -> int:
    """Approximate brace depth before a 1-based line number.

    This keeps TS/JS outline fallback focused on direct class/interface members:
    class methods sit at depth 1, while object-literal methods inside fields sit
    deeper and should not be promoted as class methods.
    """
    depth = 0
    for line in lines[:max(0, line_no - 1)]:
        for ch in line:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
    return depth

def _locate_line(file: str, name: str, kinds: set[str] | None = None) -> int | None:
    """Symbol start line via ctags, or None if not found. If `kinds` is given,
    only match ctags entries whose kind is in the set (e.g. {'class'} to locate a
    type declaration rather than a same-named constructor/method). For brace-langs,
    falls back to a regex signature scan when ctags fails (ctags 5.9.0 silently
    drops TS class members after generic-arg field initializers like `inject<T>(...)`)."""
    _, out, _ = run([CTAGS, "--fields=+Kzn", "-f", "-", file])
    for line in out.splitlines():
        p = _parse_ctags_line(line)
        if p and p[0] == name:
            if kinds is not None and p[2] not in kinds:
                continue
            try:
                return int(p[3])
            except ValueError:
                return None
    # Fallback for brace-langs (ctags TS/JS parser bug after generic-arg
    # field initializers). Cheap: only runs when ctags returns nothing.
    try:
        lang = lang_of(file, None)
    except SystemExit:
        return None
    if lang in ("typescript", "javascript", "java"):
        return _regex_locate_method(file, name, lang)
    return None
