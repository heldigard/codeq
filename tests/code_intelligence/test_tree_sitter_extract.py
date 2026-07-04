"""Tests for the optional tree-sitter body extraction (`ts_body`).

These tests exercise the AST-exact path for brace-langs. They SKIP when
tree-sitter is not installed (optional dep) so the suite stays green on
dep-free installs. The key regression is the **regex-literal-brace** case:
`_scan_braces` (the brace-count heuristic) misreads an unbalanced `}` inside
a regex literal and truncates the body; tree-sitter's grammar parses regex
literals correctly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from codeq.shared.tree_sitter_extract import ts_available, ts_body

pytestmark = pytest.mark.skipif(not ts_available(), reason="tree-sitter not installed")


def _write(root: str, name: str, body: str) -> Path:
    f = Path(root) / name
    f.write_text(body)
    return f


def test_ts_body_javascript_regex_literal_brace() -> None:
    """Regression: an unbalanced `}` inside a regex literal (`/a}b/`) breaks
    the brace-count heuristic (it closes the function early at line 2).
    tree-sitter parses the regex literal correctly and returns the full body.
    This is the one residual gap `_scan_braces` cannot close on its own."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(
            tmp,
            "a.js",
            "function foo() {\n  const re = /a}b/;\n  return re;\n}\n",
        )
        out = ts_body("foo", str(f), "javascript")
        assert out is not None, "ts_body returned None for a real function"
        # the body must include ALL three interior lines — the brace-count
        # path truncates after line 2 (`/a}b/`) because of the stray `}`.
        assert "return re;" in out, f"body truncated by regex-literal brace: {out!r}"
        assert out.count("\n") >= 3, f"body too short: {out!r}"


def test_ts_body_typescript_function_with_annotation() -> None:
    """A TS function with a return-type annotation extracts cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(
            tmp,
            "a.ts",
            "function foo(x: number): string {\n  return String(x);\n}\n",
        )
        out = ts_body("foo", str(f), "typescript")
        assert out is not None
        assert "function foo" in out
        assert "return String(x);" in out


def test_ts_body_java_method_inside_class() -> None:
    """Java methods are nested inside class_body — `_walk` must descend into
    the class node to find the method_declaration."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(
            tmp,
            "C.java",
            "class C {\n  void bar() { return; }\n  int baz() { return 1; }\n}\n",
        )
        out = ts_body("baz", str(f), "java")
        assert out is not None, "nested Java method not found"
        assert "int baz" in out
        assert "return 1" in out


def test_ts_body_go_function_and_method() -> None:
    """Go: top-level func (identifier name) and method (field_identifier name)."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(
            tmp,
            "a.go",
            "package main\nfunc foo() { return }\nfunc (r R) bar() { return }\n",
        )
        assert ts_body("foo", str(f), "go") is not None
        out = ts_body("bar", str(f), "go")
        assert out is not None, "Go method (field_identifier name) not found"
        assert "func (r R) bar()" in out


def test_ts_body_rust_function() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(tmp, "a.rs", "fn foo() {\n  let x = 1;\n}\n")
        out = ts_body("foo", str(f), "rust")
        assert out is not None
        assert "let x = 1;" in out


def test_ts_body_type_class() -> None:
    """`want_type=True` extracts a class/interface/struct span."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(
            tmp,
            "a.ts",
            "class Foo {\n  bar(): void {}\n}\ninterface I { x: number; }\n",
        )
        out = ts_body("Foo", str(f), "typescript", want_type=True)
        assert out is not None
        assert "class Foo" in out
        assert "bar(): void" in out


def test_ts_body_missing_symbol_returns_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(tmp, "a.js", "function foo() {}\n")
        assert ts_body("nope", str(f), "javascript") is None


def test_ts_body_unsupported_lang_returns_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(tmp, "a.txt", "hello\n")
        assert ts_body("foo", str(f), "brainfuck") is None
