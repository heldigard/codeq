"""Regression tests for `codeq refs`, focused on the Python AST semantic
path (`search_py_refs`). The AST walker matches only real `Name` / `Attribute`
/ import-alias nodes, so it is immune to the comment / string / kwarg-name
false positives that lexical search produces.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from codeq.features.references.command import get_refs
from codeq.shared.search import search_py_refs


def _write(root: Path, name: str, body: str) -> Path:
    f = root / name
    f.write_text(body)
    return f


def test_py_refs_matches_call_and_attribute() -> None:
    """A bare call `foo()` and an attribute `obj.foo` are real references."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(
            root,
            "a.py",
            "def foo():\n    return 1\n\nfoo()\nobj.foo\n",
        )
        rows = search_py_refs("foo", str(root))
        assert any("foo()" in r for r in rows), f"call missing: {rows}"
        assert any("obj.foo" in r for r in rows), f"attribute missing: {rows}"


def test_py_refs_excludes_definition_line() -> None:
    """`def foo():` declares foo — it is NOT a reference to foo. The AST yields
    no `Name(id='foo')` for the def identifier, so the def line must be absent.
    This is the core win over lexical search (which needs a regex def-filter
    to drop the same line)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "a.py", "def foo():\n    pass\nfoo()\n")
        rows = search_py_refs("foo", str(root))
        for r in rows:
            assert "def foo" not in r, f"def line leaked into refs: {rows}"
        assert any("foo()" in r for r in rows)


def test_py_refs_excludes_comments_and_strings() -> None:
    """Comments and string literals must NOT count as references — the head
    advantage of AST over lexical. A comment `# foo` and string `'foo'` are
    invisible to the AST parser."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(
            root,
            "a.py",
            "# call foo here\nmsg = 'foo'\nfoo()\n",
        )
        rows = search_py_refs("foo", str(root))
        assert len(rows) == 1, f"expected only the real call: {rows}"
        assert "foo()" in rows[0]


def test_py_refs_excludes_kwarg_name() -> None:
    """`bar(foo=1)` defines a keyword-argument NAME `foo`, it does not
    reference a symbol named foo. The kwarg identifier is `keyword.arg` (a
    string), not an `ast.Name` node, so it is naturally excluded."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "a.py", "def bar(**kw):\n    pass\nbar(foo=1)\n")
        rows = search_py_refs("foo", str(root))
        assert rows == [], f"kwarg name leaked as a reference: {rows}"


def test_py_refs_matches_import_binding() -> None:
    """`from m import foo` binds foo into scope — it IS a reference to foo
    (where foo enters this module). Both plain and `as` forms match."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "a.py", "from m import foo\nimport x.foo\nfoo()\n")
        rows = search_py_refs("foo", str(root))
        # the from-import line, the dotted import line, and the call
        assert any("from m import foo" in r for r in rows), (
            f"from-import binding missing: {rows}"
        )
        assert any("import x.foo" in r for r in rows), (
            f"dotted import binding missing: {rows}"
        )


def test_py_refs_no_match_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "a.py", "def bar():\n    pass\nbar()\n")
        assert search_py_refs("foo", str(root)) == []


def test_py_refs_skips_unparseable_file() -> None:
    """A syntax-error file degrades to [] for that file, not a crash. Other
    files in the tree still get walked."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "broken.py", "def (\n")
        _write(root, "good.py", "def foo():\n    pass\nfoo()\n")
        rows = search_py_refs("foo", str(root))
        assert any("good.py" in r and "foo()" in r for r in rows), rows
        assert not any("broken.py" in r for r in rows), rows


def test_get_refs_uses_ast_path_for_python() -> None:
    """End-to-end: `get_refs(name, path, lang='python')` returns AST rows,
    so a comment containing the name does not appear in the output."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "a.py", "# foo comment\ndef foo():\n    pass\nfoo()\n")
        rows = get_refs("foo", str(root), lang="python")
        assert any("foo()" in r for r in rows)
        assert not any("foo comment" in r for r in rows), rows
        assert not any("def foo" in r for r in rows), rows


def test_get_refs_lexical_for_non_python() -> None:
    """Non-python langs keep the lexical path (AST only covers python). A
    string literal CAN match under lexical — proof the dispatch is lexical,
    not AST. This test pins the lang-dispatch contract so it doesn't drift."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.js").write_text("function foo() {}\n'foo';\n")
        rows = get_refs("foo", str(root), lang="javascript")
        # The string-literal line is present under lexical search; it would
        # be ABSENT under the python AST path (which never matches strings).
        # Its presence proves the non-python dispatch goes through lexical.
        assert any("'foo'" in r for r in rows), rows
