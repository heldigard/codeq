from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codeq.shared.config import TYPE_KINDS
from codeq.shared.core import die, lang_of
from codeq.shared.extraction import _class_body, _raw_body, _sig_from_raw
from codeq.shared.locators import _locate_line
from codeq.shared.llm import _maybe_emit_summary


def cmd_class(args: argparse.Namespace) -> int:
    """Full class/type body (all members), distinct from `body` which targets a
    single method. Fixes the Java case where `body <Class>` returned only the
    constructor (ctags lists the constructor before the class)."""
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    raw = _class_body(args.file, args.name, lang)
    if raw:
        if args.summary:
            _maybe_emit_summary(args.file, args.name, raw, no_llm=args.no_llm)
        print(raw)
        return 0
    ln = _locate_line(args.file, args.name, kinds=TYPE_KINDS)
    if ln:
        print(f"{args.file}:{ln}")
        print(
            f"(no exact class-body extractor for {lang}; "
            f"try: codeq outline {args.file} to list members, "
            f"or codeq body <member> {args.file} for a specific method)",
            file=sys.stderr,
        )
        return 0
    print(f"no class/type '{args.name}' in {args.file} (lang={lang})", file=sys.stderr)
    return 1


def cmd_body(args: argparse.Namespace) -> int:
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw:
        if args.summary:
            _maybe_emit_summary(args.file, args.name, raw, no_llm=args.no_llm)
        print(raw)
        return 0
    ln = _locate_line(args.file, args.name)
    if ln:
        print(f"{args.file}:{ln}")
        print(
            f"(no exact body extractor for {lang}; "
            f"try: codeq outline {args.file} to list symbols, "
            f"or codeq sig {args.name} {args.file} for the signature only)",
            file=sys.stderr,
        )
        return 0
    print(f"no def/class '{args.name}' in {args.file} (lang={lang})", file=sys.stderr)
    return 1


def cmd_sig(args: argparse.Namespace) -> int:
    """Signature only (header line(s)); cheaper than body."""
    if not Path(args.file).is_file():
        die(f"no such file: {args.file}")
    lang = lang_of(args.file, args.lang)
    raw = _raw_body(args.file, args.name, lang)
    if raw:
        print(_sig_from_raw(raw, lang))
        return 0
    print(f"no def/class '{args.name}' in {args.file} (lang={lang})", file=sys.stderr)
    return 1
