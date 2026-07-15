from __future__ import annotations

import argparse
import builtins
from typing import Any
from unittest.mock import MagicMock, patch
import pytest

from codeq.features.doctor.command import (
    cmd_doctor,
    _detect,
    _detect_tool,
    _detect_python_module,
    _manager_available,
    _try_install,
    _run_install,
)


def test_detect_tool_present() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/dummy"),
        patch("subprocess.run") as mock_run,
    ):
        mock_proc = MagicMock()
        mock_proc.stdout = "dummy version 1.2.3\n"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        path, ver = _detect("dummy")
        assert path == "/usr/bin/dummy"
        assert ver == "dummy version 1.2.3"
        mock_run.assert_called_once_with(
            ["dummy", "--version"], capture_output=True, text=True, timeout=6
        )


def test_detect_tool_run_error() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/dummy"),
        patch("subprocess.run", side_effect=OSError("Permission denied")),
    ):
        path, ver = _detect("dummy")
        assert path == "/usr/bin/dummy"
        assert ver is None


def test_detect_tool_missing() -> None:
    with patch("shutil.which", return_value=None):
        path, ver = _detect("dummy")
        assert path is None
        assert ver is None


def test_detect_python_module_present() -> None:
    mock_spec = MagicMock()
    mock_module = MagicMock()
    mock_module.__version__ = "2.0.0"

    with (
        patch("importlib.util.find_spec", return_value=mock_spec),
        patch("builtins.__import__", return_value=mock_module),
    ):
        path, ver = _detect_python_module("dummy_module")
        assert path == "python:dummy_module"
        assert ver == "2.0.0"


def test_detect_python_module_missing() -> None:
    with patch("importlib.util.find_spec", return_value=None):
        path, ver = _detect_python_module("dummy_module")
        assert path is None
        assert ver is None


def test_detect_python_module_import_error() -> None:
    mock_spec = MagicMock()
    original_import = builtins.__import__

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "dummy_module":
            raise ImportError("No module")
        return original_import(name, *args, **kwargs)

    with (
        patch("importlib.util.find_spec", return_value=mock_spec),
        patch("builtins.__import__", side_effect=mock_import),
    ):
        path, ver = _detect_python_module("dummy_module")
        assert path == "python:dummy_module"
        assert ver == "(python module)"


def test_manager_available() -> None:
    with patch(
        "shutil.which",
        side_effect=lambda name: "/bin/cargo" if name == "cargo" else None,
    ):
        assert _manager_available("cargo") is True
        assert _manager_available("npm") is False


def test_run_install_success() -> None:
    with patch("subprocess.call", return_value=0):
        res = _run_install("ast-grep", "npm", "npm install -g @ast-grep/cli")
        assert "installed ast-grep via npm" in res


def test_run_install_failure() -> None:
    with patch("subprocess.call", return_value=1):
        res = _run_install("ast-grep", "npm", "npm install -g @ast-grep/cli")
        assert "FAILED ast-grep via npm (rc=1)" in res


def test_run_install_oserror() -> None:
    with patch("subprocess.call", side_effect=OSError("Command not found")):
        res = _run_install("ast-grep", "npm", "npm install -g @ast-grep/cli")
        assert "FAILED ast-grep via npm" in res
        assert "Command not found" in res


def test_try_install_no_sudo_available() -> None:
    tool: dict[str, object] = {
        "name": "ast-grep",
        "managers": {
            "npm": "npm install -g @ast-grep/cli",
            "cargo": "cargo install ast-grep-cli",
            "brew": "brew install ast-grep",
        },
    }
    with (
        patch(
            "shutil.which",
            side_effect=lambda name: "/bin/cargo" if name == "cargo" else None,
        ),
        patch("subprocess.call", return_value=0),
    ):
        # cargo is available, npm is not, so it uses cargo
        res = _try_install(tool)
        assert "installed ast-grep via cargo" in res


def test_try_install_manual_hint_fallback() -> None:
    tool: dict[str, object] = {
        "name": "ast-grep",
        "managers": {
            "npm": "npm install -g @ast-grep/cli",
            "brew": "brew install ast-grep",
        },
    }
    # No package managers available
    with (
        patch("shutil.which", return_value=None),
        patch("platform.system", return_value="Darwin"),
    ):
        res = _try_install(tool)
        assert "manual: brew install ast-grep" in res


def test_cmd_doctor_all_present(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(install=False)
    # mock all tools detected as OK
    with patch(
        "codeq.features.doctor.command._detect_tool", return_value=("/bin/tool", "1.0")
    ):
        rc = cmd_doctor(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "all required binaries present" in captured.out
        assert "ctags        OK" in captured.out


def test_cmd_doctor_required_missing(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(install=False)

    # Mock detection: ctags is missing, others OK
    def mock_detect(tool: dict[str, object]) -> tuple[str | None, str | None]:
        if tool["name"] == "ctags":
            return None, None
        return "/bin/tool", "1.0"

    with patch("codeq.features.doctor.command._detect_tool", side_effect=mock_detect):
        rc = cmd_doctor(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "required binaries missing" in captured.err
        assert "missing binaries — install hints" in captured.out
        assert "ctags        MISSING" in captured.out


def test_cmd_doctor_with_install(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(install=True)

    # Mock detection: shellcheck missing, cargo available to install
    def mock_detect(tool: dict[str, object]) -> tuple[str | None, str | None]:
        if tool["name"] == "shellcheck":
            return None, None
        return "/bin/tool", "1.0"

    with (
        patch("codeq.features.doctor.command._detect_tool", side_effect=mock_detect),
        patch("shutil.which", return_value=None),
        patch("platform.system", return_value="Linux"),
    ):
        # Since cargo/npm are not available, it should output manual hint
        rc = cmd_doctor(args)
        assert rc == 0  # shellcheck is optional, so it exits 0
        captured = capsys.readouterr()
        assert "shellcheck   MISSING" in captured.out
        assert "manual: sudo apt install shellcheck" in captured.out


def test_detect_tool() -> None:
    tool_bin: dict[str, object] = {"name": "ast-grep"}
    tool_mod: dict[str, object] = {
        "name": "tree-sitter",
        "python_module": "tree_sitter_language_pack",
    }

    with (
        patch(
            "codeq.features.doctor.command._detect",
            return_value=("/bin/ast-grep", "0.43.0"),
        ) as mock_detect,
        patch(
            "codeq.features.doctor.command._detect_python_module",
            return_value=("python:tree_sitter_language_pack", "1.0"),
        ) as mock_detect_mod,
    ):
        p1, v1 = _detect_tool(tool_bin)
        assert p1 == "/bin/ast-grep"
        assert v1 == "0.43.0"
        mock_detect.assert_called_once_with("ast-grep")

        p2, v2 = _detect_tool(tool_mod)
        assert p2 == "python:tree_sitter_language_pack"
        assert v2 == "1.0"
        mock_detect_mod.assert_called_once_with("tree_sitter_language_pack")
