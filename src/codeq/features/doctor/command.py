"""`codeq doctor` — detect required/optional external binaries, report what is
missing, and (with --install) install the missing ones via non-sudo managers
when possible (cargo / npm / pipx); print exact manual commands otherwise.
"""

from __future__ import annotations

import argparse
import platform
import shlex
import shutil
import subprocess
import sys
from typing import Any

# Tool registry. `managers` maps an installer key to a shell command. The
# NO_SUDO list is tried first for `--install`; apt/brew/script are manual hints.
TOOLS: list[dict[str, object]] = [
    {
        "name": "ctags",
        "importance": "required",
        "why": "universal symbol index (find/outline/tags/rdeps)",
        "managers": {
            "apt": "sudo apt install universal-ctags",
            "brew": "brew install universal-ctags",
        },
    },
    {
        "name": "ast-grep",
        "importance": "required",
        "why": "structural AST search/replace (body/class/check)",
        "managers": {
            "npm": "npm install -g @ast-grep/cli",
            "cargo": "cargo install ast-grep-cli",
            "brew": "brew install ast-grep",
        },
    },
    {
        "name": "shellcheck",
        "importance": "optional",
        "why": "shell lint",
        "managers": {
            "apt": "sudo apt install shellcheck",
            "brew": "brew install shellcheck",
        },
    },
    {
        "name": "shfmt",
        "importance": "optional",
        "why": "shell format (companion to shellcheck)",
        "managers": {
            "apt": "sudo apt install shfmt",
            "brew": "brew install shfmt",
            "go": "go install mvdan.cc/sh/v3/cmd/shfmt@latest",
        },
    },
    {
        "name": "rg",
        "importance": "optional",
        "why": "speeds up refs/rdeps (pure-Python walker used otherwise)",
        "managers": {
            "apt": "sudo apt install ripgrep",
            "cargo": "cargo install ripgrep",
            "brew": "brew install ripgrep",
        },
    },
    {
        "name": "ollama",
        "importance": "optional",
        "why": "local LLM for summary/context/relations",
        "managers": {
            "script": "curl -fsSL https://ollama.com/install.sh | sh",
        },
    },
    {
        "name": "tree-sitter",
        "importance": "optional",
        "python_module": "tree_sitter_language_pack",
        "why": (
            "AST-exact body extraction, refs comment/string filter, and map "
            "identifier frequency for JS/TS/Java/Go/Rust"
        ),
        "managers": {
            "pip": "pip install 'codeq-cli[ast]'",
            "pipx": "pipx inject codeq-cli tree-sitter tree-sitter-language-pack",
        },
    },
]

# Managers tried first for `--install` (no root required).
NO_SUDO_MANAGERS = ["cargo", "npm", "pipx"]


def _detect(name: str) -> tuple[str | None, str | None]:
    """Return (path, first-line-of-version) for NAME, or (None, None).

    Detects CLI binaries via PATH + `--version`. Tools that codeq consumes as
    a Python module (not a CLI) declare a `python_module` key and are detected
    via `importlib.util.find_spec` instead — `shutil.which` would miss them."""
    path = shutil.which(name)
    if not path:
        return None, None
    try:
        proc = subprocess.run(
            [name, "--version"], capture_output=True, text=True, timeout=6
        )
    except (OSError, subprocess.SubprocessError):
        return path, None
    out = (proc.stdout or proc.stderr or "").strip().splitlines()
    return path, (out[0] if out else None)


def _detect_tool(tool: dict[str, object]) -> tuple[str | None, str | None]:
    """Dispatch a tool's detection by how codeq consumes it: Python module
    (importlib) or CLI binary (PATH + --version). Extracted so the report loop
    reads `detected = _detect_tool(tool)` regardless of the tool's kind."""
    mod = tool.get("python_module")
    if isinstance(mod, str):
        return _detect_python_module(mod)
    return _detect(str(tool["name"]))


def _detect_python_module(module: str) -> tuple[str | None, str | None]:
    """Return (marker, version) when MODULE is importable, else (None, None).
    The marker is `python:<module>` so the report reads as a detected path."""
    import importlib.util

    spec = importlib.util.find_spec(module)
    if spec is None:
        return None, None
    try:
        mod_obj = __import__(module)
        ver = getattr(mod_obj, "__version__", None) or getattr(mod_obj, "VERSION", None)
    except ImportError:
        ver = None
    return (f"python:{module}", str(ver) if ver else "(python module)")


def _manager_available(manager: str) -> bool:
    return shutil.which(manager) is not None


def _managers_of(tool: dict[str, object]) -> dict[str, str]:
    """Typed view of a tool's installer map (empty if absent/malformed)."""
    raw = tool.get("managers", {})
    return raw if isinstance(raw, dict) else {}


def _try_install(tool: dict[str, object]) -> str:
    """Attempt a no-sudo install of TOOL. Return a one-line outcome string."""
    name = str(tool["name"])
    managers = _managers_of(tool)
    for mgr in NO_SUDO_MANAGERS:
        cmd = managers.get(mgr)
        if not (cmd and _manager_available(mgr)):
            continue
        return _run_install(name, mgr, cmd)
    return _manual_hint(tool)


def _run_install(name: str, mgr: str, cmd: str) -> str:
    """Execute CMD and return a one-line success/failure outcome."""
    print(f"  installing {name} via {mgr}: {cmd}", file=sys.stderr)
    try:
        rc = subprocess.call(shlex.split(cmd))
    except (OSError, ValueError) as exc:
        return f"FAILED {name} via {mgr} ({exc}); install manually"
    if rc == 0:
        return f"installed {name} via {mgr}"
    return f"FAILED {name} via {mgr} (rc={rc}); install manually"


def _manual_hint(tool: dict[str, object]) -> str:
    """Build a manual-install hint from the tool's managers."""
    managers = _managers_of(tool)
    is_linux = platform.system() == "Linux"
    pref = "apt" if is_linux else "brew"
    cmd = managers.get(pref) or next(iter(managers.values()), None)
    return f"manual: {cmd}" if cmd else "no install hint"


def get_doctor_data() -> dict[str, Any]:
    """Gathers status, version, and importance information for all external tool dependencies."""
    tools_data = []
    required_missing = False
    for tool in TOOLS:
        path, ver = _detect_tool(tool)
        imp = str(tool["importance"])
        tools_data.append(
            {
                "name": str(tool["name"]),
                "status": "OK" if path else "MISSING",
                "importance": imp,
                "why": str(tool["why"]),
                "version": ver or None,
                "path": path,
                "install_hint": _manual_hint(tool),
            }
        )
        if not path and imp == "required":
            required_missing = True
    return {
        "command": "doctor",
        "platform": platform.system(),
        "machine": platform.machine(),
        "required_missing": required_missing,
        "tools": tools_data,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report external-binary status; optionally install missing ones."""
    data = get_doctor_data()
    print(f"codeq dependency check (platform: {data['platform']} {data['machine']})")
    required_missing = []
    for t in data["tools"]:
        print(
            f"  {t['name']:<12} {t['status']:<8} {t['importance']:<8} {t['version'] or '(no version)'}"
        )
        if t["status"] == "MISSING":
            tool_entry = next(tool for tool in TOOLS if tool["name"] == t["name"])
            if t["importance"] == "required":
                required_missing.append(tool_entry)
            if args.install:
                print(f"  -> {_try_install(tool_entry)}")

    missing_any = [t for t in data["tools"] if t["status"] == "MISSING"]
    if missing_any and not args.install:
        print("\nmissing binaries — install hints:")
        for t in missing_any:
            print(f"  {t['name']:<12} {t['install_hint']}")
        print("\nor run: codeq doctor --install")
    if required_missing and not args.install:
        print(
            "\nrequired binaries missing — some commands will not work until installed.",
            file=sys.stderr,
        )
        return 1
    print("\nall required binaries present.")
    return 0
