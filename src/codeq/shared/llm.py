from __future__ import annotations

import os
import sys
from pathlib import Path

# Best-effort path injection for the shared local-Ollama client.
# Default lives under ~/.claude/scripts (the canonical cross-CLI scripts
# dir on this host) but is overridable via `CODEQ_HARNESS_SCRIPTS` so the
# codeq package stays portable to other homes / containers where the
# harness lives elsewhere (or is absent — in which case ollama_client is
# simply not importable and `_llm_status` returns ok=False with a clear
# reason; callers print the disabled banner and continue).
_HARNESS_SCRIPTS = Path(
    os.environ.get("CODEQ_HARNESS_SCRIPTS", str(Path.home() / ".claude" / "scripts"))
)
if _HARNESS_SCRIPTS.is_dir():
    sys.path.insert(0, str(_HARNESS_SCRIPTS))

# ---------------------------------------------------------------------------
# Ollama enrichment layer (local 4B model). Produces SHORTER & more digestable
# representations of code facts so the large LLM at the agent loop can orient
# faster. Does NOT do reasoning — that's the large LLM's job; we only deliver
# better-compressed facts, tagged so the consumer can tell they came from a
# small heuristic model and must be verified before reasoning on them.
# ---------------------------------------------------------------------------

_OLLAMA_SUMMARY_PREFIX = (
    "# [ollama-summary: {model} (local); this call {lat}s (repeats ~0.1s via"
    " cache); VERIFY before reasoning — small model, may summarize imprecisely]"
)
_OLLAMA_DISABLED_PREFIX = (
    "# [ollama summary unavailable: {reason} — re-run with Ollama up or pass --no-llm to silence]"
)

# Model used for the `summary`/`context`/`relations`/`--summary` paths.
# Default is the codeq_sum winner of the 2026-07-08 canonical refactor re-bench:
# batiai/gemma4-e4b:q4 scored 9.23 and separated from SetneufPT (9.15) after the new
# non-saturating summary metrics. Override with CODEQ_SUMMARY_MODEL on VRAM-tight
# hosts or when testing another local model. See ~/ollama-bench/RANKING.md.
_CODEQ_SUMMARY_MODEL = os.environ.get(
    "CODEQ_SUMMARY_MODEL",
    "batiai/gemma4-e4b:q4",
)


def _llm_status(no_llm: bool = False) -> tuple[bool, str, str]:
    """Returns (ok, model, reason). `ok=False` means enrichment is silently
    skipped — callers print a one-line note and continue with the body.
    Uses codeq's OWN summary model (not ollama_client's global default, which
    other harness tools share)."""
    if no_llm or os.environ.get("CODEQ_NO_LLM"):
        return (False, "", "CODEQ_NO_LLM=1 / --no-llm")
    try:
        import ollama_client
    except (ImportError, ModuleNotFoundError):
        return (False, "", "ollama_client not importable (run from this host?)")
    try:
        if not ollama_client.is_alive(timeout=2.0):
            return (False, "", "Ollama daemon not reachable on localhost:11434")
    except Exception:
        return (False, "", "Ollama liveness probe failed")
    return (True, _CODEQ_SUMMARY_MODEL, "")


def _summarize_code(
    file_path: str,
    name: str,
    body: str,
    *,
    no_llm: bool = False,
) -> tuple[str | None, str, float]:
    """Generate a 1-sentence description of `name` in `file_path` using the
    configured local Ollama model. Returns (summary_or_None, model_or_reason,
    cold_seconds). `cold_seconds` is the wall time of the Ollama call (0.0 on
    the no-llm / failure paths) — used to make the provenance banner honest
    about latency instead of a hardcoded "~500ms".

    The summary is deterministic-temp (0.2) so ollama_client's sha256 cache
    replays it on subsequent calls (warm ~0.1s vs cold 5-30s).

    `no_llm=True` short-circuits without making the HTTP call — useful when
    the caller has already decided (e.g. `--no-llm` flag).

    Hardening:
      - 30s timeout (not the ollama_client default 120s): a 30-word summary
        should never take longer; if the model hangs, the agent loop is not
        blocked for 2 minutes.
      - Body truncated to ~2.5KB AND marked when truncated, so the 4B model
        knows it is seeing a prefix and doesn't summarize the tail as if it
        were the whole function.
    """
    ok, model, reason = _llm_status(no_llm=no_llm)
    if not ok:
        return (None, reason, 0.0)
    import ollama_client
    import time as _time

    # Truncate to keep the small model focused on the signature + first ~2.5KB.
    BODY_BUDGET = 2500
    is_truncated = len(body) > BODY_BUDGET
    body_view = body[:BODY_BUDGET]
    truncation_note = (
        "\n[NOTE: BODY TRUNCATED — only the first portion is shown above; "
        "describe what is visible and do not assume the rest.]"
        if is_truncated
        else ""
    )
    prompt = (
        "You are summarizing a function/class/method for a senior LLM that is\n"
        "about to EDIT this code. It has the full body already; your ONLY job\n"
        "is to save it tokens by writing ONE short sentence (max 30 words)\n"
        "describing what this symbol does.\n\n"
        "Be precise and factual. Do not invent variables, types, or external\n"
        "dependencies. If the symbol is trivial (one-liner passthrough, getter,\n"
        "effect-only call) or its purpose is unclear, say so plainly.\n\n"
        f"FILE: {file_path}\n"
        f"SYMBOL: {name}\n\n"
        f"BODY:\n{body_view}{truncation_note}\n\n"
        "One sentence description:"
    )
    t0 = _time.monotonic()
    try:
        summary = ollama_client.generate(
            prompt,
            model=model,
            temperature=0.2,
            num_ctx=8192,
            timeout=30,
        )
    except Exception as exc:  # transport / timeout — never crash the caller
        return (None, f"Ollama call failed: {type(exc).__name__}", 0.0)
    cold = _time.monotonic() - t0
    if not summary:
        return (None, "model returned empty", cold)
    summary = summary.strip().strip('"').strip("'")
    if len(summary) > 400:  # the model sometimes runs on; truncate hard
        summary = summary[:400].rsplit(" ", 1)[0] + "..."
    return (summary, model, cold)


def _maybe_emit_summary(file_path: str, name: str, body: str, *, no_llm: bool = False) -> None:
    """Print a tagged summary line BEFORE the body. Always silent on failure
    — the body is the authoritative source; the summary is just orientation.
    `source` is the actual model tag on success, so the banner reflects the
    real model (not a hardcoded name that drifts if DEFAULT_GEN_MODEL changes).
    The banner also reports the measured cold latency (honest, not a guess)."""
    summary, source, cold = _summarize_code(file_path, name, body, no_llm=no_llm)
    if summary:
        # Build the banner as a local first so the .format() kwargs don't sit
        # inside the print() call (was 4 levels of indent). Kept inside the
        # `if summary:` branch so the variable is provably bound when used.
        banner = _OLLAMA_SUMMARY_PREFIX.format(
            model=source or "local-llm",
            lat=f"{cold:.1f}" if cold else "?",
        )
        print(banner)
        print(f"# {summary}")
        print("# [body follows — read it to verify the summary before reasoning]")
        print()
    else:
        # Emit a single muted line so the consumer knows we TRIED and skipped
        # — helpful when debugging "why doesn't the summary appear?".
        print(_OLLAMA_DISABLED_PREFIX.format(reason=source or "unknown"))
        print()
