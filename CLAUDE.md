# Project: codeq

`codeq` — precise code-fact extraction CLI for LLM coding agents. Public repo:
https://github.com/heldigard/codeq · PyPI: `codeq-cli`.

## Architecture decision: CLI + skills/instructions, NOT MCP
codeq is a **plain CLI** invoked on-demand by agents (Claude Code, Codex,
Antigravity) via the `code-intelligence` skill and project instructions. We
**do not** expose an MCP server: MCP loads tool schemas into context
permanently, whereas a CLI spends context only when called. Keep it that way —
do not add MCP server code or an `mcp` dependency.

## Commands
- Install (dev): `pip install -e .`
- Test: `python3 -m pytest tests/code_intelligence -q`
- Smoke (end-to-end): `python3 -m tests.code_intelligence.runner`
- Lint: `ruff check .` · Format check: `ruff format --check .`
- Dep check: `codeq doctor` (add `--install` to install missing binaries)

## Stack
- Python ≥ 3.11; build backend hatchling; package `codeq-cli` (import `codeq`).
- External binaries (checked by `codeq doctor`): **ctags**, **ast-grep**,
  **shellcheck** (required); `rg`, `ollama` (optional).

## Entry points / subcommands
`codeq` console script (`src/codeq/cli.py`): `find`, `outline`, `body`,
`class`, `sig`, `deps`, `rdeps`, `refs`, `tags`, `check`, `map`, `summary`,
`context`, `relations`, `rename`, `doctor`.

## Conventions
- Vertical slices in `src/codeq/features/<feature>/`; shared infra in
  `src/codeq/shared/`. One feature = one responsibility.
- **Structural integrity** over line counts (enforced by `test_codeq_modular_layout`):
  - Each feature slice has exactly one `command.py` (no stale copies)
  - Shared modules never import from features (low coupling)
  - Line count is advisory, not enforced — a cohesive 300-line module is better
    than a 100-line module with mixed responsibilities
- Lexical search (`refs`/`rdeps`) uses `shared/search.py`: ripgrep binary if
  present, else a pure-Python walker. **Never** the system `grep` (its behavior
  varies: GNU/ugrep/busybox/BSD).
- `# vs-soft-allow` marker only for pre-existing shape debt, never to land new
  deep nesting.
- TDD: add a failing regression test first, then implement.

## Key decisions
- **No MCP** (see above) — CLI + skill keeps context minimal.
- **No grep dependency** — `shared/search.py` is deterministic across envs.
- **Python deps via `ast`** (exact); brace-langs via ast-grep + brace fallback.

## Things that look wrong but aren't
- `config.py` lists `.playwright-mcp`, `.chrome-devtools-mcp`, … in
  `VENDOR_EXCLUDES` — these are **other tools'** MCP cache dirs that codeq
  excludes so they don't pollute results. Not codeq using MCP.
- `command.py` carries `# vs-soft-allow` — nesting-4 there is pre-existing
  (`_py_deps`, `_is_import_of`), not new.

## Workflow
- New feature/fix → failing test in `tests/code_intelligence/` first.
- Before editing a symbol → `codeq refs <name>` to see call sites.
- After changes → `pytest tests/code_intelligence -q` + `ruff check .`.
- Register durable decisions in `.memory-bank/systemPatterns.md`.
