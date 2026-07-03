from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from codeq.shared.config import CACHE_GLOBS, CTAGS, FILE_EXCLUDES, VENDOR_EXCLUDES, _RESERVED_KEYWORDS
from codeq.shared.core import _parse_ctags_line, die, run

# Orientational kinds for the repo map (declaration-level; variables/fields
# excluded — they inflate noise without aiding navigation).
_MAP_KINDS = frozenset({
    "class", "interface", "struct", "enum", "trait", "function", "method", "type",
})
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


def cmd_map(args: argparse.Namespace) -> int:
    """Repo orientation map (aider-style): the most-referenced files and their
    hottest symbols, ONE bounded call instead of a Glob/Read exploration sweep.
    Reference weight = project-wide identifier frequency (single scan pass) —
    approximate by design; it ranks, it does not prove. `--save` refreshes
    <root>/.memory-bank/topics/code-map.md so the orientation persists across
    sessions (memory-bank synergy: explore once, remember forever)."""
    root = Path(args.path).resolve()
    if not root.is_dir():
        die(f"no such directory: {args.path}")
    with tempfile.NamedTemporaryFile(suffix=".tags", delete=False) as tf:
        tags_path = tf.name
    per_file: dict[str, list[tuple[int, str, str]]] = {}
    _venv_cache: dict[Path, bool] = {}
    try:
        cmd = [CTAGS, "-R", "--fields=+nKz", "-f", tags_path]
        for ex in VENDOR_EXCLUDES:
            cmd += [f"--exclude={ex}"]
        for g in CACHE_GLOBS:
            cmd += [f"--exclude={g}"]
        for ex in FILE_EXCLUDES:
            cmd += [f"--exclude={ex}"]
        cmd += [str(root)]
        rc, _, err = run(cmd)
        if rc != 0:
            die(f"ctags failed: {err.strip()}", 2)
        with open(tags_path, errors="replace") as fh:
            for raw in fh:
                parsed = _parse_ctags_line(raw)
                if not parsed:
                    continue
                name, file, kind, line_no = parsed
                if kind not in _MAP_KINDS:
                    continue
                norm = file.replace("\\", "/")
                if not args.tests and _MAP_TEST_RE.search(norm):
                    continue
                if _MAP_NOISE_RE.search(norm):
                    continue
                if _in_virtualenv(file, root, _venv_cache):
                    continue
                if len(name) < 3 or name.lower() in _RESERVED_KEYWORDS:
                    continue
                try:
                    ln = int(line_no)
                except ValueError:
                    ln = 0
                per_file.setdefault(file, []).append((ln, kind, name))
    finally:
        Path(tags_path).unlink(missing_ok=True)
    if not per_file:
        print(f"no symbols indexed under {root}", file=sys.stderr)
        return 1
    # One frequency pass over the indexed source files (vendor already excluded).
    from collections import Counter
    freq: Counter[str] = Counter()
    defs: Counter[str] = Counter()
    minified: set[str] = set()
    for file, syms in per_file.items():
        try:
            p = Path(file)
            if p.stat().st_size > _MAP_FILE_SIZE_CAP:
                minified.add(file)
                continue
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if any(len(ln) > _MAP_MINIFIED_LINE_LEN for ln in text.splitlines()):
            minified.add(file)  # bundled/minified artifact, not source
            continue
        for _, _, name in syms:
            defs[name] += 1
        freq.update(re.findall(r"[A-Za-z_]\w{2,}", text))
    for file in minified:
        per_file.pop(file, None)
    if not per_file:
        print(f"only generated/minified files under {root}", file=sys.stderr)
        return 1

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
        )[: args.syms]
        score = sum(w for *_, w in weighted)
        ranked_files.append((score, file, weighted))
    ranked_files.sort(key=lambda t: (-t[0], t[1]))
    top = ranked_files[: args.top]

    lines: list[str] = []
    total_syms = sum(len(s) for s in per_file.values())
    lines.append(
        f"REPO MAP  {root}  ({len(per_file)} files, {total_syms} symbols; "
        f"top {len(top)} by reference weight)"
    )
    for score, file, weighted in top:
        try:
            rel = str(Path(file).resolve().relative_to(root))
        except ValueError:
            rel = file
        lines.append(f"{rel}  (weight {score})")
        for ln, kind, name, w in weighted:
            lines.append(f"    {ln:>5}  {kind:<10} {name}  ~{w} refs")
    out_text = "\n".join(lines)
    print(out_text)
    if args.save:
        bank = root / ".memory-bank"
        if not bank.is_dir():
            print(f"--save skipped: no .memory-bank/ under {root} "
                  "(init one with project-memory first)", file=sys.stderr)
            return 0
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
    return 0
