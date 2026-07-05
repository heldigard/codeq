"""Benchmark sample data for codeq-model-bench.

Representative functions: trivial, medium, complex-with-side-effects.
Kept stable across runs so results are comparable. Edit ONLY to add cases.
"""
from __future__ import annotations

SAMPLES: list[tuple[str, str, str]] = [
    (
        "trivial-getter",
        "ts",
        "  protected get isLoading(): boolean {\n    return this._loading;\n  }",
    ),
    (
        "medium-async",
        "ts",
        "  protected async submitMessage(): Promise<void> {\n"
        "    const message = this.draft().trim();\n"
        "    if (!message || this.sending()) return;\n"
        "    this.draft.set('');\n"
        "    await this.sendText(message);\n"
        "  }",
    ),
    (
        "complex-error",
        "ts",
        "  private handleStreamFailure(error: unknown, message: string): void {\n"
        "    if (error instanceof Error && error.name === 'AbortError') {\n"
        "      this.interactionError.set('Response stopped.');\n"
        "      this.draft.set(message);\n"
        "      this.pendingMessages.set([]);\n"
        "      this.streamedAssistantContent.set('');\n"
        "      return;\n"
        "    }\n"
        "    this.interactionError.set(error instanceof Error ? error.message : 'Chatbot failed.');\n"
        "    this.draft.set(message);\n"
        "    this.pendingMessages.set([]);\n"
        "  }",
    ),
    (
        # Real symbol from ~/.claude/scripts/agent_browser_subagent.py — trivial Python
        # (docstring + try/except liveness probe). Ecosystem domain coverage.
        "py-trivial-probe",
        "py",
        'def ollama_alive(timeout: float = 2.0) -> bool:\n'
        '    """Fast liveness probe so we fail immediately when the daemon is down,\n'
        '    instead of waiting through 4 x 30s timeouts per call."""\n'
        '    try:\n'
        '        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout).read()\n'
        '        return True\n'
        '    except Exception:\n'
        '        return False',
    ),
    (
        # Real symbol from ~/.claude/scripts/agent_browser_subagent.py — complex Python
        # parser (depth-aware JSON extractor with string/escape state machine).
        "py-complex-parser",
        "py",
        'def extract_any_json(text: str) -> dict | None:\n'
        '    """Find the FIRST plausible JSON object in messy model output."""\n'
        '    cleaned = re.sub(r\'```(?:json)?\\s*\', \'\', text).replace(\'```\', \'\')\n'
        '    for start in range(len(cleaned)):\n'
        '        if cleaned[start] != \'{\':\n'
        '            continue\n'
        '        depth, end = 0, -1\n'
        '        in_str, escape = False, False\n'
        '        for i in range(start, len(cleaned)):\n'
        '            c = cleaned[i]\n'
        '            if escape: escape = False; continue\n'
        '            if in_str:\n'
        '                if c == \'\\\\\\\\\': escape = True; continue\n'
        '                if c == \'"\': in_str = False\n'
        '                continue\n'
        '            if c == \'"\': in_str = True\n'
        '            elif c == \'{\': depth += 1\n'
        '            elif c == \'}\':\n'
        '                depth -= 1\n'
        '                if depth == 0:\n'
        '                    end = i + 1; break\n'
        '        if end > start:\n'
        '            try:\n'
        '                return json.loads(cleaned[start:end])',
    ),
]
