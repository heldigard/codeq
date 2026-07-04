"""Tests for Lombok annotation awareness in codeq."""

from __future__ import annotations

from pathlib import Path

from .helpers import run


def test_lombok_detect_annotations(fixture_dir: Path) -> None:
    """Lombok detector finds @Data, @Builder, @Slf4j annotations."""
    from codeq.shared.lombok import detect_lombok_members

    file = str(fixture_dir / "CustomerLombok.java")
    members = detect_lombok_members(file)

    # Should find getters for id, name, active
    getters = [m for m in members if m.name.startswith("get")]
    assert len(getters) >= 3, (
        f"Expected >= 3 getters, got {len(getters)}: {[m.name for m in getters]}"
    )

    # Should find setters for id, name, active
    setters = [m for m in members if m.name.startswith("set")]
    assert len(setters) >= 3, (
        f"Expected >= 3 setters, got {len(setters)}: {[m.name for m in setters]}"
    )

    # Should find boolean getter with 'is' prefix
    is_active = [m for m in members if m.name == "isActive"]
    assert len(is_active) == 1, (
        f"Expected isActive getter, got {[m.name for m in is_active]}"
    )

    # Should find equals/hashCode from @Data
    assert any(m.name == "equals" for m in members), "Missing equals from @Data"
    assert any(m.name == "hashCode" for m in members), "Missing hashCode from @Data"
    assert any(m.name == "toString" for m in members), "Missing toString from @Data"

    # Should find builder from @Builder
    assert any(m.name == "builder" for m in members), "Missing builder from @Builder"

    # Should find log field from @Slf4j
    log_fields = [m for m in members if m.name == "log"]
    assert len(log_fields) == 1, (
        f"Expected log field from @Slf4j, got {len(log_fields)}"
    )


def test_lombok_outline(fixture_dir: Path) -> None:
    """codeq outline shows Lombok-generated methods for Java files."""
    result = run(["codeq", "outline", str(fixture_dir / "CustomerLombok.java")])

    # Should show Lombok-generated getters
    assert "getId" in result.stdout, f"outline missed getId: {result.stdout}"
    assert "getName" in result.stdout, f"outline missed getName: {result.stdout}"
    assert "isActive" in result.stdout, f"outline missed isActive: {result.stdout}"

    # Should show Lombok-generated setters
    assert "setId" in result.stdout, f"outline missed setId: {result.stdout}"
    assert "setName" in result.stdout, f"outline missed setName: {result.stdout}"

    # Should show Lombok-generated methods
    assert "equals" in result.stdout, f"outline missed equals: {result.stdout}"
    assert "hashCode" in result.stdout, f"outline missed hashCode: {result.stdout}"
    assert "toString" in result.stdout, f"outline missed toString: {result.stdout}"
    assert "builder" in result.stdout, f"outline missed builder: {result.stdout}"

    # Should show Lombok-generated log field
    assert "log" in result.stdout, f"outline missed log: {result.stdout}"


def test_lombok_find(fixture_dir: Path) -> None:
    """codeq find locates Lombok-generated methods in Java files."""
    result = run(["codeq", "find", "getId", "-p", str(fixture_dir)])
    assert "CustomerLombok.java" in result.stdout, (
        f"find missed Lombok getId: {result.stdout}"
    )

    result = run(["codeq", "find", "setName", "-p", str(fixture_dir)])
    assert "CustomerLombok.java" in result.stdout, (
        f"find missed Lombok setName: {result.stdout}"
    )

    result = run(["codeq", "find", "builder", "-p", str(fixture_dir)])
    assert "CustomerLombok.java" in result.stdout, (
        f"find missed Lombok builder: {result.stdout}"
    )


def test_lombok_no_duplicate_with_explicit(fixture_dir: Path) -> None:
    """Lombok should not duplicate methods that already exist in source."""
    from codeq.shared.lombok import detect_lombok_members

    # Customer.java has explicit getId() - Lombok should not add another
    file = str(fixture_dir / "Customer.java")
    members = detect_lombok_members(file)

    # Customer.java has no Lombok annotations, so no members should be found
    assert len(members) == 0, (
        f"Expected no Lombok members for non-Lombok file, got {len(members)}"
    )


def test_lombok_json_outline(fixture_dir: Path) -> None:
    """codeq --json outline includes Lombok members."""
    import json

    result = run(
        ["codeq", "--json", "outline", str(fixture_dir / "CustomerLombok.java")]
    )
    data = json.loads(result.stdout)
    assert data["exit_code"] == 0
    assert "getId" in data["output"]
    assert "setName" in data["output"]
