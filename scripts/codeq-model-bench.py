#!/usr/bin/env python3
"""codeq summary-model benchmark — which local Ollama model is best for the
`codeq summary` task?

Uses the EXACT prompt codeq sends (kept in sync with codeq._summarize_code)
on a fixed set of representative functions, across a candidate model list,
and writes the results to JSON + Markdown so future runs can compare against
prior baselines.

Why this exists: codeq's default summary model is re-validated by this
benchmark every time the ollama-bench lineup changes. Current winner per
`~/ollama-bench/RANKING.md` 2026-07-09 validation: Qwythos-9B-Claude-Mythos
(9.40) over batiai/gemma4-e4b:q4 (9.19). Re-run whenever you install new
models or want to re-validate the choice.

Usage:
  python3 ~/codeq/scripts/codeq-model-bench.py                     # default models
  python3 ~/codeq/scripts/codeq-model-bench.py -m modelA -m modelB
  python3 ~/codeq/scripts/codeq-model-bench.py -o results.md       # write snapshot
  python3 ~/codeq/scripts/codeq-model-bench.py --no-cache          # force cold

Exit 0 = ran (some models may have errored, see output); 1 = daemon down.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    shared_scripts = Path(__file__).resolve().parents[2] / ".claude" / "scripts"
except IndexError:
    shared_scripts = Path.home() / ".claude" / "scripts"
if not (shared_scripts / "ollama_client.py").exists():
    shared_scripts = Path.home() / ".claude" / "scripts"
sys.path.insert(0, str(shared_scripts))
import ollama_client  # type: ignore[import-not-found]
from _bench_samples import SAMPLES

# Default candidate set — the models worth comparing for the summary task.
# (Embedding models excluded — they can't generate.) Override with -m.
# Aligned with ~/ollama-bench/RANKING.md 2026-07-09 validation (codeq_sum):
#   1. Qwythos-9B-Claude-Mythos  (9.40)  <- current default in codeq.shared.llm
#   2. batiai/gemma4-e4b:q4      (9.19)  <- current fallback in codeq.shared.llm
#   3. SetneufPT/Qwopus3.5-4B    (8.99)  <- structured-output champion (tool_call)
# Re-validate when RANKING.md changes; keep this list in sync.
DEFAULT_MODELS = [
    "hf.co/empero-ai/Qwythos-9B-Claude-Mythos-5-1M-GGUF:Q4_K_M",  # codeq_sum #1
    "batiai/gemma4-e4b:q4",  # codeq_sum #2
    "SetneufPT/Qwopus3.5-4B-Coder-MTP_Q4_64k_8GB-GPU:latest",  # codeq_sum #3
    "qwen3.5:4b",  # ollama_client global default / universal fallback baseline
    "fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:4b",  # historical contender
]


def make_prompt(name: str, body: str) -> str:
    """MUST stay in sync with codeq._summarize_code's prompt."""
    return (
        "You are summarizing a function/class/method for a senior LLM that is\n"
        "about to EDIT this code. It has the full body already; your ONLY job\n"
        "is to save it tokens by writing ONE short sentence (max 30 words)\n"
        "describing what this symbol does.\n\n"
        "Be precise and factual. Do not invent variables, types, or external\n"
        "dependencies. If the symbol is trivial (one-liner passthrough, getter,\n"
        "effect-only call) or its purpose is unclear, say so plainly.\n\n"
        f"FILE: bench.ts\nSYMBOL: {name}\n\nBODY:\n{body}\n\nOne sentence description:"
    )


def _word_count(s: str) -> int:
    return len(s.split())


_LEAK_SIGNALS = (
    "protected",
    "private",
    "Promise<void>",
    "{\n",
    "```",
    "Thinking:",
    "Thinking Process",
    "Analyze the Request",
)


def _leaks_code(text: str) -> bool:
    """Heuristic: did the model echo code structure back instead of prose?"""
    return any(sig in text for sig in _LEAK_SIGNALS)


def run_one(model: str, name: str, body: str, *, use_cache: bool) -> dict:
    prompt = make_prompt(name, body)
    t0 = time.monotonic()
    try:
        raw = ollama_client.generate(
            prompt,
            model=model,
            temperature=0.2,
            num_ctx=8192,
            timeout=45,
            cache=use_cache,
        )
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 1)
        return {
            "model": model,
            "sample": name,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": elapsed,
        }
    dt = time.monotonic() - t0
    text = (raw or "").strip().strip('"').strip("'")
    return {
        "model": model,
        "sample": name,
        "seconds": round(dt, 1),
        "words": _word_count(text),
        "leaks_code": _leaks_code(text),
        "respects_30w": _word_count(text) <= 35,  # small margin
        "text": text[:500],
    }


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "-m",
        "--model",
        action="append",
        dest="models",
        help="candidate model (repeatable; default: DEFAULT_MODELS)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="write a Markdown snapshot to this path (in addition to stdout)",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="force cold calls (default: use ollama_client cache for stable input)",
    )
    ap.add_argument(
        "--json", action="store_true", help="emit JSON instead of human-readable"
    )
    return ap


def main() -> int:
    args = _build_parser().parse_args()

    models = args.models or DEFAULT_MODELS
    use_cache = not args.no_cache

    if not ollama_client.is_alive(timeout=2.0):
        print("Ollama down — abort. Start it with `ollama serve`.", file=sys.stderr)
        return 1

    results: list[dict] = []
    for label, _lang_unused, body in SAMPLES:
        for model in models:
            results.append(run_one(model, label, body, use_cache=use_cache))

    if args.json:
        output = {
            "models": models,
            "samples": [s[0] for s in SAMPLES],
            "results": results,
        }
        print(json.dumps(output, indent=2))
    else:
        _print_human(results, models)

    if args.output:
        _write_markdown(args.output, results, models, use_cache)
        print(f"\n(snapshot written to {args.output})", file=sys.stderr)
    return 0


def _format_result_line(r: dict) -> str:
    """Format a single result dict into a human-readable line."""
    if "error" in r:
        return f"\n[{r['model']}]  ({r['seconds']}s)\n  ERROR: {r['error']}"
    flags = []
    if r["leaks_code"]:
        flags.append("LEAKS CODE")
    if not r["respects_30w"]:
        flags.append(f"{r['words']}w > 30")
    tag = f" — {' / '.join(flags)}" if flags else ""
    return (
        f"\n[{r['model']}]  ({r['seconds']}s, {r['words']} words{tag})\n  {r['text']}"
    )


def _results_for_sample(results: list[dict], sample: str) -> list[dict]:
    """Filter results to those matching `sample`."""
    return [r for r in results if r.get("sample") == sample]


def _print_human(results: list[dict], models: list[str]) -> None:
    print(
        f"# codeq summary-model benchmark | {len(models)} models x "
        f"{len({r['sample'] for r in results})} samples\n"
    )
    for sample in [s[0] for s in SAMPLES]:
        print(f"\n{'=' * 78}\nSAMPLE: {sample}\n{'=' * 78}")
        for r in _results_for_sample(results, sample):
            print(_format_result_line(r))


def _format_markdown_row(r: dict) -> str:
    """Format a single result dict as a Markdown table row."""
    if "error" in r:
        return f"| `{r['model']}` | {r['seconds']} | — | — | — | ERROR: {r['error']} |"
    text = r["text"].replace("|", "\\|").replace("\n", " ")[:120]
    return (
        f"| `{r['model']}` | {r['seconds']} | {r['words']} | "
        f"{'✅' if r['respects_30w'] else '❌'} | "
        f"{'❌' if r['leaks_code'] else '✅'} | {text} |"
    )


def _write_markdown(
    path: str, results: list[dict], models: list[str], use_cache: bool
) -> None:
    lines = [
        "# codeq summary-model benchmark — snapshot",
        "",
        f"- Date: {time.strftime('%Y-%m-%d')}",
        f"- Cache: {'on (warm repeats ~0.1s)' if use_cache else 'OFF (forced cold)'}",
        f"- Models ({len(models)}): {', '.join(models)}",
        "",
        "## Scoring rubric",
        "",
        "- **leaks_code**: model echoed code structure / a reasoning trace instead"
        " of a clean prose sentence → DISQUALIFIED for this task.",
        "- **respects_30w**: summary stayed within the 30-word budget.",
        "- **seconds**: wall time of the call (cold when --no-cache).",
        "",
        "## Results by sample",
        "",
    ]
    for sample in [s[0] for s in SAMPLES]:
        lines.append(f"### {sample}")
        lines.append("")
        lines.append(
            "| model | seconds | words | respects 30w | leaks code | summary |"
        )
        lines.append("|---|---|---|---|---|---|")
        for r in _results_for_sample(results, sample):
            lines.append(_format_markdown_row(r))
        lines.append("")
    Path(path).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
