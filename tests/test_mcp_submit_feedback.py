# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the submit_sop_feedback MCP tool.

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
# Success
# ---------------------------------------------------------------------------


async def test_submit_feedback_returns_success(mcp_transport):
    """Submitting feedback for an existing SOP returns success."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool(
            "submit_sop_feedback",
            {"sop_name": "sop_creation_guide", "feedback": "Test feedback."},
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["sop_name"] == "sop_creation_guide"


async def test_submit_feedback_includes_timestamp(mcp_transport):
    """Feedback response includes a UTC timestamp."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool(
            "submit_sop_feedback",
            {"sop_name": "sop_creation_guide", "feedback": "Timestamp check."},
        )
        data = json.loads(result.content[0].text)
        assert "timestamp" in data
        assert "T" in data["timestamp"]  # ISO format


async def test_submit_feedback_includes_version(mcp_transport):
    """Feedback response includes the SOP version it was submitted against."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool(
            "submit_sop_feedback",
            {"sop_name": "sop_creation_guide", "feedback": "Version check."},
        )
        data = json.loads(result.content[0].text)
        # sop_creation_guide was bumped to v2 during a format
        # migration; any positive integer version is fine.
        assert data["sop_version"] >= 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_submit_feedback_unknown_sop_errors(mcp_transport):
    """Submitting feedback for a non-existent SOP raises an error listing available SOPs."""
    import pytest
    from fastmcp.exceptions import ToolError

    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool(
                "submit_sop_feedback",
                {"sop_name": "nonexistent_sop", "feedback": "should fail"},
            )


async def test_submit_feedback_oversized_errors(mcp_transport):
    """Feedback larger than the 50 KB cap is rejected before being written."""
    import pytest
    from fastmcp.exceptions import ToolError

    oversized = "x" * (50 * 1024 + 1)
    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match="exceeds"):
            await client.call_tool(
                "submit_sop_feedback",
                {"sop_name": "sop_creation_guide", "feedback": oversized},
            )


# ---------------------------------------------------------------------------
# Feedback file is hidden from resources
# ---------------------------------------------------------------------------


async def test_feedback_not_exposed_in_resources(mcp_transport):
    """Feedback files are NOT listed as resources — they are internal."""
    async with Client(mcp_transport) as client:
        await client.call_tool(
            "submit_sop_feedback",
            {"sop_name": "sop_creation_guide", "feedback": "Should stay hidden."},
        )
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert not any("feedback.jsonl" in uri for uri in uris)


# ---------------------------------------------------------------------------
# Integration: publish then feedback
# ---------------------------------------------------------------------------


async def test_feedback_on_freshly_published_sop(mcp_transport):
    """Feedback can be submitted against a freshly published SOP."""
    content = (
        "---\n"
        "name: feedback_target_sop\n"
        "version: 1\n"
        "owner: tests\n"
        "stage: preprod\n"
        "---\n\n"
        "# Feedback Target\n\n"
        "## Overview\n\nTarget for feedback.\n\n"
        "## Parameters\n\n- **x** (required): x.\n\n"
        "## Steps\n\n"
        "### 1. Do\n\n"
        "Action body.\n\n"
        "**Constraints:**\n"
        "- You MUST act\n\n"
        "**Expected Output:** Action completed.\n"
    )
    async with Client(mcp_transport) as client:
        pub = await client.call_tool("publish_sop", {"content": content, "stage": "preprod"})
        assert json.loads(pub.content[0].text)["success"] is True

        fb = await client.call_tool(
            "submit_sop_feedback",
            {"sop_name": "feedback_target_sop", "feedback": "Works great."},
        )
        data = json.loads(fb.content[0].text)
        assert data["success"] is True
        assert data["sop_name"] == "feedback_target_sop"
