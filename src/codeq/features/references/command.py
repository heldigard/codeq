from __future__ import annotations

import argparse
import re
import sys

from codeq.shared.search import search_lexical

# Extension globs per language for the `refs` search.
_LANG_INCLUDES: dict[str, list[str]] = {
    "python": ["--include=*.py"],
    "javascript": [
        "--include=*.js",
        "--include=*.mjs",
        "--include=*.cjs",
        "--include=*.jsx",
    ],
    "typescript": ["--include=*.ts", "--include=*.tsx"],
    "go": ["--include=*.go"],
    "rust": ["--include=*.rs"],
    "java": ["--include=*.java"],
}


def _def_filter_re(lang: str, name: str) -> "re.Pattern[str]":
    """Regex matching a DECLARATION line of NAME, so `refs` can filter out the
    definition itself and show only call sites.

    Language-specific by necessity — the Java typed-decl and TS/modifier forms
    are gated to their language because the generic typed pattern would
    otherwise swallow `return foo(` / `x = foo(` call lines in py/js/etc.
    Extracted from cmd_refs to isolate this fragile regex in one testable
    place (the single most-tuned pattern in the file)."""
    name_esc = re.escape(name)
    if lang == "java":
        # Java has no def keyword: filter typed declarations [modifiers] Type name(,
        # plus class/interface/enum. Java-ONLY (see docstring).
        return re.compile(
            r"\b(?:class|interface|enum)\s+" + name_esc + r"\b"
            r"|^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|@\w+)\s+)*"
            r"[A-Za-z_][\w<>\[\],?\s]*?\s+" + name_esc + r"\s*\("
        )
    if lang in ("typescript", "javascript"):
        # TS/JS decls look like `(modifiers|function)+ name(`. Without this
        # filter, refs returns the declaration line itself as a "reference".
        return re.compile(
            r"^[ \t]*(?:export\s+)?(?:async\s+)?"
            r"(?:\s*(?:public|private|protected|static|abstract|override|readonly|async)\s+)*"
            r"(?:function\s+)?\*?\s*"
            + name_esc
            + r"\s*(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*\(",
            re.MULTILINE,
        )
    # py/go/rust/...: keyword-led declarations only (safe — won't match calls)
    return re.compile(
        r"\b(?:def|class|function|fn|func|sub|struct|interface|enum|trait|impl)\s+"
        + name_esc
        + r"\b"
    )


def get_refs(
    name: str,
    path: str,
    lang: str | None = None,
    limit: int = 200,
) -> list[str]:
    """Core refs logic: returns filtered reference lines (definitions excluded).

    Pure function — no argparse, no stdout. Callers (cmd_refs, cmd_context,
    cmd_relations) use this directly instead of constructing Namespace objects.

    Returns ['file:line:text', ...] or empty list if no references found.
    `limit=0` means unlimited."""
    includes = _LANG_INCLUDES.get(lang or "", [])
    lines = search_lexical(name, path, includes)
    if not lines:
        return []
    def_re = _def_filter_re(lang or "", name)
    result: list[str] = []
    for line in lines:
        m = re.match(r"^(.*?):(\d+):(.*)$", line)
        if not m:
            continue
        if def_re.search(m.group(3)):
            continue  # skip the declaration itself
        result.append(line)
        if limit and len(result) >= limit:
            break
    return result


def cmd_refs(args: argparse.Namespace) -> int:
    """Precise references to a symbol: word-boundary lexical search with
    definition lines filtered out, so the controller sees call sites only.

    Uses `search_lexical` (ripgrep binary, else a pure-Python walker) — NEVER
    the system `grep`, whose behavior varies (GNU/ugrep/busybox/BSD; in some
    shells `grep` is itself a function wrapping ugrep). Deterministic across
    environments. (Comments/strings can still match — ast-grep --lang is exact
    for that.)"""
    limit = getattr(args, "limit", 200) or 0
    refs = get_refs(args.name, args.path, args.lang, limit=limit)
    if not refs:
        print(f"no references to '{args.name}' under {args.path}", file=sys.stderr)
        return 1
    for line in refs:
        print(line)
    if limit and len(refs) >= limit:
        print(
            "... more references may exist (narrow with --path or increase --limit)",
            file=sys.stderr,
        )
    return 0
