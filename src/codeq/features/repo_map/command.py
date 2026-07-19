from __future__ import annotations

import argparse
import io
import re
import sys
import tempfile
import tokenize
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codeq.shared.config import CTAGS, EXT_LANG, _RESERVED_KEYWORDS
from codeq.shared.core import _parse_ctags_line, ctags_exclude_args, die, run

# TypeAlias for a ctags-indexed symbol row: (line, kind, name). Using an alias
# (not the inline `tuple[int, str, str]`) keeps function signatures free of
# internal commas that would otherwise inflate the param-count shape check.
_Sym = tuple[int, str, str]

# Identifier-shape regex used for the NON-python frequency pass (best-effort
# proxy — matches identifier-shaped tokens, including inside strings/comments
# for brace-langs; Python uses `tokenize` for an exact count instead).
_FREQ_TOKEN_RE = re.compile(r"[A-Za-z_]\w{2,}")

# Orientational kinds for the repo map (declaration-level; variables/fields
# excluded — they inflate noise without aiding navigation).
_MAP_KINDS = frozenset(
    {
        "class",
        "interface",
        "struct",
        "enum",
        "trait",
        "function",
        "method",
        "type",
    }
)
_MAP_FILE_SIZE_CAP = 512 * 1024  # skip pathological blobs in the frequency pass

# Test/spec files are excluded from the map by default (--tests to include):
# spec-local helpers named `config`/`user`/`status` lexically collide with
# ubiquitous identifiers and crowd out the real production hubs.
_MAP_TEST_RE = re.compile(
    r"(\.spec[.\-]|\.test[.\-]|_test\.|(^|/)test[_-]|(^|/)tests?/|(^|/)__tests__/|(^|/)spec/)"
)

# Map-ONLY path excludes (find/refs stay complete — orientation can afford to
# drop noise that precision tools cannot): CLI-harness runtime/vendor dirs and
# third-party plugin marketplaces that otherwise crown the ranking.
_MAP_NOISE_RE = re.compile(
    r"(^|/)(shell-snapshots|file-history|backups|summaries|delegations"
    r"|\.claude/plugins|plugins/marketplaces|plugins/cache)(/|$)"
)
# Minified/bundled artifacts (one 4K-char line of `and`/`then` "classes"):
# any line longer than this marks the file as generated, not source.
_MAP_MINIFIED_LINE_LEN = 2000


def _in_virtualenv(file: str, root: Path, _cache: dict[Path, bool]) -> bool:
    """True when FILE sits inside a Python venv NOT named .venv/venv (those are
    already in VENDOR_EXCLUDES). Detects by `pyvenv.cfg` next to any ancestor."""
    d = Path(file).parent
    chain: list[Path] = []
    hit = False
    while d != d.parent and (root in d.parents or d == root):
        if d in _cache:
            hit = _cache[d]
            break
        chain.append(d)
        if (d / "pyvenv.cfg").is_file():
            hit = True
            break
        d = d.parent
    for c in chain:
        _cache[c] = hit
    return hit


def _collect_indexed_symbols(
    tags_path: str, include_tests: bool, root: Path
) -> dict[str, list[_Sym]]:
    """Scan a ctags index file → {file: [(line, kind, name), ...]} keeping only
    navigational declaration kinds (`_MAP_KINDS`), dropping test/spec files
    (unless `include_tests`), map-noise paths, virtualenv interiors, and tiny /
    reserved names. Extracted from `cmd_map` so its try/finally stays shallow —
    the scan's own `with>for>if` nesting lives here at depth 3, not nested
    inside the tempfile cleanup try."""
    per_file: dict[str, list[_Sym]] = {}
    _venv_cache: dict[Path, bool] = {}
    # The ctags index is a small text file — read_text (no `with` manager)
    # drops one nesting level vs `for raw in fh`, keeping the guard-clause
    # filter loop at depth 3.
    for raw in Path(tags_path).read_text(errors="replace").splitlines():
        parsed = _parse_ctags_line(raw)
        if not parsed:
            continue
        name, file, kind, line_no = parsed
        if kind not in _MAP_KINDS:
            continue
        norm = file.replace("\\", "/")
        if not include_tests and _MAP_TEST_RE.search(norm):
            continue
        if _MAP_NOISE_RE.search(norm):
            continue
        if _in_virtualenv(file, root, _venv_cache):
            continue
        if len(name) < 3 or name.lower() in _RESERVED_KEYWORDS:
            continue
        # line_no is a ctags decimal ("42") or the "?" default — isdigit
        # covers it without a try/except.
        ln = int(line_no) if line_no.isdigit() else 0
        per_file.setdefault(file, []).append((ln, kind, name))
    return per_file


def _freq_text(file: str) -> tuple[str | None, bool]:
    """Read FILE's text for the frequency pass. Returns (text, is_minified):
    - (text, False): normal source — update freq/defs from it.
    - (None, True): minified/large blob — caller drops it (not real source).
    - (None, False): unreadable (OSError) — caller keeps it with zero freq.

    Extracted from cmd_map so the frequency loop stays at depth <= 3."""
    p = Path(file)
    try:
        if p.stat().st_size > _MAP_FILE_SIZE_CAP:
            return (None, True)
        text = p.read_text(errors="replace")
    except OSError:
        return (None, False)
    if any(len(ln) > _MAP_MINIFIED_LINE_LEN for ln in text.splitlines()):
        return (None, True)
    return (text, False)


def _py_freq_names(text: str) -> Counter[str]:
    """Python identifier frequency via `tokenize` → Counter of NAME tokens
    (length ≥ 3). Excludes STRING and COMMENT tokens, so a name mentioned
    50 times in docstrings does not inflate its reference weight.

    Why tokenize over the regex pass: `re.findall(r"[A-Za-z_]\\w{2,}", text)`
    matches identifier-shaped substrings INSIDE string literals and comments,
    so `codeq map` would over-rank files whose symbols share spelling with
    common words in prose. `tokenize` distinguishes NAME from STRING/COMMENT,
    giving accurate reference frequency for the dominant codeq language.

    Falls back to the regex extractor on tokenize failure (broken or partial
    files) so a degenerate file still contributes approximate frequency
    instead of zero."""
    try:
        return _py_name_tokens(io.StringIO(text))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return Counter(_FREQ_TOKEN_RE.findall(text))


def _py_name_tokens(reader: io.StringIO) -> Counter[str]:
    """Walk `tokenize` over READER.readline and return NAME tokens (len ≥ 3)
    as a Counter. Extracted from `_py_freq_names` so the try/except + loop +
    if guard does not nest past the slice budget."""
    cnt: Counter[str] = Counter()
    for tok in tokenize.generate_tokens(reader.readline):
        if tok.type == tokenize.NAME and len(tok.string) >= 3:
            cnt[tok.string] += 1
    return cnt


def _save_map(root: Path, out_text: str) -> None:
    """Persist the map to <root>/.memory-bank/topics/code-map.md, or emit a
    skip notice when no memory bank exists. Extracted so cmd_map's save tail
    is one call (avoids an if>if>print(multiline) depth-4)."""
    bank = root / ".memory-bank"
    if not bank.is_dir():
        print(
            f"--save skipped: no .memory-bank/ under {root} "
            "(init one with agent-memory first)",
            file=sys.stderr,
        )
        return
    topic = bank / "topics" / "code-map.md"
    topic.parent.mkdir(exist_ok=True)
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    topic.write_text(
        "# Code Map (auto-generated)\n"
        f"> Generated by `codeq map -p . --save` on {stamp}. Do not edit by "
        "hand — refresh with the same command after large refactors.\n\n"
        "```\n" + out_text + "\n```\n"
    )
    print(f"saved → {topic}", file=sys.stderr)


def _merge_lombok_members(per_file: dict[str, list[_Sym]]) -> None:
    """Append detected Lombok-generated methods to their Java files in place.

    Extracted from `cmd_map` — the original inline `for>if>for>if` block
    pushed nesting past the slice budget. Dispatches per-file to keep the
    outer loop shallow."""
    for file in list(per_file.keys()):
        if not file.endswith(".java"):
            continue
        _append_lombok_methods(file, per_file[file])


def _append_lombok_methods(file: str, syms: list[_Sym]) -> None:
    """Append Lombok-generated methods to SYMS in place, skipping names ctags
    already indexed (constructors/getters/setters) so no duplicate is fabricated.
    Guard-clause form keeps nesting within the slice budget."""
    from codeq.shared.lombok import detect_lombok_members

    seen = {t[2] for t in syms}
    for m in detect_lombok_members(file):
        if m.kind != "method" or m.name in seen:
            continue
        syms.append((m.line, "lombok-method", m.name))
        seen.add(m.name)


@dataclass
class _FreqAccum:
    """Mutable accumulator for the identifier-frequency pass. Bundles the three
    outputs so `_freq_for_file` takes one accum arg instead of three (keeping
    the param count inside the slice budget)."""

    freq: Counter[str] = field(default_factory=Counter)
    defs: Counter[str] = field(default_factory=Counter)
    minified: set[str] = field(default_factory=set)


def _freq_names_for(file: str, text: str) -> Counter[str]:
    """Identifier multiset for one source file.

    Dispatch:
    - `.py` → stdlib `tokenize` (NAME only; excludes STRING/COMMENT)
    - brace-langs with tree-sitter → `ts_freq_names` (AST identifiers;
      skips comment/string subtrees — same precision as tokenize for Python)
    - else → regex best-effort (identifier-shaped tokens, may include
      string/comment noise when tree-sitter is absent)
    """
    if file.endswith(".py"):
        return _py_freq_names(text)
    lang = EXT_LANG.get(Path(file).suffix.lstrip("."))
    if lang and lang != "python":
        from codeq.shared.tree_sitter_extract import ts_freq_names

        ts_counts = ts_freq_names(text, lang)
        if ts_counts is not None:
            return Counter(ts_counts)
    return Counter(_FREQ_TOKEN_RE.findall(text))


def _freq_for_file(file: str, syms: list[_Sym], acc: _FreqAccum) -> None:
    """Update ACC with one indexed file's contribution. Mutates in place so
    the caller's loop body stays flat (no `if status == ...` branch).

    - minified / unreadable files contribute no freq (minified ones are
      flagged so the caller drops them).
    - Python files use `_py_freq_names` (tokenize-exact, excludes STRING /
      COMMENT tokens); brace-langs use tree-sitter when available; otherwise
      the regex best-effort extractor.
    """
    text, is_minified = _freq_text(file)
    if is_minified:
        acc.minified.add(file)
        return
    if text is None:
        return
    acc.defs.update(name for _, _, name in syms)
    acc.freq.update(_freq_names_for(file, text))


def _freq_pass(per_file: dict[str, list[_Sym]]) -> _FreqAccum:
    """One identifier-frequency pass over the indexed files. Returns the
    populated accumulator. Extracted from `cmd_map` to keep the command
    body a flat sequence of steps."""
    acc = _FreqAccum()
    for file, syms in per_file.items():
        _freq_for_file(file, syms, acc)
    return acc


def get_repo_map_data(
    path_str: str,
    include_tests: bool = False,
    top_n: int = 20,
    syms_per_file: int = 6,
) -> dict[str, Any] | None:
    """Gathers repository map details (hot files and symbols ranked by reference weight)."""
    root = Path(path_str).resolve()
    if not root.is_dir():
        return None
    with tempfile.NamedTemporaryFile(suffix=".tags", delete=False) as tf:
        tags_path = tf.name
    try:
        cmd = [CTAGS, "-R", "--fields=+nKz", "-f", tags_path]
        cmd += ctags_exclude_args()
        cmd += [str(root)]
        rc, _, err = run(cmd)
        if rc != 0:
            die(f"ctags failed: {err.strip()}", 2)
        per_file = _collect_indexed_symbols(tags_path, include_tests, root)
    finally:
        Path(tags_path).unlink(missing_ok=True)

    # Lombok members: append to Java files.
    _merge_lombok_members(per_file)

    if not per_file:
        return {
            "root": str(root),
            "files_indexed": 0,
            "symbols_indexed": 0,
            "files": [],
        }
    # One frequency pass over the indexed source files (vendor already excluded).
    # Python: tokenize-exact (excludes STRING/COMMENT). Brace-langs: tree-sitter
    # when available (same precision); regex best-effort otherwise.
    # other langs use the regex best-effort extractor.
    acc = _freq_pass(per_file)
    freq, defs, minified = acc.freq, acc.defs, acc.minified
    for file in minified:
        per_file.pop(file, None)
    if not per_file:
        return {
            "root": str(root),
            "files_indexed": 0,
            "symbols_indexed": 0,
            "files": [],
        }

    def sym_weight(name: str) -> int:
        # Shared attribution: a name defined in N places (main/check/run
        # conventions) splits its reference weight N ways, so generic names
        # don't crown every file that happens to define them.
        n_defs = max(defs.get(name, 0), 1)
        return max(freq.get(name, 0) - n_defs, 0) // n_defs

    ranked_files: list[tuple[int, str, list[tuple[int, str, str, int]]]] = []
    for file, syms in per_file.items():
        weighted = sorted(
            ((ln, kind, name, sym_weight(name)) for ln, kind, name in syms),
            key=lambda t: -t[3],
        )[:syms_per_file]
        score = sum(w for *_, w in weighted)
        ranked_files.append((score, file, weighted))
    ranked_files.sort(key=lambda t: (-t[0], t[1]))
    top = ranked_files[:top_n]

    total_syms = sum(len(s) for s in per_file.values())
    files_list = []
    for score, file, weighted in top:
        try:
            rel = str(Path(file).resolve().relative_to(root))
        except ValueError:
            rel = file
        syms_list = []
        for ln, kind, name, w in weighted:
            syms_list.append(
                {
                    "line": ln,
                    "kind": kind,
                    "name": name,
                    "references": w,
                }
            )
        files_list.append(
            {
                "file": rel,
                "weight": score,
                "symbols": syms_list,
            }
        )

    return {
        "command": "map",
        "root": str(root),
        "files_indexed": len(per_file),
        "symbols_indexed": total_syms,
        "files": files_list,
    }


def cmd_map(args: argparse.Namespace) -> int:
    """Repo orientation map (aider-style): the most-referenced files and their
    hottest symbols, ONE bounded call instead of a Glob/Read exploration sweep.
    Reference weight = project-wide identifier frequency (single scan pass) —
    approximate by design; it ranks, it does not prove. `--save` refreshes
    <root>/.memory-bank/topics/code-map.md so the orientation persists across
    sessions (memory-bank synergy: explore once, remember forever)."""
    data = get_repo_map_data(
        args.path,
        include_tests=args.tests,
        top_n=args.top,
        syms_per_file=args.syms,
    )
    if data is None:
        die(f"no such directory: {args.path}")
    if not data["files"]:
        print(f"no symbols indexed under {args.path}", file=sys.stderr)
        return 1

    lines: list[str] = []
    lines.append(
        f"REPO MAP  {data['root']}  ({data['files_indexed']} files, {data['symbols_indexed']} symbols; "
        f"top {len(data['files'])} by reference weight)"
    )
    for f in data["files"]:
        lines.append(f"{f['file']}  (weight {f['weight']})")
        for s in f["symbols"]:
            lines.append(
                f"    {s['line']:>5}  {s['kind']:<10} {s['name']}  ~{s['references']} refs"
            )
    out_text = "\n".join(lines)
    print(out_text)
    if args.save:
        _save_map(Path(data["root"]), out_text)
    return 0
