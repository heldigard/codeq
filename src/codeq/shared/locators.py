from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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


def _regex_outline_methods(
    file: str, lang: str, skip_names: set[str]
) -> list[tuple[int, str, str]]:
    """Regex sweep that finds all method signatures in a brace-lang file (used
    by outline when ctags misses them due to the generic-arg-field bug).
    Returns [(line, kind='method', name), ...] — does NOT include names in
    `skip_names` (used to avoid duplicating entries ctags DID return)."""
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
    depths = _brace_depth_prefix(lines)
    out: list[tuple[int, str, str]] = []
    return_re = re.compile(r"\)\s*:\s*[A-Za-z_$]")
    modifier_re = re.compile(
        r"^[ \t]*(?:public|private|protected|static|abstract|readonly)\s+"
    )
    async_re = re.compile(r"^[ \t]*async\s+[A-Za-z_$][\w$]*\s*\(")
    ctx = {
        "text": text,
        "lines": lines,
        "depths": depths,
        "return_re": return_re,
        "modifier_re": modifier_re,
        "async_re": async_re,
    }
    for m in rx.finditer(text):
        hit = _try_outline_match(m, ctx, skip_names)
        if hit:
            skip_names.add(hit[1])
            out.append(hit)
    return out


def _try_outline_match(
    m: re.Match[str], ctx: dict[str, Any], skip_names: set[str]
) -> tuple[int, str, str] | None:
    """Process one regex match for _regex_outline_methods. Returns (line, name) or None.

    Line is derived from m.start(1) (the captured method NAME), not m.start():
    the type group's char class includes \\s, so a match can anchor on a
    preceding blank line and m.start() would point there — mis-numbering the
    method (TS) or dropping it entirely (Java, whose modifier/return checks
    then read the blank line)."""
    line_no = ctx["text"].count("\n", 0, m.start(1)) + 1
    if line_no - 1 >= len(ctx["lines"]) or ctx["depths"][line_no - 1] != 1:
        return None
    name = m.group(1)
    if name in _RESERVED_KEYWORDS or name in skip_names:
        return None
    line = ctx["lines"][line_no - 1]
    sig_window = "\n".join(ctx["lines"][line_no - 1 : line_no + 4])
    ret = ctx["return_re"].search(sig_window)
    mod = ctx["modifier_re"].match(line)
    asy = ctx["async_re"].match(line)
    if not (ret or mod or asy):
        return None
    return (line_no, "method", name)


def _skip_block(line: str, i: int, state: dict[str, bool]) -> int:
    """Advance one char inside a block comment; clear state at the closing `*/`."""
    if line[i] == "*" and i + 1 < len(line) and line[i + 1] == "/":
        state["in_block"] = False
        return i + 2
    return i + 1


def _skip_str(line: str, i: int, in_str: str) -> tuple[int, str | None]:
    """Advance one char inside a string literal (honoring `\\` escapes). Closes
    the string (returns None) when the matching quote is reached."""
    if line[i] == "\\":
        return i + 2, in_str
    if line[i] == in_str:
        return i + 1, None
    return i + 1, in_str


def _scan_braces(line: str, state: dict[str, bool]) -> tuple[int, bool]:
    """Count braces in LINE ignoring string/char/template literals, // line
    comments, and /* */ block comments. STATE key 'in_block' carries block-
    comment context across lines (mutated in place). Returns (net, saw_open).

    Why: a `}` in a comment or string (`getLogger("}")`, `// close }`) used to
    truncate body/class extraction and corrupt outline depth. Residual limit:
    JS/TS regex literals containing braces are not recognized as regex (rare)."""
    opens = 0
    closes = 0
    in_str: str | None = None
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if state["in_block"]:
            i = _skip_block(line, i, state)
            continue
        if in_str is not None:
            i, in_str = _skip_str(line, i, in_str)
            continue
        if c in ('"', "'", "`"):
            in_str = c
            i += 1
        elif c == "/" and i + 1 < n and line[i + 1] == "/":
            break  # line comment — rest of line is not code
        elif c == "/" and i + 1 < n and line[i + 1] == "*":
            state["in_block"] = True
            i += 2
        elif c == "{":
            opens += 1
            i += 1
        elif c == "}":
            closes += 1
            i += 1
        else:
            i += 1
    return opens - closes, opens > 0


def _brace_depth_prefix(lines: list[str]) -> list[int]:
    """Compute brace depth at the START of each line (prefix-sum).

    Returns a list where result[i] is the depth before line i (0-indexed).
    result[0] = 0 (depth before the first line). This is O(N) total and
    allows O(1) lookup per line, replacing the old O(N*L) per-call approach.
    Brace-aware (strings/comments skipped) so a `}` in a comment or literal
    does not corrupt the depth map used by outline."""
    depths = [0]
    depth = 0
    state: dict[str, bool] = {"in_block": False}
    for line in lines:
        net, _ = _scan_braces(line, state)
        depth = max(0, depth + net)
        depths.append(depth)
    return depths


def _lombok_member_line(file: str, name: str) -> int | None:
    """Line of a Lombok-generated member named NAME in FILE, or None.

    Lombok-injected methods (getId/isActive/builder/…) are absent from source,
    so ctags cannot locate them; this returns the annotation line instead.
    Extracted from _locate_line to keep nesting ≤ 3."""
    from codeq.shared.lombok import detect_lombok_members

    return next((m.line for m in detect_lombok_members(file) if m.name == name), None)


def _locate_line(file: str, name: str, kinds: set[str] | None = None) -> int | None:
    """Symbol start line via ctags, or None if not found. If `kinds` is given,
    only match ctags entries whose kind is in the set (e.g. {'class'} to locate a
    type declaration rather than a same-named constructor/method). For brace-langs,
    falls back to a regex signature scan when ctags fails (ctags 5.9.0 silently
    drops TS class members after generic-arg field initializers like `inject<T>(...)`)."""
    _, out, _ = run([CTAGS, "--fields=+Kzn", "-f", "-", file])
    for line in out.splitlines():
        p = _parse_ctags_line(line)
        if not p or p[0] != name:
            continue
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
    if lang not in ("typescript", "javascript", "java"):
        return None
    if lang == "java":
        lombok_line = _lombok_member_line(file, name)
        if lombok_line is not None:
            return lombok_line
    return _regex_locate_method(file, name, lang)
