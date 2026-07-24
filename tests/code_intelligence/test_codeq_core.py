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


def test_codeq_tags_default_output_scopes_to_search_root(fixture_dir: Path) -> None:
    """`codeq tags -p /other/repo` should write `/other/repo/.tags`, not
    `.tags` in the caller's cwd. Multi-repo agents often index sibling projects
    from one controller cwd; cwd-scoped output makes later `grep .tags` inspect
    the wrong repository."""
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        result = run(["codeq", "tags", "-p", str(fixture_dir)], cwd=cwd)

        assert result.returncode == 0, result.stderr
        assert (fixture_dir / ".tags").is_file(), result.stdout
        assert not (cwd / ".tags").exists(), (
            "default tag output leaked into the caller cwd instead of the search root"
        )
        assert str(fixture_dir / ".tags") in result.stdout


def test_codeq_check_java_probe() -> None:
    """`codeq check -l java` must NOT die with 'no probe for lang'. Java is
    already supported by `codeq rename` and by body extraction (BODY_PATTERNS),
    so the check subcommand — a pre-flight validator for ast-grep patterns —
    should be in parity. Bug: PROBE dict in shared/config.py listed only
    python/javascript/typescript/go/rust, even though ast-grep handles java
    and codeq rename has supported java since v1.6.0."""
    result = run(
        ["codeq", "check", "void foo($$$A) { $$$B }", "-l", "java"], check=False
    )
    assert "no probe for lang" not in result.stderr, (
        f"check refused java even though rename + body support it: "
        f"{result.stdout}{result.stderr}"
    )
    assert result.returncode == 0, (
        f"valid java pattern should validate cleanly: {result.stdout}{result.stderr}"
    )


def test_codeq_check_bash_probe() -> None:
    """`codeq check -l bash` must not die with 'no probe for lang'. bash is in
    EXT_LANG + LANG_INCLUDES; check must stay in lang-parity with them."""
    result = run(["codeq", "check", "echo $X", "-l", "bash"], check=False)
    assert "no probe for lang" not in result.stderr, (
        f"check refused bash even though refs supports it: "
        f"{result.stdout}{result.stderr}"
    )
    assert result.returncode == 0, (
        f"valid bash pattern should validate cleanly: {result.stdout}{result.stderr}"
    )


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
    # TS files named `mod.ts` are direct modules too (`./mod`), not only
    # package-entry files imported by their parent directory.
    (fixture_dir / "rdeps-mod-consumer.ts").write_text(
        "import { value } from './mod';\nexport const y = value;\n"
    )
    (fixture_dir / "mod.ts").write_text("export const value = 1;\n")
    result = run(
        ["codeq", "rdeps", str(fixture_dir / "mod.ts"), "-p", str(fixture_dir)]
    )
    assert "rdeps-mod-consumer.ts" in result.stdout, (
        f"rdeps TS missed direct ./mod importer: {result.stdout}"
    )
    # Python package files often have generic names like `command.py`. rdeps
    # must search the importable module path, not just the stem `command`,
    # otherwise every sibling `*.command` import is reported as a false importer.
    (fixture_dir / "pkg" / "a").mkdir(parents=True)
    (fixture_dir / "pkg" / "b").mkdir(parents=True)
    for init in (
        fixture_dir / "pkg" / "__init__.py",
        fixture_dir / "pkg" / "a" / "__init__.py",
        fixture_dir / "pkg" / "b" / "__init__.py",
    ):
        init.write_text("")
    (fixture_dir / "pkg" / "a" / "command.py").write_text(
        "def target() -> int:\n    return 1\n"
    )
    (fixture_dir / "pkg" / "b" / "command.py").write_text(
        "def other() -> int:\n    return 2\n"
    )
    (fixture_dir / "pkg_consumer.py").write_text(
        "from pkg.a.command import target\n"
        "from pkg.b.command import other\n"
        "value = target() + other()\n"
    )
    result = run(
        [
            "codeq",
            "rdeps",
            str(fixture_dir / "pkg" / "a" / "command.py"),
            "-p",
            str(fixture_dir),
        ]
    )
    assert "pkg.a.command" in result.stdout, (
        f"rdeps Python missed precise package importer: {result.stdout}"
    )
    assert "pkg.b.command" not in result.stdout, (
        f"rdeps Python used noisy stem key for command.py: {result.stdout}"
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
    """Structural integrity: each command family lives in a vertical slice,
    shared modules have single responsibility, and no module mixes unrelated
    concerns. Line count is NOT enforced — a cohesive 300-line module is
    better than a 100-line module with mixed responsibilities."""
    root = Path(__file__).resolve().parents[2]
    package = root / "src" / "codeq"
    expected_slices = {
        "capabilities",
        "code_context",
        "dependencies",
        "doctor",
        "pattern_check",
        "references",
        "rename",
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

    # Each feature slice should have exactly one command module (no stale copies)
    for name in expected_slices:
        cmd_files = list((package / "features" / name).glob("command*.py"))
        assert len(cmd_files) == 1, (
            f"feature {name} has {len(cmd_files)} command files (expected 1): "
            f"{[f.name for f in cmd_files]}"
        )

    # Shared modules should not import from features (low coupling)
    shared_dir = package / "shared"
    for shared_file in shared_dir.glob("*.py"):
        if shared_file.name == "__init__.py":
            continue
        content = shared_file.read_text()
        feature_imports = [
            line.strip()
            for line in content.splitlines()
            if "from codeq.features." in line and not line.strip().startswith("#")
        ]
        assert not feature_imports, (
            f"{shared_file.relative_to(root)} imports from features "
            f"(violates low coupling): {feature_imports}"
        )


def test_codeq_def_filter_re() -> None:
    """`_def_filter_re` (extracted from cmd_refs) isolates DECLARATION lines
    from call sites, per language. Locks the most-tuned regex in codeq so the
    extraction didn't change behavior."""
    from codeq.features.references.command import _def_filter_re

    py = _def_filter_re("python", "foo")
    assert py.search("def foo(x):")
    assert not py.search("result = foo(x)")

    ts = _def_filter_re("typescript", "foo")
    assert ts.search("  foo(): void {")
    assert ts.search("function foo() {")
    assert not ts.search("    return this.foo()")

    ja = _def_filter_re("java", "foo")
    assert ja.search("public void foo() {")
    assert not ja.search("        foo()")

    go = _def_filter_re("go", "foo")
    assert go.search("func foo() {")
    assert not go.search("    foo()")


def test_codeq_json_output(fixture_dir: Path) -> None:
    """--json flag produces valid JSON with structured data for refs/deps/rdeps
    and text envelope for other commands."""
    import json

    # refs: structured JSON
    result = run(["codeq", "--json", "refs", "calculate", "-p", str(fixture_dir)])
    data = json.loads(result.stdout)
    assert data["command"] == "refs"
    assert data["count"] > 0
    assert len(data["refs"]) > 0
    assert "calculate" in data["refs"][0]

    # deps: structured JSON
    file_path = fixture_dir / "calc.py"
    result = run(["codeq", "--json", "deps", str(file_path)])
    data = json.loads(result.stdout)
    assert data["command"] == "deps"
    assert data["count"] > 0
    assert any(imp["module"] == "json" for imp in data["imports"])

    # rdeps: structured JSON
    result = run(["codeq", "--json", "rdeps", str(file_path), "-p", str(fixture_dir)])
    data = json.loads(result.stdout)
    assert data["command"] == "rdeps"
    assert data["count"] > 0

    # context: structured editing bundle
    result = run(
        [
            "codeq",
            "--json",
            "context",
            "calculate",
            str(file_path),
            "-p",
            str(fixture_dir),
            "--no-llm",
        ]
    )
    data = json.loads(result.stdout)
    assert data["command"] == "context"
    assert data["signature"].startswith("def calculate")
    assert "def calculate" in data["body"]
    assert data["refs_count"] > 0
    assert any(imp["module"] == "json" for imp in data["imports"])
    assert data["summary"]["status"] == "skipped"
    assert data["exit_code"] == 0
    assert data["unchanged"] is False
    assert len(data["fingerprint"]) == 64

    # relations: structured, compact orientation bundle without the body/deps.
    result = run(
        [
            "codeq",
            "--json",
            "relations",
            "calculate",
            str(file_path),
            "-p",
            str(fixture_dir),
            "--no-llm",
        ]
    )
    data = json.loads(result.stdout)
    assert data["command"] == "relations"
    assert data["signature"].startswith("def calculate")
    assert "body" not in data
    assert "imports" not in data
    assert data["internal_call_hints"] == []
    assert data["unchanged"] is False
    assert len(data["fingerprint"]) == 64

    # body: structured JSON
    result = run(["codeq", "--json", "body", "calculate", str(file_path)])
    data = json.loads(result.stdout)
    assert data["command"] == "body"
    assert data["exit_code"] == 0
    assert "def calculate" in data["body"]

    # error case: missing symbol
    result = run(
        ["codeq", "--json", "body", "nonexistent", str(file_path)],
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["exit_code"] == 1
    assert "no def/class" in data["error"]


def test_codeq_json_context_incremental_receipts(fixture_dir: Path) -> None:
    """Repeat context is compact, while invalid/stale fingerprints fail open."""
    import json

    file_path = fixture_dir / "calc.py"
    base = [
        "codeq",
        "--json",
        "context",
        "calculate",
        str(file_path),
        "-p",
        str(fixture_dir),
        "--no-llm",
    ]
    first = run(base)
    first_data = json.loads(first.stdout)
    fingerprint = first_data["fingerprint"]

    repeat = run(base)
    repeat_data = json.loads(repeat.stdout)
    assert repeat_data["fingerprint"] == fingerprint

    receipt = run([*base, "--since-fingerprint", fingerprint])
    receipt_data = json.loads(receipt.stdout)
    assert receipt_data["unchanged"] is True
    assert receipt_data["fingerprint"] == fingerprint
    assert receipt_data["exit_code"] == 0
    assert "body" not in receipt_data
    assert "refs" not in receipt_data
    assert len(receipt.stdout) < len(first.stdout) / 2

    invalid = run([*base, "--since-fingerprint", "not-a-sha256"])
    invalid_data = json.loads(invalid.stdout)
    assert invalid_data["unchanged"] is False
    assert invalid_data["fingerprint"] == fingerprint
    assert "body" in invalid_data

    caller = fixture_dir / "main.py"
    caller.write_text(
        caller.read_text(encoding="utf-8")
        + "\n\ndef alternate():\n    return calculate(3, 4)\n",
        encoding="utf-8",
    )
    refs_changed = run([*base, "--since-fingerprint", fingerprint])
    refs_changed_data = json.loads(refs_changed.stdout)
    assert refs_changed_data["unchanged"] is False
    assert refs_changed_data["fingerprint"] != fingerprint
    assert refs_changed_data["refs_count"] > first_data["refs_count"]

    refs_fingerprint = refs_changed_data["fingerprint"]
    original = file_path.read_text(encoding="utf-8")
    file_path.write_text(
        original.replace("return a + b", "return a - b"), encoding="utf-8"
    )
    changed = run([*base, "--since-fingerprint", refs_fingerprint])
    changed_data = json.loads(changed.stdout)
    assert changed_data["unchanged"] is False
    assert changed_data["fingerprint"] != refs_fingerprint
    assert "return a - b" in changed_data["body"]


def test_codeq_json_relations_incremental_receipt(fixture_dir: Path) -> None:
    import json

    base = [
        "codeq",
        "--json",
        "relations",
        "calculate",
        str(fixture_dir / "calc.py"),
        "-p",
        str(fixture_dir),
        "--no-llm",
    ]
    full = run(base)
    full_data = json.loads(full.stdout)
    receipt = run([*base, "--since-fingerprint", full_data["fingerprint"]])
    receipt_data = json.loads(receipt.stdout)

    assert receipt_data["unchanged"] is True
    assert receipt_data["fingerprint"] == full_data["fingerprint"]
    assert "internal_call_hints" not in receipt_data
    assert "refs" not in receipt_data
    assert len(receipt.stdout) < len(full.stdout) / 2


def test_codeq_since_fingerprint_requires_json(fixture_dir: Path) -> None:
    result = run(
        [
            "codeq",
            "context",
            "calculate",
            str(fixture_dir / "calc.py"),
            "--no-llm",
            "--since-fingerprint",
            "abc",
        ],
        check=False,
    )

    assert result.returncode == 2
    assert "--since-fingerprint requires --json" in result.stderr


def test_codeq_capabilities_contract() -> None:
    """Routers/workers need stable risk hints before deciding which hand to use."""
    import json

    result = run(["codeq", "capabilities"])
    assert result.returncode == 0, result.stderr
    assert "rename" in result.stdout
    assert "destructive" in result.stdout

    result = run(["codeq", "--json", "capabilities"])
    data = json.loads(result.stdout)
    by_name = {item["name"]: item for item in data["capabilities"]}

    assert data["schema_version"] == 1
    assert by_name["context"]["structured_json"] is True
    assert by_name["context"]["incremental_fingerprint"] is True
    assert by_name["relations"]["read_only"] is True
    assert by_name["relations"]["incremental_fingerprint"] is True
    assert by_name["rename"]["destructive"] is True
    assert by_name["doctor"]["open_world"] is True


def test_codeq_limit_flag(fixture_dir: Path) -> None:
    """--limit flag controls max output for refs and rdeps."""
    # refs with limit
    result = run(
        [
            "codeq",
            "refs",
            "calculate",
            "-p",
            str(fixture_dir),
            "--limit",
            "1",
        ]
    )
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) <= 1, f"refs --limit 1 returned {len(lines)} lines"

    # rdeps with limit
    file_path = fixture_dir / "calc.py"
    result = run(
        [
            "codeq",
            "rdeps",
            str(file_path),
            "-p",
            str(fixture_dir),
            "--limit",
            "1",
        ]
    )
    lines = [line for line in result.stdout.strip().split("\n") if line]
    # First line is the import line, second is the summary on stderr
    assert len(lines) <= 1, f"rdeps --limit 1 returned {len(lines)} lines"


def test_codeq_module_entry_point() -> None:
    """`python -m codeq --version` works as an entry point."""
    result = run(["python3", "-m", "codeq", "--version"], check=False)
    assert result.returncode == 0, f"python -m codeq --version failed: {result.stderr}"
    assert "codeq" in result.stdout, f"unexpected output: {result.stdout}"


def test_outline_regex_line_number_after_blank(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Regression: the brace-lang outline regex's type group spans newlines
    (\\s in the char class), so when a method is preceded by a blank line the
    whole match anchored at the blank line and `line_no` pointed there. For TS
    this mis-numbered the method; for Java (no `:Type` return syntax) the
    modifier/return checks read the blank line and DROPPED the method entirely.
    Fix: derive line_no from m.start(1) (the captured name = real method line)."""
    from codeq.shared.locators import _regex_outline_methods

    # TS: method on line 3, blank line on line 2.
    ts = tmp_path / "s.ts"
    ts.write_text(
        "export class S {\n\n  public getCurrent(): string {\n    return 'x';\n  }\n}\n"
    )
    hits = {h[2]: h[0] for h in _regex_outline_methods(str(ts), "typescript", set())}
    assert "getCurrent" in hits, f"TS outline missed getCurrent: {hits}"
    assert hits["getCurrent"] == 3, (
        f"TS method mis-numbered (blank-line anchor bug): {hits}"
    )

    # Java: public method after a blank line must be found (was dropped).
    ja = tmp_path / "S.java"
    ja.write_text(
        "package x;\npublic class S {\n\n"
        '    public String getName() {\n        return "x";\n    }\n}\n'
    )
    jhits = {h[2] for h in _regex_outline_methods(str(ja), "java", set())}
    assert "getName" in jhits, (
        f"Java outline dropped public method after blank line: {jhits}"
    )


def test_body_not_truncated_by_brace_in_comment(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Regression: a `}` inside a // line comment (or a string) must not
    truncate brace-lang body extraction. The naive counter (str.count) treated
    the comment's `}` as a closing brace and cut the body before the `return`."""
    from codeq.shared.extraction import _class_body, _raw_body

    ja = tmp_path / "Service.java"
    ja.write_text(
        "public class Service {\n"
        "    public String greet() {\n"
        "        // close } in comment\n"
        '        return "x {y} z";\n'
        "    }\n"
        "    public int compute() {\n"
        "        if (true) { return 42; }\n"
        "        return 0;\n"
        "    }\n"
        "}\n"
    )
    # method body must reach past the comment brace to the return
    body = _raw_body(str(ja), "greet", "java")
    assert body is not None, "greet body not found"
    assert "return" in body, f"greet body truncated by brace-in-comment: {body!r}"

    # class body must include BOTH methods (comment/string braces must not
    # prematurely close the class block)
    cls = _class_body(str(ja), "Service", "java")
    assert cls is not None, "Service class body not found"
    assert "greet" in cls and "compute" in cls, (
        f"class body truncated: greet={('greet' in cls)} compute={('compute' in cls)}"
    )


def test_body_not_truncated_by_brace_in_string(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Regression: braces inside a TS template literal / string must not distort
    the brace count, so a method body containing them extracts whole."""
    from codeq.shared.extraction import _raw_body

    ts = tmp_path / "svc.ts"
    ts.write_text(
        "export class Svc {\n"
        "  public build(): string {\n"
        "    const map = { a: 1 };\n"
        "    return `${map.a} of {total}`;\n"
        "  }\n"
        "}\n"
    )
    body = _raw_body(str(ts), "build", "typescript")
    assert body is not None, "build body not found"
    assert "return" in body and "total" in body, (
        f"TS body truncated by brace-in-string: {body!r}"
    )
