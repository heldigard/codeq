# Code Intelligence Landscape — where codeq fits, and what complements it

> Research notes: external tools that complement `codeq`, mapped to the gaps
> `codeq` does NOT fill. Goal: a CLI-first, **no-MCP**, token-economy code-
> intelligence stack for LLM agents (Claude Code / Codex / Antigravity).
> Researched 2026-07.

## 1. The three-layer model (the consensus for AI agents)

When an AI coding agent searches a codebase, there are three layers
[ceaksan.com — Code Search for AI Agents](https://ceaksan.com/en/code-search-for-ai-agents-which-tool-when):

| Layer | Answers | Backend in codeq |
|-------|---------|------------------|
| **Lexical** | "where does the text `foo` appear" | ripgrep (`shared/search.py`) + pure-Python walker |
| **Structural** | "where is every call shaped `client.get(...)`" | ast-grep (`codeq check`, body/sig patterns) |
| **Semantic / conceptual** | "find code that does auth-rate-limiting" | repo map (`codeq map`, aider-style) + local LLM (`codeq summary/context/relations`) |

The canonical policy: **start lexical, escalate to structural when the pattern
is structural, jump to the repo map only when the query is conceptual.
Embeddings are a last resort.** Track token budget at every step and compress
to `file:line` + minimal context.

**codeq already implements layers 1–3 without a language server and without
embeddings.** That is the design intent: a CLI spends context only when called,
whereas MCP loads tool schemas into context every turn (rejected for this tool).

## 2. Gap analysis — what codeq does NOT do

1. **No precise, type-aware references.** `codeq refs` is lexical (word-
   boundary). It cannot distinguish two overloads of `foo()`, or resolve a call
   `obj.foo()` to the right `foo` among many. It also matches inside
   comments/strings (ast-grep `--lang` is the exact escape hatch, noted in docs).
2. **No precomputed call graph / dead-code / cycle analysis.** `codeq map`
   RANKS by reference frequency (approximate); it does not prove reachability.
   (Ship-time dead-code/cycles live in the separate `codescan` tool, not codeq.)
3. **No semantic (embedding) search.** "Find code that does X" without naming X
   is out of scope for codeq's lexical/AST core.
4. **Limited language coverage.** 8 langs (py/js/ts/go/rust/java/bash + ctags-
   universal for find/outline/tags). `body`/`sig`/`deps`/`rdeps` need per-lang
   patterns; C#/Ruby/PHP/Kotlin/Scala/C/C++ fall back to ctags only.

## 3. Complementary tools, ranked by how well they fit the (CLI, no-MCP, token-economy) constraints

### Tier 1 — precise type-aware layer (fills gap #1, #2): **SCIP**

[SCIP](https://scip-code.org/) (Sourcegraph Code Intelligence Protocol —
pronounced "skip") is a language-agnostic **precomputed index** for precise
go-to-definition / find-references / implementations. It is the successor to
LSIF. You generate a `.scip` file once (in CI or locally), then query it in
milliseconds — no language server stays resident. This is the precise layer
codeq deliberately does not build.

- **Language indexers** (compiler-accurate type + reference graphs):
  [scip-python](https://github.com/sourcegraph/scip-python),
  [scip-typescript](https://sourcegraph.com/blog/announcing-scip-typescript),
  scip-java, scip-ruby, scip-clang, `rust-analyzer`'s `scip` output, scip-zig.
- **[scip-cli](https://github.com/flesler/scip-cli)** (PyPI: `scip-cli`) — the
  most codeq-aligned tool in the landscape: a **CLI that gives AI agents
  precise, type-aware code navigation from SCIP indexes**, plus `analyze` for
  dead code, cycles, and coupling. Token-efficient by design, TS/JS + Python.
  Think "codeq's `refs`, but precise, when a `.scip` index exists."

**Integration idea (no MCP):** when `codeq refs` detects a `.scip` index in the
project root, it could shell out to `scip-cli` for precise results and fall back
to the lexical walker otherwise. Keeps the CLI-first model; adds precision only
when the user has paid the one-time index cost.

### Tier 2 — build-less precise nav (fills gap #1 without an index): **stack-graphs**

[GitHub's stack-graphs](https://github.blog/open-source/introducing-stack-graphs/)
+ `tree-sitter-graph` do **name resolution from a tree-sitter DSL** — go-to-def
and find-refs **without a compiler build and without a language server**. Good
fit for a CLI that wants precise nav in languages where running a SCIP indexer
is too heavy. Heavier to integrate (you write a graph per language) than to use
SCIP, so lower priority than Tier 1 for this stack.

### Tier 3 — richer symbol index than ctags (fills gap #4): **tree-sitter tags**

- **[tree-sitter](https://tree-sitter.github.io/tree-sitter/4-code-navigation.html)
  + tree-sitter-tags** — structural symbol tagging from concrete syntax trees;
  more scope/type-aware than ctags's regex parser (the ctags 5.9.0 TS
  generic-field bug that codeq works around in `locators.py` would not exist).
- **graph-sitter** / **Dossier** — graph/JSON symbol representations over
  tree-sitter ASTs; a candidate replacement backend for `codeq outline`/`find`
  if ctags's quirks ever outweigh its 50+-language breadth.

**Verdict:** ctags's universal coverage + codeq's regex fallbacks currently win
on breadth-per-effort. Revisit only for a specific language where ctags is
unreliable.

### Tier 4 — semantic / embedding search (fills gap #3): local embedding index

The 3-layer article and the Sourcegraph/Cody ["LLM antihallucinogen"
pipeline](https://www.eric-fritz.com/articles/llm-antihallucinogen) agree:
**embeddings are the last resort**, not the default — short keyword queries
collapse every semantic model (CoREB benchmark), and they cost the most tokens.
For the rare "find code doing X without naming X" query, a lightweight **local
embedding indexer** (chunk → embed with a local model like
`nomic-embed-text` → cosine search → return ranked `file:line` candidates) fits
the no-MCP constraint. codeq already uses a local Ollama model for summaries;
the same host could serve embeddings. **Low priority** — lexical + structural +
repo-map cover ~95% of real agent queries.

### Notable, but explicitly NOT adopted here

- **[ast-grep-mcp](https://github.com/ast-grep/ast-grep-mcp)** — MCP server for
  ast-grep. Rejected: MCP loads schemas into context every turn; codeq's
  CLI+skill approach spends context only when invoked. ast-grep itself (the
  binary) is already a first-class codeq backend.
- **Serena** (LSP-based MCP) — removed earlier for the same context-cost
  reason. Claude Code's native `LSP` tool covers the LSP path with zero
  per-turn schema cost; codeq is the no-LSP fallback for Codex/Antigravity.
- **PySCIPOpt / SCIP Optimization Suite** — NAME COLLISION. This is a
  mixed-integer programming solver (scipopt.org), NOT code intelligence.
  Irrelevant; do not confuse with the SCIP *protocol*.

## 4. Recommended next integration (if any)

**`scip-cli` as an optional precise-refs backend for `codeq refs`.** It is the
single tool whose philosophy (CLI, AI-agent-oriented, token-economy, precise)
matches codeq exactly, and it fills the one gap (type-aware refs) that lexical
search provably cannot. Everything else is either already covered by codeq's
existing backends or is a last-resort layer the project correctly defers.

## Sources

- [SCIP — scip-code.org](https://scip-code.org/)
- [Sourcegraph — Announcing SCIP](https://sourcegraph.com/blog/announcing-scip)
- [scip-python](https://github.com/sourcegraph/scip-python) ·
  [Announcing scip-typescript](https://sourcegraph.com/blog/announcing-scip-typescript)
- [scip-cli (flesler/scip-cli)](https://github.com/flesler/scip-cli) · [PyPI](https://pypi.org/project/scip-cli/)
- [GitHub — Introducing stack-graphs](https://github.blog/open-source/introducing-stack-graphs/)
- [tree-sitter — code navigation](https://tree-sitter.github.io/tree-sitter/4-code-navigation.html)
- [ast-grep](https://ast-grep.github.io/) · [ast-grep-mcp](https://github.com/ast-grep/ast-grep-mcp)
- [Code Search for AI Agents: ripgrep, ast-grep, or Semantic?](https://ceaksan.com/en/code-search-for-ai-agents-which-tool-when)
- [Why Coding Agents Still Use grep](https://yage.ai/share/why-coding-agents-still-use-grep-en-20260327.html)
- [Eric Fritz — LLM antihallucinogen (precise+semantic pipeline)](https://www.eric-fritz.com/articles/llm-antihallucinogen)
