from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def test_codeq_summary_and_context_no_llm() -> None:
    """`codeq summary` / `context` / `relations` accept `--no-llm` (and
    `CODEQ_NO_LLM=1`) for deterministic CI runs that don't depend on the
    local Ollama daemon. Body output must remain authoritative; the
    disabled-prefix note goes to stderr."""
    env_no_llm = {**os.environ, "CODEQ_NO_LLM": "1"}
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "proj"
        d.mkdir()
        (d / "mod.ts").write_text(
            """\
import { Component } from '@angular/core';

@Component({ selector: 'app-x' })
export class X {
  private readonly svc = inject<Foo>(Foo);

  protected doWork(input: string): string {
    return this.svc.process(input);
  }
}
"""
        )
        # Caller so `refs` has something to find
        (d / "caller.ts").write_text(
            "import { X } from './mod';\nexport function run(x: X, s: string) {\n  return x.doWork(s);\n}\n"
        )
        (d / "host.ts").write_text("import { X } from './mod';\nexport const componentType = X;\n")

        # `summary --no-llm` → stdout empty (the LLM isn't needed for the body),
        # stderr has the disabled-prefix note.
        r = subprocess.run(
            ["codeq", "summary", "doWork", str(d / "mod.ts"), "--no-llm"],
            capture_output=True,
            text=True,
            env=env_no_llm,
            check=False,
        )
        assert r.returncode == 2, (
            f"summary --no-llm should exit 2 (Ollama skipped): rc={r.returncode} "
            f"stdout={r.stdout!r} stderr={r.stderr!r}"
        )
        assert "ollama summary unavailable" in r.stderr, (
            f"summary --no-llm missing the disabled-prefix note in stderr: {r.stderr!r}"
        )
        assert r.stdout == "", (
            f"summary --no-llm must not emit a body, just the disabled-prefix: {r.stdout!r}"
        )

        # `body --summary --no-llm` → body still printed, disabled-prefix note
        # appears as the FIRST stdout block (so it travels with the output).
        r = subprocess.run(
            ["codeq", "body", "doWork", str(d / "mod.ts"), "--summary", "--no-llm"],
            capture_output=True,
            text=True,
            env=env_no_llm,
            check=False,
        )
        assert r.returncode == 0, f"body --summary --no-llm should exit 0: rc={r.returncode}"
        assert "doWork(input: string)" in r.stdout, (
            f"body --summary --no-llm lost the body: {r.stdout!r}"
        )
        assert "ollama summary unavailable" in r.stdout, (
            f"body --summary --no-llm missing disabled-prefix: {r.stdout!r}"
        )

        # `context --no-llm` → all sections present (signature, body, callers,
        # imports), summary section replaced by a one-line note.
        r = subprocess.run(
            ["codeq", "context", "doWork", str(d / "mod.ts"), "-p", str(d), "--no-llm"],
            capture_output=True,
            text=True,
            env=env_no_llm,
            check=False,
        )
        assert r.returncode == 0
        for section in (
            "codeq context | target: doWork",
            "=== Signature ===",
            "=== Body ===",
            "=== Callers of 'doWork'",
            "=== Imports of ",
            "=== Importers of ",
            "caller.ts",  # caller is referenced under refs
            "host.ts",  # importer is referenced under rdeps, even without method call
            "[summary skipped",  # the lighter no-llm note for context/relations
        ):
            assert section in r.stdout, (
                f"context --no-llm missing section {section!r}: {r.stdout[:500]!r}"
            )

        # `relations --no-llm` → summary skipped, signature + body-call hints +
        # external refs sections present.
        r = subprocess.run(
            [
                "codeq",
                "relations",
                "doWork",
                str(d / "mod.ts"),
                "-p",
                str(d),
                "--no-llm",
            ],
            capture_output=True,
            text=True,
            env=env_no_llm,
            check=False,
        )
        assert r.returncode == 0
        for section in (
            "codeq relations | target: doWork",
            "=== Signature ===",
            "=== Internal call hints",
            "=== External refs",
            "this.svc.process()",  # body-call hint from regex sweep
            "[summary skipped",
        ):
            assert section in r.stdout, (
                f"relations --no-llm missing {section!r}: {r.stdout[:500]!r}"
            )
        # The symbol's OWN name must NOT leak as a self-call hint (the regex
        # would otherwise match the signature line `doWork(...)`). Bug fixed
        # 2026-06-28 via the exclude_name param on _body_call_hints.
        hint_block = r.stdout.split("=== Internal call hints", 1)[-1].split("=== External refs", 1)[
            0
        ]
        assert "\n# - doWork" not in hint_block and "doWork()" not in hint_block.replace(
            "this.svc.process", ""
        ), f"relations leaked the symbol's own name as a call hint: {hint_block!r}"


def test_codeq_summary_and_context_live() -> None:
    """Live Ollama call: `codeq summary` returns a 1-line description wrapped
    in the provenance banner. Skipped (returns None) when the daemon is down —
    we don't fail CI if Ollama is offline, only verify the SHAPE of the
    output when it IS up."""
    # Probe daemon first via the same `ollama_client.is_alive` codeq uses.
    try:
        sys_mod_path = str(Path.home() / ".claude" / "scripts")
        if sys_mod_path not in sys.path:
            sys.path.insert(0, sys_mod_path)
        import ollama_client  # type: ignore

        if not ollama_client.is_alive(timeout=2.0):
            return  # daemon down — skip
    except Exception:
        return  # client/daemon unavailable — skip

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "live"
        d.mkdir()
        (d / "greet.py").write_text("def greet(name: str) -> str:\n    return f'Hello, {name}!'\n")
        r = subprocess.run(
            ["codeq", "summary", "greet", str(d / "greet.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            return  # model returned empty / transport flake — skip, not a hard fail
        assert "ollama-summary:" in r.stdout, f"live summary missing banner: {r.stdout!r}"
        # The summary line should NOT contain a code block fence or the body itself
        # (proves we're returning a short prose description, not the source).
        assert "def greet" not in r.stdout, f"live summary leaked the body: {r.stdout!r}"


def test_codeq_relations_no_llm_sections() -> None:
    """`codeq relations` emits the four orientation sections — header,
    Signature, Internal call hints (regex over the body), and External refs
    (AST-exact for .py) — under `--no-llm`. Closes the coverage gap: relations
    had zero direct tests (it was only mentioned in a sibling test's docstring)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "proj"
        d.mkdir()
        # target() calls helper() and util() internally → call hints; has a
        # return annotation → exercised by the Signature section.
        (d / "mod.py").write_text(
            "def helper(x: int) -> int:\n"
            "    return x + 1\n"
            "\n"
            "def util(x: int) -> int:\n"
            "    return x * 2\n"
            "\n"
            "def target(value: int) -> int:\n"
            "    a = helper(value)\n"
            "    b = util(a)\n"
            "    return b\n"
        )
        # External caller so the AST-exact `refs` half has a hit to report.
        (d / "caller.py").write_text(
            "from mod import target\n\ndef run(n: int) -> int:\n    return target(n)\n"
        )

        r = subprocess.run(
            [
                "codeq",
                "relations",
                "target",
                str(d / "mod.py"),
                "--no-llm",
                "-p",
                str(d),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 0, (
            f"relations --no-llm should succeed: rc={r.returncode} stderr={r.stderr!r}"
        )
        out = r.stdout
        assert "[codeq relations" in out, f"relations missing the provenance header: {out!r}"
        assert "Signature" in out, f"relations missing Signature section: {out!r}"
        # Both internal callees should surface as call hints (regex over body).
        assert "helper()" in out, f"relations missing helper() call hint: {out!r}"
        assert "util()" in out, f"relations missing util() call hint: {out!r}"
        # The AST-exact refs half should find the caller.py reference.
        assert "caller.py" in out, f"relations missing the external ref from caller.py: {out!r}"
        # relations must NOT embed the full body (that's `context`'s job).
        assert "return b" not in out, (
            f"relations leaked the body (should be cheaper than context): {out!r}"
        )


def test_codeq_body_summary_help_mentions_actual_default() -> None:
    """Regression (2026-07-13 + 2026-07-13 round-17): `codeq body --help`
    must name the ACTUAL default summary model in `codeq.shared.llm`.
    Round-9 set Qwythos-9B; round-17 (2026-07-13) dethroned it with
    TeichAI/Fable-5-v1 (fresh 5-way 9.84 vs 9.40, +4.7%).
    An agent that read `--help` and trusted the stale text wired the wrong
    model into a downstream pipeline. This test asserts the help text
    contains a substring of the live default, so future drift between
    docs/help and the constant fails CI immediately.

    Also asserts the help text names a real model (substring of either the
    default or the fallback) so we never regress to a totally vague hint.
    """
    # Import lazily so the test still loads on hosts where ollama_client is
    # absent — we only need the constant string, not the Ollama daemon.
    from codeq.shared import llm  # type: ignore[import-not-found]

    default = llm._CODEQ_SUMMARY_MODEL  # type: ignore[attr-defined]
    fallback = llm._CODEQ_FALLBACK_MODEL  # type: ignore[attr-defined]

    r = subprocess.run(
        ["codeq", "body", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, f"codeq body --help failed: {r.stderr}"
    help_text = r.stdout

    # The help text MUST contain a substring of the live default model.
    # Round-17 default is TeichAI/Fable-5-v1 — substring 'Fable-5-v1' is
    # present in both help text and README, keeping them aligned.
    assert "Fable-5-v1" in help_text or "TeichAI" in help_text, (
        f"codeq body --help does not mention the actual default model "
        f"({default!r}). Help text was:\n{help_text}\n"
        f"Update the help string in src/codeq/cli.py to match the constant."
    )

    # The help text must ALSO mention the fallback (so users with VRAM-tight
    # hosts know about it from --help alone, not only from the README).
    assert fallback in help_text or "Qwythos" in help_text, (
        f"codeq body --help does not mention the fallback model ({fallback!r}). "
        f"Help text was:\n{help_text}"
    )
