"""`codeq rename` — AST-exact structural rename via `ast-grep --update-all`.

Renames every occurrence of an identifier OLD to NEW under PATH, AST-aware,
so string literals (`'foo'`) and comments (`# foo`) are NEVER touched — the
two inviolable wins over sed. Safer than sed; narrower than a full LSP rename
— it does NOT respect lexical scope (a local `foo` in an unrelated function
is also renamed), and tree-sitter represents keyword-argument names as
identifier tokens so they ARE rewritten too. For scope-aware rename, use an
LSP / SCIP indexer.

Coverage varies by language grammar (verified 2026-07-04):
  - python: `def`, `async def`, `class`, method def, attribute (`obj.foo`),
    bare call, keyword-argument names. Full identifier coverage — Python's
    tree-sitter grammar treats every name position as the same identifier node.
  - javascript / typescript: function name, bare call. Attribute access
    (`obj.foo`) and method declarations INSIDE a class body are NOT matched
    by a bare-identifier pattern. For those, drop to raw `ast-grep` with a
    richer pattern (e.g. `obj.$VAR`).
  - go / rust / java: bare identifier expressions.

Use `--dry-run` / `-n` to preview the match count before writing.
"""

from __future__ import annotations

import argparse
import re
import sys

from codeq.shared.config import ASTGREP
from codeq.shared.core import die, run

# ast-grep languages codeq rename supports (subset of ast-grep's --lang enum,
# aligned with codeq's EXT_LANG). Each accepts a bare-identifier pattern and
# applies it without touching strings / comments (verified 2026-07-04).
_RENAME_LANGS = frozenset({"python", "javascript", "typescript", "go", "rust", "java"})

# Conservative identifier: letters / digits / underscore, not leading digit.
# Java also allows `$` (included). Rejecting exotic forms upfront gives a
# clean codeq error instead of an ast-grep parse failure mid-rewrite.
_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def cmd_rename(args: argparse.Namespace) -> int:
    """Structural rename OLD → NEW via `ast-grep run --update-all`.

    Builds the ast-grep invocation, validates inputs (identifier shape,
    identical-name guard, supported lang), then either applies the rewrite
    or reports the match count in dry-run mode."""
    old = args.old
    new = args.new
    lang = args.lang or "python"
    _validate_inputs(old, new, lang)
    rc, out, err = _run_astgrep(old, new, lang, args.path, args.dry_run)
    # ast-grep rc: 0 = success, 1 = no matches (grep parity), 2+ = real error.
    # NOTE: ast-grep writes its "Applied N changes" summary to STDERR as
    # normal operation — stderr is NOT an error signal here. Only a bad rc
    # or a parse-error keyword indicates failure.
    if rc not in (0, 1) or _looks_like_error(err):
        print(f"ast-grep error: {err.strip() or f'rc={rc}'}", file=sys.stderr)
        return 2
    if args.dry_run:
        return _report_dry_run(old, new, lang, args.path, out)
    summary = _parse_applied_count(err) or out.strip() or "(no changes)"
    print(f"renamed {old} → {new} (lang={lang}, path={args.path}).")
    print(summary)
    return 0


def _looks_like_error(stderr: str) -> bool:
    """True when STDERR contains an ast-grep parse/runtime error keyword (not
    the routine `Applied N changes` summary). Guards against treating the
    normal summary as a failure while still surfacing real parse errors."""
    low = stderr.lower()
    return any(
        sig in low for sig in ("error node", "cannot parse", "multiple ast nodes")
    )


def _parse_applied_count(stderr: str) -> str:
    """Extract the `Applied N changes` summary line ast-grep prints to STDERR.
    Returns the matched line, or "" if absent (caller falls back to stdout)."""
    for line in stderr.splitlines():
        if "applied" in line.lower() and "change" in line.lower():
            return line.strip()
    return ""


def _validate_inputs(old: str, new: str, lang: str) -> None:
    """Fail fast on bad identifier shape, identical names, or unsupported lang.

    Extracted from `cmd_rename` to keep the command body flat (the three
    independent guards would otherwise push nesting past the slice budget)."""
    if not _IDENT_RE.match(old) or not _IDENT_RE.match(new):
        die(
            f"OLD and NEW must be identifiers (match {_IDENT_RE.pattern}); "
            f"got old={old!r} new={new!r}."
        )
    if old == new:
        die("OLD and NEW are identical; nothing to rename.")
    if lang not in _RENAME_LANGS:
        die(
            f"rename supports langs {sorted(_RENAME_LANGS)}; got lang={lang!r}. "
            "For other langs, run ast-grep directly."
        )


def _run_astgrep(
    old: str, new: str, lang: str, path: str, dry_run: bool
) -> tuple[int, str, str]:
    """Invoke ast-grep with the rewrite flags. `--update-all` is omitted in
    dry-run mode so the tool scans + prints matches without writing."""
    cmd = [ASTGREP, "run", "--pattern", old, "--rewrite", new, "--lang", lang]
    if not dry_run:
        cmd.append("--update-all")
    cmd.append(path)
    return run(cmd)


def _report_dry_run(old: str, new: str, lang: str, path: str, out: str) -> int:
    """Summarize ast-grep's scan-mode output as an approximate match count.

    In scan mode (no `--update-all`) ast-grep prints one match block per hit.
    Counting non-empty output lines is a cheap, robust proxy — exact match
    counts would need JSON parsing and the number is informational anyway."""
    matches = [ln for ln in out.splitlines() if ln.strip()]
    print(
        f"DRY RUN: ~{len(matches)} match line(s) would be rewritten "
        f"({old} → {new}, lang={lang}, path={path})."
    )
    print("Re-run without --dry-run to apply.")
    return 0
