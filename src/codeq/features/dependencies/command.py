from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from codeq.shared.config import FILE_EXCLUDES, IMPORT_PATTERNS, VENDOR_EXCLUDES
from codeq.shared.core import die, lang_of, run

def _py_deps(file: str) -> list[tuple[int, str, str]] | None:
    """Python imports via ast (exact): Import + ImportFrom with module + names."""
    import ast as _ast
    try:
        src = Path(file).read_text(errors="replace")
        tree = _ast.parse(src)
    except (SyntaxError, OSError):
        return None
    rows: list[tuple[int, str, str]] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                rows.append((node.lineno, "import", alias.name))
        elif isinstance(node, _ast.ImportFrom):
            mod = node.module or ""
            names = ", ".join(a.name for a in node.names)
            rows.append((node.lineno, "from", f"{mod} ( {names} )"))
    return rows or None


def _re_deps(file: str, lang: str) -> list[tuple[int, str, str]] | None:
    """Non-Python imports via per-language regex (line-anchored, line numbers)."""
    patterns = IMPORT_PATTERNS.get(lang, [])
    if not patterns:
        return None
    try:
        text = Path(file).read_text(errors="replace")
    except OSError:
        return None
    rows: list[tuple[int, str, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat in patterns:
            m = pat.search(line)
            if m:
                rows.append((i, "import", m.group(1)))
                break
    return rows or None


def cmd_deps(args: argparse.Namespace) -> int:
    """Imports/dependencies of a file. Compact context to know what the file
    depends on BEFORE editing (correct-context principle)."""
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    rows = _py_deps(args.file) if lang == "python" else _re_deps(args.file, lang)
    if not rows:
        print(f"no imports found in {args.file} (lang={lang})", file=sys.stderr)
        return 1
    for ln, kind, mod in sorted(rows):
        print(f"{ln:>5}  {kind:<6}  {mod}")
    return 0


def _module_keys(file: str) -> list[str]:
    """Candidate module keys another file would use to import FILE."""
    p = Path(file)
    stem = p.stem
    keys: list[str] = []
    if stem in ("__init__", "index", "mod") and p.parent.name:
        # package entry files are imported by their DIRECTORY name
        keys.append(p.parent.name)
    else:
        keys.append(stem)
        if p.suffix == ".go" and p.parent.name:
            keys.append(p.parent.name)  # go imports the package dir, not the file
    return keys


def cmd_rdeps(args: argparse.Namespace) -> int:
    """Reverse dependencies of a FILE: which project files import it.
    Regex-level (same import shapes as `deps`), not a build graph — a module
    name shared by two packages can collide; verify ambiguous hits. Complements
    `refs` (symbol-level callers) with FILE-level importers, so the controller
    knows the blast radius of editing a module without grepping by hand."""
    f = Path(args.file)
    if not f.is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    keys = _module_keys(args.file)
    includes = {
        "python": ["--include=*.py"],
        "javascript": ["--include=*.js", "--include=*.mjs", "--include=*.cjs",
                       "--include=*.jsx", "--include=*.ts", "--include=*.tsx"],
        "typescript": ["--include=*.ts", "--include=*.tsx", "--include=*.js",
                       "--include=*.mjs", "--include=*.jsx"],
        "go": ["--include=*.go"],
        "rust": ["--include=*.rs"],
        "java": ["--include=*.java"],
    }.get(lang, [])
    target = f.resolve()
    seen: set[tuple[str, str]] = set()
    rows: list[tuple[str, int, str]] = []
    for key in keys:
        cmd = ["grep", "-rnwI", "--color=never"]
        for ex in VENDOR_EXCLUDES:
            cmd += [f"--exclude-dir={ex}"]
        for ex in FILE_EXCLUDES:
            cmd += [f"--exclude={ex}"]
        cmd += includes + ["-e", key, args.path]
        rc, out, err = run(cmd)
        if rc == 2:
            die(f"grep error: {err.strip()}", 2)
        for line in out.splitlines():
            m = re.match(r"^(.*?):(\d+):(.*)$", line)
            if not m:
                continue
            path, ln, text = m.group(1), int(m.group(2)), m.group(3)
            try:
                if Path(path).resolve() == target:
                    continue  # the module itself
            except OSError:
                pass
            if not _is_import_of(text, key, lang):
                continue
            dedup = (path, text.strip())
            if dedup in seen:
                continue
            seen.add(dedup)
            rows.append((path, ln, text.strip()))
    if not rows:
        print(f"no project file imports '{'/'.join(keys)}' under {args.path}",
              file=sys.stderr)
        return 1
    rows.sort()
    for path, ln, text in rows[:200]:
        print(f"{path}:{ln}: {text}")
    if len(rows) > 200:
        print(f"... {len(rows) - 200} more importers (narrow with --path)", file=sys.stderr)
    n_files = len({r[0] for r in rows})
    print(f"-- {len(rows)} import line(s) across {n_files} file(s)", file=sys.stderr)
    return 0


def _is_import_of(text: str, key: str, lang: str) -> bool:
    """True when TEXT is an import statement whose module path resolves to KEY."""
    key_esc = re.escape(key)
    if lang == "python":
        m = re.match(r"^\s*(?:from\s+([\w\.]+)\s+import\b|import\s+([\w\., ]+))", text)
        if not m:
            return False
        mods = m.group(1) or m.group(2) or ""
        return any(part.split(".")[-1] == key or key in part.split(".")
                   for part in re.split(r"[,\s]+", mods) if part)
    if lang in ("javascript", "typescript"):
        for pat in IMPORT_PATTERNS.get(lang, IMPORT_PATTERNS["typescript"]):
            m = pat.search(text)
            if m:
                mod = m.group(1)
                last = mod.rstrip("/").split("/")[-1]
                last = re.sub(r"\.(js|mjs|cjs|jsx|ts|tsx)$", "", last)
                return last == key
        return False
    if lang == "java":
        return re.match(rf"^\s*import\s+(?:static\s+)?[\w.]*\b{key_esc}\s*;", text) is not None
    if lang == "go":
        return (re.match(r'^\s*(?:import\s+)?(?:\w+\s+)?"[^"]+"\s*$', text) is not None
                and re.search(rf'"[^"]*\b{key_esc}"\s*$', text) is not None)
    if lang == "rust":
        return re.match(rf"^\s*(?:pub\s+)?(?:use|mod)\s+(?:[\w:]+::)?{key_esc}\b", text) is not None
    # unknown lang: accept lines that LOOK like imports mentioning the key
    return re.search(r"\b(import|require|include|use)\b", text) is not None
