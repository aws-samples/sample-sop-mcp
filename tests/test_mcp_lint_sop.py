# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the lint_sop MCP tool.

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


def _clean_sop(name: str = "lint_clean_sop") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "version: 1\n"
        "owner: tests\n"
        "stage: preprod\n"
        "---\n\n"
        f"# Test SOP: {name}\n\n"
        "## Overview\n\nSpec-compliant test overview.\n\n"
        "## Parameters\n\n- **input_data** (required): The input to process.\n\n"
        "## Steps\n\n"
        "### 1. Do the thing\n\n"
        "Perform the primary action this SOP exists for.\n\n"
        "**Constraints:**\n"
        "- You MUST complete the action\n"
        "- You SHOULD log progress\n\n"
        "**Expected Output:** The action's result payload.\n"
    )


def _broken_sop() -> str:
    # Missing title, Overview, Parameters, and Steps — guaranteed errors.
    return "---\nname: broken_sop\nversion: 1\nowner: tests\nstage: preprod\n---\n\nNo structure here.\n"


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


async def test_lint_sop_tool_registered(mcp_transport):
    """Server exposes lint_sop as a tool."""
    async with Client(mcp_transport) as client:
        tools = await client.list_tools()
        assert "lint_sop" in [t.name for t in tools]


# ---------------------------------------------------------------------------
# Behavior
# ---------------------------------------------------------------------------


async def test_lint_clean_sop_passes(mcp_transport):
    """A spec-compliant SOP returns passed=true with zero errors."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool("lint_sop", {"content": _clean_sop()})
        data = json.loads(result.content[0].text)
        assert data["passed"] is True
        assert data["summary"]["errors"] == 0


async def test_lint_broken_sop_fails_with_diagnostics(mcp_transport):
    """A malformed SOP returns passed=false and reports error diagnostics."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool("lint_sop", {"content": _broken_sop()})
        data = json.loads(result.content[0].text)
        assert data["passed"] is False
        assert data["summary"]["errors"] > 0
        codes = [d["code"] for d in data["diagnostics"]]
        # Missing Overview / Parameters / Steps are SOP1xx errors.
        assert any(c.startswith("SOP1") for c in codes)


async def test_lint_sop_does_not_persist(mcp_transport):
    """lint_sop must not write — the linted SOP stays out of list_resources."""
    async with Client(mcp_transport) as client:
        await client.call_tool("lint_sop", {"content": _clean_sop("ephemeral_lint_sop")})
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "sop://ephemeral_lint_sop" not in uris


async def test_lint_matches_publish_enforcement(mcp_transport):
    """A draft that lint_sop rejects is also rejected by publish_sop (shared engine)."""
    import pytest
    from fastmcp.exceptions import ToolError

    async with Client(mcp_transport) as client:
        lint_result = await client.call_tool("lint_sop", {"content": _broken_sop()})
        assert json.loads(lint_result.content[0].text)["passed"] is False

        # publish_sop runs the same engine and must reject the same content.
        with pytest.raises(ToolError):
            await client.call_tool("publish_sop", {"content": _broken_sop(), "stage": "preprod"})
