"""Facade re-export of per-domain JSON handlers (import stability)."""

from __future__ import annotations

from codeq.json_handler.handlers_graph import (
    _context_json,
    _deps_json,
    _map_json,
    _rdeps_json,
    _refs_json,
    _relations_json,
)
from codeq.json_handler.handlers_meta import (
    _capabilities_json,
    _check_json,
    _doctor_json,
    _rename_error_payload,
    _rename_json,
    _tags_json,
)
from codeq.json_handler.handlers_symbol import (
    _body_json,
    _class_json,
    _find_json,
    _outline_json,
    _sig_json,
    _summary_json_cmd,
)

__all__ = [
    "_body_json",
    "_capabilities_json",
    "_check_json",
    "_class_json",
    "_context_json",
    "_deps_json",
    "_doctor_json",
    "_find_json",
    "_map_json",
    "_outline_json",
    "_rdeps_json",
    "_refs_json",
    "_relations_json",
    "_rename_error_payload",
    "_rename_json",
    "_sig_json",
    "_summary_json_cmd",
    "_tags_json",
]
