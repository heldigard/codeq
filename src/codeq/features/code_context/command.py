from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from codeq.shared.config import _RESERVED_KEYWORDS
from codeq.shared.core import die, lang_of
from codeq.features.dependencies.command import cmd_deps
from codeq.shared.extraction import _raw_body, _sig_from_raw
from codeq.shared.locators import _locate_line
from codeq.shared.llm import _maybe_emit_summary, _OLLAMA_DISABLED_PREFIX, _OLLAMA_SUMMARY_PREFIX, _summarize_code
from codeq.features.references.command import cmd_refs

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
        ln = _locate_line(args.file, args.name)
        if ln:
            print(f"{args.file}:{ln}", file=sys.stderr)
            print("(no exact body extractor; can't summarize.)", file=sys.stderr)
        else:
            print(f"no def/class '{args.name}' in {args.file} (lang={lang})", file=sys.stderr)
        return 1
    summary, reason, cold = _summarize_code(args.file, args.name, raw, no_llm=args.no_llm)
    if summary:
        # `reason` holds the model tag on success (see _summarize_code return).
        print(_OLLAMA_SUMMARY_PREFIX.format(
            model=reason or "local-llm",
            lat=f"{cold:.1f}" if cold else "?",
        ))
        print(f"# {summary}")
        return 0
    # Ollama unavailable — degrade gracefully so a missing daemon never
    # blocks the agent loop. Print the reason to stderr (visible when
    # debugging, silent in the agent loop's pipe-to-LLM path).
    print(_OLLAMA_DISABLED_PREFIX.format(reason=reason or "unknown"),
          file=sys.stderr)
    return 2  # distinct from "no symbol found" (1) so callers can branch


def _print_section(title: str) -> None:
    """Markdown section header. Visible in LLM context."""
    print()
    print(f"# === {title} ===")
    print()


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
        # skip signature line and explicit comments / decorators
        s = line.strip()
        if not s or s.startswith(("#", "//", "/*", "*", "@")):
            continue
        for m in rx.finditer(s):
            name = m.group(1).lstrip(".")
            if name in _RESERVED_KEYWORDS or name in seen:
                continue
            # Skip the symbol's own name — the signature line `name(...)` is
            # not a self-call, it's the declaration. Also skip bare `name`
            # (non-dotted) when it equals exclude_name (recursion is rare and
            # not the point of an orientation hint).
            tail = name.rsplit(".", 1)[-1]
            if exclude_name and (tail == exclude_name or name == exclude_name):
                continue
            seen.add(name)
            out.append(name)
    return out[:25]  # cap so the output stays bounded


def cmd_context(args: argparse.Namespace) -> int:
    """Bundled context for code editing: summary + signature + body + call
    sites (refs) + file-level imports. ONE call replaces the typical
    LLM exploration of `find + body + refs + deps` (3-5 tool calls + a
    re-read of the body). Ollama enriches ONLY with a tagged 1-line
    summary; the rest is structural data.

    Use this when the agent is ABOUT TO EDIT a function/method and wants
    to know: what it does, who calls it, what it imports.
    """
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw is None:
        ln = _locate_line(args.file, args.name)
        if ln:
            print(f"{args.file}:{ln}", file=sys.stderr)
            print("(no exact body extractor; can't build context.)", file=sys.stderr)
        else:
            print(f"no def/class '{args.name}' in {args.file} (lang={lang})", file=sys.stderr)
        return 1
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
    proj_dir = args.path
    refs_args = argparse.Namespace(
        name=args.name, lang=lang, path=proj_dir,
    )
    rc = cmd_refs(refs_args)
    # cmd_refs prints to stdout directly; that's fine here — we want it
    # embedded. _print_section already emitted the header.
    print(f"# [refs exit: {rc}]")
    _print_section(f"Imports of {args.file} (deps)")
    deps_args = argparse.Namespace(file=args.file, lang=lang)
    rc = cmd_deps(deps_args)
    print(f"# [deps exit: {rc}]")
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
        ln = _locate_line(args.file, args.name)
        if ln:
            print(f"{args.file}:{ln}", file=sys.stderr)
            print("(no exact body extractor; can't build relations.)", file=sys.stderr)
        else:
            print(f"no def/class '{args.name}' in {args.file} (lang={lang})", file=sys.stderr)
        return 1
    sig = _sig_from_raw(raw, lang)
    print(f"# [codeq relations | target: {args.name} | file: {args.file} | lang: {lang}]")
    if args.no_llm:
        print("# [summary skipped — --no-llm]")
    else:
        _maybe_emit_summary(args.file, args.name, raw)
    _print_section("Signature")
    print(sig)
    _print_section(f"Internal call hints (from method body, regex)")
    calls = _body_call_hints(raw, exclude_name=args.name)
    if calls:
        for c in calls:
            print(f"# - {c}()")
    else:
        print("# (no candidate method calls detected — body may be very short or text-only)")
    _print_section(f"External refs — callers of '{args.name}'")
    refs_args = argparse.Namespace(
        name=args.name, lang=lang, path=args.path,
    )
    rc = cmd_refs(refs_args)
    print(f"# [refs exit: {rc}]")
    return 0
