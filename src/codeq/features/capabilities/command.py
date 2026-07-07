from __future__ import annotations

import argparse
from typing import Any


CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "name": "find",
        "purpose": "Locate exact symbol definitions under a project path.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "outline",
        "purpose": "Return a bounded symbol map for one file.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "body",
        "purpose": "Extract one exact function/class body without reading the full file.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "class",
        "purpose": "Extract one full class/type body with members.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "sig",
        "purpose": "Extract only the symbol signature/header.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "refs",
        "purpose": "Return call/reference sites for a symbol before editing.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": True,
    },
    {
        "name": "deps",
        "purpose": "Return imports/dependencies of one file.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": True,
    },
    {
        "name": "rdeps",
        "purpose": "Return files that import the target file.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": True,
    },
    {
        "name": "map",
        "purpose": "Return repo orientation by hot files and symbols.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "tags",
        "purpose": "Build a project .tags index with vendor/cache dirs excluded.",
        "read_only": False,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "check",
        "purpose": "Validate an ast-grep pattern before running it.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "summary",
        "purpose": "Return a local-LLM one-line orientation for one symbol.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "context",
        "purpose": "Return an edit bundle: summary, signature, body, refs, deps, importers.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": True,
    },
    {
        "name": "relations",
        "purpose": "Return compact call orientation: summary, signature, call hints, refs.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": True,
    },
    {
        "name": "rename",
        "purpose": "Rewrite identifiers with ast-grep structural update.",
        "read_only": False,
        "destructive": True,
        "idempotent": False,
        "open_world": False,
        "structured_json": False,
    },
    {
        "name": "doctor",
        "purpose": "Check or install required external binaries.",
        "read_only": False,
        "destructive": False,
        "idempotent": True,
        "open_world": True,
        "structured_json": False,
    },
)


def capabilities_payload() -> dict[str, Any]:
    return {
        "command": "capabilities",
        "schema_version": 1,
        "annotations": {
            "read_only": "Does not modify the project or environment.",
            "destructive": "May rewrite or remove existing user-controlled content.",
            "idempotent": "Safe to repeat with identical arguments.",
            "open_world": "May call network/package managers or external systems.",
            "structured_json": "Has first-class typed output under global --json.",
        },
        "capabilities": list(CAPABILITIES),
    }


def cmd_capabilities(args: argparse.Namespace) -> int:
    """Print a compact tool-card style capability table for routers/agents."""
    del args
    print("name          ro  destructive  idem  open  json  purpose")
    for item in CAPABILITIES:
        print(
            f"{item['name']:<13} "
            f"{_yn(item['read_only']):<3} "
            f"{_yn(item['destructive']):<12} "
            f"{_yn(item['idempotent']):<5} "
            f"{_yn(item['open_world']):<5} "
            f"{_yn(item['structured_json']):<5} "
            f"{item['purpose']}"
        )
    return 0


def _yn(value: bool) -> str:
    return "yes" if value else "no"
