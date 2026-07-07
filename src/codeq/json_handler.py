"""JSON output handler for codeq --json mode.

Provides structured JSON output for all subcommands. Commands with pure-function
APIs (refs, deps, rdeps) build structured JSON directly; others capture
stdout/stderr text in a JSON envelope.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Callable


def emit_json(data: dict[str, Any], exit_code: int) -> int:
    """Print structured JSON and return exit code."""
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    print()  # trailing newline
    return exit_code


def _refs_json(args: argparse.Namespace) -> int:
    from codeq.features.references.command import get_refs

    limit = getattr(args, "limit", 200) or 0
    refs = get_refs(args.name, args.path, args.lang, limit=limit)
    return emit_json(
        {
            "command": "refs",
            "name": args.name,
            "path": args.path,
            "lang": args.lang,
            "count": len(refs),
            "refs": refs,
            "truncated": bool(limit and len(refs) >= limit),
        },
        0 if refs else 1,
    )


def _deps_json(args: argparse.Namespace) -> int:
    from codeq.features.dependencies.command import get_deps
    from codeq.shared.core import lang_of

    lang = lang_of(args.file, args.lang)
    rows = get_deps(args.file, lang)
    imports = [{"line": ln, "kind": kind, "module": mod} for ln, kind, mod in rows]
    return emit_json(
        {
            "command": "deps",
            "file": args.file,
            "lang": lang,
            "count": len(rows),
            "imports": imports,
        },
        0 if rows else 1,
    )


def _rdeps_json(args: argparse.Namespace) -> int:
    from codeq.features.dependencies.command import get_rdeps
    from codeq.shared.core import lang_of

    lang = lang_of(args.file, args.lang)
    limit = getattr(args, "limit", 200) or 0
    rows = get_rdeps(args.file, args.path, lang, limit=limit)
    importers = [{"file": path, "line": ln, "text": text} for path, ln, text in rows]
    return emit_json(
        {
            "command": "rdeps",
            "file": args.file,
            "path": args.path,
            "lang": lang,
            "count": len(rows),
            "importers": importers,
        },
        0 if rows else 1,
    )


def _context_json(args: argparse.Namespace) -> int:
    from codeq.features.code_context.command import build_context_payload

    payload, exit_code = build_context_payload(
        args.name,
        args.file,
        args.path,
        args.lang,
        no_llm=getattr(args, "no_llm", False),
    )
    return emit_json(payload, exit_code)


def _relations_json(args: argparse.Namespace) -> int:
    from codeq.features.code_context.command import build_relations_payload

    payload, exit_code = build_relations_payload(
        args.name,
        args.file,
        args.path,
        args.lang,
        no_llm=getattr(args, "no_llm", False),
    )
    return emit_json(payload, exit_code)


def _capabilities_json(args: argparse.Namespace) -> int:
    del args
    from codeq.features.capabilities.command import capabilities_payload

    return emit_json(capabilities_payload(), 0)


# Commands with structured JSON support via pure functions.
_STRUCTURED_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "refs": _refs_json,
    "deps": _deps_json,
    "rdeps": _rdeps_json,
    "context": _context_json,
    "relations": _relations_json,
    "capabilities": _capabilities_json,
}


def _capture_cmd_output(
    func: Callable[[argparse.Namespace], int], args: argparse.Namespace
) -> tuple[int, str, str]:
    """Execute func(args) with stdout/stderr captured. Returns (exit_code, stdout, stderr)."""
    out_buf, err_buf = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            exit_code = func(args)
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 1
    return exit_code, out_buf.getvalue(), err_buf.getvalue()


def run_with_json(args: argparse.Namespace) -> int:
    """Execute the command with JSON output.

    For commands that have pure-function APIs (refs, deps, rdeps), we build
    structured JSON directly. For others, we capture text output in a JSON
    envelope."""
    cmd_name = args.cmd

    handler = _STRUCTURED_HANDLERS.get(cmd_name)
    if handler:
        return handler(args)

    # All other commands: capture stdout/stderr text
    func = getattr(args, "func", None)
    if func is None:
        return emit_json(
            {"command": cmd_name, "exit_code": 2, "error": f"no handler for '{cmd_name}'"},
            2,
        )
    exit_code, stdout_text, stderr_text = _capture_cmd_output(func, args)
    return emit_json(
        {
            "command": cmd_name,
            "exit_code": exit_code,
            "output": stdout_text,
            "error": stderr_text or None,
        },
        exit_code,
    )
