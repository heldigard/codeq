"""Import-parsing helpers for the `deps` feature.

ES-module (JS/TS) statements are flattened (multi-line barrel/harness imports
collapsed to one logical line) and their named bindings surfaced
(`from m ( a, b )`) for parity with Python's `deps` output. Extracted from
`command.py` to respect the per-module line budget.
"""

from __future__ import annotations

import re
from pathlib import Path

from codeq.shared.config import IMPORT_PATTERNS


def _esm_complete(acc: str) -> bool:
    """True when accumulated ES-module statement text is complete: braces
    balanced AND a terminator present (`from '...'`, `;`, `require(`, or
    dynamic `import(`). Stops `_esm_flatten` line accumulation."""
    if acc.count("{") - acc.count("}") > 0:
        return False
    return bool(
        re.search(r"from\s+['\"]", acc)
        or ";" in acc
        or re.search(r"\brequire\s*\(", acc)
        or re.search(r"\bimport\s*\(", acc)
    )


def _esm_flatten(text: str) -> list[tuple[int, str]]:
    """Collapse multi-line ES module import/export statements into single
    logical lines, each tagged with its START line number (1-based). Lines
    that do not begin an import/export statement pass through verbatim; a
    statement that already terminates on its first line is returned as-is.

    Why: `import { a, b, ... } from './harness'` with one name per line is the
    barrel/harness pattern; the line-anchored regex in `_re_deps` saw only the
    `import {` opener and dropped the whole dependency. Flattening first lets
    the existing IMPORT_PATTERNS match against the full statement."""
    out: list[tuple[int, str]] = []
    lines = text.splitlines()
    start_re = re.compile(r"^\s*(?:import|export)\b")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not start_re.match(line):
            out.append((i + 1, line))
            i += 1
            continue
        if _esm_complete(line):
            out.append((i + 1, line))
            i += 1
            continue
        logical, nxt = _esm_accumulate(lines, i)
        out.append((i + 1, logical))
        i = nxt
    return out


def _esm_accumulate(lines: list[str], start: int) -> tuple[str, int]:
    """Gather lines from START until a multi-line ES-module statement completes
    (per `_esm_complete`). Returns (joined_logical_line, index_after_statement)."""
    buf = [lines[start]]
    j = start + 1
    while j < len(lines):
        buf.append(lines[j])
        if _esm_complete(" ".join(buf)):
            break
        j += 1
    return " ".join(buf), j + 1


def _esm_bindings(line: str) -> str | None:
    """Named bindings of a (flattened) ES-module statement, comma-joined, or
    None for forms with no named-import list (side-effect, CommonJS, dynamic).
    Mirrors Python's `deps` output (`from m ( a, b )`) so the controller can
    answer "which subset of this barrel does this file use" without a whole-
    file read."""
    parts: list[str] = []
    # default binding sitting before braces: `import X from` / `import X, {`
    m_def = re.match(r"\s*import\s+(\w+)\s*(?:,|from\b)", line)
    if m_def:
        parts.append(m_def.group(1))
    # named braces: `{ a, b as c }`
    m_braces = re.search(r"\{([^{}]*)\}", line)
    if m_braces:
        parts.extend(p.strip() for p in m_braces.group(1).split(",") if p.strip())
    if parts:
        return ", ".join(parts)
    # namespace: `import * as ns` / `export * as ns`
    m_ns = re.search(r"\*\s+as\s+(\w+)", line)
    if m_ns:
        return f"* as {m_ns.group(1)}"
    # wildcard re-export: `export * from`
    if re.search(r"\bexport\s+\*\s+from\b", line):
        return "*"
    return None


def _first_module(patterns: list[re.Pattern[str]], line: str) -> str | None:
    """First import-spec match group (the module path) across PATTERNS, or None."""
    for pat in patterns:
        m = pat.search(line)
        if m:
            return m.group(1)
    return None


def _esm_dep_row(
    patterns: list[re.Pattern[str]], ln: int, logical: str
) -> tuple[int, str, str] | None:
    """One flattened JS/TS statement → deps row, or None if it is not an
    import. Surfaces named bindings (`from m ( a, b )`) for Python parity."""
    mod = _first_module(patterns, logical)
    if mod is None:
        return None
    names = _esm_bindings(logical)
    kind = "from" if names else "import"
    detail = f"{mod} ( {names} )" if names else mod
    return (ln, kind, detail)


def _esm_dep_rows(
    patterns: list[re.Pattern[str]], text: str
) -> list[tuple[int, str, str]]:
    """JS/TS dep rows: flatten multi-line statements, surface named bindings."""
    rows: list[tuple[int, str, str]] = []
    for ln, logical in _esm_flatten(text):
        row = _esm_dep_row(patterns, ln, logical)
        if row:
            rows.append(row)
    return rows


def _line_dep_rows(
    patterns: list[re.Pattern[str]], text: str
) -> list[tuple[int, str, str]]:
    """Line-anchored dep rows for languages without multi-line flattening."""
    rows: list[tuple[int, str, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        mod = _first_module(patterns, line)
        if mod is not None:
            rows.append((i, "import", mod))
    return rows


def re_deps(file: str, lang: str) -> list[tuple[int, str, str]] | None:
    """Non-Python imports via per-language regex. JS/TS statements are first
    flattened (multi-line barrel imports collapsed) and their named bindings
    surfaced (`from m ( a, b )`) for Python parity; other languages stay
    line-anchored as before."""
    patterns = IMPORT_PATTERNS.get(lang, [])
    if not patterns:
        return None
    try:
        text = Path(file).read_text(errors="replace")
    except OSError:
        return None
    if lang in ("javascript", "typescript"):
        rows = _esm_dep_rows(patterns, text)
    else:
        rows = _line_dep_rows(patterns, text)
    return rows or None
