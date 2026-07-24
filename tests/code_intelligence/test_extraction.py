"""Unit tests for codeq.shared.extraction — covers the low-coverage helpers
(_astgrep_body, _py_body, _brace_collect, _sig_from_raw, _class_body,
_lombok_synthetic_body) with mocked externals (no real binaries needed)."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from codeq.shared.extraction import (
    _astgrep_body,
    _brace_collect,
    _class_body,
    _lombok_synthetic_body,
    _py_body,
    _sig_from_raw,
)

# ---------------------------------------------------------------------------
# _astgrep_body
# ---------------------------------------------------------------------------


class TestAstgrepBody:
    """Mock run() to exercise all branches of _astgrep_body."""

    @patch("codeq.shared.extraction.run")
    def test_returns_text_from_list_match(self, mock_run: MagicMock) -> None:
        """Happy path: JSON list with a dict containing 'text'."""
        payload = [{"text": "def foo():\n    pass\n"}]
        mock_run.return_value = (0, json.dumps(payload), "")
        result = _astgrep_body("pattern", "python", "file.py")
        assert result == "def foo():\n    pass"

    @patch("codeq.shared.extraction.run")
    def test_returns_text_from_dict_match(self, mock_run: MagicMock) -> None:
        """JSON object with 'matches' key."""
        payload = {"matches": [{"text": "fn bar() {}\n"}]}
        mock_run.return_value = (0, json.dumps(payload), "")
        result = _astgrep_body("pattern", "rust", "file.rs")
        assert result == "fn bar() {}"

    @patch("codeq.shared.extraction.run")
    def test_returns_none_on_nonzero_rc(self, mock_run: MagicMock) -> None:
        mock_run.return_value = (1, "", "error")
        assert _astgrep_body("p", "python", "f.py") is None

    @patch("codeq.shared.extraction.run")
    def test_returns_none_on_empty_output(self, mock_run: MagicMock) -> None:
        mock_run.return_value = (0, "  \n", "")
        assert _astgrep_body("p", "python", "f.py") is None

    @patch("codeq.shared.extraction.run")
    def test_returns_none_on_invalid_json(self, mock_run: MagicMock) -> None:
        mock_run.return_value = (0, "not json at all", "")
        assert _astgrep_body("p", "python", "f.py") is None

    @patch("codeq.shared.extraction.run")
    def test_returns_none_when_no_text_field(self, mock_run: MagicMock) -> None:
        """Match dict present but missing 'text' key."""
        payload = [{"kind": "function", "range": [1, 2]}]
        mock_run.return_value = (0, json.dumps(payload), "")
        assert _astgrep_body("p", "python", "f.py") is None

    @patch("codeq.shared.extraction.run")
    def test_returns_none_when_match_is_not_dict(self, mock_run: MagicMock) -> None:
        """List items are strings, not dicts."""
        payload = ["some string"]
        mock_run.return_value = (0, json.dumps(payload), "")
        assert _astgrep_body("p", "python", "f.py") is None

    @patch("codeq.shared.extraction.run")
    def test_returns_first_text_match(self, mock_run: MagicMock) -> None:
        """Multiple matches — first one wins."""
        payload = [{"text": "first"}, {"text": "second"}]
        mock_run.return_value = (0, json.dumps(payload), "")
        assert _astgrep_body("p", "python", "f.py") == "first"


# ---------------------------------------------------------------------------
# _py_body
# ---------------------------------------------------------------------------


class TestPyBody:
    """Create real temp .py files and test AST-based extraction."""

    def test_extracts_simple_function(self) -> None:
        src = "def hello(x: int) -> str:\n    return str(x)\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            result = _py_body(f.name, "hello")
        assert result is not None
        assert "def hello" in result
        assert "return str(x)" in result

    def test_extracts_async_function(self) -> None:
        src = "async def fetch(url):\n    return url\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            result = _py_body(f.name, "fetch")
        assert result is not None
        assert "async def fetch" in result

    def test_extracts_class(self) -> None:
        src = "class Foo:\n    def bar(self):\n        pass\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            result = _py_body(f.name, "Foo")
        assert result is not None
        assert "class Foo" in result
        assert "def bar" in result

    def test_only_class_mode_skips_functions(self) -> None:
        src = "def Foo():\n    pass\n\nclass Foo:\n    x = 1\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            result = _py_body(f.name, "Foo", only_class=True)
        assert result is not None
        assert "class Foo" in result
        assert "def Foo" not in result

    def test_returns_none_for_missing_name(self) -> None:
        src = "def hello():\n    pass\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            assert _py_body(f.name, "nonexistent") is None

    def test_returns_none_for_syntax_error(self) -> None:
        src = "def broken(\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            assert _py_body(f.name, "broken") is None

    def test_returns_none_for_nonexistent_file(self) -> None:
        assert _py_body("/no/such/file.py", "x") is None

    def test_includes_decorator(self) -> None:
        src = "@staticmethod\ndef greet():\n    pass\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            result = _py_body(f.name, "greet")
        assert result is not None
        assert "@staticmethod" in result

    def test_extracts_method_inside_class(self) -> None:
        src = "class C:\n    def method(self):\n        return 42\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            result = _py_body(f.name, "method")
        assert result is not None
        assert "def method" in result
        assert "return 42" in result


# ---------------------------------------------------------------------------
# _brace_collect
# ---------------------------------------------------------------------------


class TestBraceCollect:
    """Test brace counting on in-memory line lists (no I/O)."""

    def test_simple_function(self) -> None:
        lines = [
            "function foo() {",
            "  return 1;",
            "}",
        ]
        result = _brace_collect(lines, start=1)
        assert result is not None
        assert "function foo()" in result
        assert "return 1;" in result
        assert result.endswith("}")

    def test_nested_braces(self) -> None:
        lines = [
            "function outer() {",
            "  if (true) {",
            "    return 0;",
            "  }",
            "}",
        ]
        result = _brace_collect(lines, start=1)
        assert result is not None
        assert result.count("}") == 2  # inner + outer

    def test_returns_none_when_no_open_brace(self) -> None:
        lines = ["int x = 5;", "int y = 10;"]
        assert _brace_collect(lines, start=1) is None

    def test_multiline_signature_before_brace(self) -> None:
        lines = [
            "function bar(",
            "  x: number,",
            "  y: number",
            ") {",
            "  return x + y;",
            "}",
        ]
        result = _brace_collect(lines, start=1)
        assert result is not None
        assert "function bar(" in result
        assert "return x + y;" in result

    def test_brace_in_string_ignored(self) -> None:
        lines = [
            "function f() {",
            '  console.log("}");',
            "  return 1;",
            "}",
        ]
        result = _brace_collect(lines, start=1)
        assert result is not None
        assert "return 1;" in result

    def test_collects_remaining_lines_when_unbalanced(self) -> None:
        """If braces never balance, returns all lines from start when begun."""
        lines = [
            "function broken() {",
            "  // missing closing brace",
        ]
        result = _brace_collect(lines, start=1)
        assert result is not None  # begun=True, but depth > 0 at end
        assert "broken" in result

    def test_start_in_middle(self) -> None:
        lines = [
            "// preamble",
            "function f() {",
            "  x();",
            "}",
            "// trailer",
        ]
        result = _brace_collect(lines, start=2)
        assert result is not None
        assert "// preamble" not in result
        assert "function f()" in result


# ---------------------------------------------------------------------------
# _sig_from_raw
# ---------------------------------------------------------------------------


class TestSigFromRaw:
    """Test signature-extraction logic for Python and brace-langs."""

    def test_python_single_line(self) -> None:
        raw = "def foo(x: int) -> int:\n    return x"
        sig = _sig_from_raw(raw, "python")
        assert sig == "def foo(x: int) -> int:"

    def test_python_multiline(self) -> None:
        raw = "def bar(\n    a: str,\n    b: str\n) -> str:\n    return a + b"
        sig = _sig_from_raw(raw, "python")
        assert sig == "def bar(\n    a: str,\n    b: str\n) -> str:"

    def test_python_class(self) -> None:
        raw = "class MyClass(Base):\n    x = 1"
        sig = _sig_from_raw(raw, "python")
        assert sig == "class MyClass(Base):"

    def test_brace_lang_single_line(self) -> None:
        raw = "function foo(x) {\n  return x;\n}"
        sig = _sig_from_raw(raw, "javascript")
        assert sig == "function foo(x) {"

    def test_brace_lang_multiline_sig(self) -> None:
        raw = "public void process(\n    String input\n) {\n    run();\n}"
        sig = _sig_from_raw(raw, "java")
        assert sig == "public void process(\n    String input\n) {"

    def test_no_stop_marker_returns_all(self) -> None:
        """If there is no colon (python) or brace, returns all stripped."""
        raw = "x = 42\ny = 10"
        sig = _sig_from_raw(raw, "python")
        # No line ends with ':', so all lines are consumed
        assert "x = 42" in sig
        assert "y = 10" in sig

    def test_rust_fn(self) -> None:
        raw = "fn compute(a: i32) -> i32 {\n    a * 2\n}"
        sig = _sig_from_raw(raw, "rust")
        assert sig == "fn compute(a: i32) -> i32 {"

    def test_decorator_stops_at_def_colon(self) -> None:
        raw = "@decorator\ndef func():\n    pass"
        sig = _sig_from_raw(raw, "python")
        # The decorator line does NOT end with ':', the def line does
        assert sig == "@decorator\ndef func():"


# ---------------------------------------------------------------------------
# _class_body
# ---------------------------------------------------------------------------


class TestClassBody:
    """Test _class_body with mocked sub-functions."""

    def test_python_delegates_to_py_body(self) -> None:
        src = "class Widget:\n    size: int = 0\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            result = _class_body(f.name, "Widget", "python")
        assert result is not None
        assert "class Widget" in result

    @patch("codeq.shared.extraction._ts_body", return_value=None)
    @patch("codeq.shared.extraction._astgrep_body", return_value=None)
    @patch("codeq.shared.extraction._locate_line", return_value=None)
    def test_returns_none_when_not_found_brace(
        self, mock_locate: MagicMock, mock_ast: MagicMock, mock_ts: MagicMock
    ) -> None:
        result = _class_body("file.java", "NoSuchClass", "java")
        assert result is None

    @patch("codeq.shared.extraction._ts_body", return_value=None)
    @patch("codeq.shared.extraction._astgrep_body", return_value=None)
    @patch("codeq.shared.extraction._locate_line", return_value=3)
    @patch("codeq.shared.extraction._brace_extract", return_value="class Foo {\n}")
    def test_falls_back_to_brace_extract(
        self,
        mock_brace: MagicMock,
        mock_locate: MagicMock,
        mock_ast: MagicMock,
        mock_ts: MagicMock,
    ) -> None:
        result = _class_body("file.java", "Foo", "java")
        assert result == "class Foo {\n}"
        mock_brace.assert_called_once_with("file.java", start=3)

    @patch("codeq.shared.extraction._astgrep_body")
    def test_astgrep_pattern_hit(self, mock_ast: MagicMock) -> None:
        """If ast-grep returns a body for TS/JS class, use it directly."""
        mock_ast.return_value = "class App { run() {} }"
        result = _class_body("file.ts", "App", "typescript")
        assert result == "class App { run() {} }"

    def test_returns_none_for_unknown_lang(self) -> None:
        """Non-Python, non-brace lang with no patterns returns None."""
        result = _class_body("file.sh", "Foo", "bash")
        assert result is None


# ---------------------------------------------------------------------------
# _lombok_synthetic_body
# ---------------------------------------------------------------------------


class TestLombokSyntheticBody:
    """Test _lombok_synthetic_body with mocked detect_lombok_members."""

    @patch("codeq.shared.lombok.detect_lombok_members")
    def test_returns_synthetic_body(self, mock_detect: MagicMock) -> None:
        @dataclass
        class FakeMember:
            line: int
            kind: str
            name: str
            signature: str
            source: str

        mock_detect.return_value = [
            FakeMember(
                line=10,
                kind="method",
                name="getName",
                signature="public String getName()",
                source="@Getter",
            )
        ]
        result = _lombok_synthetic_body("Foo.java", "getName")
        assert result is not None
        assert "public String getName()" in result
        assert "lombok-generated method from @Getter" in result

    @patch("codeq.shared.lombok.detect_lombok_members")
    def test_returns_none_when_not_lombok(self, mock_detect: MagicMock) -> None:
        mock_detect.return_value = []
        assert _lombok_synthetic_body("Foo.java", "bar") is None
