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
from codeq.shared.tree_sitter_extract import ts_available as _ts_available


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
    """Non-python langs use the lexical path (AST only covers python), then a
    tree-sitter filter drops hits inside comments/strings when tree-sitter is
    available. The real call appears; a bare string literal does not.

    Pins the lang-dispatch contract: python → AST (string never matches);
    brace-langs → lexical (then ts-filtered). A call `foo()` must appear so
    the dispatch is provably wired; the filtered-out `'foo'` proves the
    ts-filter layer sits on top of lexical (without it, lexical would keep
    the string)."""
    if not _ts_available():
        return  # ts is an optional dep; skip the filter assertion when absent
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # `const r = foo()` survives the JS def-filter (a bare top-level
        # `foo();` is regex-collapsed into a declaration — known limitation
        # of the depth-unaware def_re, not in scope here).
        (root / "a.js").write_text("function foo() {}\nconst r = foo();\n'foo';\n")
        rows = get_refs("foo", str(root), lang="javascript")
        assert any("const r = foo()" in r for r in rows), f"call missing: {rows}"
        assert not any("'foo'" in r for r in rows), (
            f"string literal not filtered: {rows}"
        )


def test_ts_filter_drops_comment_and_string_refs() -> None:
    """A symbol mentioned in a comment AND a string AND a real call: refs must
    return only the call line. This is the brace-lang analog of
    `test_py_refs_excludes_comments_and_strings`, closed via tree-sitter
    instead of the `ast` module."""
    if not _ts_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.ts").write_text(
            "// call foo here\n"
            "const note = 'foo';\n"
            "function foo() { return 1; }\n"
            "const result = foo();\n"
        )
        rows = get_refs("foo", str(root), lang="typescript")
        # def line filtered by def_re; comment + string filtered by tree-sitter.
        assert any("foo()" in r for r in rows), f"call missing: {rows}"
        assert not any("call foo here" in r for r in rows), f"comment leaked: {rows}"
        assert not any("note =" in r for r in rows), f"string leaked: {rows}"
        assert not any("function foo" in r for r in rows), f"def leaked: {rows}"


def test_ts_filter_preserves_member_access() -> None:
    """`obj.foo` (member access) is real code, not a string or comment — it
    must survive the tree-sitter filter. This is the key safety property of
    the filter approach (vs reimplementing refs from tree-sitter, which would
    risk losing member-access true positives across grammars)."""
    if not _ts_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.ts").write_text("function foo() { return 1; }\nobj.foo;\n")
        rows = get_refs("foo", str(root), lang="typescript")
        assert any("obj.foo" in r for r in rows), f"member access lost: {rows}"


def test_ts_filter_works_without_explicit_lang() -> None:
    """The `refs` CLI path passes lang=None for a mixed tree. The filter must
    infer the language per file from its extension (`.ts` → typescript) and
    still drop comment/string hits. Regression: the first implementation gated
    on the caller's lang and silently no-op'd when it was empty, so the CLI
    returned comment/string matches while unit tests (which passed an explicit
    lang) passed."""
    if not _ts_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.ts").write_text(
            "// see foo\nconst label = 'foo';\nfunction foo() {}\nconst r = foo();\n"
        )
        rows = get_refs("foo", str(root))  # lang defaults to None
        assert any("foo();" in r for r in rows), f"call missing: {rows}"
        assert not any("see foo" in r for r in rows), f"comment leaked: {rows}"
        assert not any("label =" in r for r in rows), f"string leaked: {rows}"


def test_ts_decl_filter_keeps_top_level_call() -> None:
    """A bare top-level `foo();` is a CALL, not a declaration — it must
    survive the def filter. The regex def_re is greedy (the `function`
    keyword is optional), so it collapsed `foo();` into a declaration and
    refs lost every top-level statement call. tree-sitter classifies the node
    as `call_expression`, so it is kept; only the `function foo()` node is
    dropped."""
    if not _ts_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.ts").write_text("function foo() { return 1; }\nfoo();\n")
        rows = get_refs("foo", str(root), lang="typescript")
        assert any(r.endswith("foo();") for r in rows), f"top-level call lost: {rows}"
        assert not any("function foo" in r for r in rows), f"def leaked: {rows}"


def test_ts_decl_filter_works_without_explicit_lang() -> None:
    """A TS class method declaration must be filtered even when lang is not
    passed (the `refs` CLI path, lang=None). Regression: the first version
    gated the filter on `lang in (javascript, typescript)`, so a mixed-tree
    call with no explicit lang left `protected foo(...)` declaration lines in
    the output. The filter now infers the language per file from extension."""
    if not _ts_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "svc.ts").write_text(
            "export class Svc {\n"
            "  protected foo(event: Event): void { return; }\n"
            "}\n"
            "foo(new Event('x'));\n"
        )
        rows = get_refs("foo", str(root))  # lang defaults to None
        assert any(r.endswith("foo(new Event('x'));") for r in rows), (
            f"top-level call lost: {rows}"
        )
        assert not any("protected foo" in r for r in rows), f"method def leaked: {rows}"


def test_bash_refs_filters_bare_function_declaration() -> None:
    """Bash `name() { ... }` (no `function` keyword) is a declaration, not a
    call. The generic def-filter misses this form because it requires a
    keyword. Regression: refs showed the declaration line as a reference."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(
            root,
            "lib.sh",
            "shared_func() {\n    echo ok\n}\nshared_func\n",
        )
        rows = get_refs("shared_func", str(root), lang="bash")
        assert any("shared_func" in r and "echo" not in r for r in rows), (
            f"call missing: {rows}"
        )
        # The declaration line `shared_func() {` must NOT appear as a ref.
        decls = [r for r in rows if "shared_func()" in r and "{" in r]
        assert decls == [], f"bare-func declaration leaked into refs: {rows}"


def test_bash_refs_filters_function_keyword_declaration() -> None:
    """Bash `function name() { ... }` and `function name { ... }` are both
    declarations — the keyword-led def-filter must catch them."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(
            root,
            "lib.sh",
            "function my_func() {\n    echo ok\n}\nfunction other_func {\n    echo ok\n}\nmy_func\n",
        )
        rows = get_refs("my_func", str(root), lang="bash")
        assert any(
            "my_func" in r and "echo" not in r and "function" not in r for r in rows
        ), f"call missing: {rows}"
        # The declaration lines must NOT appear as refs.
        assert not any("function my_func" in r for r in rows), (
            f"function-keyword declaration leaked: {rows}"
        )
