from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from codeq.features.dependencies.parsing import re_deps
from codeq.shared.config import FILE_EXCLUDES, IMPORT_PATTERNS, VENDOR_EXCLUDES
from codeq.shared.core import die, lang_of, run

# vs-soft-allow — remaining nesting-depth-4 hits are PRE-EXISTING (the
# for/if/for chain in _py_deps and _is_import_of, plus one line-continuation),
# not introduced by the deps work; the deps/rdeps logic is shallow.


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


def cmd_deps(args: argparse.Namespace) -> int:
    """Imports/dependencies of a file. Compact context to know what the file
    depends on BEFORE editing (correct-context principle)."""
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    rows = _py_deps(args.file) if lang == "python" else re_deps(args.file, lang)
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


def _resolves_to(path: str, target: Path) -> bool:
    """True when PATH resolves to TARGET (so we skip the module listing itself).
    `Path.resolve()` can raise OSError on broken symlinks — tolerate it."""
    try:
        return Path(path).resolve() == target
    except OSError:
        return False


def _rdep_rows_for_key(
    out: str, key: str, target: Path, lang: str
) -> list[tuple[str, int, str]]:
    """Parse one grep result block OUT into candidate rdep rows for module KEY
    (self-references filtered, not yet deduped across keys). Extracted from
    cmd_rdeps to keep nesting shallow; caller dedups across keys."""
    rows: list[tuple[str, int, str]] = []
    for line in out.splitlines():
        m = re.match(r"^(.*?):(\d+):(.*)$", line)
        if not m:
            continue
        path, ln, text = m.group(1), int(m.group(2)), m.group(3)
        if _resolves_to(path, target):
            continue  # the module itself
        if not _is_import_of(text, key, lang):
            continue
        rows.append((path, ln, text.strip()))
    return rows


# grep `--include` globs per language for `rdeps`. Module-level so the
# multi-entry lists don't trip deep-indent continuation inside cmd_rdeps.
_INCLUDES_BY_LANG: dict[str, list[str]] = {
    "python": ["--include=*.py"],
    "javascript": [
        "--include=*.js",
        "--include=*.mjs",
        "--include=*.cjs",
        "--include=*.jsx",
        "--include=*.ts",
        "--include=*.tsx",
    ],
    "typescript": [
        "--include=*.ts",
        "--include=*.tsx",
        "--include=*.js",
        "--include=*.mjs",
        "--include=*.jsx",
    ],
    "go": ["--include=*.go"],
    "rust": ["--include=*.rs"],
    "java": ["--include=*.java"],
}


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
    includes = _INCLUDES_BY_LANG.get(lang, [])
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
        for path, ln, text in _rdep_rows_for_key(out, key, target, lang):
            dedup = (path, text)
            if dedup in seen:
                continue
            seen.add(dedup)
            rows.append((path, ln, text))
    if not rows:
        print(
            f"no project file imports '{'/'.join(keys)}' under {args.path}",
            file=sys.stderr,
        )
        return 1
    rows.sort()
    for path, ln, text in rows[:200]:
        print(f"{path}:{ln}: {text}")
    if len(rows) > 200:
        print(
            f"... {len(rows) - 200} more importers (narrow with --path)",
            file=sys.stderr,
        )
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
        candidates = [p for p in re.split(r"[,\s]+", mods) if p]
        return any(
            part.split(".")[-1] == key or key in part.split(".") for part in candidates
        )
    if lang in ("javascript", "typescript"):
        for pat in IMPORT_PATTERNS.get(lang, IMPORT_PATTERNS["typescript"]):
            m = pat.search(text)
            if m:
                mod = m.group(1)
                last = mod.rstrip("/").split("/")[-1]
                last = re.sub(r"\.(js|mjs|cjs|jsx|ts|tsx)$", "", last)
                return last == key
        # Multi-line import closer: `} from './module';` carries the module
        # path but no leading import/export keyword, so the anchored patterns
        # above miss it — without this, rdeps reports zero importers for any
        # barrel/harness module. Match the closer and compare the last segment.
        m = re.search(r"\bfrom\s+['\"]([^'\"]+)['\"]", text)
        if m:
            last = m.group(1).rstrip("/").split("/")[-1]
            last = re.sub(r"\.(js|mjs|cjs|jsx|ts|tsx)$", "", last)
            return last == key
        return False
    if lang == "java":
        return (
            re.match(rf"^\s*import\s+(?:static\s+)?[\w.]*\b{key_esc}\s*;", text)
            is not None
        )
    if lang == "go":
        return (
            re.match(r'^\s*(?:import\s+)?(?:\w+\s+)?"[^"]+"\s*$', text) is not None
            and re.search(rf'"[^"]*\b{key_esc}"\s*$', text) is not None
        )
    if lang == "rust":
        return (
            re.match(rf"^\s*(?:pub\s+)?(?:use|mod)\s+(?:[\w:]+::)?{key_esc}\b", text)
            is not None
        )
    # unknown lang: accept lines that LOOK like imports mentioning the key
    return re.search(r"\b(import|require|include|use)\b", text) is not None
