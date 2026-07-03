from __future__ import annotations

import tempfile
from pathlib import Path

from .helpers import run


def test_codeq(fixture_dir: Path) -> None:
    # find
    result = run(["codeq", "find", "calculate", "-p", str(fixture_dir)])
    assert "calculate" in result.stdout, f"codeq find failed: {result.stdout}"

    # body
    file_path = fixture_dir / "calc.py"
    result = run(["codeq", "body", "calculate", str(file_path)])
    assert "def calculate" in result.stdout, f"codeq body failed: {result.stdout}"

    # sig
    result = run(["codeq", "sig", "calculate", str(file_path)])
    assert "def calculate" in result.stdout, f"codeq sig failed: {result.stdout}"

    # refs
    result = run(["codeq", "refs", "calculate", "-p", str(fixture_dir)])
    assert "main.py" in result.stdout, f"codeq refs failed: {result.stdout}"

    # outline
    result = run(["codeq", "outline", str(file_path)])
    assert "calculate" in result.stdout, f"codeq outline failed: {result.stdout}"

    # deps
    result = run(["codeq", "deps", str(file_path)])
    assert "json" in result.stdout, f"codeq deps failed: {result.stdout}"

    # check
    result = run(["codeq", "check", "print($X)", "-l", "python"])
    assert result.returncode == 0, f"codeq check failed: {result.stderr}"


def test_codeq_java(fixture_dir: Path) -> None:
    """Java symbol extraction. `outline <Class>` lists members — the supported
    workaround for the codeq Java class-body limitation (body of a class would
    return only the constructor)."""
    customer = fixture_dir / "Customer.java"

    # find
    result = run(["codeq", "find", "Customer", "-p", str(fixture_dir)])
    assert "Customer.java" in result.stdout, f"codeq find Java failed: {result.stdout}"

    # outline lists the class + its methods/fields
    result = run(["codeq", "outline", str(customer)])
    assert "Customer" in result.stdout and "displayName" in result.stdout, (
        f"codeq outline Java failed: {result.stdout}"
    )

    # body of a METHOD (not the class) returns the exact method body
    result = run(["codeq", "body", "getId", str(customer)])
    assert "public Long getId" in result.stdout, (
        f"codeq body Java method failed: {result.stdout}"
    )

    # refs finds the call site in CustomerService.java
    result = run(["codeq", "refs", "displayName", "-p", str(fixture_dir)])
    assert "CustomerService.java" in result.stdout, (
        f"codeq refs Java failed: {result.stdout}"
    )


def test_codeq_class(fixture_dir: Path) -> None:
    """`codeq class` returns the FULL class body (all members), NOT just the
    constructor — the fix for the Java class-body limitation where `body <Class>`
    returned only the constructor (ctags lists the constructor before the class)."""
    customer = fixture_dir / "Customer.java"
    result = run(["codeq", "class", "Customer", str(customer)])
    # displayName + getId are non-constructor methods; present only if the whole
    # class body was returned, not truncated to the constructor.
    assert "public class Customer" in result.stdout, (
        f"codeq class missing class line: {result.stdout}"
    )
    assert "displayName" in result.stdout and "getId" in result.stdout, (
        f"codeq class did not return the full class body: {result.stdout}"
    )


def test_codeq_rdeps(fixture_dir: Path) -> None:
    """`rdeps FILE` = reverse deps: which project files import this module.
    Python: main.py does `from calc import calculate` → calc.py's importer.
    TS: relative-path import resolves by last path segment. The module itself
    must never list as its own importer; a never-imported file exits 1."""
    result = run(
        ["codeq", "rdeps", str(fixture_dir / "calc.py"), "-p", str(fixture_dir)]
    )
    assert "main.py" in result.stdout, f"rdeps missed main.py: {result.stdout}"
    assert "calc.py:" not in result.stdout, (
        f"rdeps listed the module itself: {result.stdout}"
    )
    # TS relative import
    (fixture_dir / "rdeps-consumer.ts").write_text(
        "import { helper } from './rdeps-lib';\nexport const x = helper();\n"
    )
    (fixture_dir / "rdeps-lib.ts").write_text(
        "export function helper(): number { return 1; }\n"
    )
    result = run(
        ["codeq", "rdeps", str(fixture_dir / "rdeps-lib.ts"), "-p", str(fixture_dir)]
    )
    assert "rdeps-consumer.ts" in result.stdout, (
        f"rdeps TS missed consumer: {result.stdout}"
    )
    # never-imported file → exit 1
    result = run(
        ["codeq", "rdeps", str(fixture_dir / "debug.py"), "-p", str(fixture_dir)],
        check=False,
    )
    assert result.returncode == 1, (
        f"rdeps should exit 1 for no importers: {result.stdout}"
    )


def test_codeq_rdeps_multiline_importer(fixture_dir: Path) -> None:
    """`rdeps` must detect importers whose import statement spans MULTIPLE
    lines (the barrel/harness pattern). The line carrying the module path is
    `} from './module';` — no leading import/export keyword — so the anchored
    IMPORT_PATTERNS in `_is_import_of` missed it and rdeps reported ZERO
    importers. Real incident: RevOpsAIFrontend server-test-harness.mjs (5
    importing specs, rdeps said 'no project file imports'). Same bug class
    as the deps multi-line barrel fix."""
    lib = fixture_dir / "rdeps-barrel-lib.mjs"
    lib.write_text("export function helper() { return 1; }\n")
    consumer = fixture_dir / "rdeps-barrel-consumer.spec.mjs"
    consumer.write_text(
        "import {\n  helper,\n} from './rdeps-barrel-lib';\nconst v = helper();\n"
    )
    result = run(["codeq", "rdeps", str(lib), "-p", str(fixture_dir)], check=False)
    assert "rdeps-barrel-consumer.spec.mjs" in result.stdout, (
        f"rdeps missed the multi-line importer: {result.stdout}{result.stderr}"
    )


def test_codeq_doctor() -> None:
    """`doctor` reports each external binary (OK/MISSING + version), never
    installs without --install, and exits 0 when all REQUIRED binaries are
    present (rg/ollama are optional)."""
    result = run(["codeq", "doctor"], check=False)
    assert "codeq dependency check" in result.stdout, (
        f"doctor header missing: {result.stdout}"
    )
    assert "ctags" in result.stdout, (
        f"doctor must list ctags (required): {result.stdout}"
    )
    # without --install it must NOT attempt installs
    assert "installing" not in result.stderr, (
        f"doctor installed without --install: {result.stderr}"
    )
    # required binaries present → exit 0 (CI/local has ctags + ast-grep)
    assert result.returncode == 0, (
        f"doctor should exit 0 when required binaries present: {result.stdout}"
    )


def test_codeq_map(fixture_dir: Path) -> None:
    """`map` = repo orientation: hottest files + symbols by reference weight,
    bounded output. Test files are excluded by default (--tests includes);
    --save persists to .memory-bank/topics/code-map.md only when a bank exists."""
    (fixture_dir / "test_dummy.py").write_text("def noisy_helper():\n    return 1\n")
    result = run(["codeq", "map", "-p", str(fixture_dir), "--top", "10", "--syms", "3"])
    assert "REPO MAP" in result.stdout, f"map header missing: {result.stdout}"
    assert "calc.py" in result.stdout, f"map missed calc.py: {result.stdout}"
    assert "calculate" in result.stdout, f"map missed hot symbol: {result.stdout}"
    assert "test_dummy.py" not in result.stdout, (
        f"map must exclude test files by default: {result.stdout}"
    )
    with_tests = run(
        [
            "codeq",
            "map",
            "-p",
            str(fixture_dir),
            "--top",
            "50",
            "--syms",
            "3",
            "--tests",
        ]
    )
    assert "test_dummy.py" in with_tests.stdout, (
        f"--tests must include test files: {with_tests.stdout}"
    )
    # --save without a memory bank: no crash, explicit skip notice
    saved = run(["codeq", "map", "-p", str(fixture_dir), "--save"], check=False)
    assert saved.returncode == 0 and "skipped" in saved.stderr, (
        f"--save without bank should skip gracefully: {saved.stderr}"
    )
    # --save with a bank: topic file written
    (fixture_dir / ".memory-bank" / "topics").mkdir(parents=True)
    run(["codeq", "map", "-p", str(fixture_dir), "--save"])
    topic = fixture_dir / ".memory-bank" / "topics" / "code-map.md"
    assert topic.is_file() and "REPO MAP" in topic.read_text(), (
        "map --save did not write topics/code-map.md"
    )


def test_codeq_version_and_sweep_cap() -> None:
    """--version prints the package version (sanity check). Sweep cap stays
    silent on small trees (no spurious truncation notice)."""
    version = run(["codeq", "--version"], check=False)
    assert version.stdout.startswith("codeq "), (
        f"--version did not print version banner: {version.stdout}{version.stderr}"
    )
    with tempfile.TemporaryDirectory() as tmp:
        small = Path(tmp) / "small"
        small.mkdir()
        # Real-world Angular code is multi-line; the regex locator expects
        # the name at line-start with indentation, so we mirror that.
        (small / "a.ts").write_text(
            """\
import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class A {
  private x = inject<Foo>(Foo);
  bar(): number { return 1; }
}
"""
        )
        result = run(["codeq", "find", "bar", "-p", str(small)], check=False)
        assert "[codeq] find sweep truncated" not in result.stderr, (
            f"small-tree find emitted spurious truncation notice: {result.stderr}"
        )
        assert "a.ts" in result.stdout, (
            f"find missed the broken-ctags method: {result.stdout}"
        )


def test_codeq_modular_layout() -> None:
    """Each command family lives in a vertical slice and large shared files stay bounded."""
    root = Path(__file__).resolve().parents[2]
    package = root / "src" / "codeq"
    expected_slices = {
        "code_context",
        "dependencies",
        "pattern_check",
        "references",
        "repo_map",
        "symbol_body",
        "symbol_search",
        "tags",
    }
    missing = sorted(
        name
        for name in expected_slices
        if not (package / "features" / name / "command.py").is_file()
    )
    assert not missing, f"missing vertical slices: {missing}"

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text().splitlines())}"
        for path in package.rglob("*.py")
        if len(path.read_text().splitlines()) > 250
    ]
    assert not oversized, (
        f"codeq modules exceeded the 250-line vertical-slice budget: {oversized}"
    )
