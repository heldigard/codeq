from __future__ import annotations

import tempfile
from pathlib import Path

from .helpers import run


EXCLUDED_DIRS = [
    "node_modules/lodash",
    "__pycache__",
    "dist",
    ".pytest_cache",
    ".memory-bank",
    ".claude/projects/-tmp-proj",
    ".codex/sessions",
    ".claude/file-history",
    ".angular/cache",
    ".nx/cache",
    "storybook-static",
    "cdk.out",
    ".aws-sam",
    "amplify/backend",
    ".expo",
    ".metro",
    "wheelhouse",
    ".jdtls-data",
    ".metals",
    ".gopls",
    ".rust-analyzer",
    ".tsserver",
    ".kilocode",
    ".cursor",
    ".continue",
    ".trae",
    ".windsurf",
    ".cline",
    ".roo",
    ".cody",
    ".augment",
    ".aider",
    ".codebuddy",
    ".playwright-mcp",
    ".chrome-devtools-mcp",
    ".puppeteer-mcp",
    ".browserbase-mcp",
    ".firecrawl-mcp",
    ".agent-browser",
    ".puppeteer",
    ".playwright",
]

EXCLUDED_OUTPUT_MARKERS = [
    "node_modules",
    "__pycache__",
    "/dist/",
    ".pytest_cache",
    ".memory-bank",
    "file-history",
    ".angular",
    "/.nx/",
    "storybook-static",
    "cdk.out",
    ".aws-sam",
    "/amplify/",
    "/.expo/",
    "/.metro/",
    "wheelhouse",
    ".jdtls-data",
    "/.metals/",
    "/.gopls/",
    ".rust-analyzer",
    ".tsserver",
    ".kilocode",
    "/.cursor/",
    ".continue",
    "/.trae/",
    ".windsurf",
    "/.cline/",
    "/.roo/",
    "/.cody/",
    "/.augment/",
    "/.aider",
    "/.codebuddy/",
    ".playwright-mcp",
    ".chrome-devtools-mcp",
    ".puppeteer-mcp",
    ".browserbase-mcp",
    ".firecrawl-mcp",
    ".agent-browser",
    "/.puppeteer",
    "/.playwright",
]

SESSION_MARKERS = ["session.jsonl"]


def _write_noisy_fixture(path: Path, index: int) -> None:
    if path.suffix == ".jsonl":
        path.write_text('{"message": "vendored_check() from old transcript"}\n')
        return
    path.write_text(f"def vendored_check():\n    return {index}\n")


def _build_vendor_project(root: Path) -> Path:
    proj = root / "proj"
    (proj / "src").mkdir(parents=True)
    for rel in EXCLUDED_DIRS:
        (proj / rel).mkdir(parents=True)

    (proj / "src" / "app.py").write_text(
        "def vendored_check():\n    return 1\n\n"
        "def caller():\n    return vendored_check()\n"
    )

    noisy_files = [
        "node_modules/lodash/x.py",
        "__pycache__/y.py",
        "dist/z.py",
        ".pytest_cache/w.py",
        ".memory-bank/currentTask.py",
        ".claude/projects/-tmp-proj/session.jsonl",
        ".codex/sessions/session.jsonl",
        ".claude/file-history/old.py",
        ".angular/cache/a.py",
        ".nx/cache/n.py",
        "storybook-static/s.py",
        "cdk.out/c.py",
        ".aws-sam/sam.py",
        "amplify/backend/b.py",
        ".expo/expo.py",
        ".metro/metro.py",
        "wheelhouse/whl.py",
        ".jdtls-data/j.py",
        ".metals/m.py",
        ".gopls/g.py",
        ".rust-analyzer/r.py",
        ".tsserver/t.py",
        ".kilocode/k.py",
        ".cursor/cu.py",
        ".continue/co.py",
        ".trae/tr.py",
        ".windsurf/w.py",
        ".cline/cl.py",
        ".roo/ro.py",
        ".cody/cd.py",
        ".augment/au.py",
        ".aider/ai.py",
        ".codebuddy/cb.py",
        ".playwright-mcp/pw.py",
        ".chrome-devtools-mcp/cd.py",
        ".puppeteer-mcp/pm.py",
        ".browserbase-mcp/bb.py",
        ".firecrawl-mcp/fc.py",
        ".agent-browser/ab.py",
        ".puppeteer/pp.py",
        ".playwright/pl.py",
    ]
    for index, rel in enumerate(noisy_files, start=2):
        _write_noisy_fixture(proj / rel, index)
    return proj


def _assert_src_only(output: str, *, include_sessions: bool = False) -> None:
    assert "src/app.py" in output, f"missing src hit: {output}"
    markers = EXCLUDED_OUTPUT_MARKERS + (SESSION_MARKERS if include_sessions else [])
    for marker in markers:
        assert marker not in output, f"leaked excluded path {marker}: {output}"


def test_codeq_excludes_vendor() -> None:
    """codeq find/refs/tags must not return symbols from vendor/cache/session dirs."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _build_vendor_project(Path(tmp))

        find = run(["codeq", "find", "vendored_check", "-p", str(proj)])
        _assert_src_only(find.stdout)

        refs = run(["codeq", "refs", "vendored_check", "-p", str(proj)])
        _assert_src_only(refs.stdout, include_sessions=True)

        tags_path = proj / ".tags"
        run(["codeq", "tags", "-p", str(proj), "-o", str(tags_path)])
        _assert_src_only(tags_path.read_text())


def _build_aider_wildcard_project(root: Path) -> Path:
    """Project where the only TS file lives under `.aider.chat.history` —
    a directory whose name matches the VENDOR_EXCLUDES wildcard entry
    `.aider*` (see codeq.shared.config). The bug pre-fix: ``_walk_source_files``
    used ``p in VENDOR_EXCLUDES`` (exact equality), so this wildcard entry
    silently leaked Aider wildcard-segment cache dirs through the find
    fallback sweep. The primary ctags pass already excluded them via
    ``ctags --exclude='.aider*'``, so this test exercises the SECONDARY
    brace-lang regex sweep / Lombok walk in `cmd_find` (called only when
    ctags primary returns 0 hits) by giving ctags nothing it can index
    (no .py / .ts files in src/) — the TS file in `.aider.chat.history/`
    alone would otherwise be picked up by ctags. After the fix, the fnmatch
    filter excludes it and find returns no hits."""
    proj = root / "proj"
    (proj / ".aider.chat.history").mkdir(parents=True)
    (proj / ".aider.tags.cache").mkdir(parents=True)
    (proj / "src").mkdir(parents=True)
    # Symbol only in the wildcard-segment dir.
    (proj / ".aider.chat.history" / "notes.ts").write_text(
        "export class AiderOnly {\n  run(): void {}\n}\n"
    )
    (proj / ".aider.tags.cache" / "stuff.ts").write_text(
        "export class TagsCacheOnly {\n  run(): void {}\n}\n"
    )
    # Empty src to keep ctags primary pass empty (forces the fallback sweep).
    (proj / "src" / ".keep").write_text("")
    return proj


def test_codeq_find_excludes_aider_wildcard_segments() -> None:
    """Regression: `codeq find` must exclude VENDOR_EXCLUDES wildcards
    (not just literal entries) in the brace-lang fallback sweep. Pre-fix
    this asserted on `/workspace/proj/.aider.chat.history` leaking through
    `codeq find AiderOnly -p ...`. Asserted end-to-end via the CLI so
    the test fails on any future regression of the filter uniform
    semantics (rg / ctags / pure-Python walker / find fallback)."""
    from .helpers import run  # local re-import keeps the test self-contained

    with tempfile.TemporaryDirectory() as tmp:
        proj = _build_aider_wildcard_project(Path(tmp))
        for sym in ("AiderOnly", "TagsCacheOnly"):
            result = run(["codeq", "find", sym, "-p", str(proj)], check=False)
            # `.aider.chat.history` and `.aider.tags.cache` must NOT appear.
            assert ".aider" not in result.stdout, (
                f"codeq find {sym} leaked VENDOR_EXCLUDES wildcard dir: "
                f"{result.stdout!r}"
            )
            assert "no symbol named" in result.stderr or result.returncode != 0, (
                f"expected no-hit for {sym} (only files are in wildcard dirs), "
                f"got stdout={result.stdout!r} stderr={result.stderr!r}"
            )
