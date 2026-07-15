from __future__ import annotations

import argparse
import re
import sys

from codeq.shared.search import search_lexical, search_py_refs

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
    "bash": ["--include=*.sh", "--include=*.bash"],
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
    if lang == "bash":
        # Bash has two function-declaration forms:
        #   function name() { ... }   (keyword + parens)
        #   function name { ... }     (keyword, no parens)
        #   name() { ... }            (no keyword, bare word + parens)
        # The generic fallback catches the `function` keyword forms but misses
        # `name() {`, which is the most common style. Filter all three.
        return re.compile(
            r"^\s*(?:function\s+)?" + name_esc + r"\s*\(\s*\)\s*\{"
            r"|^\s*function\s+" + name_esc + r"\s*\{"
        )
    # py/go/rust/...: keyword-led declarations only (safe — won't match calls)
    return re.compile(
        r"\b(?:def|class|function|fn|func|sub|struct|interface|enum|trait|impl)\s+"
        + name_esc
        + r"\b"
    )


def _refs_lines(name: str, path: str, lang: str) -> list[str]:
    """Pick the reference-finder backend by language.

    - python → `search_py_refs` (AST-exact; no comment/string/kwarg noise).
    - other  → `search_lexical` (ripgrep / Python walker, word-boundary).

    AST is stdlib-only and already powers `body`/`outline`/`deps`; for python
    it strictly dominates lexical (which can match comments and strings). The
    other brace-langs have no stdlib AST available, so they keep the lexical
    path until an optional tree-sitter integration lands."""
    if lang == "python":
        return search_py_refs(name, path)
    includes = _LANG_INCLUDES.get(lang, [])
    return search_lexical(name, path, includes)


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
    lines = _refs_lines(name, path, lang or "")
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
    if getattr(args, "quick", False) and (limit == 0 or limit > 20):
        limit = 20
    refs = get_refs(args.name, args.path, args.lang, limit=limit)
    if not refs:
        print(f"no references to '{args.name}' under {args.path}", file=sys.stderr)
        return 1
    for line in refs:
        print(line)
    if limit and len(refs) >= limit:
        print(
            f"... more references may exist (--quick capped at {limit}; raise --limit for more)",
            file=sys.stderr,
        )
    return 0
