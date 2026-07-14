"""Unit tests for codeq.shared.core — covers _parse_ctags_line edge cases,
ctags_exclude_args, run() timeout handling, and lang_of()."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from codeq.shared.core import (
    _parse_ctags_line,
    ctags_exclude_args,
    die,
    lang_of,
    run,
)


# ---------------------------------------------------------------------------
# _parse_ctags_line
# ---------------------------------------------------------------------------

class TestParseCtagsLine:
    """Exercise every branch of _parse_ctags_line."""

    def test_pseudo_tag_returns_none(self) -> None:
        assert _parse_ctags_line("!_TAG_FILE_FORMAT\t2\t/extended/") is None

    def test_short_line_returns_none(self) -> None:
        """Fewer than 3 tab-separated fields."""
        assert _parse_ctags_line("foo\tbar") is None
        assert _parse_ctags_line("only_one") is None

    def test_no_alpha_chars_returns_none(self) -> None:
        """Names with no alphabetic chars (numeric/garbage) are rejected."""
        assert _parse_ctags_line("123\tfile.py\t/pattern/") is None
        assert _parse_ctags_line("_000\tfile.py\t/pattern/") is None

    def test_basic_valid_line(self) -> None:
        line = "foo\tbar.py\t/pattern/;\"\tkind:function\tline:42"
        result = _parse_ctags_line(line)
        assert result is not None
        name, file, kind, line_no = result
        assert name == "foo"
        assert file == "bar.py"
        assert kind == "function"
        assert line_no == "42"

    def test_missing_kind_and_line(self) -> None:
        """When parts[3:] has no kind:/line: fields, defaults to '?'."""
        line = "myFunc\tapp.js\t/pattern/;\"\tscope:Foo"
        result = _parse_ctags_line(line)
        assert result is not None
        name, file, kind, line_no = result
        assert name == "myFunc"
        assert file == "app.js"
        assert kind == "?"
        assert line_no == "?"

    def test_kind_without_line(self) -> None:
        line = "hello\tmod.go\t/pattern/;\"\tkind:function"
        result = _parse_ctags_line(line)
        assert result is not None
        assert result[2] == "function"
        assert result[3] == "?"

    def test_line_without_kind(self) -> None:
        line = "greet\tmod.rs\t/pattern/;\"\tline:7"
        result = _parse_ctags_line(line)
        assert result is not None
        assert result[2] == "?"
        assert result[3] == "7"

    def test_name_with_underscore_prefix_is_valid(self) -> None:
        """Names like '_init' have alpha chars and should pass."""
        line = "_init\tlib.py\t/pattern/;\"\tkind:function\tline:1"
        result = _parse_ctags_line(line)
        assert result is not None
        assert result[0] == "_init"

    def test_empty_line(self) -> None:
        assert _parse_ctags_line("") is None

    def test_exactly_three_fields(self) -> None:
        """Exactly 3 tab fields — valid but no kind/line extras."""
        line = "main\tmain.go\t/func main()/"
        result = _parse_ctags_line(line)
        assert result is not None
        assert result == ("main", "main.go", "?", "?")


# ---------------------------------------------------------------------------
# ctags_exclude_args
# ---------------------------------------------------------------------------

class TestCtagsExcludeArgs:
    def test_returns_exclude_flags(self) -> None:
        args = ctags_exclude_args()
        assert isinstance(args, list)
        assert len(args) > 0
        assert all(a.startswith("--exclude=") for a in args)

    def test_includes_vendor_excludes(self) -> None:
        args = ctags_exclude_args()
        vals = [a.split("=", 1)[1] for a in args]
        assert "node_modules" in vals
        assert ".venv" in vals

    def test_includes_cache_globs(self) -> None:
        args = ctags_exclude_args()
        vals = [a.split("=", 1)[1] for a in args]
        assert "*_cache" in vals

    def test_includes_file_excludes(self) -> None:
        args = ctags_exclude_args()
        vals = [a.split("=", 1)[1] for a in args]
        assert "*.jsonl" in vals
        assert ".tags" in vals


# ---------------------------------------------------------------------------
# run() — timeout
# ---------------------------------------------------------------------------

class TestRunTimeout:
    @patch("codeq.shared.core.subprocess.run")
    def test_normal_execution(self, mock_subp: MagicMock) -> None:
        mock_subp.return_value = MagicMock(returncode=0, stdout="out", stderr="err")
        rc, out, err = run(["echo", "hello"])
        assert rc == 0
        assert out == "out"
        assert err == "err"

    @patch("codeq.shared.core.subprocess.run")
    def test_timeout_calls_die(self, mock_subp: MagicMock) -> None:
        mock_subp.side_effect = subprocess.TimeoutExpired(cmd="ctags", timeout=60)
        with pytest.raises(SystemExit) as exc_info:
            run(["ctags", "--fields=+Kzn", "-f", "-", "file.py"])
        assert exc_info.value.code == 2

    @patch("codeq.shared.core.subprocess.run")
    def test_timeout_empty_cmd(self, mock_subp: MagicMock) -> None:
        """Timeout with an empty cmd list still works (tool = 'command')."""
        mock_subp.side_effect = subprocess.TimeoutExpired(cmd="", timeout=60)
        with pytest.raises(SystemExit) as exc_info:
            run([])
        assert exc_info.value.code == 2

    @patch("codeq.shared.core.subprocess.run")
    def test_nonzero_return_code(self, mock_subp: MagicMock) -> None:
        mock_subp.return_value = MagicMock(returncode=1, stdout="", stderr="fail")
        rc, out, err = run(["false"])
        assert rc == 1
        assert err == "fail"


# ---------------------------------------------------------------------------
# lang_of
# ---------------------------------------------------------------------------

class TestLangOf:
    def test_override_wins(self) -> None:
        assert lang_of("file.xyz", "python") == "python"

    def test_known_extension_py(self) -> None:
        assert lang_of("module.py", None) == "python"

    def test_known_extension_ts(self) -> None:
        assert lang_of("app.ts", None) == "typescript"

    def test_known_extension_java(self) -> None:
        assert lang_of("App.java", None) == "java"

    def test_known_extension_go(self) -> None:
        assert lang_of("main.go", None) == "go"

    def test_known_extension_js(self) -> None:
        assert lang_of("index.js", None) == "javascript"

    def test_known_extension_rs(self) -> None:
        assert lang_of("lib.rs", None) == "rust"

    def test_unknown_extension_dies(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            lang_of("file.xyz", None)
        assert exc_info.value.code == 2

    def test_pyi_maps_to_python(self) -> None:
        assert lang_of("stubs.pyi", None) == "python"

    def test_jsx_maps_to_javascript(self) -> None:
        assert lang_of("component.jsx", None) == "javascript"

    def test_tsx_maps_to_typescript(self) -> None:
        assert lang_of("component.tsx", None) == "typescript"


# ---------------------------------------------------------------------------
# die
# ---------------------------------------------------------------------------

class TestDie:
    def test_die_exits_with_code(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            die("test error", code=3)
        assert exc_info.value.code == 3

    def test_die_default_code(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            die("boom")
        assert exc_info.value.code == 2
