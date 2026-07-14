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

    payload = capabilities_payload()
    payload["exit_code"] = 0
    return emit_json(payload, 0)


def _find_json(args: argparse.Namespace) -> int:
    from codeq.features.symbol_search.command import get_find_hits

    hits = get_find_hits(args.name, args.path)
    hits_list = [{"file": f, "line": ln, "kind": k, "name": n} for f, ln, k, n in hits]
    exit_code = 0 if hits else 1
    return emit_json(
        {
            "command": "find",
            "name": args.name,
            "path": args.path,
            "count": len(hits),
            "hits": hits_list,
            "exit_code": exit_code,
        },
        exit_code,
    )


def _outline_json(args: argparse.Namespace) -> int:
    from codeq.features.symbol_search.command import get_outline_rows

    rows = get_outline_rows(args.file)
    symbols = [{"line": ln, "kind": k, "name": n} for ln, k, n in rows]
    exit_code = 0 if rows else 1
    return emit_json(
        {
            "command": "outline",
            "file": args.file,
            "count": len(rows),
            "symbols": symbols,
            "exit_code": exit_code,
        },
        exit_code,
    )


def _body_json(args: argparse.Namespace) -> int:
    from codeq.shared.core import lang_of
    from codeq.shared.extraction import _raw_body
    from codeq.shared.locators import _locate_line
    from codeq.features.code_context.command import _summary_payload

    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw is not None:
        summary = _summary_payload(
            args.file,
            args.name,
            raw,
            no_llm=getattr(args, "no_llm", False)
            or not getattr(args, "summary", False),
        )
        return emit_json(
            {
                "command": "body",
                "name": args.name,
                "file": args.file,
                "lang": lang,
                "body": raw,
                "summary": summary if getattr(args, "summary", False) else None,
                "exit_code": 0,
            },
            0,
        )
    ln = _locate_line(args.file, args.name)
    if ln:
        return emit_json(
            {
                "command": "body",
                "name": args.name,
                "file": args.file,
                "lang": lang,
                "line": ln,
                "error": f"no exact body extractor for {lang}",
                "exit_code": 0,
            },
            0,
        )
    return emit_json(
        {
            "command": "body",
            "name": args.name,
            "file": args.file,
            "lang": lang,
            "error": f"no def/class '{args.name}' in {args.file} (lang={lang})",
            "exit_code": 1,
        },
        1,
    )


def _class_json(args: argparse.Namespace) -> int:
    from codeq.shared.config import TYPE_KINDS
    from codeq.shared.core import lang_of
    from codeq.shared.extraction import _class_body
    from codeq.shared.locators import _locate_line
    from codeq.features.code_context.command import _summary_payload

    lang = lang_of(args.file, args.lang)
    raw = _class_body(args.file, args.name, lang)
    if raw is not None:
        summary = _summary_payload(
            args.file,
            args.name,
            raw,
            no_llm=getattr(args, "no_llm", False)
            or not getattr(args, "summary", False),
        )
        return emit_json(
            {
                "command": "class",
                "name": args.name,
                "file": args.file,
                "lang": lang,
                "body": raw,
                "summary": summary if getattr(args, "summary", False) else None,
                "exit_code": 0,
            },
            0,
        )
    ln = _locate_line(args.file, args.name, kinds=TYPE_KINDS)
    if ln:
        return emit_json(
            {
                "command": "class",
                "name": args.name,
                "file": args.file,
                "lang": lang,
                "line": ln,
                "error": f"no exact class-body extractor for {lang}",
                "exit_code": 0,
            },
            0,
        )
    return emit_json(
        {
            "command": "class",
            "name": args.name,
            "file": args.file,
            "lang": lang,
            "error": f"no class/type '{args.name}' in {args.file} (lang={lang})",
            "exit_code": 1,
        },
        1,
    )


def _sig_json(args: argparse.Namespace) -> int:
    from codeq.shared.core import lang_of
    from codeq.shared.extraction import _raw_body, _sig_from_raw

    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw is not None:
        sig = _sig_from_raw(raw, lang)
        return emit_json(
            {
                "command": "sig",
                "name": args.name,
                "file": args.file,
                "lang": lang,
                "signature": sig,
                "exit_code": 0,
            },
            0,
        )
    return emit_json(
        {
            "command": "sig",
            "name": args.name,
            "file": args.file,
            "lang": lang,
            "error": f"no def/class '{args.name}' in {args.file} (lang={lang})",
            "exit_code": 1,
        },
        1,
    )


def _summary_json_cmd(args: argparse.Namespace) -> int:
    from codeq.shared.core import lang_of
    from codeq.shared.extraction import _raw_body
    from codeq.features.code_context.command import _summary_payload

    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw is None:
        from codeq.shared.locators import _locate_line

        ln = _locate_line(args.file, args.name)
        return emit_json(
            {
                "command": "summary",
                "name": args.name,
                "file": args.file,
                "lang": lang,
                "line": ln,
                "error": f"no exact body extractor to summarize for {lang}",
                "exit_code": 1,
            },
            1,
        )
    summary = _summary_payload(args.file, args.name, raw, no_llm=args.no_llm)
    exit_code = 0 if summary.get("status") == "ok" else 2
    return emit_json(
        {
            "command": "summary",
            "name": args.name,
            "file": args.file,
            "lang": lang,
            "summary": summary,
            "exit_code": exit_code,
        },
        exit_code,
    )


def _map_json(args: argparse.Namespace) -> int:
    from codeq.features.repo_map.command import get_repo_map_data

    data = get_repo_map_data(
        args.path,
        include_tests=args.tests,
        top_n=args.top,
        syms_per_file=args.syms,
    )
    if data is None:
        return emit_json(
            {
                "command": "map",
                "path": args.path,
                "error": f"no such directory: {args.path}",
                "exit_code": 2,
            },
            2,
        )
    exit_code = 0 if data["files"] else 1
    data["exit_code"] = exit_code
    return emit_json(data, exit_code)


def _check_json(args: argparse.Namespace) -> int:
    from codeq.features.pattern_check.command import check_pattern

    res = check_pattern(args.pattern, args.lang)
    exit_code = 0 if res["valid"] else 2
    return emit_json(
        {
            "command": "check",
            "pattern": res["pattern"],
            "lang": res["lang"],
            "valid": res["valid"],
            "error": res["error"],
            "hint": res["hint"],
            "exit_code": exit_code,
        },
        exit_code,
    )


def _doctor_json(args: argparse.Namespace) -> int:
    from codeq.features.doctor.command import get_doctor_data

    data = get_doctor_data()
    exit_code = 1 if data["required_missing"] else 0
    data["exit_code"] = exit_code
    return emit_json(data, exit_code)


def _rename_json(args: argparse.Namespace) -> int:
    from codeq.features.rename.command import (
        _validate_inputs,
        _run_astgrep,
        _looks_like_error,
        _count_dry_run_matches,
        _parse_applied_count,
    )

    old = args.old
    new = args.new
    lang = args.lang or "python"
    try:
        _validate_inputs(old, new, lang)
    except SystemExit:
        return emit_json(
            {
                "command": "rename",
                "old": old,
                "new": new,
                "lang": lang,
                "path": args.path,
                "error": "validation failed",
                "status": "error",
                "exit_code": 1,
            },
            1,
        )
    rc, out, err = _run_astgrep(old, new, lang, args.path, args.dry_run)
    if rc not in (0, 1) or _looks_like_error(err):
        return emit_json(
            {
                "command": "rename",
                "old": old,
                "new": new,
                "lang": lang,
                "path": args.path,
                "error": err.strip() or f"rc={rc}",
                "status": "error",
                "exit_code": 2,
            },
            2,
        )
    if args.dry_run:
        n_matches = _count_dry_run_matches(old, new, lang, args.path)
        return emit_json(
            {
                "command": "rename",
                "old": old,
                "new": new,
                "lang": lang,
                "path": args.path,
                "dry_run": True,
                "matches": n_matches,
                "status": "success",
                "exit_code": 0,
            },
            0,
        )
    summary = _parse_applied_count(err) or out.strip() or "(no changes)"
    return emit_json(
        {
            "command": "rename",
            "old": old,
            "new": new,
            "lang": lang,
            "path": args.path,
            "dry_run": False,
            "summary": summary,
            "status": "success",
            "exit_code": 0,
        },
        0,
    )


def _tags_json(args: argparse.Namespace) -> int:
    from pathlib import Path
    from codeq.features.tags.command import (
        CTAGS,
        VENDOR_EXCLUDES,
        ctags_exclude_args,
        run,
    )

    out_file = args.output or str(Path(args.path) / ".tags")
    cmd = [CTAGS, "-R", "--fields=+nKz", "-f", out_file]
    cmd += ctags_exclude_args()
    cmd += [args.path]
    rc, _, err = run(cmd)
    if rc != 0:
        return emit_json(
            {
                "command": "tags",
                "path": args.path,
                "output": out_file,
                "error": err.strip(),
                "status": "error",
                "exit_code": 2,
            },
            2,
        )
    p = Path(out_file)
    if not p.is_file() or p.stat().st_size == 0:
        return emit_json(
            {
                "command": "tags",
                "path": args.path,
                "output": out_file,
                "error": "empty tags file",
                "status": "warning",
                "exit_code": 1,
            },
            1,
        )
    return emit_json(
        {
            "command": "tags",
            "path": args.path,
            "output": out_file,
            "size_bytes": p.stat().st_size,
            "vendor_excludes_count": len(VENDOR_EXCLUDES),
            "status": "success",
            "exit_code": 0,
        },
        0,
    )


# Commands with structured JSON support via pure functions.
_STRUCTURED_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "find": _find_json,
    "outline": _outline_json,
    "body": _body_json,
    "class": _class_json,
    "sig": _sig_json,
    "summary": _summary_json_cmd,
    "map": _map_json,
    "check": _check_json,
    "doctor": _doctor_json,
    "rename": _rename_json,
    "tags": _tags_json,
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
    """Execute the command with structured JSON output."""
    cmd_name = args.cmd

    handler = _STRUCTURED_HANDLERS.get(cmd_name)
    if handler:
        return handler(args)

    # All other commands: capture stdout/stderr text
    func = getattr(args, "func", None)
    if func is None:
        return emit_json(
            {
                "command": cmd_name,
                "exit_code": 2,
                "error": f"no handler for '{cmd_name}'",
            },
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
