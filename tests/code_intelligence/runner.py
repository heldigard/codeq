from __future__ import annotations

import tempfile
from pathlib import Path

from .fixtures import write_fixtures, write_java_fixtures, write_typescript_fixtures
from .helpers import run
from .test_codeq_context import (
    test_codeq_summary_and_context_live,
    test_codeq_summary_and_context_no_llm,
)
from .test_codeq_core import (
    test_codeq,
    test_codeq_class,
    test_codeq_java,
    test_codeq_map,
    test_codeq_modular_layout,
    test_codeq_rdeps,
    test_codeq_version_and_sweep_cap,
)
from .test_codeq_typescript import (
    test_codeq_deps_ts_reexports_and_dynamic,
    test_codeq_refs_ts_filters_method_declaration,
    test_codeq_typescript,
    test_codeq_typescript_after_generic_field,
    test_codeq_typescript_outline_after_partial_ctags_hit,
)
from .test_codeq_vendor import test_codeq_excludes_vendor
from .test_external_tools import (
    test_ast_grep,
    test_ast_grep_java_expression,
    test_ctags,
    test_shellcheck,
)


def main() -> int:
    print("code-intelligence layer smoke test")

    required = ["codeq", "ast-grep", "ctags", "shellcheck"]
    for tool in required:
        run(["which", tool])

    with tempfile.TemporaryDirectory() as tmp:
        fixture_dir = Path(tmp) / "project"
        fixture_dir.mkdir()
        write_fixtures(fixture_dir)
        write_java_fixtures(fixture_dir)
        write_typescript_fixtures(fixture_dir)

        checks = [
            (lambda: test_codeq(fixture_dir), "  codeq (python): OK"),
            (lambda: test_codeq_java(fixture_dir), "  codeq (java): OK"),
            (lambda: test_codeq_class(fixture_dir), "  codeq (class): OK"),
            (lambda: test_codeq_typescript(fixture_dir), "  codeq (typescript): OK"),
            (lambda: test_codeq_typescript_after_generic_field(fixture_dir), "  codeq (typescript after generic-arg field): OK"),
            (lambda: test_codeq_typescript_outline_after_partial_ctags_hit(fixture_dir), "  codeq (typescript mixed ctags/regex outline): OK"),
            (lambda: test_codeq_refs_ts_filters_method_declaration(fixture_dir), "  codeq (refs ts filter method decl): OK"),
            (lambda: test_codeq_deps_ts_reexports_and_dynamic(fixture_dir), "  codeq (deps ts reexports + dynamic + commonjs): OK"),
            (lambda: test_codeq_rdeps(fixture_dir), "  codeq (rdeps python + ts + self-exclusion): OK"),
            (lambda: test_codeq_map(fixture_dir), "  codeq (map ranking + test-exclusion + --save): OK"),
            (test_codeq_version_and_sweep_cap, "  codeq (--version + sweep cap silent): OK"),
            (test_codeq_modular_layout, "  codeq (modular layout): OK"),
            (test_codeq_summary_and_context_no_llm, "  codeq (summary/context/relations --no-llm shape): OK"),
            (test_codeq_summary_and_context_live, "  codeq (summary/context live - skipped if daemon down): OK"),
            (lambda: test_ast_grep(fixture_dir), "  ast-grep (python): OK"),
            (lambda: test_ast_grep_java_expression(fixture_dir), "  ast-grep (java expression): OK"),
            (lambda: test_ctags(fixture_dir), "  ctags (py/java/ts): OK"),
            (test_codeq_excludes_vendor, "  codeq (vendor-exclude find/refs/tags): OK"),
            (test_shellcheck, "  shellcheck: OK"),
        ]
        for check, label in checks:
            check()
            print(label)

    print("\nall code-intelligence checks passed")
    return 0
