from __future__ import annotations

from pathlib import Path

from .helpers import run


def test_codeq_typescript(fixture_dir: Path) -> None:
    service = fixture_dir / "version-check.service.ts"

    # find
    result = run(["codeq", "find", "VersionCheckService", "-p", str(fixture_dir)])
    assert "version-check.service.ts" in result.stdout, (
        f"codeq find TS failed: {result.stdout}"
    )

    # outline lists class + methods
    result = run(["codeq", "outline", str(service)])
    assert "VersionCheckService" in result.stdout and "getCurrent" in result.stdout, (
        f"codeq outline TS failed: {result.stdout}"
    )

    # body of a method returns the exact body
    result = run(["codeq", "body", "getCurrent", str(service)])
    assert "this.version" in result.stdout, (
        f"codeq body TS method failed: {result.stdout}"
    )

    # refs finds the call site in caller.ts
    result = run(["codeq", "refs", "getCurrent", "-p", str(fixture_dir)])
    assert "caller.ts" in result.stdout, f"codeq refs TS failed: {result.stdout}"


def test_codeq_typescript_after_generic_field(fixture_dir: Path) -> None:
    """ctags 5.9.0 silently drops TS class members after a generic-arg field
    initializer like `private x = inject<T>(...)` (Angular standalone-component
    pattern). codeq must fall back to a regex-based locator so `body` / `find`
    / `outline` still work on those methods. Regression locked in 2026-06-28.
    """
    service = fixture_dir / "angular-component.service.ts"

    # body — each method must return its body via the regex fallback inside _locate_line
    body = run(["codeq", "body", "onMessagesScroll", str(service)])
    assert "console.log(event)" in body.stdout, (
        f"codeq body regex fallback failed: {body.stdout}{body.stderr}"
    )
    body = run(["codeq", "body", "submitMessage", str(service)])
    assert "await Promise.resolve()" in body.stdout, (
        f"codeq body submitMessage regex fallback failed: {body.stdout}{body.stderr}"
    )
    body = run(["codeq", "body", "handleStreamFailure", str(service)])
    assert "console.error(msg, error)" in body.stdout, (
        f"codeq body handleStreamFailure regex fallback failed: {body.stdout}{body.stderr}"
    )

    # sig — same fallback path; signature-only should still resolve via regex
    sig = run(["codeq", "sig", "submitMessage", str(service)])
    assert "submitMessage" in sig.stdout, (
        f"codeq sig regex fallback failed: {sig.stdout}{sig.stderr}"
    )

    # find — per-file regex sweep kicks in when ctags-wide finds nothing
    find = run(["codeq", "find", "onMessagesScroll", "-p", str(fixture_dir)])
    assert "angular-component.service.ts" in find.stdout, (
        f"codeq find regex sweep failed: {find.stdout}{find.stderr}"
    )

    # outline — must list the methods even though ctags missed them; must NOT
    # fabricate entries for keywords like `if`/`effect`/`clearTimeout`.
    outline = run(["codeq", "outline", str(service)])
    for name in ("onMessagesScroll", "submitMessage", "handleStreamFailure"):
        assert name in outline.stdout, (
            f"codeq outline missing method {name} after generic-arg field: {outline.stdout}"
        )
    for kw in ("if", "while", "for", "effect", "clearTimeout", "try"):
        # Only complain if the keyword appears in a `method` kind row (not elsewhere).
        bad = [
            line
            for line in outline.stdout.splitlines()
            if "method" in line
            and (f" {kw} " in line or line.endswith(f"method        {kw}"))
        ]
        assert not bad, f"codeq outline leaked keyword {kw!r} as method: {bad}"


def test_codeq_typescript_outline_after_partial_ctags_hit(fixture_dir: Path) -> None:
    """If ctags sees methods before an Angular-style generic field initializer,
    `outline` must still merge regex-discovered methods after that field. This
    locks the TS generics/inheritance failure mode where agents fell back to
    grepping signatures because the method-name map was incomplete."""
    service = fixture_dir / "advanced-generic.service.ts"

    outline = run(["codeq", "outline", str(service)])
    for name in ("ngOnInit", "loadFor", "selectOne", "handleFailure"):
        assert name in outline.stdout, (
            f"codeq outline missed method {name} in mixed ctags/regex TS file: {outline.stdout}"
        )
    assert "method        pick" not in outline.stdout, (
        f"codeq outline promoted an object-literal method as a class method: {outline.stdout}"
    )

    body = run(["codeq", "body", "selectOne", str(service)])
    assert "return this.adapter.pick(key)" in body.stdout, (
        f"codeq body failed for generic inherited TS method: {body.stdout}{body.stderr}"
    )


def test_codeq_refs_ts_filters_method_declaration(fixture_dir: Path) -> None:
    """`refs` on TS class methods must NOT echo back the declaration line —
    `private foo(event: T): void {` is not a reference. (Bug pre-2026-06-28:
    the keyword-only decl filter missed access-modifier methods.)"""
    service = fixture_dir / "angular-component.service.ts"
    refs = run(
        [
            "codeq",
            "refs",
            "onMessagesScroll",
            "-l",
            "typescript",
            "-p",
            str(fixture_dir),
        ]
    )
    # Call sites in caller-of-chatbot.ts MUST appear.
    assert "caller-of-chatbot.ts" in refs.stdout, (
        f"refs missed call sites: {refs.stdout}{refs.stderr}"
    )
    # The declaration line in service.ts must NOT appear.
    decl_lines = [
        line
        for line in refs.stdout.splitlines()
        if str(service) in line and "protected onMessagesScroll" in line
    ]
    assert not decl_lines, (
        f"refs returned the TS method declaration line as a 'reference': {decl_lines}\n"
        f"full output: {refs.stdout}"
    )


def test_codeq_deps_ts_reexports_and_dynamic(fixture_dir: Path) -> None:
    """`deps` must catch the full TS/JS import surface, not just plain
    `import x from 'x'` lines: re-exports (`export ... from 'x'`), wildcard
    re-exports (`export * from 'x'`), dynamic imports (`await import('x')`),
    and TS-CommonJS (`import x = require('x')`). Regression locked 2026-06-28."""
    src = fixture_dir / "module-with-reexports.ts"
    src.write_text(
        """\
import a from 'a';
import { b } from 'b';
export { c } from 'c';
export * from 'd';
export { e as f } from './e';
const dyn = await import('./dynamic');
const dyn2 = import('./dynamic2');
import cjs = require('cjs-mod');
"""
    )
    deps = run(["codeq", "deps", str(src)])
    expected = {"a", "b", "c", "d", "./e", "./dynamic", "./dynamic2", "cjs-mod"}
    # Module path is the token after the kind column; the `( names )` suffix
    # (named bindings, Python parity) must NOT be mistaken for the module.
    found = set()
    for line in deps.stdout.splitlines():
        if not line.strip():
            continue
        rest = line.split(None, 2)[2] if len(line.split(None, 2)) > 2 else ""
        found.add(rest.split(" (")[0].strip())
    missing = expected - found
    assert not missing, (
        f"deps missed re-exports/dynamic/CommonJS: missing={missing}\n"
        f"expected={expected}\nfound={found}\nstdout={deps.stdout}"
    )


def test_codeq_deps_ts_multiline_barrel(fixture_dir: Path) -> None:
    """`deps` must capture ES-module imports that span MULTIPLE lines — the
    barrel/harness pattern (`import { a, b, c } from './harness'` with each
    name on its own line). Pre-fix, the line-anchored regex saw only the
    `import {` line and DROPPED the barrel entirely (real incident:
    RevOpsAIFrontend tests/server-*.spec.mjs importing server-test-harness.mjs
    — `codeq deps` returned only `vitest`). Also asserts named bindings are
    surfaced with Python parity (`module ( names )`). Regression locked
    2026-07-03."""
    spec = fixture_dir / "barrel-consumer.spec.mjs"
    spec.write_text(
        "import { describe } from 'vitest';\n"
        "import {\n"
        "  Readable,\n"
        "  existsSync,\n"
        "  PayloadTooLargeError,\n"
        "} from './server-test-harness.mjs';\n"
        "import defaultOnly from './single.js';\n"
    )
    deps = run(["codeq", "deps", str(spec)])
    out = deps.stdout
    # 1. the barrel module MUST resolve (the bug: dropped entirely because the
    #    `import {` opener and the `} from './...'` closer sat on different lines)
    assert "./server-test-harness.mjs" in out, (
        f"deps dropped the multi-line barrel import: {out}{deps.stderr}"
    )
    # 2. named bindings surfaced (Python parity: `from  m ( a, b )`)
    assert "Readable" in out and "PayloadTooLargeError" in out, (
        f"deps did not surface named bindings from the barrel: {out}"
    )
    # 3. sibling imports still resolve and are not disturbed by the flattening
    assert "vitest" in out and "./single.js" in out, (
        f"deps lost sibling single-line imports: {out}"
    )
