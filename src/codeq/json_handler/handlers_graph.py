"""JSON handlers: refs/deps/rdeps/context/relations/map."""

from __future__ import annotations

import argparse

from codeq.json_handler.core import emit_json


def _refs_json(args: argparse.Namespace) -> int:
    from codeq.features.references.command import get_refs

    limit = getattr(args, "limit", 200) or 0
    if getattr(args, "quick", False) and (limit == 0 or limit > 20):
        limit = 20
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
            "quick": bool(getattr(args, "quick", False)),
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
    from codeq.features.code_context.command import (
        _QUICK_REFS_LIMIT,
        _ContextOptions,
        build_context_payload,
    )

    payload, exit_code = build_context_payload(
        args.name,
        args.file,
        args.path,
        _ContextOptions(
            lang_override=args.lang,
            no_llm=getattr(args, "no_llm", False),
            mode="full",
        ),
    )
    if getattr(args, "quick", False) and "refs" in payload:
        payload["refs"] = payload["refs"][:_QUICK_REFS_LIMIT]
        payload["refs_count"] = len(payload["refs"])
        payload["truncated"] = len(payload["refs"]) >= _QUICK_REFS_LIMIT
    return emit_json(payload, exit_code)


def _relations_json(args: argparse.Namespace) -> int:
    from codeq.features.code_context.command import (
        _QUICK_REFS_LIMIT,
        _ContextOptions,
        build_relations_payload,
    )

    payload, exit_code = build_relations_payload(
        args.name,
        args.file,
        args.path,
        _ContextOptions(
            lang_override=args.lang,
            no_llm=getattr(args, "no_llm", False),
        ),
    )
    if getattr(args, "quick", False) and "refs" in payload:
        payload["refs"] = payload["refs"][:_QUICK_REFS_LIMIT]
        payload["refs_count"] = len(payload["refs"])
        payload["truncated"] = len(payload["refs"]) >= _QUICK_REFS_LIMIT
    return emit_json(payload, exit_code)


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
