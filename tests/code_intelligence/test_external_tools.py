from __future__ import annotations

import tempfile
from pathlib import Path

from codeq.shared.search import rg_binary, search_lexical

from .helpers import run


def test_ast_grep(fixture_dir: Path) -> None:
    result = run(
        [
            "ast-grep",
            "run",
            "-p",
            "print($X)",
            "--lang",
            "python",
            str(fixture_dir),
        ]
    )
    assert "hello" in result.stdout or result.returncode == 0, (
        f"ast-grep failed: {result.stdout}"
    )


def test_ast_grep_java_expression(fixture_dir: Path) -> None:
    """ast-grep --lang java binds EXPRESSION/call patterns (new Customer($$$)),
    even though class/method DECLARATION patterns do not in 0.43.0. This asserts
    the working subset so the limitation is documented as 'expressions OK'."""
    result = run(
        [
            "ast-grep",
            "run",
            "-p",
            "new Customer($$$)",
            "--lang",
            "java",
            str(fixture_dir),
        ],
        check=False,
    )
    assert "CustomerService.java" in result.stdout, (
        f"ast-grep Java expression pattern failed: {result.stdout}{result.stderr}"
    )


def test_ctags(fixture_dir: Path) -> None:
    result = run(
        [
            "ctags",
            "-R",
            "--fields=+nKz",
            "-f",
            ".tags",
            ".",
        ],
        cwd=fixture_dir,
    )
    tags_file = fixture_dir / ".tags"
    assert tags_file.exists(), "ctags did not generate .tags"

    result = run(["grep", "-F", "calculate", str(tags_file)])
    assert "calculate" in result.stdout, (
        f"ctags index missing calculate: {result.stdout}"
    )

    # Java + TypeScript symbols live in the same single .tags index.
    result = run(["grep", "-F", "Customer", str(tags_file)])
    assert "Customer.java" in result.stdout, (
        f"ctags index missing Java Customer: {result.stdout}"
    )

    result = run(["grep", "-F", "VersionCheckService", str(tags_file)])
    assert "version-check.service.ts" in result.stdout, (
        f"ctags index missing TS VersionCheckService: {result.stdout}"
    )


def test_shellcheck() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "test.sh"
        script.write_text("#!/bin/bash\necho $UNQUOTED\n")
        result = run(["shellcheck", str(script)], check=False)
        assert "SC2086" in result.stdout or result.stderr, (
            f"shellcheck did not flag SC2086: {result.stdout}"
        )


def test_search_lexical_rg_path_keeps_filename() -> None:
    """Regression: the rg backend must emit `file:line:text` rows (filename
    present), matching the pure-Python fallback. A previous version passed
    `-I` to rg, which in rg means `--no-filename` and silently dropped the
    file prefix — breaking every consumer (refs/rdeps/find) that splits on
    the first two `:`. This test forces the rg path and asserts the format.

    Skipped when no real rg binary is on PATH (rg is optional per CLAUDE.md);
    the Python fallback is covered by the rest of the suite."""
    if not rg_binary():
        return  # no rg installed — Python walker path is covered elsewhere
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("def alpha():\n    return 'alpha'\n")
        (root / "b.py").write_text("from a import alpha\nalpha()\n")
        rows = search_lexical("alpha", str(root), word=True)
        assert rows, "rg path returned no rows for a present symbol"
        # Every row must start with the file path (filename not stripped).
        for row in rows:
            parts = row.split(":", 2)
            assert len(parts) == 3, (
                f"rg path row not in file:line:text format (missing filename?): {row!r}"
            )
            assert parts[0].endswith(".py"), (
                f"filename segment not a .py path (rg -I regression?): {row!r}"
            )
            assert parts[1].isdigit(), f"line-number segment not numeric: {row!r}"
        # And the match in b.py (the importer) must be surfaced with its file.
        assert any(r.startswith(str(root / "b.py")) for r in rows), (
            f"rg path dropped the b.py importer row: {rows}"
        )


def test_search_lexical_rg_literal_parity_with_python() -> None:
    """Regression: rg must treat the pattern as a LITERAL, not a regex —
    matching `_py_search`'s `re.escape` semantics. Without `--fixed-strings`,
    rg would match `a.b` against `aXb` (`.` = any char) and produce
    false positives for dotted symbol names like `MyClass.method`.

    Asserts the rg and Python backends return identical rows for a dotted
    pattern over a fixture that contains both the literal and the regex-trap
    form. Skipped when no real rg binary is on PATH."""
    from codeq.shared.search import _py_search, _rg_search

    rg = rg_binary()
    if not rg:
        return  # no rg installed — Python-only path is self-consistent
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # line 1: regex trap (aXb) — must NOT match pattern "a.b" under either backend.
        # line 2: literal target (a.b) — must match under both.
        (root / "y.py").write_text("aXb = 1\na.b = 2\n")
        rg_rows = _rg_search(rg, "a.b", str(root), [], word=True) or []
        py_rows = _py_search("a.b", str(root), [], word=True)
        assert rg_rows == py_rows, (
            f"rg/py parity broken for dotted pattern:\n  rg={rg_rows}\n  py={py_rows}"
        )
        # Both backends must reject the regex-trap line and accept only the literal.
        assert any("a.b = 2" in r for r in rg_rows), f"literal match missing: {rg_rows}"
        assert not any("aXb" in r for r in rg_rows), (
            f"rg matched aXb as if a.b were regex (missing --fixed-strings?): {rg_rows}"
        )
