from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from codeq.shared.config import _RESERVED_KEYWORDS
from codeq.shared.core import die, lang_of
from codeq.features.dependencies.command import get_deps, get_rdeps
from codeq.shared.extraction import _raw_body, _sig_from_raw
from codeq.shared.locators import _locate_line
from codeq.shared.llm import (
    _maybe_emit_summary,
    _OLLAMA_DISABLED_PREFIX,
    _OLLAMA_SUMMARY_PREFIX,
    _summarize_code,
)
from codeq.features.references.command import get_refs


def cmd_summary(args: argparse.Namespace) -> int:
    """Compact 1-line description of a function/method. Uses local Ollama
    (qwen3.5:4b) for orientation; the large LLM must verify before reasoning.

    Intended for the agent loop's "should I dig deeper into this body?"
    decision: a one-line answer is far cheaper than the full body, and
    enough for 'do I need to call body next or is this a passthrough I can
    skip?'"""
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw is None:
        return _no_body_error(args.file, args.name, lang, "summarize")
    summary, reason, cold = _summarize_code(
        args.file, args.name, raw, no_llm=args.no_llm
    )
    if summary:
        # `reason` holds the model tag on success (see _summarize_code return).
        print(
            _OLLAMA_SUMMARY_PREFIX.format(
                model=reason or "local-llm",
                lat=f"{cold:.1f}" if cold else "?",
            )
        )
        print(f"# {summary}")
        return 0
    # Ollama unavailable — degrade gracefully so a missing daemon never
    # blocks the agent loop. Print the reason to stderr (visible when
    # debugging, silent in the agent loop's pipe-to-LLM path).
    print(_OLLAMA_DISABLED_PREFIX.format(reason=reason or "unknown"), file=sys.stderr)
    return 2  # distinct from "no symbol found" (1) so callers can branch


def _print_section(title: str) -> None:
    """Markdown section header. Visible in LLM context."""
    print()
    print(f"# === {title} ===")
    print()


def _extract_calls_from_line(
    line: str,
    rx: re.Pattern[str],
    seen: set[str],
    exclude_name: str,
) -> list[str]:
    """Extract candidate call names from a single body line. Helper for
    _body_call_hints to keep nesting shallow."""
    calls: list[str] = []
    for m in rx.finditer(line):
        name = m.group(1).lstrip(".")
        if name in _RESERVED_KEYWORDS or name in seen:
            continue
        tail = name.rsplit(".", 1)[-1]
        if exclude_name and (tail == exclude_name or name == exclude_name):
            continue
        seen.add(name)
        calls.append(name)
    return calls


def _body_call_hints(body: str, exclude_name: str = "") -> list[str]:
    """Extract candidate method/function invocations from a body via a
    lightweight regex: a dotted-identifier path (`foo`, `this.x.bar`,
    `..baz`) immediately followed by `(`. Skips control-flow keywords
    (see `_RESERVED_KEYWORDS`), comment/decorator lines, and the symbol's
    OWN name (`exclude_name`) — which the signature line would otherwise
    leak as a self-call. Coarse — orientation only, not a real call graph."""
    out: list[str] = []
    rx = re.compile(r"(?:^|[^.\w])((?:\.{0,2}\w+)+)\s*\(")
    seen: set[str] = set()
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "//", "/*", "*", "@")):
            continue
        out.extend(_extract_calls_from_line(s, rx, seen, exclude_name))
    return out[:25]  # cap so the output stays bounded


def _no_body_error(file: str, name: str, lang: str, action: str) -> int:
    """Shared error handler when body extraction fails. Returns exit code 1."""
    ln = _locate_line(file, name)
    if ln:
        print(f"{file}:{ln}", file=sys.stderr)
        print(
            f"(no exact body extractor to {action} for {lang}; "
            f"try: codeq outline {file} to list symbols, "
            f"or codeq sig {name} {file} for signature only)",
            file=sys.stderr,
        )
    else:
        print(f"no def/class '{name}' in {file} (lang={lang})", file=sys.stderr)
    return 1


def _print_file_importers(file: str, path: str, lang: str) -> None:
    """Print bounded reverse deps so context includes edit blast radius."""
    _print_section(f"Importers of {file} (rdeps, edit blast radius)")
    rows = get_rdeps(file, path, lang, limit=25)
    if rows:
        for importer, ln, text in rows:
            print(f"{importer}:{ln}:{text}")
    else:
        print(f"(no project files import {file} under {path})")


def cmd_context(args: argparse.Namespace) -> int:
    """Bundled context for code editing: summary + signature + body + call
    sites (refs) + file-level imports + bounded file importers. ONE call
    replaces the typical LLM exploration of `find + body + refs + deps + rdeps`
    (4-6 tool calls + a re-read of the body). Ollama enriches ONLY with a
    tagged 1-line summary; the rest is structural data.

    Use this when the agent is ABOUT TO EDIT a function/method and wants
    to know: what it does, who calls it, what it imports, and which files
    import the edited module.
    """
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw is None:
        return _no_body_error(args.file, args.name, lang, "build context")
    sig = _sig_from_raw(raw, lang)
    print(f"# [codeq context | target: {args.name} | file: {args.file} | lang: {lang}]")
    if args.no_llm:
        print("# [summary skipped — --no-llm]")
    else:
        _maybe_emit_summary(args.file, args.name, raw)
    _print_section("Signature")
    print(sig)
    _print_section("Body")
    print(raw)
    _print_section(f"Callers of '{args.name}' (refs across project)")
    refs = get_refs(args.name, args.path, lang)
    if refs:
        for line in refs:
            print(line)
    else:
        print(f"(no references to '{args.name}' under {args.path})")
    _print_section(f"Imports of {args.file} (deps)")
    deps = get_deps(args.file, lang)
    if deps:
        for ln, kind, mod in deps:
            print(f"{ln:>5}  {kind:<6}  {mod}")
    else:
        print(f"(no imports found in {args.file})")
    _print_file_importers(args.file, args.path, lang)
    return 0


def cmd_relations(args: argparse.Namespace) -> int:
    """Call-graph orientation for a symbol: summary + body calls (greppable
    hints within the body) + external refs + signature. NO transitive
    call-graph resolution (we don't have an AST index) — just the data
    that lets the LLM decide if a deeper exploration is needed.

    Cheaper than `context` — no embedded body, no `deps`. Use this when
    the LLM is orienting on call SHAPE ("does this method touch the
    auth layer?") rather than editing the method itself.
    """
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw is None:
        return _no_body_error(args.file, args.name, lang, "build relations")
    sig = _sig_from_raw(raw, lang)
    print(
        f"# [codeq relations | target: {args.name} | file: {args.file} | lang: {lang}]"
    )
    if args.no_llm:
        print("# [summary skipped — --no-llm]")
    else:
        _maybe_emit_summary(args.file, args.name, raw)
    _print_section("Signature")
    print(sig)
    _print_section("Internal call hints (from method body, regex)")
    calls = _body_call_hints(raw, exclude_name=args.name)
    if calls:
        for c in calls:
            print(f"# - {c}()")
    else:
        print(
            "# (no candidate method calls detected — body may be very short or text-only)"
        )
    _print_section(f"External refs — callers of '{args.name}'")
    refs = get_refs(args.name, args.path, lang)
    if refs:
        for line in refs:
            print(line)
    else:
        print(f"(no references to '{args.name}' under {args.path})")
    return 0
