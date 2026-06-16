# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SOP MCP Server — stdio entry point.

Run with: ``uvx --from git+https://github.com/aws-samples/sample-sop-mcp sop-mcp`` or ``uv run sop-mcp``.
"""

from __future__ import annotations

import logging

from sop_mcp.tools import lint_sop, publish_sop, run_sop, submit_sop_feedback
from sop_mcp.utils import register_sop_resources
from sop_mcp.utils.stdiomcp import StdioMCP
from sop_mcp.utils.storage import LocalFilesystemBackend

logger = logging.getLogger(__name__)

# Initialize storage backend at module level
backend = LocalFilesystemBackend.from_env()


# Initialize MCP server
mcp = StdioMCP(
    "SOP MCP Server",
    instructions=(
        "This server guides you through Standard Operating Procedures (SOPs) one step at a time. "
        "Use list_resources to discover available SOPs, then run_sop to execute them step by step. "
        "You MUST execute each step's actions before advancing — do not skip or summarize. "
        "Use publish_sop to create new SOPs — it enforces the same lint rules as the "
        "lint_sop tool, so validate draft SOPs with lint_sop first. "
        "Use submit_sop_feedback to record improvement suggestions."
    ),
)

# Register tools. Each carries MCP annotations describing its side effects:
# the executing/reading tools are read-only; publish_sop and submit_sop_feedback
# write but are non-destructive (create/update and append-only, respectively).
_TOOL_ANNOTATIONS: dict[object, dict[str, bool]] = {
    run_sop: {"readOnlyHint": True},
    lint_sop: {"readOnlyHint": True},
    publish_sop: {"readOnlyHint": False, "destructiveHint": False},
    submit_sop_feedback: {"readOnlyHint": False, "destructiveHint": False},
}
for _mod, _annotations in _TOOL_ANNOTATIONS.items():
    mcp.tool(name=_mod.NAME, description=_mod.DESCRIPTION, annotations=_annotations)(_mod.handler)

# Register SOP resources for discoverability
register_sop_resources(mcp)


def run() -> None:
    """Entry point for uvx / uv run sop-mcp."""
    mcp.run(transport="stdio")
