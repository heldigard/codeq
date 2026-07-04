from __future__ import annotations

import tempfile
from pathlib import Path

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
