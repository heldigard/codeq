from __future__ import annotations

import re
import sys

from codeq.shared.config import FILE_EXCLUDES, VENDOR_EXCLUDES
from codeq.shared.core import die, run

def cmd_refs(args: argparse.Namespace) -> int:
    """Precise references to a symbol: `grep -rnw` (word-boundary, recursive)
    with definition lines filtered out, so the controller sees call sites only.
    Uses grep (NOT rg) because rg here is only a Claude-Code shell function
    wrapping the embedded ripgrep — invisible to subprocess and to other CLIs.
    grep is universal. (Comments/strings can still match — ast-grep --lang is
    exact for that.)"""
    import re as _re
    includes = {
        "python": ["--include=*.py"],
        "javascript": ["--include=*.js", "--include=*.mjs", "--include=*.cjs", "--include=*.jsx"],
        "typescript": ["--include=*.ts", "--include=*.tsx"],
        "go": ["--include=*.go"],
        "rust": ["--include=*.rs"],
        "java": ["--include=*.java"],
    }.get(args.lang, [])
    cmd = ["grep", "-rnHwI", "--color=never"]  # -H: print filename even for single file
    for ex in VENDOR_EXCLUDES:
        cmd += [f"--exclude-dir={ex}"]
    for ex in FILE_EXCLUDES:
        cmd += [f"--exclude={ex}"]
    cmd += includes + ["-e", args.name, args.path]
    rc, out, err = run(cmd)
    if rc == 1:
        print(f"no references to '{args.name}' under {args.path}", file=sys.stderr)
        return 1
    if rc == 2:
        die(f"grep error: {err.strip()}", 2)
    name_esc = _re.escape(args.name)
    if args.lang == "java":
        # Java has no def keyword: filter typed declarations [modifiers] Type name(,
        # plus class/interface/enum. (Gated to java ONLY — the typed pattern would
        # otherwise swallow `return foo(` / `x = foo(` call lines in py/js/etc.)
        def_re = _re.compile(
            r'\b(?:class|interface|enum)\s+' + name_esc + r'\b'
            r'|^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|@\w+)\s+)*'
            r'[A-Za-z_][\w<>\[\],?\s]*?\s+' + name_esc + r'\s*\('
        )
    elif args.lang in ("typescript", "javascript"):
        # TS/JS method declarations don't use a `function` keyword — they look
        # like `(modifiers)+ name(`. Without this filter, refs would return the
        # declaration line itself as a "reference" alongside the call sites.
        # Match the name at line-start, optional modifiers, optional generics, then `(`.
        def_re = _re.compile(
            r'^[ \t]*(?:export\s+)?(?:async\s+)?'
            r'(?:\s*(?:public|private|protected|static|abstract|override|readonly|async)\s+)*'
            r"\*?\s*" + name_esc + r'\s*(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*\(',
            re.MULTILINE,
        )
    else:
        # py/go/rust/...: keyword-led declarations only (safe — won't match calls)
        def_re = _re.compile(
            r'\b(?:def|class|function|fn|func|sub|struct|interface|enum|trait|impl)\s+'
            + name_esc + r'\b'
        )
    total = 0
    shown = 0
    for line in out.splitlines():
        m = _re.match(r'^(.*?):(\d+):(.*)$', line)
        if not m:
            continue
        if def_re.search(m.group(3)):
            continue  # skip the declaration itself
        total += 1
        if shown < 200:
            print(line)
            shown += 1
    if total == 0:
        print(f"'{args.name}' only appears in its definition(s) under {args.path}",
              file=sys.stderr)
        return 1
    if total > shown:
        print(f"... {total - shown} more references (narrow with --path)",
              file=sys.stderr)
    return 0
