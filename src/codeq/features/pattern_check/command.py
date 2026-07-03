from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from codeq.shared.config import ASTGREP, PROBE
from codeq.shared.core import die, run

def cmd_check(args: argparse.Namespace) -> int:
    lang = args.lang or "python"
    probe = PROBE.get(lang)
    if probe is None:
        die(f"no probe for lang '{lang}'; supported: {', '.join(PROBE)}")
    with tempfile.NamedTemporaryFile("w", suffix=f".{lang}", delete=False) as tf:
        tf.write(probe)
        probe_path = tf.name
    # ast-grep exit code is NOT a validity signal (no-match valid patterns exit 1,
    # like grep). The authoritative signal is stderr: empty = clean parse.
    try:
        _, _, err = run([ASTGREP, "run", "-p", args.pattern, "--lang", lang, probe_path])
    finally:
        Path(probe_path).unlink(missing_ok=True)
    err_s = err.strip()
    if not err_s:
        print(f"VALID — pattern parses cleanly as a single AST node (lang={lang}).")
        print(f"PATTERN: {args.pattern}")
        return 0
    low = err_s.lower()
    if "multiple ast nodes" in low:
        verdict = "INVALID — pattern is NOT a single AST node."
        hint = "Wrap it in its complete parent statement (e.g. full try:/except:, not a lone 'except:')."
    elif "error node" in low:
        verdict = "INVALID — pattern parsed but contains an ERROR node (invalid syntax)."
        hint = "Refine the pattern; it will match nothing or behave unexpectedly."
    elif "cannot parse" in low or "error" in low:
        verdict = "INVALID — pattern failed to parse."
        hint = err_s.splitlines()[-1]
    else:
        verdict = "INVALID."
        hint = err_s.splitlines()[-1]
    print(verdict, file=sys.stderr)
    print(f"PATTERN: {args.pattern}", file=sys.stderr)
    print(f"HINT:    {hint}", file=sys.stderr)
    return 2
