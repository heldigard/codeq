from __future__ import annotations

import argparse

from codeq import __version__
from codeq.features.symbol_body.command import cmd_body, cmd_class, cmd_sig
from codeq.features.code_context.command import cmd_context, cmd_relations, cmd_summary
from codeq.features.dependencies.command import cmd_deps, cmd_rdeps
from codeq.features.doctor.command import cmd_doctor
from codeq.features.repo_map.command import cmd_map
from codeq.features.pattern_check.command import cmd_check
from codeq.features.symbol_search.command import cmd_find, cmd_outline
from codeq.features.references.command import cmd_refs
from codeq.features.rename.command import cmd_rename
from codeq.features.tags.command import cmd_tags

# vs-soft-allow — argparse subparser defs carry long multi-line help strings
# that read as deep indent (string-continuation alignment), not logical nesting.
# Flat CLI definition; no real deep control-flow nesting.


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="codeq",
        description="Precise code-fact extractor for big LLM controllers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  codeq find Foo -p src/          exact symbol locations
  codeq outline src/app.py        symbol map of one file
  codeq body Foo src/app.py       exact function/class body
  codeq class Foo src/app.py      full class body (all members)
  sig Foo src/app.py              signature only (cheaper than body)
  codeq refs Foo -p src/          call sites (definition filtered)
  codeq deps src/app.py           imports of a file
  codeq rdeps src/foo.py -p src/  which files import foo.py
  codeq context Foo src/app.py -p src/  bundled editing context
  codeq map -p . --top 10         repo orientation map
  codeq doctor                    check external binaries
""",
    )
    ap.add_argument("--version", action="version", version=f"codeq {__version__}")
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="output structured JSON instead of human-readable text",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="exact symbol locations under a path")
    f.add_argument("name", help="exact symbol name (identifier)")
    f.add_argument("-p", "--path", default=".", help="search root (default: cwd)")
    f.set_defaults(func=cmd_find)

    o = sub.add_parser("outline", help="symbol map of one file")
    o.add_argument("file")
    o.set_defaults(func=cmd_outline)

    b = sub.add_parser(
        "body", help="exact def/class body without reading the whole file"
    )
    b.add_argument("name", help="symbol name (function/class)")
    b.add_argument("file", help="file containing the symbol")
    b.add_argument("-l", "--lang", default=None, help="override language")
    b.add_argument(
        "--summary",
        action="store_true",
        help="prepend a 1-line Ollama summary (qwen3.5:4b) before the body; tagged so the consumer treats it as orientation, not truth",
    )
    b.add_argument(
        "--no-llm",
        action="store_true",
        help="skip Ollama enrichment even if --summary is set (or set CODEQ_NO_LLM=1)",
    )
    b.set_defaults(func=cmd_body)

    cl = sub.add_parser(
        "class",
        help="full class/type body (all members); use instead of body for a Java/TS class",
    )
    cl.add_argument("name", help="class/type name")
    cl.add_argument("file", help="file containing the type")
    cl.add_argument("-l", "--lang", default=None, help="override language")
    cl.add_argument(
        "--summary",
        action="store_true",
        help="prepend a 1-line Ollama summary before the class body",
    )
    cl.add_argument("--no-llm", action="store_true", help="skip Ollama enrichment")
    cl.set_defaults(func=cmd_class)

    tg = sub.add_parser(
        "tags",
        help="project .tags index with vendor dirs excluded (replaces raw ctags -R)",
    )
    tg.add_argument("-p", "--path", default=".", help="search root (default: cwd)")
    tg.add_argument(
        "-o", "--output", default=".tags", help="output tags file (default: .tags)"
    )
    tg.set_defaults(func=cmd_tags)

    c = sub.add_parser(
        "check", help="validate an ast-grep pattern (single-node) before running"
    )
    c.add_argument("pattern", help="ast-grep -p pattern")
    c.add_argument("-l", "--lang", default=None, help="language (default: python)")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("refs", help="precise references (word-boundary, def-filtered)")
    r.add_argument("name", help="symbol name")
    r.add_argument("-p", "--path", default=".", help="search root")
    r.add_argument("-l", "--lang", default=None, help="restrict file type")
    r.add_argument(
        "--limit",
        type=int,
        default=200,
        help="max references to show (default: 200; 0 = unlimited)",
    )
    r.set_defaults(func=cmd_refs)

    sg = sub.add_parser(
        "sig", help="signature only (header line(s); cheaper than body)"
    )
    sg.add_argument("name", help="symbol name (function/class)")
    sg.add_argument("file", help="file containing the symbol")
    sg.add_argument("-l", "--lang", default=None, help="override language")
    sg.set_defaults(func=cmd_sig)

    dp = sub.add_parser(
        "deps", help="imports/dependencies of a file (context before editing)"
    )
    dp.add_argument("file")
    dp.add_argument("-l", "--lang", default=None, help="override language")
    dp.set_defaults(func=cmd_deps)

    rd = sub.add_parser(
        "rdeps", help="reverse deps: which project files import this file"
    )
    rd.add_argument("file", help="the module/file whose importers you want")
    rd.add_argument("-p", "--path", default=".", help="search root")
    rd.add_argument("-l", "--lang", default=None, help="override language")
    rd.add_argument(
        "--limit",
        type=int,
        default=200,
        help="max import lines to show (default: 200; 0 = unlimited)",
    )
    rd.set_defaults(func=cmd_rdeps)

    mp = sub.add_parser(
        "map",
        help="repo orientation map: hottest files+symbols by reference weight "
        "(one bounded call instead of a Glob/Read exploration sweep)",
    )
    mp.add_argument("-p", "--path", default=".", help="project root")
    mp.add_argument("--top", type=int, default=20, help="files to show (default 20)")
    mp.add_argument("--syms", type=int, default=6, help="symbols per file (default 6)")
    mp.add_argument(
        "--save",
        action="store_true",
        help="also write .memory-bank/topics/code-map.md (persist orientation)",
    )
    mp.add_argument(
        "--tests",
        action="store_true",
        help="include test/spec files (excluded by default — spec helpers "
        "lexically collide with ubiquitous identifiers)",
    )
    mp.set_defaults(func=cmd_map)

    sm = sub.add_parser(
        "summary",
        help="1-line Ollama summary of a function/method (local 4B; verify before reasoning); cheaper than `body --summary`",
    )
    sm.add_argument("name", help="symbol name")
    sm.add_argument("file", help="file containing the symbol")
    sm.add_argument("-l", "--lang", default=None, help="override language")
    sm.add_argument(
        "--no-llm", action="store_true", help="skip Ollama (always emits a notice)"
    )
    sm.set_defaults(func=cmd_summary)

    cx = sub.add_parser(
        "context",
        help="bundled context for editing: summary + signature + body + callers + file imports (one call replaces find+body+refs+deps)",
    )
    cx.add_argument("name", help="symbol name to orient on")
    cx.add_argument("file", help="file containing the symbol")
    cx.add_argument(
        "-p",
        "--path",
        default=".",
        help="project root for the `refs` half (default: cwd); ctags-style vendor excludes apply",
    )
    cx.add_argument("-l", "--lang", default=None, help="override language")
    cx.add_argument(
        "--no-llm", action="store_true", help="skip the Ollama summary half"
    )
    cx.set_defaults(func=cmd_context)

    rl = sub.add_parser(
        "relations",
        help="call-graph orientation: summary + signature + body-call hints + external refs (cheaper than `context` — no embedded body, no deps)",
    )
    rl.add_argument("name", help="symbol name to map")
    rl.add_argument("file", help="file containing the symbol")
    rl.add_argument(
        "-p", "--path", default=".", help="project root for the `refs` half"
    )
    rl.add_argument("-l", "--lang", default=None, help="override language")
    rl.add_argument(
        "--no-llm", action="store_true", help="skip the Ollama summary half"
    )
    rl.set_defaults(func=cmd_relations)

    rn = sub.add_parser(
        "rename",
        help="AST-exact structural rename via ast-grep (strings/comments/kwargs never touched)",
    )
    rn.add_argument("old", help="identifier to rename")
    rn.add_argument("new", help="new identifier")
    rn.add_argument(
        "-p",
        "--path",
        default=".",
        help="file or directory to rewrite in place (default: cwd)",
    )
    rn.add_argument(
        "-l",
        "--lang",
        default=None,
        help="ast-grep language; default python. Supported: see --help / doctor.",
    )
    rn.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="report match count without writing",
    )
    rn.set_defaults(func=cmd_rename)

    doc = sub.add_parser(
        "doctor",
        help="check required/optional external binaries and (with --install) install missing ones",
    )
    doc.add_argument(
        "--install",
        action="store_true",
        help="install missing binaries via non-sudo managers (cargo/npm/pipx); "
        "print exact manual commands for system managers (apt/brew)",
    )
    doc.set_defaults(func=cmd_doctor)

    args = ap.parse_args()
    if args.json_output:
        from codeq.json_handler import run_with_json

        return run_with_json(args)
    from typing import Callable

    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)
