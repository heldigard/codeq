from __future__ import annotations

import json
from pathlib import Path

from codeq.shared.config import (
    ASTGREP,
    BODY_PATTERNS,
    BRACE_LANGS,
    CLASS_BODY_PATTERNS,
    TYPE_KINDS,
)
from codeq.shared.core import run
from codeq.shared.locators import _locate_line


def _astgrep_body(pattern: str, lang: str, file: str) -> str | None:
    """Return clean matched-node text (via --json) or None."""
    rc, out, _ = run([ASTGREP, "run", "-p", pattern, "--lang", lang, "--json", file])
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    matches = data if isinstance(data, list) else data.get("matches", [])
    for m in matches:
        text = m.get("text") if isinstance(m, dict) else None
        if text:
            return text.rstrip("\n")
    return None


def _py_body(file: str, name: str, only_class: bool = False) -> str | None:
    """Exact Python def/class body via the ast module — handles methods inside
    classes, decorators, and the precise end line. More accurate than ast-grep
    for Python (which misses nested methods). If `only_class`, match ClassDef
    only (used by the `class` subcommand)."""
    import ast as _ast

    try:
        src = Path(file).read_text(errors="replace")
        tree = _ast.parse(src)
    except (SyntaxError, OSError):
        return None
    lines = src.splitlines()
    want = (
        _ast.ClassDef
        if only_class
        else (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)
    )
    for node in _ast.walk(tree):
        if isinstance(node, want) and node.name == name:
            deco = node.decorator_list
            start = deco[0].lineno if deco else node.lineno
            end = node.end_lineno or node.lineno
            return "\n".join(lines[start - 1 : end])
    return None


def _brace_extract(
    file: str, name: str | None = None, start: int | None = None
) -> str | None:
    """Brace-lang body (method, top-level, or class) via ctags locate + brace
    counting. Fallback for nodes ast-grep cannot bind as a single pattern (TS/JS
    class methods, Java constructors, Java/Go/Rust class/struct decls). If
    `start` is given, brace-count from that line directly (used by the `class`
    subcommand after locating the type-decl line). Approximate: braces inside
    strings/comments are not skipped (rare in real bodies)."""
    if start is None:
        start = _locate_line(file, name) if name else None
    if not start:
        return None
    try:
        lines = Path(file).read_text(errors="replace").splitlines()
    except OSError:
        return None
    return _brace_collect(lines, start)


def _brace_collect(lines: list[str], start: int) -> str | None:
    """Count braces from START line and return the body text. Extracted to
    keep nesting ≤ 3 inside the per-line loop."""
    depth = 0
    begun = False
    out: list[str] = []
    for i in range(start - 1, len(lines)):
        out.append(lines[i])
        depth += lines[i].count("{") - lines[i].count("}")
        begun = begun or "{" in lines[i]
        if begun and depth <= 0:
            return "\n".join(out)
    return "\n".join(out) if begun else None


def _raw_body(file: str, name: str, lang: str) -> str | None:
    """Full def/class/method text. Python via ast (exact, methods); brace-langs
    via ast-grep first (top-level, AST-exact) then brace-count (methods); other
    langs return None (caller falls back to the ctags line)."""
    if lang == "python":
        return _py_body(file, name)
    for pat in BODY_PATTERNS.get(lang, []):
        b = _astgrep_body(pat.replace("{N}", name), lang, file)
        if b:
            return b
    if lang in BRACE_LANGS:
        return _brace_extract(file, name)
    return None


def _sig_from_raw(raw: str, lang: str) -> str:
    """Header line(s) only. Python: stop at the line ENDING with ':' (the `):`
    of a multi-line sig, or the `:` of a single-line def — NOT an annotation
    colon mid-line). Brace-langs: stop at the line opening the body `{`."""

    def stop(ln: str) -> bool:
        return ln.rstrip().endswith(":") if lang == "python" else "{" in ln

    out: list[str] = []
    for ln in raw.splitlines():
        out.append(ln)
        if stop(ln):
            break
    return "\n".join(out).rstrip()


def _class_body(file: str, name: str, lang: str) -> str | None:
    """Full class/type-declaration body. Python via ast (ClassDef, exact);
    TS/JS via ast-grep class pattern (AST-exact); Java/Go/Rust via brace-count
    from the ctags type-decl line (ast-grep class/struct patterns do not bind
    there). Returns None if no type named `name` is found."""
    if lang == "python":
        return _py_body(file, name, only_class=True)
    for pat in CLASS_BODY_PATTERNS.get(lang, []):
        b = _astgrep_body(pat.replace("{N}", name), lang, file)
        if b:
            return b
    if lang in BRACE_LANGS:
        start = _locate_line(file, name, kinds=TYPE_KINDS)
        if start:
            return _brace_extract(file, start=start)
    return None
