"""JSON output package for codeq --json mode.

Public surface (stable for cli.py and tests):
  emit_json, run_with_json, STRUCTURED_HANDLERS
"""

from codeq.json_handler.core import emit_json
from codeq.json_handler.dispatch import STRUCTURED_HANDLERS, run_with_json

# Back-compat alias used by some tests
_STRUCTURED_HANDLERS = STRUCTURED_HANDLERS

__all__ = [
    "STRUCTURED_HANDLERS",
    "_STRUCTURED_HANDLERS",
    "emit_json",
    "run_with_json",
]
