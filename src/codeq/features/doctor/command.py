"""`codeq doctor` — detect required/optional external binaries, report what is
missing, and (with --install) install the missing ones via non-sudo managers
when possible (cargo / npm / pipx); print exact manual commands otherwise.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys

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
]

# Managers tried first for `--install` (no root required).
NO_SUDO_MANAGERS = ["cargo", "npm", "pipx"]


def _detect(name: str) -> tuple[str | None, str | None]:
    """Return (path, first-line-of-version) for NAME, or (None, None)."""
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
    rc = subprocess.call(cmd, shell=True)
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


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report external-binary status; optionally install missing ones."""
    print(
        f"codeq dependency check (platform: {platform.system()} {platform.machine()})"
    )
    required_missing: list[dict[str, object]] = []
    # Detect each binary ONCE; reuse the result for the report, the required
    # check, and the missing-summary (a previous version re-ran `_detect` in a
    # list comprehension, spawning `--version` twice per tool).
    detected: list[tuple[dict[str, object], str | None]] = []
    for tool in TOOLS:
        path, ver = _detect(str(tool["name"]))
        detected.append((tool, path))
        status = "OK" if path else "MISSING"
        imp = str(tool["importance"])
        detail = ver or "(no version)"
        print(f"  {str(tool['name']):<12} {status:<8} {imp:<8} {detail}")
        if not path and imp == "required":
            required_missing.append(tool)
        if not path and args.install:
            print(f"  -> {_try_install(tool)}")
    missing_any = [t for (t, path) in detected if not path]
    if missing_any and not args.install:
        print("\nmissing binaries — install hints:")
        for tool in missing_any:
            print(f"  {str(tool['name']):<12} {_manual_hint(tool)}")
        print("\nor run: codeq doctor --install")
    if required_missing:
        print(
            "\nrequired binaries missing — some commands will not work until installed.",
            file=sys.stderr,
        )
        return 1
    print("\nall required binaries present.")
    return 0
