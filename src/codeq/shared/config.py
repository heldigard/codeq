from __future__ import annotations

import re

CTAGS = "ctags"
ASTGREP = "ast-grep"  # resolved on PATH (~~/.local/bin/ast-grep)

# Cap the per-file `_locate_line` regex sweep in `cmd_find` so a user-supplied
# huge root (e.g. `-p /`) doesn't trigger runaway recursion. When exceeded,
# the sweep stops and a truncation notice goes to stderr.
_FIND_SWEEP_FILE_CAP = 10000

# Reserved control-flow / declaration keywords shared by the regex-based
# outline sweep (`_regex_outline_methods`) and the body-call-hint extractor
# (`_body_call_hints`). Single source of truth so they don't drift.
_RESERVED_KEYWORDS = frozenset(
    {
        "if",
        "while",
        "for",
        "switch",
        "catch",
        "do",
        "return",
        "throw",
        "try",
        "new",
        "typeof",
        "instanceof",
        "in",
        "of",
        "void",
        "delete",
        "yield",
        "await",
        "async",
        "function",
        "class",
        "const",
        "let",
        "var",
        "import",
        "export",
        "case",
        "default",
        "continue",
        "break",
        # constructors/getters/setters — ctags would have indexed them; don't fabricate.
        "constructor",
        "get",
        "set",
    }
)

EXT_LANG = {
    "py": "python",
    "pyi": "python",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "sh": "bash",
    "bash": "bash",
}

# Canonical language names (values of EXT_LANG). Single set for parity tests
# and feature tables — when adding a language, extend EXT_LANG + every table
# that lang_matrix_test asserts.
SUPPORTED_LANGS: frozenset[str] = frozenset(EXT_LANG.values())


def _lang_includes(*exts: str) -> list[str]:
    """Build ripgrep/walker --include globs for the given extensions."""
    return [f"--include=*.{ext}" for ext in exts]


# Exact-language file globs for `refs` (and similar). One source of truth —
# do not re-declare per-feature include tables.
LANG_INCLUDES: dict[str, list[str]] = {
    "python": _lang_includes("py"),
    "javascript": _lang_includes("js", "mjs", "cjs", "jsx"),
    "typescript": _lang_includes("ts", "tsx"),
    "go": _lang_includes("go"),
    "rust": _lang_includes("rs"),
    "java": _lang_includes("java"),
    "bash": _lang_includes("sh", "bash"),
}

# `rdeps` searches a slightly wider set for JS/TS so mixed projects still
# find importers across the .js ↔ .ts boundary.
LANG_RDEPS_INCLUDES: dict[str, list[str]] = {
    lang: list(includes) for lang, includes in LANG_INCLUDES.items()
}
LANG_RDEPS_INCLUDES["javascript"] = [
    *LANG_INCLUDES["javascript"],
    *LANG_INCLUDES["typescript"],
]
LANG_RDEPS_INCLUDES["typescript"] = [
    *LANG_INCLUDES["typescript"],
    *LANG_INCLUDES["javascript"],
]

# Languages with ast-grep body/rename support (bash is ctags/refs-only).
STRUCTURAL_LANGS: frozenset[str] = frozenset(
    {"python", "javascript", "typescript", "go", "rust", "java"}
)
RENAME_LANGS: frozenset[str] = STRUCTURAL_LANGS

# ast-grep def/class patterns per language. Metavariables MUST be uppercase
# (lowercase multi-metavars do not bind). Tried in order; first match wins.
BODY_PATTERNS: dict[str, list[str]] = {
    "python": [
        "def {N}($$$A): $$$B",
        "async def {N}($$$A): $$$B",
        "class {N}($$$A): $$$B",
        "class {N}: $$$B",
    ],
    "javascript": [
        "function {N}($$$A) { $$$B }",
        "class {N} { $$$B }",
    ],
    "typescript": [
        "function {N}($$$A) { $$$B }",
        "function {N}($$$A): $$$R { $$$B }",
        "class {N} { $$$B }",
    ],
    "go": [
        "func {N}($$$A) {{ $$$B }}",
        "func ($$$R) {N}($$$A) {{ $$$B }}",
    ],
    "rust": [
        "fn {N}($$$A) {{ $$$B }}",
        "fn {N}($$$A) -> $$$R {{ $$$B }}",
    ],
    "java": [
        "$$$M {N}($$$A) {{ $$$B }}",
    ],
}

BRACE_LANGS = {"javascript", "typescript", "go", "rust", "java"}

# Fallback locator for brace-lang class methods when ctags misses them.
# ctags 5.9.0 silently drops TS class members after a generic-arg field
# initializer (`private x = foo<T>(...)` — the Angular `inject<T>(...)` pattern
# is the common case). These regexes match the method signature directly:
# optional modifiers (any order, any count), optional generics, then `(`.
# Patterns are templates with a single `{name}` placeholder.
_METHOD_LOCATOR: dict[str, str] = {
    "typescript": (
        r"^[ \t]*(?:export\s+)?(?:async\s+)?"
        r"(?:\s*(?:public|private|protected|static|abstract|override|readonly|async)\s+)*"
        r"\*?\s*{name}\s*(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*\("
    ),
    "javascript": (
        r"^[ \t]*(?:export\s+)?(?:async\s+)?"
        r"(?:\s*(?:public|private|protected|static|abstract|override|readonly|async)\s+)*"
        r"\*?\s*{name}\s*(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*\("
    ),
    "java": (
        r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"
        r"(?:\s*(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)*"
        r"(?:<[^>]+>\s+)?[\w<>\[\],?\s]+?\s+{name}\s*(?:<[^>]+>)?\s*\("
    ),
}


# NOTE: `_regex_locate_method` (the consumer of `_METHOD_LOCATOR`) lives in
# `shared/locators.py` — single source of truth. Do NOT re-add a copy here; the
# previous duplicate drifted (config's copy was dead, locators' was live).

# ast-grep class/type patterns for the `class` subcommand (AST-exact where the
# parser supports it — TS/JS). Java/Go/Rust fall back to brace-count from the
# ctags type-decl line (their ast-grep class/struct patterns do not bind).
CLASS_BODY_PATTERNS: dict[str, list[str]] = {
    "typescript": ["class {N} { $$$B }", "export class {N} { $$$B }"],
    "javascript": ["class {N} { $$$B }", "export class {N} { $$$B }"],
}

# ctags "kind" values that denote a type declaration (for the `class` subcommand).
TYPE_KINDS = {"class", "struct", "interface", "enum", "record", "union"}

# Dependency/vendor/cache/IDE dirs excluded by default in find/refs/tags so results
# stay in PROJECT code (not site-packages/node_modules) and stay fast. Single source
# of truth — shared by cmd_find, cmd_refs, cmd_tags. Override by grepping directly.
# NOTE: `vendor/` intentionally NOT excluded — Go/PHP vendored deps are sometimes
# project code the caller wants indexed. Add it project-side if needed.
# NOTE: `bin/` `obj/` NOT excluded — often real source in C#/.NET/legacy projects.
VENDOR_EXCLUDES = [
    # Python
    ".venv",
    "venv",
    "env",
    "site-packages",
    ".python_packages",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".eggs",
    ".benchmarks",
    ".pyre",
    ".pytype",
    "htmlcov",
    ".ipynb_checkpoints",
    # Node / JS / TS
    "node_modules",
    "bower_components",
    "jspm_packages",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".remix",
    ".astro",
    ".gatsby",
    ".turbo",
    ".nx",
    ".nx-cache",
    ".parcel-cache",
    ".ngc-cache",
    ".vite",
    ".angular",  # Angular CLI: .angular/cache/, .angular/build-cache/, .angular/service-worker/
    ".eslintcache",
    ".stylelintcache",
    ".cache",
    ".npm",
    ".pnpm-store",
    ".yarn",
    "coverage",
    ".nyc_output",
    ".docusaurus",
    "storybook-static",  # Storybook build output (sibling of dist/)
    # Cloud / serverless artifacts (JSON/YAML, never source) — common in node + py + spring
    "cdk.out",  # AWS CDK synthesized CloudFormation
    ".aws-sam",  # AWS SAM CLI build artifacts
    "amplify",  # AWS Amplify generated backend (amplify/backend/, amplify/#current-cloud-backend/)
    # React Native / Expo (Node/TS mobile)
    ".expo",
    ".expo-shared",
    ".metro",
    # Python offline wheel cache
    "wheelhouse",
    # Generic build / output
    "dist",
    "build",
    "out",
    "target",
    "dist-electron",
    ".serverless",
    ".vercel",
    "tmp",
    "temp",
    # Agent harness / memory noise (project facts, transcripts, and backups are
    # not source code and should not steer symbol lookup unless grepped directly).
    ".memory-bank",
    "memory-bank",
    ".claude",
    ".codex",
    ".grok",  # Grok Build TUI / xAI agent harness
    ".opencode",  # OpenCode CLI agent
    ".gemini",  # Gemini / Antigravity harness config tree
    ".antigravity",  # Google Antigravity agent
    ".kimi",  # Kimi CLI
    ".qwen",  # Qwen CLI
    "file-history",
    # JVM
    ".gradle",
    ".mvn",
    # Rust / Go
    # (target already above; vendor/ intentionally NOT excluded)
    # VCS / IDE / editors
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".vs",
    ".history",
    # LSP server workspaces (indexes, never source) — Java/Scala/Go/Rust/TS
    ".jdtls-data",  # Eclipse JDT LS (nvim/helix/emacs) — common in Spring Boot
    ".metals",  # Scala Metals
    ".gopls",  # Go gopls
    ".rust-analyzer",  # Rust analyzer
    ".tsserver",  # TypeScript standalone server
    # AI coding-assistant caches (prompts, embeddings, snapshots — pollute refs)
    ".kilocode",  # Kilo Code extension
    ".cursor",  # Cursor editor
    ".continue",  # Continue.dev extension
    ".trae",  # Trae AI editor
    ".windsurf",  # Windsurf / Cascade
    ".cline",  # Cline extension
    ".roo",  # Roo Code extension
    ".cody",  # Sourcegraph Cody
    ".augment",  # Augment Code
    ".aider*",  # Aider (Aider.chat) — covers .aider, .aider.input.history, .aider.chat.history
    ".codebuddy",  # Codebuddy IDE (JetBrains-style AI coding IDE)
    # Browser automation / MCP server caches (snapshots, profiles, traces)
    ".playwright-mcp",  # Playwright MCP server (Microsoft official)
    ".chrome-devtools-mcp",  # Chrome DevTools MCP
    ".puppeteer-mcp",  # Puppeteer MCP variants
    ".browserbase-mcp",  # Browserbase MCP
    ".firecrawl-mcp",  # Firecrawl MCP local cache
    ".agent-browser",  # agent-browser CLI snapshot/trace cache
    ".puppeteer",  # Puppeteer default cache
    ".playwright",  # Playwright core (older versions, project-local cache)
]

# ctags --exclude supports shell wildcards; grep --exclude-dir does NOT. So we apply
# these glob patterns ONLY in the ctags-backed commands (find, tags) as a safety net
# to catch any future `*_cache` dir without enumerating it. ctags matches the pattern
# against each directory NAME component during the walk, so a bare `*_cache` covers
# .pytest_cache, .ruff_cache, .mypy_cache, custom_cache, .my_custom_cache, etc.
# The explicit list above (which grep also uses) already covers every cache we know.
# NOTE: deliberately NOT `.*` — that would exclude .github/workflows (code worth indexing).
CACHE_GLOBS = [
    "*_cache",
]

# File-level noise. Session transcripts and generated tag/log files are frequent
# under shared CLI roots and make `codeq refs` look like code references.
FILE_EXCLUDES = [
    "*.jsonl",
    "*.log",
    ".tags",
]

# import-deps regex per language (for codeq deps). Python uses ast (exact).
IMPORT_PATTERNS = {
    "javascript": [
        re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]"),
        # Re-exports: `export ... from 'x'` and `export * from 'x'`
        re.compile(r"^\s*export\s+(?:\{[^}]*\}|\*(?:\s+as\s+\w+)?)\s+from\s+['\"]([^'\"]+)['\"]"),
        # CommonJS require
        re.compile(r"""^\s*const\s+\w+\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)"""),
        # Dynamic import
        re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "typescript": [
        re.compile(r"^\s*import\s+(?:type\s+)?.*?\s+from\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]"),
        # Re-exports: `export ... from 'x'` and `export * from 'x'`
        re.compile(r"^\s*export\s+(?:\{[^}]*\}|\*(?:\s+as\s+\w+)?)\s+from\s+['\"]([^'\"]+)['\"]"),
        # TS-CommonJS: `import x = require('...')` and `import x = pkg.foo`
        re.compile(r"^\s*import\s+\w+\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        re.compile(r"^\s*const\s+\w+\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        # Dynamic import (mid-line): `await import('x')` or `import('x').then(...)`
        re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "java": [
        re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;"),
    ],
}

# Minimal valid probe content for `check` (pattern parse happens before search).
# Keep keys in parity with EXT_LANG languages that ast-grep can pattern-check
# (python/js/ts/go/rust/java/bash). Adding a lang to EXT_LANG without a PROBE
# entry makes `codeq check -l <lang>` die with "no probe for lang".
PROBE: dict[str, str] = {
    "python": "pass\n",
    "javascript": "let x = 1;\n",
    "typescript": "let x = 1;\n",
    "go": "package p\n",
    "rust": "fn _main() {}\n",
    # Minimal valid Java for ast-grep pattern parsing. A bare class with empty
    # body parses cleanly across tree-sitter-java; methods inside are unnecessary
    # for pattern validation (probe is syntactic context, not a target). Parity:
    # rename + body extraction already support java.
    "java": "class _P {}\n",
    # Bash: ast-grep --lang bash; refs/deps already support bash. Probe is a
    # trivial assignment so pattern parse has a valid syntactic context.
    "bash": "x=1\n",
}
