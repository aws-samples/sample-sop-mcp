# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Publish SOP tool."""

import logging
from typing import Annotated, Any

from sop_lint.engine import lint, load_config
from sop_mcp.utils import SOP, register_sop_resources, set_version_in_content
from sop_mcp.utils.sop_parser import _normalise_stage, _split_frontmatter
from sop_mcp.utils.storage import LocalFilesystemBackend

logger = logging.getLogger(__name__)


backend = LocalFilesystemBackend.from_env()


NAME = "publish_sop"
DESCRIPTION = (
    "Publish a new or updated Standard Operating Procedure document.\n\n"
    "The content parameter MUST contain the complete SOP markdown string with "
    "YAML frontmatter declaring:\n"
    "  - name    (required, snake_case, ≥3 underscore segments — the SOP's identity)\n"
    "  - owner   (required, non-empty string — team, alias, or email. This is the\n"
    "            point of contact surfaced when feedback is submitted or a mismatch\n"
    "            is detected during review. Pick a name you want pinged.)\n"
    "  - stage   (required, 'preprod' or 'prod' — informational lifecycle label;\n"
    "            see the `stage` argument below for mismatch behaviour)\n"
    "  - version (required, positive integer — advisory revision counter. The tool\n"
    "            auto-bumps on each publish (+1), but we ask authors to declare it\n"
    "            explicitly so a mismatch between the file on disk and what the\n"
    "            author thinks they are updating is visible in the response)\n"
    "  - description (optional — when omitted, the SOP's `## Overview` section is\n"
    "            used for short summaries)\n\n"
    "Version & stage mismatch: the tool never trusts the frontmatter values blindly. "
    "The `stage` argument wins over the frontmatter `stage`, and the version is "
    "computed server-side (max existing + 1). Both values are overwritten in the "
    "stored content so the file on disk always reflects what actually happened. "
    "If you pass a version or stage that disagrees with the final stored values, "
    "the response surfaces the difference under `warning` so you can decide whether "
    "you were editing the right version.\n\n"
    'Example call: {"content": "---\\nname: my_sop_name\\nversion: 1\\n'
    "owner: my-team\\nstage: preprod\\n---\\n\\n"
    "# My SOP\\n\\n## Overview\\nOverview text.\\n\\n"
    '### Step 1: First step\\nDo the thing."}\n\n'
    "Versioning: plain positive integers — 1, 2, 3, 4, … New SOPs start at 1; "
    "each subsequent publish increments by one. No semver.\n\n"
    "Lint enforcement: every publish runs the same rule engine as the standalone "
    "`sop-lint` CLI. Errors (SOP rules at severity=error) BLOCK the publish — "
    "the tool raises and nothing is written. Warnings are returned under the "
    "`warning` field but do not block. Iterate locally with `sop-lint <file>` "
    "before calling publish_sop to avoid MCP round-trip latency."
)


# Hard cap on SOP content size. 1 MB is far larger than any realistic SOP
# (the bundled ones are a few KB); anything bigger is almost certainly an
# accidental paste or a deliberate attempt to exhaust memory on parse/lint.
MAX_SOP_CONTENT_BYTES = 1024 * 1024


def _bump(latest: int) -> int:
    return latest + 1


def _overwrite_meta(content: str, *, version: int, stage: str) -> str:
    """Overwrite the frontmatter's version and stage values before writing."""
    import yaml

    meta, body = _split_frontmatter(content)
    meta["version"] = version
    meta["stage"] = stage
    new_frontmatter = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{new_frontmatter}\n---\n{body}"


def _collect_mismatch_warnings(
    *,
    declared_version: int | None,
    final_version: int,
    declared_stage: str,
    final_stage: str,
    owner: str,
) -> list[str]:
    """Surface disagreements between what the caller sent and what was stored.

    Authors edit SOPs in their own tooling and can end up publishing against a
    version they no longer hold — we want that to be loud, not silent. The
    owner is included so the response points at the person to ping.
    """
    warnings: list[str] = []

    if declared_version is not None and declared_version != final_version:
        warnings.append(
            f"Frontmatter declared version {declared_version} but this publish stored "
            f"version {final_version} (previous max + 1). If you expected to update "
            f"v{declared_version}, contact the owner ({owner}) — someone else may have "
            "published in between."
        )

    if declared_stage and declared_stage != final_stage:
        warnings.append(
            f"Frontmatter stage was '{declared_stage}' but the `stage` argument "
            f"('{final_stage}') took precedence. The stored file now reads '{final_stage}'."
        )

    return warnings


def _refresh_resources() -> None:
    """Re-register MCP resources after a publish."""
    try:
        from sop_mcp.server import mcp as _mcp

        register_sop_resources(_mcp, backend=backend, notify=True)
    except Exception as exc:
        logger.warning("Failed to re-register resources after publish: %s", exc)


def handler(
    content: Annotated[str, "Complete SOP markdown with YAML frontmatter (name, owner, stage, version)"],
    stage: Annotated[str, "Deployment stage: 'preprod' or 'prod'"],
) -> dict[str, Any]:
    """Publish a new or updated SOP document."""
    stage_norm = _normalise_stage(stage)

    content_bytes = len(content.encode("utf-8"))
    if content_bytes > MAX_SOP_CONTENT_BYTES:
        raise ValueError(
            f"SOP content exceeds {MAX_SOP_CONTENT_BYTES} bytes ({content_bytes} received). "
            "Split the procedure into smaller SOPs or trim oversized step content."
        )

    logger.info(
        "Invoking publish_sop with args: content=<%s chars>, stage=%s",
        len(content),
        stage_norm,
    )

    sop = SOP.from_content(content)

    if not sop.owner:
        raise ValueError("Frontmatter `owner` is required and must be a non-empty string.")

    # Run the lint engine before writing. Errors block the publish so
    # the agent is forced to fix the SOP; warnings flow through as
    # informational response fields. The same engine is available
    # standalone via the `sop-lint` CLI — which agents should use for
    # iterative linting since it avoids MCP round-trip latency.
    lint_config = load_config(backend.base_dir)
    lint_result = lint(content, config=lint_config)
    if lint_result.has_errors:
        error_lines = [f"  - {d.code} (line {d.line}): {d.message}" for d in lint_result.errors]
        raise ValueError(
            "SOP failed lint checks. Iterate with the `sop-lint` CLI, or fix the errors below:\n"
            + "\n".join(error_lines)
        )

    # Capture what the author declared before we overwrite it — these feed
    # the mismatch warnings so the author can tell whether they were editing
    # the file they thought they were.
    declared_version = sop.version
    declared_stage = sop.stage

    existing_version = backend.get_version(sop.name)
    new_version = 1 if existing_version is None else _bump(existing_version)

    content = _overwrite_meta(content, version=new_version, stage=stage_norm)
    content = set_version_in_content(content, new_version)

    written_path = backend.write_sop(sop.name, new_version, content)

    sop = SOP.from_content(content)
    _refresh_resources()

    logger.info("publish_sop completed successfully")
    result: dict[str, Any] = {
        "success": True,
        "sop_name": sop.name,
        "title": sop.title,
        "version": new_version,
        "stage": sop.stage,
        "owner": sop.owner,
        "total_steps": sop.total_steps,
        "path": str(written_path.relative_to(backend.base_dir)),
        "message": f"SOP '{sop.name}' published as v{new_version} ({sop.stage}).",
    }

    warnings = _collect_mismatch_warnings(
        declared_version=declared_version,
        final_version=new_version,
        declared_stage=declared_stage,
        final_stage=sop.stage,
        owner=sop.owner,
    )
    # Re-lint the canonicalised content so the response surfaces lint
    # warnings against what was actually stored (not what the author
    # initially sent). Errors were caught above; only warnings remain.
    post_lint = lint(content, config=lint_config)
    for diag in post_lint.warnings:
        warnings.append(f"{diag.code} (line {diag.line}): {diag.message}")
    if warnings:
        result["warning"] = " | ".join(warnings)
    return result
