"""Regression tests for `codeq map`'s reference-weighting pass.

The weight of a symbol is its project-wide identifier frequency (a proxy for
"how referenced is this name"). The frequency pass must count REAL identifier
tokens only — not tokens that merely look like identifiers inside string
literals or comments. For Python files, `codeq map` uses the stdlib `tokenize`
module, which distinguishes NAME from STRING/COMMENT.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_map(root: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "codeq", "map", "-p", root, "--top", "20"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"map failed: {proc.stderr}"
    return proc.stdout


def test_map_py_freq_excludes_string_and_comment_tokens() -> None:
    """A symbol mentioned many times ONLY in strings / comments must NOT have
    its ref weight inflated. `tokenize` excludes STRING/COMMENT tokens, so
    only real NAME occurrences count.

    Setup: a.py defines `widget` and calls it twice (2 real refs). b.py
    defines an unrelated symbol `thing` but mentions `widget` five times
    inside a string literal and a comment (zero real refs). The reported
    `~N refs` for `widget` must reflect ~2 (the real calls), not ~7 (the
    regex count that includes b.py's string/comment noise)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("def widget():\n    pass\nwidget()\nwidget()\n")
        (root / "b.py").write_text(
            'def thing():\n    x = "widget widget widget"\n    # widget widget\n'
        )
        out = _run_map(str(root))
        # find the widget line: `    <line>  <kind>     widget  ~N refs`
        widget_lines = [ln for ln in out.splitlines() if re.search(r"\bwidget\b", ln)]
        assert widget_lines, f"widget missing from map:\n{out}"
        # extract the ref count from the first widget hit
        m = re.search(r"~(\d+) refs", widget_lines[0])
        assert m, f"no ref count on widget line: {widget_lines[0]}"
        refs = int(m.group(1))
        # tokenize path → only the 2 real calls in a.py count; b.py's 5
        # string/comment mentions are excluded. Allow headroom for the
        # shared-attribution floor (max(.,0)) but the value must stay small.
        assert refs <= 3, (
            f"widget ref weight inflated by string/comment tokens: ~{refs} refs "
            f"(tokenize should count ~2 real calls).\nmap:\n{out}"
        )


def test_map_py_freq_counts_real_calls() -> None:
    """Sanity: a symbol called several times in real code DOES accumulate
    ref weight (the tokenize fix must not zero out legitimate references)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text(
            "def helper():\n    pass\n"
            "helper()\nhelper()\nhelper()\nhelper()\nhelper()\n"
        )
        out = _run_map(str(root))
        helper_lines = [ln for ln in out.splitlines() if "helper" in ln]
        assert helper_lines, f"helper missing from map:\n{out}"
        m = re.search(r"~(\d+) refs", helper_lines[0])
        assert m, f"no ref count on helper line: {helper_lines[0]}"
        refs = int(m.group(1))
        # 5 real calls; shared attribution (defs=1) keeps it near 5 minus floor.
        assert refs >= 3, (
            f"helper ref weight too low — real calls not counted: ~{refs}.\n{out}"
        )
