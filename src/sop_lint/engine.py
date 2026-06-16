# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SOP lint engine — rule-based static analysis for Agent SOP markdown.

Implements the SOP format specification as a set of rule classes,
inspired by ruff's ergonomics: stable codes, configurable severity,
``select`` / ``ignore`` semantics via a ``sop-lint.toml`` config file.

Rule families:

- ``SOP1xx`` — document structure (title, Overview, Parameters, Steps, …)
- ``SOP2xx`` — per-step content (description, Constraints, RFC 2119 keywords, …)
- ``SOP3xx`` — style (allowed top-level sections, named anti-patterns, …)
- ``SOPMCP0xx`` — sop-mcp strict extras (YAML frontmatter). Enable via
  ``select = ["SOP", "SOPMCP"]``.

The engine is deliberately stdlib-plus-PyYAML (TOML parsing uses the
stdlib ``tomllib``, which requires Python 3.11+) so the CLI and the
``sop_mcp`` publish path can share the exact same rule set without heavy
dependencies.
"""

from __future__ import annotations

import logging
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import yaml

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "sop-lint.toml"
SOP_FILE_SUFFIX = ".sop.md"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class Severity(StrEnum):
    """Severity levels, ordered least to most severe."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Diagnostic:
    """A single lint finding — where it is, what's wrong, how bad it is."""

    code: str
    severity: Severity
    line: int  # 1-based; 0 means whole-document
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "line": self.line,
            "message": self.message,
        }
        if self.suggestion:
            data["suggestion"] = self.suggestion
        return data


# ---------------------------------------------------------------------------
# Parsed document model — what every rule receives
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
# Step heading: "### 1. Name" — matches the Agent SOP format spec.
_STEP_HEADING_RE = re.compile(r"^(###\s+(\d+)\.\s+(.+))$", re.MULTILINE)
_TOP_LEVEL_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_CONSTRAINTS_MARKER = "**Constraints:**"
_RFC2119_POSITIVE = (
    "MUST NOT",
    "SHOULD NOT",
    "SHALL NOT",
    "MUST",
    "SHALL",
    "SHOULD",
    "MAY",
    "NEVER",
    "REQUIRED",
    "RECOMMENDED",
    "OPTIONAL",
    "NOT RECOMMENDED",
)
_RFC2119_NEGATIVE = ("MUST NOT", "SHOULD NOT", "SHALL NOT", "NEVER", "NOT RECOMMENDED")
# Phrases that qualify as providing context on a negative constraint.
# Matched case-insensitively; order doesn't matter.
_NEGATIVE_CONTEXT_MARKERS = ("because", "since", "due to", "to avoid", " as ")

# Top-level ``## Section`` headings permitted by the SOP spec.
# The spec requires Overview, Parameters, and Steps; Examples,
# Troubleshooting, and Desired Outcome are seen in real spec-compliant
# SOPs and are therefore allowed without warning.
_ALLOWED_TOP_LEVEL_SECTIONS = frozenset(
    {"Overview", "Parameters", "Steps", "Examples", "Troubleshooting", "Desired Outcome", "References"}
)

# Sections with specific anti-pattern messaging. Each entry pairs a
# regex (matched case-insensitively against the heading text) with a
# reason. SOP302 fires these ahead of SOP301's generic "unknown
# section" warning so the author gets actionable advice.
_DISALLOWED_NAMED_SECTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^appendix\b", re.IGNORECASE),
        "Operational content belongs in a step; reference procedures belong in their own SOP.",
    ),
    (
        re.compile(r"^(definitions|glossary|terms)$", re.IGNORECASE),
        "Explain terms inline where they're first used rather than maintaining a separate glossary.",
    ),
    (
        re.compile(r"^(revision history|changelog)$", re.IGNORECASE),
        "Use git history instead of an in-document changelog.",
    ),
    (
        re.compile(r"^contact$", re.IGNORECASE),
        "Drop the Contact section — the owner (frontmatter or repository ownership) is the canonical pointer.",
    ),
    (
        re.compile(r"^tool reference$", re.IGNORECASE),
        "Name tools inline in the step that uses them rather than collecting them separately.",
    ),
    (
        re.compile(r"^roles and responsibilities$", re.IGNORECASE),
        "Agent SOPs are written for one executor; role tables are redundant.",
    ),
    (
        re.compile(r"^procedure$", re.IGNORECASE),
        "Use `## Steps` instead — `## Procedure` is not the Agent SOP convention.",
    ),
    (
        re.compile(r"^scope$", re.IGNORECASE),
        "Fold into `## Overview` as a short sentence.",
    ),
    (
        re.compile(r"^prerequisites$", re.IGNORECASE),
        "Fold into `## Overview` or into Step 1 as preconditions.",
    ),
)


@dataclass
class Step:
    """A single ``### N. Name`` block parsed out of the body."""

    number: int
    name: str  # the text after "N. "
    heading: str  # full heading line without the leading ###
    body: str  # everything between this heading and the next (or end)
    line: int  # 1-based line of the heading


@dataclass
class SopDocument:
    """Everything rules need to inspect a SOP, parsed once."""

    raw: str
    path: Path | None  # None when linting content without a file (e.g. stdin)
    frontmatter: dict[str, Any]
    frontmatter_error: str | None  # non-None when YAML parsing failed
    body: str
    body_line_offset: int  # line number (1-based) where body starts
    title: str | None
    overview: str | None
    parameters: str | None
    steps: list[Step]
    top_level_sections: list[tuple[str, int]]  # (heading text, 1-based line)

    @classmethod
    def parse(cls, raw: str, path: Path | None = None) -> SopDocument:
        """Parse a raw SOP string into the structured model rules consume.

        Deliberately forgiving: malformed frontmatter, missing sections,
        absent steps all produce ``None``/empty fields rather than
        raising, because the rules are what decide whether those
        absences are reportable.
        """
        frontmatter, frontmatter_error, body, body_line_offset = _split_frontmatter(raw)
        title = _extract_title(body)
        overview = _extract_section(body, "Overview")
        parameters = _extract_section(body, "Parameters")
        steps = _extract_steps(body, body_line_offset)
        top_level_sections = _extract_top_level_sections(body, body_line_offset)
        return cls(
            raw=raw,
            path=path,
            frontmatter=frontmatter,
            frontmatter_error=frontmatter_error,
            body=body,
            body_line_offset=body_line_offset,
            title=title,
            overview=overview,
            parameters=parameters,
            steps=steps,
            top_level_sections=top_level_sections,
        )


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str | None, str, int]:
    """Return ``(frontmatter, yaml_error, body, body_line_offset)``.

    When no frontmatter is present (the Agent SOP spec doesn't require
    it), ``frontmatter`` is empty and ``yaml_error`` is ``None`` — the
    body starts at line 1. Frontmatter is only a requirement of the
    ``SOPMCP`` extras.
    """
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, None, raw, 1

    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        return {}, str(exc), raw[m.end() :], raw[: m.end()].count("\n") + 1

    if not isinstance(meta, dict):
        return {}, "YAML frontmatter must be a mapping", raw[m.end() :], raw[: m.end()].count("\n") + 1

    body = raw[m.end() :]
    body_line_offset = raw[: m.end()].count("\n") + 1
    return meta, None, body, body_line_offset


def _extract_title(body: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def _extract_section(body: str, section: str) -> str | None:
    """Extract the text of a ``## Section`` block.

    Stops at the next same-or-higher-level heading (``#`` / ``##``) or
    any ``### N.`` step heading. Sub-sections (``### foo`` directly
    under the section, other than steps) are kept intact so SOP108's
    structure check can still see them.
    """
    pattern = rf"^##\s+{re.escape(section)}\s*\n(.*?)(?=^#{{1,2}}\s|^###\s+\d+\.\s|\Z)"
    m = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_steps(body: str, body_line_offset: int) -> list[Step]:
    matches = list(_STEP_HEADING_RE.finditer(body))
    if not matches:
        return []

    steps: list[Step] = []
    for i, match in enumerate(matches):
        number = int(match.group(2))
        name = match.group(3).strip()
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        step_body = body[start:end].strip()
        line = body[: match.start()].count("\n") + body_line_offset
        steps.append(Step(number=number, name=name, heading=heading, body=step_body, line=line))
    return steps


def _extract_top_level_sections(body: str, body_line_offset: int) -> list[tuple[str, int]]:
    sections: list[tuple[str, int]] = []
    for m in _TOP_LEVEL_HEADING_RE.finditer(body):
        line = body[: m.start()].count("\n") + body_line_offset
        sections.append((m.group(1).strip(), line))
    return sections


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class Rule(Protocol):
    """Every lint rule implements this shape."""

    code: str
    default_severity: Severity

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]: ...


def _contains_rfc2119(text: str, keywords: tuple[str, ...] = _RFC2119_POSITIVE) -> bool:
    """True if any RFC 2119 keyword appears in ``text`` as a bounded word.

    Case-sensitive — lowercase ``must`` is just prose, not a requirement.
    Multi-word keywords (``MUST NOT``) are tested against the exact
    substring because the surrounding whitespace already acts as a
    boundary.
    """
    return any(kw in text for kw in keywords)


def _contains_negative_rfc2119(text: str) -> bool:
    return any(kw in text for kw in _RFC2119_NEGATIVE)


def _has_context_marker(text: str) -> bool:
    """True if text contains a word indicating context for a negative constraint."""
    lowered = text.lower()
    return any(marker in lowered for marker in _NEGATIVE_CONTEXT_MARKERS)


def _extract_constraints_block(step_body: str) -> tuple[str, int] | None:
    """Return ``(block_text, line_offset)`` for the step's Constraints block.

    ``line_offset`` is 0-based relative to the start of ``step_body`` and
    points at the first bullet line after the ``**Constraints:**``
    marker. Returns ``None`` if the marker is absent.
    """
    idx = step_body.find(_CONSTRAINTS_MARKER)
    if idx < 0:
        return None
    # Find the end of the Constraints heading line and walk forward to
    # collect contiguous bullet lines.
    after = step_body[idx + len(_CONSTRAINTS_MARKER) :]
    # Drop the newline that ends the heading line.
    after = after.removeprefix("\n")
    line_offset = step_body[: idx + len(_CONSTRAINTS_MARKER) + 1].count("\n")
    lines = after.splitlines()
    block_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "":
            block_lines.append(line)
            continue
        if stripped.startswith(("-", "  ", "\t")):
            block_lines.append(line)
            continue
        # First non-bullet, non-indented line ends the block.
        break
    return "\n".join(block_lines), line_offset


def _iter_constraint_bullets(block_text: str, block_line_offset: int) -> Iterable[tuple[int, str]]:
    """Yield ``(relative_line, bullet_text)`` for each top-level bullet.

    Continuation lines (indented under a bullet) are folded into the
    preceding bullet's text so rules that look for keywords in a
    multi-line constraint still match.
    """
    lines = block_text.splitlines()
    current_start: int | None = None
    current_parts: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("-"):
            # Flush the previous bullet.
            if current_start is not None:
                yield block_line_offset + current_start, " ".join(current_parts).strip()
            current_start = i
            current_parts = [stripped.lstrip("-").strip()]
        elif stripped and current_start is not None:
            current_parts.append(stripped)
        # empty lines between bullets are harmless
    if current_start is not None:
        yield block_line_offset + current_start, " ".join(current_parts).strip()


# --- SOP1xx: document structure --------------------------------------------


class DocumentHasTitle:
    """SOP101 — document has a level-1 title."""

    code = "SOP101"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if not doc.title:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=doc.body_line_offset,
                message="Missing level-1 title (expected `# SOP Name` as the first heading).",
            )


class DocumentHasOverview:
    """SOP102 — document has a ``## Overview`` section."""

    code = "SOP102"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if doc.overview is None:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=doc.body_line_offset,
                message="Missing `## Overview` section.",
                suggestion="Add a concise description of what the SOP does and when to use it.",
            )


class DocumentHasParameters:
    """SOP103 — document has a ``## Parameters`` section.

    Required by the Agent SOP spec. Parameterised inputs are the spec's
    mechanism for flexible reuse across contexts.
    """

    code = "SOP103"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if doc.parameters is None:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=doc.body_line_offset,
                message="Missing `## Parameters` section.",
                suggestion=(
                    "Add a `## Parameters` section listing required and optional inputs. "
                    "If the SOP genuinely has no inputs, write `_(none)_` under the heading."
                ),
            )


class DocumentHasSteps:
    """SOP104 — document has at least one ``### N. Name`` step."""

    code = "SOP104"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if not doc.steps:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=doc.body_line_offset,
                message="SOP has no steps — expected at least one `### N. Step Name` heading under `## Steps`.",
            )


class StepsAreSequential:
    """SOP105 — steps are numbered 1, 2, 3, … without gaps."""

    code = "SOP105"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if not doc.steps:
            return
        expected = list(range(1, len(doc.steps) + 1))
        actual = [s.number for s in doc.steps]
        if actual != expected:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=doc.steps[0].line,
                message=f"Steps are not sequential: found {actual}, expected {expected}.",
            )


class FileHasSopMdExtension:
    """SOP106 — file name ends in ``.sop.md``.

    The spec requires this for clear identification. When linting
    content without a file (e.g. from stdin) the rule is a no-op.
    """

    code = "SOP106"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if doc.path is None:
            return
        if not doc.path.name.endswith(SOP_FILE_SUFFIX):
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message=f"File name {doc.path.name!r} does not end in `{SOP_FILE_SUFFIX}`.",
            )


class ParameterSchema:
    """SOP109 — parameters under ``## Parameters`` follow the spec schema.

    The Agent SOP format specification defines parameter lines as::

        - **name** (required): description
        - **name** (optional): description
        - **name** (optional, default: value): description

    This rule fires once per malformed bullet with a message listing
    every aspect of the schema the bullet violates (missing snake_case
    name, missing required/optional tag, missing description, etc.).
    Fires only when ``## Parameters`` has at least one bullet; an empty
    or absent Parameters section is handled by SOP103.

    Merged what used to be SOP107's snake_case name check so authors
    see one holistic parameter-schema message instead of two separate
    warnings for the same bullet.
    """

    code = "SOP109"
    default_severity = Severity.WARNING

    _bullet_pattern = re.compile(r"^\s*-\s+(.+)$", re.MULTILINE)
    _full_pattern = re.compile(
        r"^\*\*(?P<name>[^*]+)\*\*\s*"
        r"\((?P<kind>required|optional)(?:\s*,\s*default:\s*[^)]+)?\)"
        r"\s*:\s*(?P<description>\S.*)$"
    )
    _name_only_pattern = re.compile(r"^\*\*(?P<name>[^*]+)\*\*")
    _snake_case_pattern = re.compile(r"^[a-z][a-z0-9_]*$")

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if doc.parameters is None:
            return
        section_line = next(
            (line for heading, line in doc.top_level_sections if heading == "Parameters"),
            doc.body_line_offset,
        )
        for bullet_match in self._bullet_pattern.finditer(doc.parameters):
            bullet = bullet_match.group(1).strip()
            rel_line = doc.parameters[: bullet_match.start()].count("\n")
            # +1 because section_line is the `## Parameters` heading
            # itself; bullets live on subsequent lines.
            line = section_line + rel_line + 1

            problems = self._classify(bullet)
            if problems:
                preview = bullet if len(bullet) <= 80 else bullet[:77] + "..."
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=line,
                    message=(
                        f"Parameter `- {preview}` does not follow the schema "
                        f"`- **name** (required|optional[, default: value]): description`. "
                        f"Issues: {', '.join(problems)}."
                    ),
                )

    def _classify(self, bullet: str) -> list[str]:
        """Return a list of human-readable problem descriptions."""
        if self._full_pattern.match(bullet):
            name = self._full_pattern.match(bullet).group("name").strip()
            if not self._snake_case_pattern.match(name):
                return [f"name `{name}` is not snake_case"]
            return []

        problems: list[str] = []

        # Name present and snake_case?
        name_match = self._name_only_pattern.match(bullet)
        if not name_match:
            problems.append("missing `**name**` prefix")
        else:
            name = name_match.group("name").strip()
            if not self._snake_case_pattern.match(name):
                problems.append(f"name `{name}` is not snake_case")

        # (required) / (optional) tag present?
        if not re.search(r"\((?:required|optional)(?:\s*,\s*default:\s*[^)]+)?\)", bullet):
            problems.append("missing `(required)` or `(optional)` tag")

        # Description after colon?
        colon_idx = bullet.find(":")
        if colon_idx < 0:
            problems.append("missing `: description` after the tag")
        else:
            desc = bullet[colon_idx + 1 :].strip()
            if not desc:
                problems.append("description after `:` is empty")

        return problems or ["does not match the canonical parameter syntax"]


class OverviewIsSimple:
    """SOP108 — Overview is a plain-text summary, ≤500 chars, no structure.

    The Overview is the primary signal an agent uses when deciding
    whether the SOP applies to the current task. Long or structured
    overviews push that decision cost onto the agent and waste tokens.
    Cap at 500 characters and forbid lists, tables, code blocks, and
    sub-sections so the Overview stays a skimmable one-paragraph
    summary.
    """

    code = "SOP108"
    default_severity = Severity.WARNING
    MAX_CHARS = 500

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if doc.overview is None:
            return

        overview_line = self._overview_heading_line(doc)

        length = len(doc.overview)
        if length > self.MAX_CHARS:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=overview_line,
                message=(
                    f"Overview is {length} characters (max {self.MAX_CHARS}). Keep it to a short, skimmable summary."
                ),
            )

        raw_overview = self._raw_overview_region(doc)

        has_subsection = any(line.lstrip().startswith("### ") for line in raw_overview.splitlines())
        has_list = any(
            line.lstrip().startswith(("- ", "* ")) or re.match(r"^\s*\d+\.\s", line)
            for line in raw_overview.splitlines()
        )
        has_table = any("|" in line and line.count("|") >= 2 for line in raw_overview.splitlines())
        has_code = "```" in raw_overview

        problems: list[str] = []
        if has_subsection:
            problems.append("`### sub-sections`")
        if has_list:
            problems.append("lists")
        if has_table:
            problems.append("tables")
        if has_code:
            problems.append("code blocks")

        if problems:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=overview_line,
                message=(
                    f"Overview contains {', '.join(problems)}. "
                    "Keep it to plain prose — structured content belongs in a step."
                ),
            )

    @staticmethod
    def _overview_heading_line(doc: SopDocument) -> int:
        for heading, line in doc.top_level_sections:
            if heading == "Overview":
                return line
        return doc.body_line_offset

    @staticmethod
    def _raw_overview_region(doc: SopDocument) -> str:
        m = re.search(r"^##\s+Overview\s*\n", doc.body, re.MULTILINE)
        if not m:
            return ""
        start = m.end()
        tail = doc.body[start:]
        end = len(tail)
        # Stop at the next top-level section or any step heading.
        for line_match in re.finditer(r"^(##\s|###\s+\d+\.\s)", tail, re.MULTILINE):
            end = line_match.start()
            break
        return tail[:end]


# --- SOP2xx: per-step content -----------------------------------------------


class StepHasDescription:
    """SOP201 — step has a description paragraph before ``**Constraints:**``.

    A step without prose is just a bag of tags: the Constraints list a
    set of MUST / SHOULD requirements but never explains *what* the
    step is for. The description is the "what needs to be done"; the
    Constraints are the "hard facts" for how it must happen.
    """

    code = "SOP201"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for step in doc.steps:
            pre_constraints = step.body.split(_CONSTRAINTS_MARKER, 1)[0].strip()
            if not pre_constraints:
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=step.line,
                    message=(
                        f"Step {step.number} ({step.name!r}) has no description. "
                        "Add a paragraph before `**Constraints:**` explaining what the step accomplishes."
                    ),
                )


class StepHasConstraints:
    """SOP202 — each step has a ``**Constraints:**`` block."""

    code = "SOP202"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for step in doc.steps:
            if _CONSTRAINTS_MARKER not in step.body:
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=step.line,
                    message=(
                        f"Step {step.number} ({step.name!r}) has no `**Constraints:**` block. "
                        "List the MUST / SHOULD / MAY requirements below the description."
                    ),
                )


class ConstraintsUseRFC2119:
    """SOP203 — every constraint bullet contains an RFC 2119 keyword."""

    code = "SOP203"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for step in doc.steps:
            block = _extract_constraints_block(step.body)
            if block is None:
                continue  # SOP202 will report the missing block
            block_text, block_line_offset = block
            for rel_line, bullet in _iter_constraint_bullets(block_text, block_line_offset):
                if not bullet:
                    continue
                if not _contains_rfc2119(bullet):
                    yield Diagnostic(
                        code=self.code,
                        severity=self.default_severity,
                        line=step.line + rel_line,
                        message=(
                            f"Step {step.number}: constraint bullet `- {bullet[:60]}{'…' if len(bullet) > 60 else ''}` "
                            "does not contain an RFC 2119 keyword. "
                            "Use MUST / MUST NOT / SHOULD / SHOULD NOT / MAY (all caps)."
                        ),
                    )


class NegativeConstraintsHaveContext:
    """SOP204 — negative constraints include an explanatory context clause.

    The Agent SOP spec requires that every ``MUST NOT`` / ``SHOULD NOT``
    / ``SHALL NOT`` / ``NEVER`` bullet explain *why*: "you MUST provide
    context explaining why the restriction exists". We look for context
    markers like ``because``, ``since``, ``as``, ``due to``, or
    ``to avoid`` in the bullet text.
    """

    code = "SOP204"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for step in doc.steps:
            block = _extract_constraints_block(step.body)
            if block is None:
                continue
            block_text, block_line_offset = block
            for rel_line, bullet in _iter_constraint_bullets(block_text, block_line_offset):
                if not bullet:
                    continue
                if _contains_negative_rfc2119(bullet) and not _has_context_marker(bullet):
                    yield Diagnostic(
                        code=self.code,
                        severity=self.default_severity,
                        line=step.line + rel_line,
                        message=(
                            f"Step {step.number}: negative constraint `- {bullet[:60]}{'…' if len(bullet) > 60 else ''}` "
                            "has no context. "
                            "Explain why — end with `because …`, `since …`, `as …`, `due to …`, or `to avoid …`."
                        ),
                    )


class StepHasTimeEstimate:
    """SOP205 — step has a ``**Time Estimate:**`` marker (recommended, warning-level).

    A time estimate is planning metadata, not a structural requirement —
    a step without one still executes fine. So this is a SHOULD, and the
    rule fires at ``warning`` severity: it nudges authors toward
    estimating each step's duration without blocking publish the way the
    structural errors (description, constraints, expected output) do.

    Previously this lived as a hand-rolled check inside ``publish_sop``,
    which meant ``lint_sop`` and the ``sop-lint`` CLI silently disagreed
    with the publish path. Moving it into the engine keeps every entry
    point — CLI, ``lint_sop``, and ``publish_sop`` — on the same rule set.
    """

    code = "SOP205"
    default_severity = Severity.WARNING

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for step in doc.steps:
            if "**Time Estimate:**" not in step.body:
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=step.line,
                    message=(
                        f"Step {step.number} ({step.name!r}) has no `**Time Estimate:**` marker. "
                        "Each step SHOULD include an estimated duration so the executor can plan."
                    ),
                )


class StepHasExamples:
    """SOP206 — step has ``**Example Input:**`` and ``**Example Output:**`` (optional, info-level).

    The Agent SOP spec puts Examples at the SOP level under ``##
    Examples``. For this project we additionally nudge authors toward
    per-step Example Input / Example Output markers — they're not
    required by the spec, so this rule fires at ``info`` severity and
    never blocks CI.
    """

    code = "SOP206"
    default_severity = Severity.INFO

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for step in doc.steps:
            missing: list[str] = []
            if "**Example Input:**" not in step.body:
                missing.append("**Example Input:**")
            if "**Example Output:**" not in step.body:
                missing.append("**Example Output:**")
            if missing:
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=step.line,
                    message=(
                        f"Step {step.number}: consider adding {' / '.join(missing)}. "
                        "Example blocks help readers verify they understand the step's contract."
                    ),
                )


# --- SOP3xx: style ----------------------------------------------------------


class AllowedTopLevelSections:
    """SOP301 — top-level ``##`` headings come from the spec allowlist."""

    code = "SOP301"
    default_severity = Severity.WARNING

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for heading, line in doc.top_level_sections:
            if heading in _ALLOWED_TOP_LEVEL_SECTIONS:
                continue
            # Defer to SOP302 if a named anti-pattern matches.
            if any(pattern.match(heading) for pattern, _ in _DISALLOWED_NAMED_SECTIONS):
                continue
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=line,
                message=(
                    f"`## {heading}` is not a recognised Agent SOP section. "
                    f"Allowed top-level sections: {sorted(_ALLOWED_TOP_LEVEL_SECTIONS)}. "
                    "Consider folding into `## Overview` or a step."
                ),
            )


class DisallowedNamedSections:
    """SOP302 — specific anti-pattern sections with targeted messaging."""

    code = "SOP302"
    default_severity = Severity.WARNING

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for heading, line in doc.top_level_sections:
            for pattern, reason in _DISALLOWED_NAMED_SECTIONS:
                if pattern.match(heading):
                    yield Diagnostic(
                        code=self.code,
                        severity=self.default_severity,
                        line=line,
                        message=f"`## {heading}` doesn't belong in an Agent SOP. {reason}",
                    )
                    break


class FileNameIsKebabCase:
    """SOP303 — file stem uses kebab-case (spec SHOULD)."""

    code = "SOP303"
    default_severity = Severity.INFO
    _kebab_pattern = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if doc.path is None:
            return
        name = doc.path.name
        if not name.endswith(SOP_FILE_SUFFIX):
            return  # SOP106 handles this
        stem = name[: -len(SOP_FILE_SUFFIX)]
        if not self._kebab_pattern.match(stem):
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message=(
                    f"File stem {stem!r} is not kebab-case. "
                    "The spec SHOULDs kebab-case filenames like `idea-honing.sop.md`."
                ),
            )


class ReferencesAreLinks:
    """SOP304 — every entry in ``## References`` must be a Markdown link.

    A ``## References`` section is optional, but when present every
    non-blank content line must be a bullet whose sole content is a
    Markdown link: ``- [text](url)``.  Plain text, bare URLs, and
    non-bullet lines are all rejected so the section stays machine-
    readable and consistently formatted.
    """

    code = "SOP304"
    default_severity = Severity.ERROR
    # Matches "- [any text](any url)" — the canonical link-bullet form.
    _link_bullet_re = re.compile(r"^\s*-\s+\[.+\]\(.+\)\s*$")

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        refs_body = _extract_section(doc.body, "References")
        if refs_body is None:
            return  # section absent — nothing to validate

        # Find the 1-based line of the "## References" heading so we can
        # report accurate line numbers for each offending entry.
        heading_match = re.search(r"^##\s+References\s*$", doc.body, re.MULTILINE)
        heading_line = (
            doc.body[: heading_match.start()].count("\n") + doc.body_line_offset
            if heading_match
            else doc.body_line_offset
        )

        for offset, line_text in enumerate(refs_body.splitlines(), start=1):
            stripped = line_text.strip()
            if not stripped:
                continue  # blank lines are fine
            if stripped.startswith("#"):
                continue  # sub-headings are fine
            if not self._link_bullet_re.match(line_text):
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=heading_line + offset,
                    message=(
                        f"References entry is not a Markdown link bullet: {stripped!r}. "
                        "Every entry must use the form `- [Description](https://url)`."
                    ),
                    suggestion="- [Description](https://url)",
                )


# --- SOPMCP0xx: sop-mcp strict extras ---------------------------------------


class _FrontmatterPresent:
    """SOPMCP001 — document has YAML frontmatter."""

    code = "SOPMCP001"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if doc.frontmatter_error:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message=f"Invalid YAML frontmatter: {doc.frontmatter_error}",
            )
            return
        if not doc.frontmatter:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message="Missing YAML frontmatter — sop-mcp SOPs must start with a `---` block.",
                suggestion="Add a frontmatter block with at least `name`, `version`, `owner`, `stage`.",
            )


class _FrontmatterRequiredFields:
    """SOPMCP002 — required frontmatter fields."""

    code = "SOPMCP002"
    default_severity = Severity.ERROR
    required = ("name", "version", "owner", "stage")

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if not doc.frontmatter:
            return
        missing = [f for f in self.required if f not in doc.frontmatter]
        if missing:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message=f"Missing required frontmatter fields: {', '.join(missing)}",
            )


class _FrontmatterNameFormat:
    """SOPMCP003 — ``name`` is snake_case, ≥3 underscore segments."""

    code = "SOPMCP003"
    default_severity = Severity.ERROR
    _pattern = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+){2,}$")

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        name = doc.frontmatter.get("name")
        if name is None:
            return
        if not isinstance(name, str) or not self._pattern.match(name):
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message=(
                    f"Frontmatter `name` must be snake_case with at least 3 underscore-separated segments "
                    f"(e.g. `my_sop_name`), got {name!r}."
                ),
            )


class _FrontmatterVersionInteger:
    """SOPMCP004 — ``version`` is a positive integer."""

    code = "SOPMCP004"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if "version" not in doc.frontmatter:
            return
        version = doc.frontmatter["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message=f"Frontmatter `version` must be a positive integer, got {version!r}.",
                suggestion="Plain integers only — no semver, no quoted strings. Example: `version: 2`.",
            )


class _FrontmatterStageValid:
    """SOPMCP005 — ``stage`` is ``preprod`` or ``prod``."""

    code = "SOPMCP005"
    default_severity = Severity.ERROR
    valid = ("preprod", "prod")

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if "stage" not in doc.frontmatter:
            return
        stage = doc.frontmatter["stage"]
        if stage not in self.valid:
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message=f"Frontmatter `stage` must be one of {list(self.valid)}, got {stage!r}.",
            )


class _FrontmatterOwnerNonEmpty:
    """SOPMCP006 — ``owner`` is a non-empty string."""

    code = "SOPMCP006"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        if "owner" not in doc.frontmatter:
            return
        owner = doc.frontmatter["owner"]
        if not isinstance(owner, str) or not owner.strip():
            yield Diagnostic(
                code=self.code,
                severity=self.default_severity,
                line=1,
                message="Frontmatter `owner` must be a non-empty string (team name, alias, or email).",
            )


class _StepHasExpectedOutput:
    """SOPMCP007 — each step has an ``**Expected Output:**`` marker.

    sop-mcp delivers SOPs step-by-step, and each step's ``step_output``
    is fed back as context for the next step. The ``**Expected Output:**``
    marker documents what that payload should look like — effectively a
    per-step contract for ``done``. The base SOP spec doesn't require
    it (Expected Output lives at the SOP level under ``## Examples``),
    so this rule is a sop-mcp strict extra: opt-in via
    ``select = ["SOP", "SOPMCP"]``, invisible to spec-only consumers.
    """

    code = "SOPMCP007"
    default_severity = Severity.ERROR

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        for step in doc.steps:
            if "**Expected Output:**" not in step.body:
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=step.line,
                    message=(
                        f"Step {step.number} ({step.name!r}) has no `**Expected Output:**` marker. "
                        "Document the concrete deliverable the agent must produce so the next step "
                        "can use it as context."
                    ),
                )


# --- Pattern rules (user-defined via config) --------------------------------


@dataclass(frozen=True)
class PatternRule:
    """A regex-matching rule declared in ``sop-lint.toml``."""

    code: str
    default_severity: Severity
    pattern: re.Pattern[str]
    message: str
    applies_to: str  # "body" | "frontmatter" | "any"

    def check(self, doc: SopDocument) -> Iterable[Diagnostic]:
        targets: list[tuple[str, int]] = []
        if self.applies_to in ("body", "any"):
            targets.append((doc.body, doc.body_line_offset))
        if self.applies_to in ("frontmatter", "any"):
            frontmatter_len = len(doc.raw) - len(doc.body)
            if frontmatter_len > 0:
                frontmatter_text = doc.raw[:frontmatter_len]
                targets.append((frontmatter_text, 1))

        for text, line_offset in targets:
            for match in self.pattern.finditer(text):
                line = text[: match.start()].count("\n") + line_offset
                yield Diagnostic(
                    code=self.code,
                    severity=self.default_severity,
                    line=line,
                    message=self.message,
                )


# --- Registry ---------------------------------------------------------------

BUILTIN_RULES: tuple[Rule, ...] = (
    # Document structure (1xx)
    DocumentHasTitle(),
    DocumentHasOverview(),
    DocumentHasParameters(),
    DocumentHasSteps(),
    StepsAreSequential(),
    FileHasSopMdExtension(),
    ParameterSchema(),
    OverviewIsSimple(),
    # Per-step content (2xx)
    StepHasDescription(),
    StepHasConstraints(),
    ConstraintsUseRFC2119(),
    NegativeConstraintsHaveContext(),
    StepHasTimeEstimate(),
    StepHasExamples(),
    # Style (3xx)
    AllowedTopLevelSections(),
    DisallowedNamedSections(),
    FileNameIsKebabCase(),
    ReferencesAreLinks(),
    # sop-mcp strict extras (MCP0xx) — opt-in
    _FrontmatterPresent(),
    _FrontmatterRequiredFields(),
    _FrontmatterNameFormat(),
    _FrontmatterVersionInteger(),
    _FrontmatterStageValid(),
    _FrontmatterOwnerNonEmpty(),
    _StepHasExpectedOutput(),
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LintConfig:
    """Resolved lint configuration."""

    select: tuple[str, ...] = ("SOP",)
    ignore: tuple[str, ...] = ()
    pattern_rules: tuple[PatternRule, ...] = ()

    def is_enabled(self, code: str) -> bool:
        """True if a rule with this code should run.

        Matches ruff's semantics: a code is enabled when it matches any
        ``select`` prefix AND is not matched by any ``ignore`` prefix.
        ``ignore`` wins on overlap.
        """
        if any(code == ig or code.startswith(ig) for ig in self.ignore):
            return False
        return any(code == sel or code.startswith(sel) for sel in self.select)


_DEFAULT_CONFIG = LintConfig()


def load_config(storage_dir: Path | None) -> LintConfig:
    """Load ``{storage_dir}/sop-lint.toml`` or return defaults."""
    if storage_dir is None:
        return _DEFAULT_CONFIG
    path = storage_dir / CONFIG_FILENAME
    if not path.is_file():
        return _DEFAULT_CONFIG
    return load_config_file(path)


def load_config_file(path: Path) -> LintConfig:
    """Load a specific TOML config file."""
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc

    select = tuple(data.get("select", ("SOP",)))
    ignore = tuple(data.get("ignore", ()))

    pattern_rules: list[PatternRule] = []
    for idx, raw in enumerate(data.get("pattern-rules", [])):
        try:
            pattern_rules.append(_parse_pattern_rule(raw))
        except ValueError as exc:
            raise ValueError(f"pattern-rules[{idx}] in {path}: {exc}") from exc

    return LintConfig(select=select, ignore=ignore, pattern_rules=tuple(pattern_rules))


def _parse_pattern_rule(raw: dict[str, Any]) -> PatternRule:
    """Validate and construct a PatternRule from a TOML table."""
    try:
        code = raw["code"]
        pattern_str = raw["pattern"]
        message = raw["message"]
    except KeyError as exc:
        raise ValueError(f"missing required field: {exc.args[0]}") from exc

    if not isinstance(code, str) or not code.strip():
        raise ValueError("`code` must be a non-empty string")
    if not isinstance(pattern_str, str):
        raise ValueError("`pattern` must be a string")
    if not isinstance(message, str):
        raise ValueError("`message` must be a string")

    try:
        pattern = re.compile(pattern_str)
    except re.error as exc:
        raise ValueError(f"invalid regex {pattern_str!r}: {exc}") from exc

    severity_raw = raw.get("severity", "warning")
    try:
        severity = Severity(severity_raw)
    except ValueError as exc:
        raise ValueError(f"invalid severity {severity_raw!r}; expected one of {[s.value for s in Severity]}") from exc

    applies_to = raw.get("applies_to", "body")
    if applies_to not in ("body", "frontmatter", "any"):
        raise ValueError(f"invalid applies_to {applies_to!r}; expected 'body', 'frontmatter', or 'any'")

    return PatternRule(
        code=code,
        default_severity=severity,
        pattern=pattern,
        message=message,
        applies_to=applies_to,
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class LintResult:
    """What ``lint()`` returns: diagnostics + a compact summary."""

    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]

    @property
    def infos(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.INFO]

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.diagnostics)

    def summary(self) -> dict[str, int]:
        return {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "infos": len(self.infos),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "summary": self.summary(),
        }


def lint(content: str, *, config: LintConfig | None = None, path: Path | None = None) -> LintResult:
    """Run every enabled rule against the content and return the result.

    Diagnostics are sorted by (line, code) so output is stable and
    deterministic — two runs against the same input produce
    byte-identical results, which matters for CI diffs.
    """
    cfg = config or _DEFAULT_CONFIG
    doc = SopDocument.parse(content, path=path)

    rules: list[Rule] = [r for r in BUILTIN_RULES if cfg.is_enabled(r.code)]
    rules.extend(r for r in cfg.pattern_rules if cfg.is_enabled(r.code))

    diagnostics: list[Diagnostic] = []
    for rule in rules:
        try:
            diagnostics.extend(rule.check(doc))
        except Exception as exc:  # defensive — a broken rule shouldn't break linting
            logger.warning("Rule %s raised %s; skipping", rule.code, exc)

    diagnostics.sort(key=lambda d: (d.line, d.code))
    return LintResult(diagnostics=diagnostics)
