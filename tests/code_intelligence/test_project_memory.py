from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def test_project_memory_maintain_report_shape() -> None:
    """`project-memory.py maintain` must (a) exit 0, (b) emit the audit-report
    header, (c) flag an over-budget file — regardless of whether Ollama is up
    (semantic audit) or down (budget-only degradation). Deterministic: no
    network/model dependency in the assertions."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "p"
        proj.mkdir()
        # init a bank, then blow past progress.md's 300-line budget
        subprocess.run(
            ["python3", str(Path.home() / ".claude" / "scripts" / "project-memory.py"),
             "--root", str(proj), "init"],
            check=True, capture_output=True,
        )
        progress = proj / ".memory-bank" / "progress.md"
        lines = ["# Progress"] + [f"- 2026-06-0{i%9+1}: entry {i}." for i in range(320)]
        progress.write_text("\n".join(lines) + "\n")
        r = subprocess.run(
            ["python3", str(Path.home() / ".claude" / "scripts" / "project-memory.py"),
             "--root", str(proj), "maintain", "--no-llm"],
            capture_output=True, text=True, check=False,
        )
        assert r.returncode == 0, f"maintain exited {r.returncode}: {r.stderr}"
        assert "Memory Bank Audit" in r.stdout, (
            f"maintain missing audit header: {r.stdout[:300]!r}"
        )
        # The over-budget flag is deterministic (no Ollama needed).
        assert "progress.md" in r.stdout and "OVER 80% BUDGET" in r.stdout, (
            f"maintain did not flag the over-budget progress.md: {r.stdout[:500]!r}"
        )
