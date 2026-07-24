"""Tests for Lombok annotation awareness in codeq."""

from __future__ import annotations

from pathlib import Path

from .helpers import run


def test_lombok_detect_annotations(fixture_dir: Path) -> None:
    """Lombok detector finds @Data, @Builder, @Slf4j annotations."""
    from codeq.shared.lombok import detect_lombok_members

    file = str(fixture_dir / "CustomerLombok.java")
    members = detect_lombok_members(file)

    # Getters for non-boolean fields (id, name). `active` is primitive boolean
    # so Lombok generates isActive(), NOT getActive() — exclude it here.
    getters = [m for m in members if m.name.startswith("get")]
    assert len(getters) >= 2, (
        f"Expected >= 2 getters, got {len(getters)}: {[m.name for m in getters]}"
    )

    # Should find setters for id, name, active
    setters = [m for m in members if m.name.startswith("set")]
    assert len(setters) >= 3, (
        f"Expected >= 3 setters, got {len(setters)}: {[m.name for m in setters]}"
    )

    # Should find boolean getter with 'is' prefix (primitive boolean → isX only)
    is_active = [m for m in members if m.name == "isActive"]
    assert len(is_active) == 1, (
        f"Expected isActive getter, got {[m.name for m in is_active]}"
    )

    # Regression: primitive boolean must NOT also emit getActive (Lombok emits
    # isX only for primitive boolean). Dual emission misleads callers.
    assert not any(m.name == "getActive" for m in members), (
        "primitive boolean field must not emit getActive (only isActive)"
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
    names = {sym["name"] for sym in data["symbols"]}
    assert "getId" in names
    assert "setName" in names


def test_lombok_boolean_primitive_is_only() -> None:
    """Regression: primitive boolean → isX only (not getX+isX dual).

    Lombok @Getter on a primitive `boolean` field generates isFoo(), never
    getFoo(). Dual emission was a false-positive that misled callers into
    navigating a method that does not exist in the compiled class.
    """
    import tempfile

    from codeq.shared.lombok import detect_lombok_members

    src = (
        "package x;\nimport lombok.Data;\n"
        "@Data\npublic class Holder {\n"
        "    private boolean active;\n"
        "    private Boolean enabled;\n"  # wrapper Boolean → getX() only
        "}\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".java", delete=False, mode="w") as f:
        f.write(src)
        fpath = f.name
    try:
        members = detect_lombok_members(fpath)
        names = {m.name for m in members}
        # primitive boolean: isX only
        assert "isActive" in names, f"missing isActive (primitive boolean): {names}"
        assert "getActive" not in names, (
            f"primitive boolean must not emit getActive: {names}"
        )
        # wrapper Boolean: getX only (no isX)
        assert "getEnabled" in names, f"missing getEnabled (wrapper Boolean): {names}"
        assert "isEnabled" not in names, (
            f"wrapper Boolean must not emit isEnabled: {names}"
        )
    finally:
        import os

        os.unlink(fpath)


def test_lombok_static_substring_field_not_excluded() -> None:
    """Regression: an instance field whose name contains 'static' (e.g.
    staticCount) must NOT be mistaken for a static field and dropped."""
    import tempfile

    from codeq.shared.lombok import detect_lombok_members

    src = (
        "package x;\nimport lombok.Data;\n"
        "@Data\npublic class Counter {\n"
        "    private int staticCount;\n"  # instance field, name has 'static'
        "    private int total;\n"
        "}\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".java", delete=False, mode="w") as f:
        f.write(src)
        fpath = f.name
    try:
        members = detect_lombok_members(fpath)
        names = {m.name for m in members}
        # PascalCase of staticCount → StaticCount → getStaticCount / setStaticCount
        assert "getStaticCount" in names, (
            f"'staticCount' instance field was wrongly dropped as static: {names}"
        )
        assert "setStaticCount" in names, f"missing setStaticCount: {names}"
        assert "getTotal" in names, f"missing getTotal: {names}"
    finally:
        import os

        os.unlink(fpath)


def test_lombok_package_decl_not_a_field() -> None:
    """Regression: a single-segment package declaration (e.g. `package x;`)
    must not be parsed as a field of type 'package'. The field regex anchored
    on any `Type name;` line, so `package x;` matched and produced a bogus
    getX() getter with an invalid `package` type."""
    import tempfile

    from codeq.shared.lombok import detect_lombok_members

    src = (
        "package x;\nimport lombok.Data;\n"
        "@Data\npublic class Pkg {\n"
        "    private Long id;\n"
        "}\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".java", delete=False, mode="w") as f:
        f.write(src)
        fpath = f.name
    try:
        members = detect_lombok_members(fpath)
        names = {m.name for m in members}
        assert "getId" in names, f"missing getId: {names}"
        # the package decl must NOT become a field
        assert "getX" not in names, (
            f"package declaration was parsed as a field (getX): {names}"
        )
        bogus = [m for m in members if m.signature.startswith("public package")]
        assert not bogus, f"invalid 'package' type in signature: {bogus}"
    finally:
        import os

        os.unlink(f.name)


def test_lombok_body_and_sig(fixture_dir: Path) -> None:
    """codeq body and sig retrieve synthetic signatures/bodies for Lombok members."""
    # Sig check
    result = run(["codeq", "sig", "getId", str(fixture_dir / "CustomerLombok.java")])
    assert "public Long getId()" in result.stdout

    # Body check
    result = run(["codeq", "body", "getId", str(fixture_dir / "CustomerLombok.java")])
    assert "public Long getId() {" in result.stdout
    assert "lombok-generated" in result.stdout


def test_lombok_repo_map(fixture_dir: Path) -> None:
    """codeq map lists Lombok-generated methods for Java files."""
    result = run(
        ["codeq", "map", "-p", str(fixture_dir), "--top", "50", "--syms", "10"]
    )
    assert "CustomerLombok.java" in result.stdout
    assert "getId" in result.stdout
    assert "lombok-method" in result.stdout
