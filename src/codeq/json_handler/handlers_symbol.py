"""JSON handlers: find/outline/body/class/sig/summary."""

from __future__ import annotations

import argparse

from codeq.json_handler.core import emit_json


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
