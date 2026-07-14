from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from typing import Any

from codeq.shared.config import ASTGREP, PROBE
from codeq.shared.core import die, run


def check_pattern(pattern: str, lang_override: str | None = None) -> dict[str, Any]:
    """Validates an ast-grep pattern by parsing it against a minimal language probe."""
    lang = lang_override or "python"
    probe = PROBE.get(lang)
    if probe is None:
        return {
            "valid": False,
            "pattern": pattern,
            "lang": lang,
            "error": f"no probe for lang '{lang}'; supported: {', '.join(PROBE)}",
            "verdict": "INVALID — unsupported language.",
            "hint": "Use a supported language.",
        }
    with tempfile.NamedTemporaryFile("w", suffix=f".{lang}", delete=False) as tf:
        tf.write(probe)
        probe_path = tf.name
    # ast-grep exit code is NOT a validity signal (no-match valid patterns exit 1,
    # like grep). The authoritative signal is stderr: empty = clean parse.
    try:
        _, _, err = run([ASTGREP, "run", "-p", pattern, "--lang", lang, probe_path])
    finally:
        Path(probe_path).unlink(missing_ok=True)
    err_s = err.strip()
    if not err_s:
        return {
            "valid": True,
            "pattern": pattern,
            "lang": lang,
            "error": None,
            "verdict": f"VALID — pattern parses cleanly as a single AST node (lang={lang}).",
            "hint": None,
        }
    low = err_s.lower()
    if "multiple ast nodes" in low:
        error = "pattern is NOT a single AST node."
        verdict = "INVALID — pattern is NOT a single AST node."
        hint = "Wrap it in its complete parent statement (e.g. full try:/except:, not a lone 'except:')."
    elif "error node" in low:
        error = "pattern parsed but contains an ERROR node (invalid syntax)."
        verdict = (
            "INVALID — pattern parsed but contains an ERROR node (invalid syntax)."
        )
        hint = "Refine the pattern; it will match nothing or behave unexpectedly."
    elif "cannot parse" in low or "error" in low:
        error = "pattern failed to parse."
        verdict = "INVALID — pattern failed to parse."
        hint = err_s.splitlines()[-1]
    else:
        error = "invalid pattern."
        verdict = "INVALID."
        hint = err_s.splitlines()[-1]
    return {
        "valid": False,
        "pattern": pattern,
        "lang": lang,
        "error": error,
        "verdict": verdict,
        "hint": hint,
    }


def cmd_check(args: argparse.Namespace) -> int:
    lang = args.lang or "python"
    if lang not in PROBE:
        die(f"no probe for lang '{lang}'; supported: {', '.join(PROBE)}")
    res = check_pattern(args.pattern, args.lang)
    if res["valid"]:
        print(
            f"VALID — pattern parses cleanly as a single AST node (lang={res['lang']})."
        )
        print(f"PATTERN: {res['pattern']}")
        return 0
    print(res["verdict"], file=sys.stderr)
    print(f"PATTERN: {res['pattern']}", file=sys.stderr)
    print(f"HINT:    {res['hint']}", file=sys.stderr)
    return 2
