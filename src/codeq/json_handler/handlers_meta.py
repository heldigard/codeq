"""JSON handlers: capabilities/check/doctor/rename/tags."""

from __future__ import annotations

import argparse
from typing import Any

from codeq.json_handler.core import emit_json


def _capabilities_json(args: argparse.Namespace) -> int:
    del args
    from codeq.features.capabilities.command import capabilities_payload

    payload = capabilities_payload()
    payload["exit_code"] = 0
    return emit_json(payload, 0)


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


def _rename_error_payload(
    args: argparse.Namespace, error: str, exit_code: int
) -> dict[str, Any]:
    """Shared rename-error envelope (validation/ast-grep failure paths)."""
    return {
        "command": "rename",
        "old": args.old,
        "new": args.new,
        "lang": args.lang or "python",
        "path": args.path,
        "error": error,
        "status": "error",
        "exit_code": exit_code,
    }


def _rename_json(args: argparse.Namespace) -> int:
    from codeq.features.rename.command import (
        _validate_inputs,
        _run_astgrep,
        _looks_like_error,
        _count_dry_run_matches,
        _parse_applied_count,
    )

    old, new = args.old, args.new
    lang = args.lang or "python"
    try:
        _validate_inputs(old, new, lang)
    except SystemExit:
        return emit_json(_rename_error_payload(args, "validation failed", 1), 1)
    rc, out, err = _run_astgrep(old, new, lang, args.path, args.dry_run)
    if rc not in (0, 1) or _looks_like_error(err):
        return emit_json(_rename_error_payload(args, err.strip() or f"rc={rc}", 2), 2)
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
