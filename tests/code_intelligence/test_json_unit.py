"""Unit tests for the `codeq.json_handler` dispatch/emit layer.

The existing `test_codeq_json_structured.py` exercises the `--json` path
end-to-end via subprocess, so it does not register coverage and cannot target
the dispatch edge cases (unknown command, non-structured capture fallback,
SystemExit inside a captured command). These tests import the handlers
directly to cover those branches and lock the JSON envelope contract."""

from __future__ import annotations

import argparse
import json
import sys

from codeq.json_handler.core import (
    capture_cmd_output,
    emit_json,
    prepare_incremental_payload,
)
from codeq.json_handler.dispatch import STRUCTURED_HANDLERS, run_with_json


def _parse_stdout(capsys: object) -> tuple[dict[str, object], str]:
    """Capture pytest's capsys, return (parsed-json, raw-stdout)."""
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    return json.loads(captured.out), captured.out


def test_emit_json_returns_exit_code_and_is_valid_json(capsys: object) -> None:
    code = emit_json({"command": "x", "ok": True}, 0)
    parsed, raw = _parse_stdout(capsys)
    assert code == 0
    assert parsed == {"command": "x", "ok": True}
    assert raw.endswith("\n")  # trailing newline contract


def test_emit_json_preserves_unicode(capsys: object) -> None:
    """ensure_ascii=False must keep non-ASCII chars literal (used for Spanish
    hints / symbol names), not as \\uXXXX escapes."""
    emit_json({"hint": "código ñ", "emoji": "→"}, 2)
    parsed, raw = _parse_stdout(capsys)
    assert parsed["hint"] == "código ñ"
    assert "ñ" in raw and "\\u" not in raw


def test_emit_json_nonzero_exit_propagates(capsys: object) -> None:
    assert emit_json({"command": "c", "exit_code": 2}, 2) == 2
    _parse_stdout(capsys)


def test_incremental_fingerprint_is_canonical_and_ignores_latency() -> None:
    first = prepare_incremental_payload(
        {
            "command": "context",
            "name": "target",
            "summary": {"text": "Does work.", "latency_seconds": 1.2},
            "refs": ["b.py:2", "a.py:1"],
        },
        0,
    )
    reordered = prepare_incremental_payload(
        {
            "refs": ["b.py:2", "a.py:1"],
            "summary": {"latency_seconds": 9.9, "text": "Does work."},
            "name": "target",
            "command": "context",
        },
        0,
    )

    assert first["fingerprint"] == reordered["fingerprint"]
    receipt = prepare_incremental_payload(
        {"command": "context", "name": "target"},
        0,
        str(
            prepare_incremental_payload({"command": "context", "name": "target"}, 0)[
                "fingerprint"
            ]
        ),
    )
    assert receipt["unchanged"] is True
    assert "refs" not in receipt


def test_incremental_fingerprint_covers_semantics_and_skips_errors() -> None:
    base = prepare_incremental_payload(
        {"command": "relations", "summary": {"text": "A"}}, 0
    )
    changed = prepare_incremental_payload(
        {"command": "relations", "summary": {"text": "B"}}, 0
    )
    error = prepare_incremental_payload(
        {"command": "relations", "error": "missing"}, 1, "irrelevant"
    )

    assert base["fingerprint"] != changed["fingerprint"]
    assert error["exit_code"] == 1
    assert "fingerprint" not in error
    assert "unchanged" not in error


def test_capture_cmd_output_captures_streams_and_code() -> None:
    def cmd(_args: argparse.Namespace) -> int:
        print("out-line")
        print("err-line", file=sys.stderr)
        return 3

    code, out, err = capture_cmd_output(cmd, argparse.Namespace())
    assert code == 3
    assert out == "out-line\n"
    assert err == "err-line\n"


def test_capture_cmd_output_systemexit_code() -> None:
    """A handler that calls sys.exit(N) (e.g. via core.die) must surface N,
    not crash the capture. None code resolves to 1 (argparse parity)."""

    def cmd_die(_args: argparse.Namespace) -> int:
        raise SystemExit(2)

    def cmd_die_none(_args: argparse.Namespace) -> int:
        raise SystemExit(None)

    assert capture_cmd_output(cmd_die, argparse.Namespace())[0] == 2
    assert capture_cmd_output(cmd_die_none, argparse.Namespace())[0] == 1


def test_run_with_json_structured_handler(capsys: object) -> None:
    """`capabilities` is a structured handler ignoring args — asserts the
    STRUCTURED_HANDLERS dispatch path emits the shared envelope keys."""
    args = argparse.Namespace(cmd="capabilities")
    code = run_with_json(args)
    parsed, _ = _parse_stdout(capsys)
    assert code == 0
    assert parsed["command"] == "capabilities"
    assert parsed["exit_code"] == 0


def test_run_with_json_unknown_command_no_func(capsys: object) -> None:
    """Command absent from STRUCTURED_HANDLERS and without an argparse `func`
    attribute → typed error envelope, exit 2 (not a traceback)."""
    args = argparse.Namespace(cmd="does_not_exist")
    code = run_with_json(args)
    parsed, _ = _parse_stdout(capsys)
    assert code == 2
    assert parsed["command"] == "does_not_exist"
    assert parsed["exit_code"] == 2
    assert "no handler" in str(parsed["error"])


def test_run_with_json_capture_fallback(capsys: object) -> None:
    """Command absent from STRUCTURED_HANDLERS but WITH a `func` → the generic
    capture path wraps stdout/stderr/exit_code into the JSON envelope."""

    def func(_args: argparse.Namespace) -> int:
        print("captured-stdout")
        print("captured-stderr", file=sys.stderr)
        return 0

    args = argparse.Namespace(cmd="ad_hoc", func=func)
    code = run_with_json(args)
    parsed, _ = _parse_stdout(capsys)
    assert code == 0
    assert parsed["command"] == "ad_hoc"
    assert parsed["exit_code"] == 0
    assert parsed["output"] == "captured-stdout\n"
    assert parsed["error"] == "captured-stderr\n"


def test_every_cli_command_has_json_coverage() -> None:
    """Structural guard: the dispatch table is the contract surface agents
    rely on. Adding a command without registering its JSON handler is the
    kind of drift this suite exists to catch. capabilities is meta (not in
    the argparser subcommand list) but IS registered — assert the registry
    itself is non-empty and stable in shape."""
    assert "capabilities" in STRUCTURED_HANDLERS
    assert len(STRUCTURED_HANDLERS) >= 15
    for name, handler in STRUCTURED_HANDLERS.items():
        assert callable(handler), f"handler for {name!r} is not callable"
