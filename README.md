# codeq

`codeq` is a small CLI that returns precise code facts for LLM coding agents without requiring a resident LSP server or MCP process.

It composes local tools — `ctags` for symbol indexing, `ast-grep` for structural search, and a deterministic lexical search (ripgrep when available, else a built-in pure-Python walker) — to answer narrow questions:

```bash
codeq find NAME -p .
codeq outline FILE
codeq body NAME FILE
codeq class NAME FILE
codeq sig NAME FILE
codeq refs NAME -p .
codeq deps FILE
codeq rdeps FILE -p .
codeq map -p . --save
codeq tags -p .
codeq check 'print($X)' -l python
codeq rename OLD NEW -p . -l python -n   # AST structural rename (dry-run; strings/comments/kwargs never touched)
codeq summary NAME FILE --no-llm
codeq context NAME FILE -p . --no-llm
codeq relations NAME FILE -p . --no-llm
codeq --json context NAME FILE -p . --no-llm
codeq --json relations NAME FILE -p . --no-llm
codeq capabilities
codeq --json capabilities
codeq doctor                # check required/optional external binaries
```

The goal is to give an agent the exact symbol body, signature, references, imports, reverse importers, or repo map it needs without dumping whole files into context.

Use Markdown output for direct controller reading. Use `--json context` and
`--json relations` when another worker, script, or MCP bridge consumes the
result; those commands expose typed fields instead of forcing downstream code
to parse Markdown sections.

`capabilities` is a local tool-card manifest for routers. It marks each command
with read-only, destructive, idempotent, open-world, and structured-JSON hints
so a controller can decide when to call a hand directly, ask for approval, or
prefer a cheaper structured path.

## Requirements

- Python 3.11+
- `ctags` on `PATH` (Universal Ctags; required)
- `ast-grep` on `PATH` (required)
- Optional: `ripgrep` on `PATH` — speeds up `refs`/`rdeps`; a built-in pure-Python walker is used otherwise. codeq NEVER depends on the system `grep`, whose behavior varies across GNU/ugrep/busybox/BSD.
- Optional: local Ollama plus `ollama_client.py` for `summary`, `context`, `relations`, and `--summary`. Default summary model is `TeichAI/Qwen3.5-9B-Fable-5-v1` (codeq_sum #1, ~6.5GB); override with `CODEQ_SUMMARY_MODEL`. Falls back to `Qwythos-9B` (~6.8GB) on VRAM contention; override with `CODEQ_FALLBACK_MODEL`.

Run `codeq doctor` to check what is installed (`codeq doctor --install` installs missing binaries via cargo/npm/pipx where possible).

## Install For Development

```bash
git clone https://github.com/heldigard/codeq.git
cd codeq
python3 -m pip install -e '.[test]'
pytest
```

## Architecture

The project is organized around vertical slices: each command family owns its CLI behavior under `src/codeq/features/`.

```text
src/codeq/
├── cli.py
├── features/
│   ├── capabilities/      # capabilities manifest for routers
│   ├── code_context/      # summary, context, relations
│   ├── dependencies/      # deps, rdeps
│   ├── doctor/            # doctor (external-binary health check)
│   ├── pattern_check/     # check
│   ├── references/        # refs
│   ├── rename/            # rename (AST structural rename via ast-grep)
│   ├── repo_map/          # map
│   ├── symbol_body/       # body, class, sig
│   ├── symbol_search/     # find, outline
│   └── tags/              # tags
└── shared/                # language config, ctags parsing, extraction, LLM helpers
```

The `shared/` package is intentionally small and holds reusable infrastructure only. New functionality should normally start as a new slice under `features/`.

## Test

```bash
python3 -m pytest
python3 tests/test-code-intelligence.py
```

The runner exercises the full CLI contract across Python, TypeScript, Java, vendor exclusion, `map`, `rdeps`, context/summary shape, `ctags`, `ast-grep`, and `shellcheck`.

## License

MIT.
