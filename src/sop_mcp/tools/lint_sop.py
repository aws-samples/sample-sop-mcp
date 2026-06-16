# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Lint SOP tool.

Runs the same rule engine as ``publish_sop`` (and the standalone
``sop-lint`` CLI) against a draft SOP string, but never writes anything.
Lets an agent validate a draft in-process — no CLI, no shell, no publish
round-trip — so a draft that passes here will also pass ``publish_sop``.
"""

import logging
from typing import Annotated, Any

from sop_lint.engine import Severity, lint, load_config
from sop_mcp.utils.storage import LocalFilesystemBackend

logger = logging.getLogger(__name__)

backend = LocalFilesystemBackend.from_env()

NAME = "lint_sop"
DESCRIPTION = (
    "Validate a draft SOP against the sop-mcp format rules WITHOUT writing it.\n\n"
    "Runs the exact rule engine that `publish_sop` enforces at write time, so a "
    "draft that lints clean here is guaranteed to pass `publish_sop`. Use this to "
    "iterate on a draft before publishing — there is no need for the `sop-lint` CLI "
    "or any shell access.\n\n"
    "The `content` parameter MUST be the complete SOP markdown string (frontmatter "
    "plus body). Reads `sop-lint.toml` from the active storage directory if present, "
    "so team rule customisations (select/ignore/pattern-rules) apply identically to "
    "publish.\n\n"
    "Returns:\n"
    "  - passed (bool): true when there are zero error-severity diagnostics\n"
    "  - summary: counts of errors / warnings / infos\n"
    "  - diagnostics: list of {code, severity, line, message, suggestion?}\n"
    "  - report: a human-readable rendering you can show the author\n\n"
    "Errors block a real publish; warnings and infos do not. Resolve every error, "
    "and resolve warnings unless you have a documented reason to keep them."
)

_SEVERITY_LABEL = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}


def _render_report(diagnostics: list, summary: dict[str, int]) -> str:
    """Render diagnostics as a human-readable, copy-pasteable report."""
    if not diagnostics:
        return "SOP is clean — 0 errors, 0 warnings, 0 infos."

    lines: list[str] = []
    for d in diagnostics:
        lines.append(f"line {d.line}: {_SEVERITY_LABEL[d.severity]} [{d.code}] {d.message}")
        if d.suggestion:
            lines.append(f"    suggestion: {d.suggestion}")
    lines.append(f"\n{summary['errors']} error(s), {summary['warnings']} warning(s), {summary['infos']} info(s)")
    return "\n".join(lines)


def handler(
    content: Annotated[str, "Complete SOP markdown to lint (frontmatter + body). Nothing is written."],
) -> dict[str, Any]:
    """Lint a draft SOP and return structured diagnostics — no write."""
    logger.info("Invoking lint_sop: content=<%s chars>", len(content))

    config = load_config(backend.base_dir)
    result = lint(content, config=config)
    summary = result.summary()

    return {
        "passed": not result.has_errors,
        "summary": summary,
        "diagnostics": [d.to_dict() for d in result.diagnostics],
        "report": _render_report(result.diagnostics, summary),
    }
