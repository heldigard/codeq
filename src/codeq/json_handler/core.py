"""JSON emit/capture helpers for codeq --json mode."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from typing import Any


def prepare_incremental_payload(
    payload: dict[str, Any],
    exit_code: int,
    since_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Attach a deterministic fingerprint or return an unchanged receipt.

    The fingerprint covers the successful semantic JSON bundle after any
    command-level truncation. Volatile local-LLM latency metadata is excluded,
    but summary text and every structural fact remain covered. No cache is
    stored: callers opt into a smaller repeat response by returning the prior
    fingerprint.
    """
    result = dict(payload)
    result["exit_code"] = exit_code
    if exit_code != 0:
        return result

    fingerprint_input = dict(result)
    summary = fingerprint_input.get("summary")
    if isinstance(summary, dict) and "latency_seconds" in summary:
        fingerprint_input["summary"] = {
            key: value for key, value in summary.items() if key != "latency_seconds"
        }
    canonical = json.dumps(
        fingerprint_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fingerprint = hashlib.sha256(canonical).hexdigest()

    if since_fingerprint == fingerprint:
        identity_keys = ("command", "name", "file", "path", "lang")
        receipt = {key: result[key] for key in identity_keys if key in result}
        receipt.update(
            {
                "exit_code": 0,
                "fingerprint": fingerprint,
                "unchanged": True,
            }
        )
        return receipt

    result["fingerprint"] = fingerprint
    result["unchanged"] = False
    return result


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
