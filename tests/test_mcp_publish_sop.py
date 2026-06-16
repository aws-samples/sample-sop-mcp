# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the publish_sop MCP tool.

Each test spawns sop-mcp as a subprocess and connects via FastMCP Client.
Full MCP protocol over stdio — no mocking, no in-process shortcuts.

Best practices:
- Single behavior per test
- Self-contained — each test opens its own client
- Clear intent — test name describes the verified behavior
"""

from __future__ import annotations

import json

from fastmcp import Client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sop_content(name: str, overview: str = "Spec-compliant test overview.") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "version: 1\n"
        "owner: tests\n"
        "stage: preprod\n"
        "---\n\n"
        f"# Test SOP: {name}\n\n"
        f"## Overview\n\n{overview}\n\n"
        "## Parameters\n\n- **input_data** (required): The input to process.\n\n"
        "## Steps\n\n"
        "### 1. Do the thing\n\n"
        "Perform the primary action this SOP exists for.\n\n"
        "**Constraints:**\n"
        "- You MUST complete the action\n"
        "- You SHOULD log progress\n\n"
        "**Expected Output:** The action's result payload.\n"
    )


# ---------------------------------------------------------------------------
# Fresh publish
# ---------------------------------------------------------------------------


async def test_publish_returns_success(mcp_transport):
    """Publishing a valid SOP returns success with name and version."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool("publish_sop", {"content": _sop_content("fresh_pub_sop"), "stage": "preprod"})
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["sop_name"] == "fresh_pub_sop"
        assert data["version"] == 1


async def test_publish_registers_resource(mcp_transport):
    """Published SOP becomes discoverable via list_resources."""
    async with Client(mcp_transport) as client:
        await client.call_tool("publish_sop", {"content": _sop_content("test_resource_sop"), "stage": "preprod"})
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "sop://test_resource_sop" in uris


async def test_publish_sop_is_runnable(mcp_transport):
    """Published SOP can be executed via run_sop."""
    async with Client(mcp_transport) as client:
        await client.call_tool("publish_sop", {"content": _sop_content("test_runnable_sop"), "stage": "preprod"})
        result = await client.call_tool("run_sop", {"sop_name": "test_runnable_sop"})
        data = json.loads(result.content[0].text)
        assert data["sop_name"] == "test_runnable_sop"
        assert data["total_steps"] == 1


# ---------------------------------------------------------------------------
# Version bumping
# ---------------------------------------------------------------------------


async def test_republish_bumps_version(mcp_transport):
    """Publishing the same SOP name twice increments the version."""
    async with Client(mcp_transport) as client:
        r1 = await client.call_tool("publish_sop", {"content": _sop_content("test_bump_sop"), "stage": "preprod"})
        r2 = await client.call_tool("publish_sop", {"content": _sop_content("test_bump_sop"), "stage": "preprod"})
        assert json.loads(r1.content[0].text)["version"] == 1
        assert json.loads(r2.content[0].text)["version"] == 2


async def test_republish_updates_in_place(mcp_transport):
    """Re-publishing the same name updates the existing file, not creates a new one."""
    async with Client(mcp_transport) as client:
        r1 = await client.call_tool("publish_sop", {"content": _sop_content("test_update_sop"), "stage": "preprod"})
        r2 = await client.call_tool("publish_sop", {"content": _sop_content("test_update_sop"), "stage": "preprod"})
        d1 = json.loads(r1.content[0].text)
        d2 = json.loads(r2.content[0].text)
        assert d1["path"] == d2["path"], "Same file should be updated in place"
        assert d2["version"] == 2


# ---------------------------------------------------------------------------
# Invalid content
# ---------------------------------------------------------------------------


async def test_publish_rejects_missing_frontmatter(mcp_transport):
    """Content without valid structure raises a ToolError."""
    import pytest
    from fastmcp.exceptions import ToolError

    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match="Overview"):
            await client.call_tool("publish_sop", {"content": "# No frontmatter\n\nJust text.", "stage": "preprod"})


async def test_publish_rejects_missing_owner(mcp_transport):
    """Content without an owner field raises a ToolError mentioning owner."""
    import pytest
    from fastmcp.exceptions import ToolError

    content = (
        "---\n"
        "name: no_owner_sop\n"
        "version: 1\n"
        "stage: preprod\n"
        "---\n\n"
        "# No Owner\n\n"
        "## Overview\n\nTest fixture.\n\n"
        "## Parameters\n\n- **x** (required): x.\n\n"
        "## Steps\n\n"
        "### 1. Do\n\n"
        "Action.\n\n"
        "**Constraints:**\n"
        "- You MUST act\n\n"
        "**Expected Output:** Action completed.\n"
    )
    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match="owner"):
            await client.call_tool("publish_sop", {"content": content, "stage": "preprod"})


async def test_publish_rejects_oversized_content(mcp_transport):
    """Content over the 1 MB cap raises a ToolError before parsing/linting."""
    import pytest
    from fastmcp.exceptions import ToolError

    # A valid SOP padded past the 1 MB limit with filler in the overview.
    filler = "x" * (1024 * 1024 + 1)
    content = _sop_content("oversized_sop", overview=filler)
    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match="exceeds"):
            await client.call_tool("publish_sop", {"content": content, "stage": "preprod"})
