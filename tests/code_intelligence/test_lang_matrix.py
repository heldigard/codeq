"""Lang-matrix parity — every EXT_LANG language must appear in the tables
that feature code relies on. Prevents regressions like `check -l bash`
dying with "no probe for lang" while refs already supported bash.

When adding a language: update EXT_LANG, then make this test green.
"""

from __future__ import annotations

from codeq.shared.config import (
    BODY_PATTERNS,
    EXT_LANG,
    LANG_INCLUDES,
    LANG_RDEPS_INCLUDES,
    PROBE,
    RENAME_LANGS,
    STRUCTURAL_LANGS,
    SUPPORTED_LANGS,
)


def test_supported_langs_matches_ext_lang_values() -> None:
    assert SUPPORTED_LANGS == frozenset(EXT_LANG.values())


def test_lang_includes_cover_every_supported_lang() -> None:
    missing = SUPPORTED_LANGS - set(LANG_INCLUDES)
    assert not missing, f"LANG_INCLUDES missing langs: {sorted(missing)}"


def test_rdeps_includes_cover_every_supported_lang() -> None:
    missing = SUPPORTED_LANGS - set(LANG_RDEPS_INCLUDES)
    assert not missing, f"LANG_RDEPS_INCLUDES missing langs: {sorted(missing)}"


def test_probe_covers_every_supported_lang() -> None:
    """`codeq check -l <lang>` needs a PROBE entry for every supported lang."""
    missing = SUPPORTED_LANGS - set(PROBE)
    assert not missing, f"PROBE missing langs (check will die): {sorted(missing)}"


def test_structural_and_rename_langs_are_body_pattern_subset() -> None:
    """body/rename need BODY_PATTERNS; bash is intentionally refs/check-only."""
    assert STRUCTURAL_LANGS == RENAME_LANGS
    missing_body = STRUCTURAL_LANGS - set(BODY_PATTERNS)
    assert not missing_body, (
        f"BODY_PATTERNS missing structural langs: {sorted(missing_body)}"
    )
    # bash stays out of structural tables by design
    assert "bash" not in STRUCTURAL_LANGS
    assert "bash" in SUPPORTED_LANGS
    assert "bash" in PROBE
    assert "bash" in LANG_INCLUDES


def test_js_ts_rdeps_search_both_families() -> None:
    """Mixed JS/TS projects: rdeps must see importers across the boundary."""
    js = set(LANG_RDEPS_INCLUDES["javascript"])
    ts = set(LANG_RDEPS_INCLUDES["typescript"])
    assert "--include=*.ts" in js
    assert "--include=*.js" in ts
    # refs stays exact-lang (no cross-bleed)
    assert "--include=*.ts" not in LANG_INCLUDES["javascript"]
    assert "--include=*.js" not in LANG_INCLUDES["typescript"]
