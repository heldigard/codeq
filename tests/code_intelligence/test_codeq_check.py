from __future__ import annotations

import argparse
from unittest.mock import patch
import pytest

from codeq.features.pattern_check.command import cmd_check


def test_cmd_check_no_probe_for_lang() -> None:
    args = argparse.Namespace(lang="invalid_lang", pattern="print($X)")
    with pytest.raises(SystemExit) as excinfo:
        cmd_check(args)
    assert excinfo.value.code == 2


def test_cmd_check_valid_pattern(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(lang="python", pattern="print($X)")
    with patch("codeq.features.pattern_check.command.run", return_value=(0, "", "")) as mock_run:
        rc = cmd_check(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "VALID — pattern parses cleanly" in captured.out
        assert "PATTERN: print($X)" in captured.out
        mock_run.assert_called_once()


def test_cmd_check_invalid_multiple_nodes(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(lang="python", pattern="except:")
    # ast-grep reports multiple AST nodes
    err_msg = "Error: multiple AST nodes found"
    with patch("codeq.features.pattern_check.command.run", return_value=(1, "", err_msg)):
        rc = cmd_check(args)
        assert rc == 2
        captured = capsys.readouterr()
        assert "INVALID — pattern is NOT a single AST node" in captured.err
        assert "HINT:    Wrap it in its complete parent statement" in captured.err


def test_cmd_check_invalid_error_node(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(lang="python", pattern="def foo(")
    # ast-grep reports error node (syntax error)
    err_msg = "Error: pattern contains ERROR node"
    with patch("codeq.features.pattern_check.command.run", return_value=(1, "", err_msg)):
        rc = cmd_check(args)
        assert rc == 2
        captured = capsys.readouterr()
        assert "parsed but contains an ERROR node" in captured.err
        assert "Refine the pattern; it will match nothing" in captured.err


def test_cmd_check_invalid_cannot_parse(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(lang="python", pattern="[invalid")
    err_msg = "Error: cannot parse pattern\nSome detail message"
    with patch("codeq.features.pattern_check.command.run", return_value=(1, "", err_msg)):
        rc = cmd_check(args)
        assert rc == 2
        captured = capsys.readouterr()
        assert "pattern failed to parse" in captured.err
        assert "HINT:    Some detail message" in captured.err


def test_cmd_check_invalid_other_error(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(lang="python", pattern="[invalid")
    err_msg = "Something unspecified happened\nLine two other details"
    with patch("codeq.features.pattern_check.command.run", return_value=(1, "", err_msg)):
        rc = cmd_check(args)
        assert rc == 2
        captured = capsys.readouterr()
        assert "INVALID." in captured.err
        assert "HINT:    Line two other details" in captured.err

