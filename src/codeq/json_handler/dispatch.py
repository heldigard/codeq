"""Dispatch --json mode to structured handlers or capture fallback."""

from __future__ import annotations

import argparse
import io
from collections.abc import Callable
from contextlib import redirect_stderr

from codeq.json_handler.core import capture_cmd_output, emit_json
from codeq.json_handler.handlers import (
    _body_json,
    _capabilities_json,
    _check_json,
    _class_json,
    _context_json,
    _deps_json,
    _doctor_json,
    _find_json,
    _map_json,
    _outline_json,
    _rdeps_json,
    _refs_json,
    _relations_json,
    _rename_json,
    _sig_json,
    _summary_json_cmd,
    _tags_json,
)

# Commands with structured JSON support via pure functions.
STRUCTURED_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
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


def _invoke_structured(
    cmd_name: str,
    handler: Callable[[argparse.Namespace], int],
    args: argparse.Namespace,
) -> int:
    """Run a structured JSON handler, converting die()/SystemExit to JSON.

    Feature functions call ``die()`` (plain stderr + sys.exit) on hard errors
    like a missing file. Under ``--json`` that would leak plain text and break
    the JSON contract, so we capture stderr and re-wrap the failure as a JSON
    error envelope. Handlers only emit JSON at the end (after data collection),
    so stdout is always empty when die() fires mid-collection.
    """
    err_buf = io.StringIO()
    try:
        with redirect_stderr(err_buf):
            return handler(args)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 1
        msg = err_buf.getvalue().strip().removeprefix("codeq: ")
        return emit_json(
            {
                "command": cmd_name,
                "error": msg or f"exit code {code}",
                "exit_code": code,
            },
            code,
        )


def run_with_json(args: argparse.Namespace) -> int:
    """Execute the command with structured JSON output."""
    cmd_name = args.cmd

    handler = STRUCTURED_HANDLERS.get(cmd_name)
    if handler:
        return _invoke_structured(cmd_name, handler, args)

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
    exit_code, stdout_text, stderr_text = capture_cmd_output(func, args)
    return emit_json(
        {
            "command": cmd_name,
            "exit_code": exit_code,
            "output": stdout_text,
            "error": stderr_text or None,
        },
        exit_code,
    )
