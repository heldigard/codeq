"""Coverage for structured ``codeq --json`` handlers not yet exercised.

Extends test_codeq_json_structured.py (find/class/sig/summary/map/check/doctor)
to cover: outline, body, refs, deps, rdeps, capabilities, tags, rename.
Each test invokes the real CLI with ``--json`` and locks the envelope shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from .fixtures import write_fixtures
from .helpers import run

# ── JSON error envelope (die() must not leak plain text under --json) ──


def test_json_missing_file_emits_json_error() -> None:
    """A missing file must produce a JSON error envelope, not plain text.

    Regression: feature functions call die() (plain stderr + sys.exit) which
    bypassed the --json contract, breaking machine consumers expecting JSON.
    """
    result = run(
        ["codeq", "--json", "outline", "/nonexistent_file.py"],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["command"] == "outline"
    assert "error" in data
    assert "nonexistent" in data["error"]
    assert data["exit_code"] == 2


# ── outline ──────────────────────────────────────────────────────────


def test_json_outline(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(["codeq", "--json", "outline", str(fixture_dir / "calc.py")])
    data = json.loads(result.stdout)
    assert data["command"] == "outline"
    assert data["exit_code"] == 0
    assert data["count"] >= 2  # calculate + Calculator at minimum
    names = {s["name"] for s in data["symbols"]}
    assert "calculate" in names
    assert "Calculator" in names
    sym = data["symbols"][0]
    assert {"line", "kind", "name"} == set(sym)


def test_json_outline_empty_file(fixture_dir: Path) -> None:
    empty = fixture_dir / "empty.py"
    empty.write_text("")
    result = run(["codeq", "--json", "outline", str(empty)], check=False)
    data = json.loads(result.stdout)
    assert data["command"] == "outline"
    assert data["exit_code"] == 1
    assert data["count"] == 0


# ── body ─────────────────────────────────────────────────────────────


def test_json_body_found(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(["codeq", "--json", "body", "calculate", str(fixture_dir / "calc.py")])
    data = json.loads(result.stdout)
    assert data["command"] == "body"
    assert data["exit_code"] == 0
    assert data["lang"] == "python"
    assert "def calculate" in data["body"]
    assert "return a + b" in data["body"]
    assert data["summary"] is None  # --summary not requested


def test_json_body_miss(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(
        ["codeq", "--json", "body", "nope", str(fixture_dir / "calc.py")],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["command"] == "body"
    assert data["exit_code"] == 1
    assert "error" in data


# ── refs ─────────────────────────────────────────────────────────────


def test_json_refs_hit(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(["codeq", "--json", "refs", "calculate", "-p", str(fixture_dir)])
    data = json.loads(result.stdout)
    assert data["command"] == "refs"
    assert data["count"] >= 1
    assert isinstance(data["refs"], list)
    # main.py imports and calls calculate
    ref_files = {r.split(":")[0] for r in data["refs"]}
    assert any("main.py" in f for f in ref_files)


def test_json_refs_miss(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(
        ["codeq", "--json", "refs", "zzz_no_refs", "-p", str(fixture_dir)],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["command"] == "refs"
    assert data["count"] == 0
    assert data["refs"] == []


# ── deps ─────────────────────────────────────────────────────────────


def test_json_deps(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(["codeq", "--json", "deps", str(fixture_dir / "main.py")])
    data = json.loads(result.stdout)
    assert data["command"] == "deps"
    assert data["count"] >= 1
    modules = [imp["module"] for imp in data["imports"]]
    assert any("calc" in m for m in modules)
    imp = data["imports"][0]
    assert {"line", "kind", "module"} == set(imp)


# ── rdeps ────────────────────────────────────────────────────────────


def test_json_rdeps(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(
        [
            "codeq",
            "--json",
            "rdeps",
            str(fixture_dir / "calc.py"),
            "-p",
            str(fixture_dir),
        ]
    )
    data = json.loads(result.stdout)
    assert data["command"] == "rdeps"
    assert data["count"] >= 1
    importers = data["importers"]
    assert any("main.py" in imp["file"] for imp in importers)
    imp = importers[0]
    assert {"file", "line", "text"} == set(imp)


# ── capabilities ─────────────────────────────────────────────────────


def test_json_capabilities() -> None:
    result = run(["codeq", "--json", "capabilities"])
    data = json.loads(result.stdout)
    assert data["command"] == "capabilities"
    assert data["exit_code"] == 0
    assert data["schema_version"] == 1
    # capabilities payload lists subcommands with annotations
    assert "annotations" in data
    assert isinstance(data["capabilities"], list)


# ── tags ─────────────────────────────────────────────────────────────


def test_json_tags(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(
        ["codeq", "--json", "tags", "-p", str(fixture_dir)],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["command"] == "tags"
    if data["exit_code"] == 0:
        assert data["status"] == "success"
        assert data["size_bytes"] > 0
        assert data["output"].endswith(".tags")
    else:
        # ctags missing or failed — still valid JSON envelope
        assert data["status"] in ("error", "warning")


# ── rename (dry-run) ─────────────────────────────────────────────────


def test_json_rename_dry_run(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(
        [
            "codeq",
            "--json",
            "rename",
            "calculate",
            "compute",
            "-p",
            str(fixture_dir),
            "-l",
            "python",
            "-n",
        ],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["command"] == "rename"
    assert data["old"] == "calculate"
    assert data["new"] == "compute"
    if data["exit_code"] == 0:
        assert data["dry_run"] is True
        assert data["status"] == "success"
        assert data["matches"] >= 1
    else:
        # ast-grep missing or validation error
        assert data["status"] == "error"
        assert data["error"]
