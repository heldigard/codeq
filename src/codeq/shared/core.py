from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from codeq.shared.config import EXT_LANG

def die(msg: str, code: int = 2) -> NoReturn:
    print(f"codeq: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def lang_of(file_path: str, override: str | None) -> str:
    if override:
        return override
    ext = Path(file_path).suffix.lstrip(".")
    lang = EXT_LANG.get(ext)
    if not lang:
        die(f"unknown extension '.{ext}' for {file_path}; pass --lang")
    return lang


def _parse_ctags_line(line: str) -> tuple[str, str, str, str] | None:
    """Return (name, file, kind, line) or None for pseudo-tags."""
    if line.startswith("!_"):
        return None
    parts = line.split("\t")
    if len(parts) < 3:
        return None
    name, file = parts[0], parts[1]
    if not any(c.isalpha() for c in name):
        return None  # skip numeric/garbage fragments (e.g. "_000" from a 5_000 literal)
    kind = line_no = "?"
    for p in parts[3:]:
        if p.startswith("kind:"):
            kind = p[5:]
        elif p.startswith("line:"):
            line_no = p[5:]
    return name, file, kind, line_no
