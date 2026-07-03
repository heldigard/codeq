from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codeq.shared.config import CTAGS, VENDOR_EXCLUDES
from codeq.shared.core import ctags_exclude_args, die, run

def cmd_tags(args: argparse.Namespace) -> int:
    """Project-wide ctags index (.tags) with VENDOR_EXCLUDES applied. Replaces the
    raw `ctags -R --fields=+nKz -f .tags .` documented in older rules, which would
    otherwise index node_modules/__pycache__/dist and bloat the tag file with vendor
    symbols. Shares the SAME exclude list as find/refs (single source of truth)."""
    out_file = args.output
    cmd = [CTAGS, "-R", "--fields=+nKz", "-f", out_file]
    cmd += ctags_exclude_args()
    cmd += [args.path]
    rc, _, err = run(cmd)
    if rc != 0:
        die(f"ctags failed: {err.strip()}", 2)
    p = Path(out_file)
    if not p.is_file() or p.stat().st_size == 0:
        print(f"warning: {out_file} empty (no symbols indexed under {args.path})",
              file=sys.stderr)
        return 1
    n_excludes = len(VENDOR_EXCLUDES)
    print(f"{out_file}  ({p.stat().st_size} bytes, {n_excludes} vendor/cache dirs excluded)")
    return 0
