"""End-to-end tests for `codeq rename` via the CLI entry point.

`codeq rename` shells out to `ast-grep run --update-all`. These tests write
small fixtures, invoke the command, and assert the on-disk result — proving
the AST-exact property (strings / comments untouched) that distinguishes
`rename` from sed.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def _run_cli(*args: str) -> tuple[int, str, str]:
    """Invoke `codeq <args>` as a subprocess (real CLI path, not in-process)."""
    proc = subprocess.run(
        [sys.executable, "-m", "codeq", *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_rename_python_rewrites_def_and_call_only() -> None:
    """`codeq rename foo bar` on a python file rewrites the def, the call,
    attribute access, and kwarg names — but NOT the string literal or comment.

    ast-grep uses tree-sitter, which represents keyword-argument names as
    identifier tokens, so they ARE rewritten (unlike CPython's `ast` module
    in `codeq refs`, where `keyword.arg` is a bare string and excluded).
    The wins over sed are the inviolable cases: string literals and comments
    are never touched because they are not identifier nodes in any grammar."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.py"
        f.write_text(
            "# foo comment\n"
            "def foo():\n"
            "    return 'foo'\n"
            "foo()\n"
            "obj.foo()\n"
            "bar(foo=1)\n"
        )
        rc, out, err = _run_cli("rename", "foo", "bar", "-p", str(f))
        assert rc == 0, f"rename failed: rc={rc} out={out} err={err}"
        result = f.read_text()
        assert "def bar():" in result, f"def not renamed: {result}"
        assert "bar()" in result, f"call not renamed: {result}"
        assert "obj.bar()" in result, f"attribute not renamed: {result}"
        # the string literal MUST be untouched (the AST-exact win over sed)
        assert "'foo'" in result, f"string literal wrongly rewritten: {result}"
        # the comment MUST be untouched
        assert "# foo comment" in result, f"comment wrongly rewritten: {result}"
        # kwarg names ARE rewritten (tree-sitter identifier token) — scope-blind
        assert "bar(bar=1)" in result, f"kwarg not rewritten: {result}"


def test_rename_dry_run_does_not_write() -> None:
    """`--dry-run` reports matches but leaves the file unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.py"
        original = "def foo():\n    pass\nfoo()\n"
        f.write_text(original)
        rc, out, _ = _run_cli("rename", "foo", "bar", "-p", str(f), "-n")
        assert rc == 0, f"dry-run failed: rc={rc} out={out}"
        assert "DRY RUN" in out, f"missing dry-run banner: {out}"
        assert f.read_text() == original, "dry-run wrote to disk!"


def test_rename_rejects_non_identifier() -> None:
    """Non-identifier inputs (containing a dot, space, etc.) fail fast with a
    clear error, not an ast-grep parse failure mid-rewrite."""
    with tempfile.TemporaryDirectory() as tmp:
        rc, _, err = _run_cli("rename", "a.b", "c.d", "-p", tmp)
        assert rc != 0, "non-identifier rename unexpectedly succeeded"
        assert "identifier" in err.lower(), f"unclear error: {err}"


def test_rename_rejects_identical_names() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rc, _, err = _run_cli("rename", "foo", "foo", "-p", tmp)
        assert rc != 0, "identical-name rename unexpectedly succeeded"
        assert "identical" in err.lower(), f"unclear error: {err}"


def test_rename_rejects_unsupported_lang() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rc, _, err = _run_cli("rename", "foo", "bar", "-p", tmp, "-l", "cobol")
        assert rc != 0, "unsupported-lang rename unexpectedly succeeded"
        assert "lang" in err.lower(), f"unclear error: {err}"
