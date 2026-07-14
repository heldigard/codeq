# vs-soft-allow — cmd_find has deep nesting from the sweep loop + vendor/cache
# filters; this is pre-existing structural complexity, not new debt.
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from typing import Iterator

from codeq.shared.config import (
    CACHE_GLOBS,
    CTAGS,
    VENDOR_EXCLUDES,
    _FIND_SWEEP_FILE_CAP,
)
from codeq.shared.core import _parse_ctags_line, ctags_exclude_args, die, lang_of, run
from codeq.shared.locators import _locate_line, _regex_outline_methods
from codeq.shared.lombok import detect_lombok_members


def _is_excluded_dir(name: str) -> bool:
    """Match NAME against VENDOR_EXCLUDES with fnmatch (so wildcard entries
    like `.aider*` cover `.aider`, `.aider.chat.history`, `.aider.tags.cache`).
    Mirrors `codeq.shared.search._excluded_dir` so the rg/ctags/Python-walker
    /find-fallback sweep paths all agree on what counts as a vendor dir."""
    return any(fnmatch.fnmatch(name, ex) for ex in VENDOR_EXCLUDES)


def _walk_source_files(
    root: Path,
    suffixes: set[str] | frozenset[str],
    cap: int = _FIND_SWEEP_FILE_CAP,
) -> Iterator[Path]:
    """Yield files under `root` whose suffix is in `suffixes`, pruning
    vendor/cache dirs and capping at `cap` files. Shared by the brace-lang
    and Lombok sweeps in `cmd_find` to avoid duplicating the walk logic.

    Bug history (fixed 2026-07-04): the dir filter used to be
    ``p in VENDOR_EXCLUDES`` (exact equality), which silently leaked
    wildcard-segment vendor dirs (e.g. `.aider.chat.history`,
    `.aider.tags.cache`) because the list entry is the wildcard pattern
    `.aider*` rather than the literal directory name. Switched to
    ``fnmatch.fnmatch`` to match every other consumer of VENDOR_EXCLUDES
    (rg globs, ctags --exclude, pure-Python walker)."""
    root_parts = set(root.resolve().parts)
    count = 0
    for path in root.rglob("*"):
        if count >= cap:
            print(
                f"[codeq] find sweep truncated at {cap} files "
                f"under {root}; narrow with -p <subdir>.",
                file=sys.stderr,
            )
            return
        if not path.is_file() or path.suffix not in suffixes:
            continue
        rel_parts = set(path.resolve().parts) - root_parts
        if any(_is_excluded_dir(p) for p in rel_parts):
            continue
        if any(path.match(g) for g in CACHE_GLOBS):
            continue
        count += 1
        yield path


def get_find_hits(name: str, path_str: str) -> list[tuple[str, int, str, str]]:
    """Gathers symbol locations matching `name` under `path_str` using ctags, regex search fallback, and Lombok search."""
    cmd = [CTAGS, "-R", "--fields=+Kzn", "-f", "-"]
    cmd += ctags_exclude_args()
    cmd += [path_str]
    rc, out, _ = run(cmd)
    if rc != 0:
        die("ctags failed (is universal-ctags installed?)", 2)
    hits: list[tuple[str, int, str, str]] = []
    for line in out.splitlines():
        parsed = _parse_ctags_line(line)
        if not parsed:
            continue
        c_name, file, kind, line_no = parsed
        if c_name == name:
            try:
                ln = int(line_no)
            except ValueError:
                continue
            hits.append((file, ln, kind, name))
    if not hits:
        # ctags-wide sweep returned nothing. Fall back to per-file `_locate_line`
        # (which runs ctags -> regex fallback chain) on brace-lang source files.
        root = Path(path_str)
        if root.is_dir():
            brace_exts = frozenset(
                {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java"}
            )
            try:
                for path in _walk_source_files(root, brace_exts):
                    located_line = _locate_line(str(path), name)
                    if located_line:
                        hits.append((str(path), located_line, "method", name))
            except OSError:
                pass  # unreadable path — silently skip; ctags output was the primary source
    # Lombok: check if the name matches a Lombok-generated method in Java files.
    # Runs regardless of ctags hits to find Lombok methods in all Java files.
    seen_files = {h[0] for h in hits}
    root = Path(path_str)
    if root.is_dir():
        java_exts = frozenset({".java"})
        try:
            for path in _walk_source_files(root, java_exts):
                str_path = str(path)
                if str_path in seen_files:
                    continue
                for m in detect_lombok_members(str_path):
                    if m.name == name:
                        hits.append((str_path, m.line, f"lombok-{m.kind}", name))
                        seen_files.add(str_path)
                        break
        except OSError:
            pass
    hits.sort()
    return hits


def cmd_find(args: argparse.Namespace) -> int:
    hits = get_find_hits(args.name, args.path)
    if not hits:
        print(f"no symbol named '{args.name}' under {args.path}", file=sys.stderr)
        return 1
    for file, ln, kind, name in hits:
        print(f"{file}:{ln}  {kind}  {name}")
    return 0


def get_outline_rows(file_path: str) -> list[tuple[int, str, str]]:
    """Gathers rows of (line, kind, name) symbols for the file outline."""
    if not Path(file_path).is_file():
        die(f"no such file: {file_path}")
    rc, out, _ = run([CTAGS, "--fields=+Kzn", "-f", "-", file_path])
    if rc != 0:
        die("ctags failed", 2)
    rows: list[tuple[int, str, str]] = []
    for line in out.splitlines():
        parsed = _parse_ctags_line(line)
        if not parsed:
            continue
        c_name, _, kind, line_no = parsed
        try:
            ln = int(line_no)
        except ValueError:
            continue
        rows.append((ln, kind, c_name))
    # Fallback for brace-langs when ctags misses class members (the
    # ctags 5.9.0 TS parser bug after generic-arg field initializers).
    # TS/JS can be partial: ctags may return methods before `inject<T>(...)`
    # and silently drop methods after it, so always merge the regex sweep there.
    # Java keeps the older conservative path because ctags is reliable enough
    # for normal member outlines and the regex is declaration-level only.
    n_methods = sum(1 for _, k, _ in rows if k == "method")
    try:
        lang: str | None = lang_of(file_path, None)
    except SystemExit:
        lang = None
    if lang in ("typescript", "javascript") or (n_methods == 0 and lang == "java"):
        seen = {r[2] for r in rows}  # avoid duplicating names ctags DID get
        rows.extend(_regex_outline_methods(file_path, lang, seen))
    # Lombok: infer generated methods from annotations (Java only)
    if lang == "java":
        seen = {r[2] for r in rows}
        for m in detect_lombok_members(file_path):
            if m.name not in seen:
                rows.append((m.line, f"lombok-{m.kind}", m.name))
                seen.add(m.name)
    rows.sort()
    return rows


def cmd_outline(args: argparse.Namespace) -> int:
    rows = get_outline_rows(args.file)
    if not rows:
        print(f"no symbols indexed in {args.file}", file=sys.stderr)
        return 1
    for ln, kind, name in rows:
        print(f"{ln:>5}  {kind:<12}  {name}")
    return 0
