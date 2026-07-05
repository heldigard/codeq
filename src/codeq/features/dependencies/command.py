from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from codeq.features.dependencies.parsing import re_deps
from codeq.shared.config import IMPORT_PATTERNS
from codeq.shared.core import die, lang_of
from codeq.shared.search import search_lexical


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
            rows.extend((node.lineno, "import", a.name) for a in node.names)
        elif isinstance(node, _ast.ImportFrom):
            mod = node.module or ""
            names = ", ".join(a.name for a in node.names)
            rows.append((node.lineno, "from", f"{mod} ( {names} )"))
    return rows or None


def get_deps(file: str, lang: str | None = None) -> list[tuple[int, str, str]]:
    """Core deps logic: returns import rows as (line, kind, module).

    Pure function — no argparse, no stdout. Callers (cmd_deps, cmd_context)
    use this directly instead of constructing Namespace objects.

    Returns sorted [(line_no, 'import'|'from', module_name), ...] or empty."""
    resolved_lang = lang or ""
    if not resolved_lang:
        try:
            resolved_lang = lang_of(file, None)
        except SystemExit:
            return []
    rows = _py_deps(file) if resolved_lang == "python" else re_deps(file, resolved_lang)
    return sorted(rows) if rows else []


def cmd_deps(args: argparse.Namespace) -> int:
    """Imports/dependencies of a file. Compact context to know what the file
    depends on BEFORE editing (correct-context principle)."""
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    rows = get_deps(args.file, lang)
    if not rows:
        print(f"no imports found in {args.file} (lang={lang})", file=sys.stderr)
        return 1
    for ln, kind, mod in rows:
        print(f"{ln:>5}  {kind:<6}  {mod}")
    return 0


def _module_keys(file: str) -> list[str]:
    """Candidate module keys another file would use to import FILE."""
    p = Path(file)
    stem = p.stem
    keys: list[str] = []
    if stem == "__init__" and p.parent.name:
        # Python package entry files are imported by their DIRECTORY name.
        keys.append(p.parent.name)
    elif stem in ("index", "mod") and p.parent.name:
        # Directory entry files are commonly imported by the directory name
        # (`./pkg` -> `pkg/index.ts`, Rust `mod.rs`), but `mod.ts` and
        # `index.ts` can also be imported directly as `./mod` / `./index`.
        keys.extend([p.parent.name, stem])
    else:
        keys.append(stem)
        if p.suffix == ".go" and p.parent.name:
            keys.append(p.parent.name)  # go imports the package dir, not the file
    return keys


def _dedup_keys(keys: list[str]) -> list[str]:
    """Deduplicate module keys while preserving search order."""
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _python_package_module(file: str) -> str | None:
    """Importable module path for FILE when it lives under Python packages."""
    p = Path(file).resolve()
    parts = [p.stem] if p.stem != "__init__" else []
    cur = p.parent
    while (cur / "__init__.py").is_file():
        parts.append(cur.name)
        cur = cur.parent
    return ".".join(reversed(parts)) if parts else None


def _python_src_layout_module(file: str, path: str) -> str | None:
    """Best-effort src-layout module path when package __init__ files are absent."""
    try:
        rel = Path(file).resolve().relative_to(Path(path).resolve())
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _rdep_module_keys(file: str, path: str, lang: str) -> list[str]:
    """Candidate module keys for rdeps.

    Python package files often share generic names (`command.py`, `models.py`).
    For those, a stem-only search is noisy, so prefer precise importable module
    paths when we can infer them. Script-like files keep the legacy stem key.
    """
    if lang != "python":
        return _module_keys(file)
    precise = _dedup_keys(
        [
            _python_package_module(file) or "",
            _python_src_layout_module(file, path) or "",
        ]
    )
    return precise or _module_keys(file)


def _resolves_to(path: str, target: Path) -> bool:
    """True when PATH resolves to TARGET (so we skip the module listing itself).
    `Path.resolve()` can raise OSError on broken symlinks — tolerate it."""
    try:
        return Path(path).resolve() == target
    except OSError:
        return False


def _rdep_rows_for_key(
    lines: list[str], key: str, target: Path, lang: str
) -> list[tuple[str, int, str]]:
    """Parse search result LINES (`path:line:text`) into candidate rdep rows
    for module KEY (self-references filtered, not yet deduped across keys).
    Extracted from cmd_rdeps to keep nesting shallow; caller dedups."""
    rows: list[tuple[str, int, str]] = []
    for line in lines:
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
    "bash": ["--include=*.sh", "--include=*.bash"],
}


def get_rdeps(
    file: str,
    path: str,
    lang: str | None = None,
    limit: int = 200,
) -> list[tuple[str, int, str]]:
    """Core rdeps logic: returns reverse dependency rows as (file, line, text).

    Pure function — no argparse, no stdout. Callers (cmd_rdeps, JSON output)
    use this directly instead of constructing Namespace objects.

    Returns sorted [(file, line_no, import_text), ...] or empty."""
    f = Path(file)
    if not f.is_file():
        return []
    resolved_lang = lang or ""
    if not resolved_lang:
        try:
            resolved_lang = lang_of(file, None)
        except SystemExit:
            return []
    keys = _rdep_module_keys(file, path, resolved_lang)
    includes = _INCLUDES_BY_LANG.get(resolved_lang, [])
    target = f.resolve()
    seen: set[tuple[str, str]] = set()
    rows: list[tuple[str, int, str]] = []
    for key in keys:
        hits = search_lexical(key, path, includes)
        _dedup_extend(rows, seen, _rdep_rows_for_key(hits, key, target, resolved_lang))
    rows.sort()
    if limit:
        return rows[:limit]
    return rows


def _dedup_extend(
    rows: list[tuple[str, int, str]],
    seen: set[tuple[str, str]],
    candidates: list[tuple[str, int, str]],
) -> None:
    """Append non-duplicate rdep rows. Extracted to keep nesting ≤ 3."""
    for rpath, ln, text in candidates:
        dedup = (rpath, text)
        if dedup in seen:
            continue
        seen.add(dedup)
        rows.append((rpath, ln, text))


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
    limit = getattr(args, "limit", 200) or 0
    rows = get_rdeps(args.file, args.path, lang, limit=limit)
    if not rows:
        keys = _rdep_module_keys(args.file, args.path, lang)
        print(
            f"no project file imports '{'/'.join(keys)}' under {args.path}",
            file=sys.stderr,
        )
        return 1
    for path, ln, text in rows:
        print(f"{path}:{ln}: {text}")
    n_files = len({r[0] for r in rows})
    print(f"-- {len(rows)} import line(s) across {n_files} file(s)", file=sys.stderr)
    return 0


def _ts_module_matches(mod_path: str, key: str) -> bool:
    """Check if a JS/TS module path's last segment matches KEY."""
    last = mod_path.rstrip("/").split("/")[-1]
    last = re.sub(r"\.(js|mjs|cjs|jsx|ts|tsx)$", "", last)
    return last == key


def _ts_pattern_matches(text: str, lang: str, key: str) -> bool:
    """Check if any JS/TS import pattern matches TEXT for module KEY."""
    for pat in IMPORT_PATTERNS.get(lang, IMPORT_PATTERNS["typescript"]):
        m = pat.search(text)
        if m and _ts_module_matches(m.group(1), key):
            return True
    return False


def _py_module_matches(candidate: str, key: str) -> bool:
    """True when Python import CANDIDATE names KEY.

    Dotted keys are precise (`pkg.a.command`). Stem/package keys keep the
    legacy segment fallback used for script files and package entry modules.
    """
    if candidate == key or candidate.startswith(f"{key}."):
        return True
    if "." in key:
        return False
    parts = candidate.split(".")
    return parts[-1] == key or key in parts


def _is_import_of(text: str, key: str, lang: str) -> bool:
    """True when TEXT is an import statement whose module path resolves to KEY."""
    key_esc = re.escape(key)
    if lang == "python":
        m = re.match(r"^\s*(?:from\s+([\w\.]+)\s+import\b|import\s+([\w\., ]+))", text)
        if not m:
            return False
        mods = m.group(1) or m.group(2) or ""
        candidates = [p for p in re.split(r"[,\s]+", mods) if p]
        return any(_py_module_matches(part, key) for part in candidates)
    if lang in ("javascript", "typescript"):
        if _ts_pattern_matches(text, lang, key):
            return True
        # Multi-line import closer: `} from './module';` carries the module
        # path but no leading import/export keyword, so the anchored patterns
        # above miss it — without this, rdeps reports zero importers for any
        # barrel/harness module. Match the closer and compare the last segment.
        m = re.search(r"\bfrom\s+['\"]([^'\"]+)['\"]", text)
        if m:
            return _ts_module_matches(m.group(1), key)
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
