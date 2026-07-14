"""Regression tests for the structured `codeq --json` handlers.

The JSON envelope used to be a text-capture wrapper (`{"output": "..."}`
for most commands). It is now structured per-command: each payload carries
a `command` discriminator, typed fields, and a machine-branchable
`exit_code`. These tests lock that contract so a refactor cannot silently
regress find/class/sig/summary/map/check/doctor back to text envelopes
(body + outline are already covered in test_codeq_core.py).
"""

from __future__ import annotations

import json
from pathlib import Path

from codeq.features.pattern_check.command import check_pattern

from .fixtures import write_fixtures
from .helpers import run


def test_json_find_hit(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(["codeq", "--json", "find", "calculate", "-p", str(fixture_dir)])
    data = json.loads(result.stdout)
    assert data["command"] == "find"
    assert data["exit_code"] == 0
    assert data["count"] >= 1
    hit = data["hits"][0]
    assert hit["name"] == "calculate"
    assert hit["file"].endswith("calc.py")
    assert hit["line"] == 6  # calculate sits after the module docstring + imports
    assert {"file", "line", "kind", "name"} == set(hit)


def test_json_find_miss(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(
        ["codeq", "--json", "find", "nope_not_here", "-p", str(fixture_dir)],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["command"] == "find"
    assert data["exit_code"] == 1
    assert data["count"] == 0
    assert data["hits"] == []


def test_json_class_body(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    file_path = fixture_dir / "calc.py"
    result = run(["codeq", "--json", "class", "Calculator", str(file_path)])
    data = json.loads(result.stdout)
    assert data["command"] == "class"
    assert data["exit_code"] == 0
    assert data["lang"] == "python"
    assert "class Calculator" in data["body"]
    assert "total" in data["body"]  # member included
    assert data["summary"] is None  # --summary not requested


def test_json_sig(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    file_path = fixture_dir / "calc.py"
    result = run(["codeq", "--json", "sig", "calculate", str(file_path)])
    data = json.loads(result.stdout)
    assert data["command"] == "sig"
    assert data["exit_code"] == 0
    assert data["signature"].startswith("def calculate")
    assert "body" not in data  # sig stays header-only


def test_json_summary_no_llm(fixture_dir: Path) -> None:
    """--no-llm degrades to status=skipped with exit_code 2 (distinct from
    'symbol not found'=1). Mirrors the text-mode cmd_summary contract."""
    write_fixtures(fixture_dir)
    file_path = fixture_dir / "calc.py"
    result = run(
        ["codeq", "--json", "summary", "calculate", str(file_path), "--no-llm"],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["command"] == "summary"
    assert data["exit_code"] == 2
    assert data["summary"]["status"] == "skipped"


def test_json_map(fixture_dir: Path) -> None:
    write_fixtures(fixture_dir)
    result = run(["codeq", "--json", "map", "-p", str(fixture_dir), "--top", "2"])
    data = json.loads(result.stdout)
    assert data["command"] == "map"
    assert data["exit_code"] == 0
    assert data["files_indexed"] >= 1
    assert isinstance(data["files"], list)
    if data["files"]:
        top = data["files"][0]
        assert {"file", "weight", "symbols"} <= set(top)
        sym = top["symbols"][0]
        assert {"line", "kind", "name", "references"} == set(sym)


def test_json_check_valid() -> None:
    result = run(["codeq", "--json", "check", "print($X)", "-l", "python"], check=False)
    data = json.loads(result.stdout)
    assert data["command"] == "check"
    assert data["valid"] is True
    assert data["exit_code"] == 0


def test_json_check_invalid() -> None:
    # `except:` alone is NOT a single AST node — ast-grep rejects it.
    result = run(["codeq", "--json", "check", "except:", "-l", "python"], check=False)
    data = json.loads(result.stdout)
    assert data["command"] == "check"
    assert data["valid"] is False
    assert data["exit_code"] == 2
    assert data["error"]


def test_check_pattern_returns_dict_contract() -> None:
    """Pure-function contract for check_pattern (drives _check_json). The dict
    shape is what machines branch on, so pin it independent of ast-grep env."""
    res = check_pattern("print($X)", "python")
    assert set(res) == {"valid", "pattern", "lang", "error", "verdict", "hint"}

    bad = check_pattern("except:", "python")
    assert bad["valid"] is False
    assert bad["lang"] == "python"
    assert bad["pattern"] == "except:"

    unsupported = check_pattern("x", "klingon")
    assert unsupported["valid"] is False
    assert "klingon" in unsupported["error"]


def test_json_doctor() -> None:
    result = run(["codeq", "--json", "doctor"], check=False)
    data = json.loads(result.stdout)
    assert data["command"] == "doctor"
    assert isinstance(data["tools"], list)
    assert data["tools"]  # TOOLS registry is non-empty
    assert isinstance(data["required_missing"], bool)
    assert data["exit_code"] in (0, 1)
    tool = data["tools"][0]
    assert {"name", "status", "importance", "version", "path"} <= set(tool)
