"""JSON emit/capture helpers for codeq --json mode."""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from typing import Any


def emit_json(data: dict[str, Any], exit_code: int) -> int:
    """Print structured JSON and return exit code."""
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    print()  # trailing newline
    return exit_code


def capture_cmd_output(
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
