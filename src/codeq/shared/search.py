"""Deterministic lexical search for codeq's `refs` / `rdeps` / `tags`.

Replaces the old `subprocess.run(["grep", ...])` calls. Why: the system
`grep` is not a stable target for a public CLI — it can be GNU grep, ugrep,
busybox, or BSD grep, and in some shells `grep` is itself a *function*
wrapping ugrep. That variance caused a real bug (ugrep returned `.mjs` under
`--include=*.ts`). Here we prefer a real `rg` binary when present; otherwise
a pure-Python walker. We NEVER fall back to the system `grep`, so behavior is
identical across GNU/ugrep/busybox/BSD environments.
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

from codeq.shared.config import FILE_EXCLUDES, VENDOR_EXCLUDES

# `_RG` caches the ripgrep path lookup: a path string, or False when absent.
_RG: str | bool | None = None


def rg_binary() -> str | None:
    """Real ripgrep binary on PATH (None if absent). `shutil.which` ignores
    shell functions/aliases, so this is the binary subprocess would invoke."""
    global _RG
    if _RG is None:
        _RG = shutil.which("rg") or False
    return _RG if isinstance(_RG, str) else None


def search_lexical(
    pattern: str,
    path: str,
    includes: list[str] | None = None,
    word: bool = True,
) -> list[str]:
    """Grep-style lexical search → `['file:line:text', ...]` lines.

    Uses ripgrep when a real binary exists (fast); otherwise a pure-Python
    walker (deterministic, no external tool). Excludes VENDOR_EXCLUDES dirs
    and FILE_EXCLUDES file globs. `word=True` matches on word boundaries
    (grep `-w` parity). `includes` are codeq `--include=*.ts` style globs;
    empty/None means all extensions."""
    includes = includes or []
    rg = rg_binary()
    if rg is not None:
        rows = _rg_search(rg, pattern, path, includes, word)
        if rows is not None:
            return rows
    return _py_search(pattern, path, includes, word)


def _rg_search(
    rg: str, pattern: str, path: str, includes: list[str], word: bool
) -> list[str] | None:
    """ripgrep invocation. Returns lines, or None to fall back to Python
    (only on a non-recoverable rg failure / unexpected exit code).

    Output format MUST stay `file:line:text` to match `_py_search` and the
    `file:line:text` contract documented on `search_lexical`. Do NOT add
    `-I`: in rg `-I` means `--no-filename` (it overrides `--with-filename`
    and silently drops the file prefix, breaking every consumer that splits
    on the first two `:`). rg skips binary files by default already, so the
    grep-style `-I` (ignore-binary) intent is moot here.

    `--fixed-strings` makes rg treat PATTERN as a literal (not regex), giving
    parity with `_py_search`'s `re.escape`. Without it, rg would match `a.b`
    against `aXb` (`.` = any char) — a false-positive source for callers
    that pass dotted symbol names like `MyClass.method`. `-F` composes with
    `-w` (literal pattern + word boundaries)."""
    cmd = [
        rg,
        "--line-number",
        "--with-filename",
        "--no-heading",
        "--color=never",
        "--no-ignore",
        "--fixed-strings",
    ]
    if word:
        cmd.append("-w")
    for ex in VENDOR_EXCLUDES:
        cmd += ["-g", f"!{ex}"]
    for ex in FILE_EXCLUDES:
        cmd += ["-g", f"!{ex}"]
    for inc in includes:
        glob = inc.split("=", 1)[1] if inc.startswith("--include=") else inc
        cmd += ["-g", glob]
    cmd += ["--", pattern, path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return None  # rg hung/missing → fall back to the pure-Python walker
    if proc.returncode not in (0, 1):  # 0 = matches, 1 = no matches
        return None
    return proc.stdout.splitlines()


def search_py_refs(name: str, path: str) -> list[str]:
    """Semantic Python references via the `ast` module → `['file:line:text']`.

    Matches only real `Name` / `Attribute` / import-alias nodes, so it is
    immune to the comment / string / keyword-argument-name false positives
    that `search_lexical` (word-boundary) produces. The definition line
    (`def name(...)` / `class name`) is naturally absent — `ast` does not
    emit a `Name` node for the declaration identifier, so no def-filter
    regex is needed on the caller side.

    Walks PATH with the same VENDOR_EXCLUDES / FILE_EXCLUDES pruning as the
    lexical search. Unparseable files contribute no rows (no crash). Returns
    rows sorted by file-then-line on a best-effort basis (walk order).

    Why ast (not rg) for python refs: rg cannot distinguish a call from a
    comment or a kwarg name without a parser; the `ast` module is in the
    stdlib, has no external dep, and already powers `body` / `outline` /
    `deps` — this is the same tool applied to the references problem. For
    non-python langs, `get_refs` keeps the lexical path (AST coverage of
    those langs would need tree-sitter, an optional future add).
    """
    root = Path(path)
    files = [root] if root.is_file() else _walk_files(root)
    out: list[str] = []
    for f in files:
        if f.suffix != ".py":
            continue
        out.extend(_py_refs_in_file(name, f))
    return out


def _py_refs_in_file(name: str, f: Path) -> list[str]:
    """AST refs for ONE python file. Returns rows in source order (line-num
    ascending), deduped per line (a `Name` and an `Attribute` on the same
    line yield a single row). Returns [] on syntax error / IO error so the
    caller's walk continues with the next file."""
    try:
        src = f.read_text(errors="replace")
        tree = ast.parse(src, filename=str(f))
    except (SyntaxError, OSError, ValueError):
        return []
    lines = src.splitlines()
    rows: list[str] = []
    seen: set[int] = set()
    matches: list[int] = []
    for node in ast.walk(tree):
        lineno = _py_ref_lineno(node, name)
        if lineno is not None and lineno not in seen:
            seen.add(lineno)
            matches.append(lineno)
    for lineno in sorted(set(matches)):
        text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        rows.append(f"{f}:{lineno}:{text}")
    return rows


def _py_ref_lineno(node: ast.AST, name: str) -> int | None:
    """Line of NODE if it is a reference to NAME, else None.

    - `ast.Name(id=name)` — bare identifier reference (`foo`, `foo()`).
    - `ast.Attribute(attr=name)` — member access (`obj.foo`).
    - `ast.Import` / `ast.ImportFrom` — an `alias` whose imported name or
      final segment or asname equals NAME. `from m import foo`,
      `import pkg.foo`, and `from m import foo as bar` all count (the
      symbol enters this module here).

    `keyword.arg` (kwarg names in `bar(foo=1)`) is a plain string on the
    `keyword` node, NOT an `ast.Name`, so it is naturally excluded — that
    is the false positive the AST path eliminates vs lexical."""
    if isinstance(node, ast.Name):
        return node.lineno if node.id == name else None
    if isinstance(node, ast.Attribute):
        return node.lineno if node.attr == name else None
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _import_alias_lineno(node, name)
    return None


def _import_alias_lineno(node: ast.AST, name: str) -> int | None:
    """Line of an `import` / `from ... import` statement that binds NAME.
    Matched when the imported name, its final dotted segment, or its asname
    equals NAME. Extracted from `_py_ref_lineno` to keep nesting shallow
    (the for+if branch would otherwise push depth past the slice budget)."""
    for alias in getattr(node, "names", []):
        if (
            alias.name == name
            or alias.name.endswith("." + name)
            or alias.asname == name
        ):
            lineno = getattr(node, "lineno", 0)
            return lineno or None
    return None


def _py_search(pattern: str, path: str, includes: list[str], word: bool) -> list[str]:
    """Pure-Python fallback: walk PATH, skip vendor/file excludes and binary
    files, match word-boundary PATTERN, return grep-style lines."""
    inc_globs = [
        i.split("=", 1)[1] if i.startswith("--include=") else i for i in includes
    ]
    rx = re.compile(
        (r"\b" if word else "") + re.escape(pattern) + (r"\b" if word else "")
    )
    root = Path(path)
    files = [root] if root.is_file() else _walk_files(root)
    out: list[str] = []
    for f in files:
        out.extend(_py_search_file(f, inc_globs, rx))
    return out


def _py_search_file(f: Path, inc_globs: list[str], rx: re.Pattern[str]) -> list[str]:
    """Match RX in a single file, honoring extension globs and skipping binary
    / unreadable files. Extracted from `_py_search` to keep nesting shallow."""
    if inc_globs and not any(fnmatch.fnmatch(f.name, g) for g in inc_globs):
        return []
    try:
        text = f.read_text(errors="replace")
    except OSError:
        return []
    if "\x00" in text:
        return []  # binary file — grep -I parity
    return [
        f"{f}:{i}:{line}"
        for i, line in enumerate(text.splitlines(), 1)
        if rx.search(line)
    ]


def _walk_files(root: Path) -> Iterator[Path]:
    """Yield project files under ROOT, pruning VENDOR_EXCLUDES dirs in-place
    and FILE_EXCLUDES file globs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _excluded_dir(d)]
        yield from (Path(dirpath) / fn for fn in filenames if not _excluded_file(fn))


def _excluded_dir(name: str) -> bool:
    return any(fnmatch.fnmatch(name, ex) for ex in VENDOR_EXCLUDES)


def _excluded_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, ex) for ex in FILE_EXCLUDES)
