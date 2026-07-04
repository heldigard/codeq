"""Lombok annotation awareness for Java code intelligence.

Detects Lombok annotations on Java classes and infers the methods/constructors
they generate, so codeq can surface them in `outline` and `find`. Returns
structured data marked as `[lombok]` so consumers know these are inferred, not
present in source text.

Limitations:
  - Field extraction is regex-based (not AST) — works for typical Java field
    declarations but may miss exotic patterns (anonymous classes, lambdas).
  - Only infers method SIGNATURES, not bodies (Lombok generates bodies at
    compile time; codeq operates on source text).
  - Does not handle `@Accessor(chain=true, fluent=true)` or `@FieldNameConstants`
    customizations — defaults only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LombokMember:
    """A method/constructor inferred from Lombok annotations."""

    line: int  # line of the annotation (not the generated method)
    kind: str  # "method", "constructor", "field"
    name: str  # method/field name
    signature: str  # e.g. "public String getName()"
    source: str  # annotation that generates it, e.g. "@Getter"


@dataclass
class LombokContext:
    """Bundled context for Lombok inference helpers."""

    class_name: str
    class_line: int
    class_anns: set[str]
    ann_lines: dict[str, int]
    fields: list[tuple[int, str, str]]
    field_anns: dict[str, set[str]]
    text: str


# Lombok annotations that generate methods/constructors.
_CLASS_ANNOTATIONS = {
    "@Data",
    "@Value",
    "@Getter",
    "@Setter",
    "@Builder",
    "@RequiredArgsConstructor",
    "@AllArgsConstructor",
    "@NoArgsConstructor",
    "@ToString",
    "@EqualsAndHashCode",
    "@Slf4j",
    "@Log4j",
    "@Log4j2",
    "@CommonsLog",
    "@Flogger",
    "@JBossLog",
    "@CustomLog",
}

# Annotations that generate loggers.
_LOGGER_ANNOTATIONS = {
    "@Slf4j": (
        "org.slf4j.Logger",
        "org.slf4j.LoggerFactory",
        "LoggerFactory.getLogger({cls}.class)",
    ),
    "@Log4j": (
        "org.apache.log4j.Logger",
        "org.apache.log4j.Logger",
        "Logger.getLogger({cls}.class)",
    ),
    "@Log4j2": (
        "org.apache.logging.log4j.Logger",
        "org.apache.logging.log4j.LogManager",
        "LogManager.getLogger({cls}.class)",
    ),
}

# Field regex: matches `private Type name;` or `private Type name = value;`
# with optional annotations before the field. The leading negative lookahead
# rejects package/import declarations — a single-segment `package x;` would
# otherwise match (type=`package`, name=`x`) and pollute every file.
_FIELD_RE = re.compile(
    r"^(?![ \t]*(?:package|import)\b)"  # NOT a package/import declaration
    r"[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"  # optional annotations
    r"(?:private|protected|public)?\s*"
    r"(?:final\s+)?"
    r"([\w<>\[\],\s?]+?)\s+"  # type (group 1)
    r"(\w+)\s*"  # field name (group 2)
    r"(?:=.*)?;",  # optional initializer
    re.MULTILINE,
)


def _camel_to_pascal(name: str) -> str:
    """Convert field name to PascalCase: myField → MyField."""
    return name[0].upper() + name[1:] if name else name


def _is_static_field(text: str, match: re.Match[str]) -> bool:
    """Check if a field is declared as static.

    Only inspects the declaration portion (after annotations), not the
    annotation prefix — avoids false positives on annotation names that
    contain 'static' (e.g. @StaticFactory).
    """
    full = text[match.start() : match.end()]
    # Skip annotation prefix: anything before the access modifier or type.
    # The declaration starts at the first non-annotation token.
    decl = re.sub(r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*", "", full)
    return re.search(r"\bstatic\b", decl) is not None


def _extract_fields(text: str) -> list[tuple[int, str, str]]:
    """Extract Java fields. Returns [(line, type, name), ...]."""
    fields: list[tuple[int, str, str]] = []
    for m in _FIELD_RE.finditer(text):
        if _is_static_field(text, m):
            continue
        fields.append(
            (text.count("\n", 0, m.start()) + 1, m.group(1).strip(), m.group(2).strip())
        )
    return fields


def _extract_class_annotations(text: str) -> tuple[set[str], dict[str, int]]:
    """Extract class-level Lombok annotations."""
    annotations: set[str] = set()
    annotation_lines: dict[str, int] = {}
    for m in re.finditer(r"@(\w+)(?:\([^)]*\))?", text):
        ann = f"@{m.group(1)}"
        if ann in _CLASS_ANNOTATIONS:
            annotations.add(ann)
            annotation_lines[ann] = text.count("\n", 0, m.start()) + 1
    return annotations, annotation_lines


def _extract_field_annotations(text: str) -> dict[str, set[str]]:
    """Extract per-field Lombok annotations."""
    field_anns: dict[str, set[str]] = {}
    for m in re.finditer(
        r"^[ \t]*((?:@\w+(?:\([^)]*\))?\s+)+)"
        r"(?:private|protected|public)?\s*(?:final\s+)?"
        r"[\w<>\[\],\s?]+?\s+(\w+)\s*(?:=.*)?;",
        text,
        re.MULTILINE,
    ):
        anns = set(re.findall(r"@(\w+)", m.group(1)))
        lombok_anns = {f"@{a}" for a in anns if f"@{a}" in _CLASS_ANNOTATIONS}
        if lombok_anns:
            field_anns[m.group(2)] = lombok_anns
    return field_anns


# String template for _is_final_field — uses re.search (cached by CPython's
# re module) instead of re.compile per call.
_FINAL_FIELD_TPL = (
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:private|protected|public)?\s*final\s+"
    r"[\w<>\[\],\s?]+?\s+{name}\s*(?:=.*)?;"
)


def _is_final_field(text: str, field_name: str) -> bool:
    """Check if a field is declared as final."""
    return (
        re.search(
            _FINAL_FIELD_TPL.format(name=re.escape(field_name)),
            text,
            re.MULTILINE,
        )
        is not None
    )


def _mk(line: int, kind: str, name: str, sig: str, src: str) -> LombokMember:
    """Build a LombokMember positionally. Single-line call sites keep the
    inference loops at nesting ≤ 3 — the multi-line LombokMember(...) calls
    pushed continuation indent past the vertical-slice guard's depth limit."""
    return LombokMember(line, kind, name, sig, src)


def _ann_line(ctx: LombokContext, *keys: str) -> int:
    """First annotation line among KEYS present on the class, else class line.

    Replaces the nested ctx.ann_lines.get(k1, ctx.ann_lines.get(k2, ...))
    chains scattered across the inference helpers (shorter + DRY)."""
    for k in keys:
        if k in ctx.ann_lines:
            return ctx.ann_lines[k]
    return ctx.class_line


# Fixed Lombok-generated signatures (kept as constants so _mk call sites stay
# single-line and under the line-length limit).
_EQ_SIG = "public boolean equals(Object o)"
_HC_SIG = "public int hashCode()"
_TS_SIG = "public String toString()"


def _infer_getters(ctx: LombokContext) -> list[LombokMember]:
    """Infer getter methods from @Getter or @Data/@Value.

    Primitive boolean → isFoo(); every other type (incl. Boolean wrapper) →
    getFoo(). Lombok generates isX only for the primitive boolean, never the
    Boolean wrapper — emitting both was a false positive that misled callers
    into navigating a method absent from the compiled class."""
    has_class = (
        "@Getter" in ctx.class_anns
        or "@Data" in ctx.class_anns
        or "@Value" in ctx.class_anns
    )
    members: list[LombokMember] = []
    for line, ftype, fname in ctx.fields:
        has_field = "@Getter" in ctx.field_anns.get(fname, set())
        if not (has_class or has_field):
            continue
        prefix = "is" if ftype == "boolean" else "get"
        getter = f"{prefix}{_camel_to_pascal(fname)}"
        ann = _ann_line(ctx, "@Getter", "@Data", "@Value") if has_class else line
        src = "@Getter" if has_field else "@Data"
        sig = f"public {ftype} {getter}()"
        members.append(_mk(ann, "method", getter, sig, src))
    return members


def _infer_setters(ctx: LombokContext) -> list[LombokMember]:
    """Infer setter methods from @Setter or @Data (skipping final fields)."""
    has_class = "@Setter" in ctx.class_anns or (
        "@Data" in ctx.class_anns and "@Value" not in ctx.class_anns
    )
    members: list[LombokMember] = []
    for line, ftype, fname in ctx.fields:
        if _is_final_field(ctx.text, fname):
            continue
        has_field = "@Setter" in ctx.field_anns.get(fname, set())
        if not (has_class or has_field):
            continue
        setter = f"set{_camel_to_pascal(fname)}"
        ann = _ann_line(ctx, "@Setter", "@Data") if has_class else line
        sig = f"public void {setter}({ftype} {fname})"
        src = "@Setter" if has_field else "@Data"
        members.append(_mk(ann, "method", setter, sig, src))
    return members


def _final_fields(ctx: LombokContext) -> list[tuple[str, str]]:
    return [(t, n) for _, t, n in ctx.fields if _is_final_field(ctx.text, n)]


def _infer_constructors(ctx: LombokContext) -> list[LombokMember]:
    """Infer constructors from @RequiredArgsConstructor / @AllArgsConstructor /
    @NoArgsConstructor / @Data."""
    members: list[LombokMember] = []
    cls = ctx.class_name
    if "@RequiredArgsConstructor" in ctx.class_anns or "@Data" in ctx.class_anns:
        required = _final_fields(ctx)
        if required:
            params = ", ".join(f"{t} {n}" for t, n in required)
            ann = _ann_line(ctx, "@RequiredArgsConstructor", "@Data")
            sig = f"public {cls}({params})"
            mem = _mk(ann, "constructor", cls, sig, "@RequiredArgsConstructor")
            members.append(mem)
    if "@AllArgsConstructor" in ctx.class_anns:
        params = ", ".join(f"{t} {n}" for _, t, n in ctx.fields)
        ann = _ann_line(ctx, "@AllArgsConstructor")
        sig = f"public {cls}({params})"
        members.append(_mk(ann, "constructor", cls, sig, "@AllArgsConstructor"))
    if "@NoArgsConstructor" in ctx.class_anns:
        ann = _ann_line(ctx, "@NoArgsConstructor")
        sig = f"public {cls}()"
        members.append(_mk(ann, "constructor", cls, sig, "@NoArgsConstructor"))
    return members


def _infer_extras(ctx: LombokContext) -> list[LombokMember]:
    """Infer equals/hashCode/toString/builder/logger from class annotations."""
    members: list[LombokMember] = []
    cls = ctx.class_name
    if "@Data" in ctx.class_anns or "@EqualsAndHashCode" in ctx.class_anns:
        ann = _ann_line(ctx, "@Data", "@EqualsAndHashCode")
        members.append(_mk(ann, "method", "equals", _EQ_SIG, "@Data"))
        members.append(_mk(ann, "method", "hashCode", _HC_SIG, "@Data"))
    if "@Data" in ctx.class_anns or "@ToString" in ctx.class_anns:
        ann = _ann_line(ctx, "@Data", "@ToString")
        members.append(_mk(ann, "method", "toString", _TS_SIG, "@Data"))
    if "@Builder" in ctx.class_anns:
        ann = _ann_line(ctx, "@Builder")
        sig = f"public static {cls}.Builder builder()"
        members.append(_mk(ann, "method", "builder", sig, "@Builder"))
    # Logger: at most one per class (break after the first matching annotation).
    for ann_key, (logger_type, _, factory_call) in _LOGGER_ANNOTATIONS.items():
        if ann_key in ctx.class_anns:
            ann = _ann_line(ctx, ann_key)
            init = factory_call.format(cls=cls)
            sig = f"private static final {logger_type} log = {init}"
            members.append(_mk(ann, "field", "log", sig, ann_key))
            break
    return members


def detect_lombok_members(file: str) -> list[LombokMember]:
    """Scan a Java file and return Lombok-inferred members (methods/constructors
    that Lombok would generate at compile time). Each member is annotated with
    the source annotation and the line where the annotation appears."""
    try:
        text = Path(file).read_text(errors="replace")
    except OSError:
        return []
    class_match = re.search(r"\bclass\s+(\w+)", text)
    if not class_match:
        return []
    class_anns, ann_lines = _extract_class_annotations(text)
    ctx = LombokContext(
        class_name=class_match.group(1),
        class_line=text.count("\n", 0, class_match.start()) + 1,
        class_anns=class_anns,
        ann_lines=ann_lines,
        fields=_extract_fields(text),
        field_anns=_extract_field_annotations(text),
        text=text,
    )
    members: list[LombokMember] = []
    members.extend(_infer_getters(ctx))
    members.extend(_infer_setters(ctx))
    members.extend(_infer_constructors(ctx))
    members.extend(_infer_extras(ctx))
    return members
