from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codeq.shared.config import CACHE_GLOBS, CTAGS, VENDOR_EXCLUDES, _FIND_SWEEP_FILE_CAP
from codeq.shared.core import _parse_ctags_line, ctags_exclude_args, die, lang_of, run
from codeq.shared.locators import _locate_line, _regex_outline_methods

def cmd_find(args: argparse.Namespace) -> int:
    cmd = [CTAGS, "-R", "--fields=+Kzn", "-f", "-"]
    cmd += ctags_exclude_args()
    cmd += [args.path]
    rc, out, _ = run(cmd)
    if rc != 0:
        die("ctags failed (is universal-ctags installed?)", 2)
    hits: list[tuple[str, int, str, str]] = []
    for line in out.splitlines():
        parsed = _parse_ctags_line(line)
        if not parsed:
            continue
        name, file, kind, line_no = parsed
        if name == args.name:
            try:
                ln = int(line_no)
            except ValueError:
                continue
            hits.append((file, ln, kind, name))
    if not hits:
        # ctags-wide sweep returned nothing. Fall back to per-file `_locate_line`
        # (which runs ctags -> regex fallback chain) on brace-lang source files.
        # Only runs when ctags found nothing — fast path for the common case.
        # Skip vendor dirs RELATIVE to root (not the root itself) — `tmp`/`temp`
        # appear in VENDOR_EXCLUDES for ctags-wide legacy reasons but a user-supplied
        # `-p /tmp/myproj` root should still walk its contents.
        # Bound at _FIND_SWEEP_FILE_CAP files so a huge root (e.g. `-p /`) doesn't
        # trigger runaway recursion.
        walker_exts = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java")
        root = Path(args.path)
        if root.is_dir():
            try:
                root_parts = set(root.resolve().parts)
                files_seen = 0
                for path in root.rglob("*"):
                    if files_seen >= _FIND_SWEEP_FILE_CAP:
                        print(
                            f"[codeq] find sweep truncated at {_FIND_SWEEP_FILE_CAP} files "
                            f"under {args.path}; narrow with -p <subdir>.",
                            file=sys.stderr,
                        )
                        break
                    if not path.is_file() or path.suffix not in walker_exts:
                        continue
                    rel_parts = set(path.resolve().parts) - root_parts
                    if any(rel_part in VENDOR_EXCLUDES for rel_part in rel_parts):
                        continue
                    if any(path.match(g) for g in CACHE_GLOBS):
                        continue
                    files_seen += 1
                    located_line = _locate_line(str(path), args.name)
                    if located_line:
                        hits.append((str(path), located_line, "method", args.name))
            except OSError:
                pass  # unreadable path — silently skip; ctags output was the primary source
    if not hits:
        print(f"no symbol named '{args.name}' under {args.path}", file=sys.stderr)
        return 1
    hits.sort()
    for file, ln, kind, name in hits:
        print(f"{file}:{ln}  {kind}  {name}")
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    rc, out, _ = run([CTAGS, "--fields=+Kzn", "-f", "-", args.file])
    if rc != 0:
        die("ctags failed", 2)
    rows: list[tuple[int, str, str]] = []
    for line in out.splitlines():
        parsed = _parse_ctags_line(line)
        if not parsed:
            continue
        _, _, kind, line_no = parsed
        try:
            ln = int(line_no)
        except ValueError:
            continue
        rows.append((ln, kind, parsed[0]))
    # Fallback for brace-langs when ctags misses class members (the
    # ctags 5.9.0 TS parser bug after generic-arg field initializers).
    # TS/JS can be partial: ctags may return methods before `inject<T>(...)`
    # and silently drop methods after it, so always merge the regex sweep there.
    # Java keeps the older conservative path because ctags is reliable enough
    # for normal member outlines and the regex is declaration-level only.
    n_methods = sum(1 for _, k, _ in rows if k == "method")
    try:
        lang: str | None = lang_of(args.file, None)
    except SystemExit:
        lang = None
    if lang in ("typescript", "javascript") or (n_methods == 0 and lang == "java"):
        seen = {(r[2]) for r in rows}  # avoid duplicating names ctags DID get
        rows.extend(_regex_outline_methods(args.file, lang, seen))
    if not rows:
        print(f"no symbols indexed in {args.file}", file=sys.stderr)
        return 1
    rows.sort()
    for ln, kind, name in rows:
        print(f"{ln:>5}  {kind:<12}  {name}")
    return 0
