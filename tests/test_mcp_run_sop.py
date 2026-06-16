# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the run_sop MCP tool.

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
# Start
# ---------------------------------------------------------------------------


async def test_start_returns_sop_name(mcp_transport):
    """Starting an SOP returns the correct sop_name in the response."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        data = json.loads(result.content[0].text)
        assert data["sop_name"] == "sop_creation_guide"


async def test_start_returns_version(mcp_transport):
    """Starting an SOP returns a positive integer version."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        data = json.loads(result.content[0].text)
        assert isinstance(data["sop_version"], int)
        assert data["sop_version"] >= 1


async def test_start_returns_step_zero(mcp_transport):
    """Starting an SOP sets current_step to 0."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        data = json.loads(result.content[0].text)
        assert data["current_step"] == 0


async def test_start_instruction_contains_overview(mcp_transport):
    """First step instruction includes the SOP title and overview."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        data = json.loads(result.content[0].text)
        assert "You are executing:" in data["instruction"]
        assert "Total steps:" in data["instruction"]


# ---------------------------------------------------------------------------
# Continue
# ---------------------------------------------------------------------------


async def test_continue_returns_next_step(mcp_transport):
    """Advancing from step 1 returns Step 2 instruction."""
    async with Client(mcp_transport) as client:
        result = await client.call_tool(
            "run_sop", {"sop_name": "sop_creation_guide", "current_step": 1, "step_output": "done"}
        )
        data = json.loads(result.content[0].text)
        assert "Step 2" in data["instruction"]


async def test_continue_last_step_returns_completion(mcp_transport):
    """Advancing past the final step returns a completion message."""
    async with Client(mcp_transport) as client:
        # Get total steps first.
        start = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        total = json.loads(start.content[0].text)["total_steps"]

        result = await client.call_tool(
            "run_sop", {"sop_name": "sop_creation_guide", "current_step": total, "step_output": "final"}
        )
        data = json.loads(result.content[0].text)
        assert "complete" in data["instruction"].lower()


async def test_continue_requires_step_output(mcp_transport):
    """Continuing without step_output raises an error about the missing output."""
    import pytest
    from fastmcp.exceptions import ToolError

    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match="step_output is required"):
            await client.call_tool("run_sop", {"sop_name": "sop_creation_guide", "current_step": 1})


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_error_unknown_sop(mcp_transport):
    """Requesting a non-existent SOP raises an error listing available SOPs."""
    import pytest
    from fastmcp.exceptions import ToolError

    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match=r"not found.*Available"):
            await client.call_tool("run_sop", {"sop_name": "nonexistent_sop"})


async def test_error_negative_step(mcp_transport):
    """Negative step number raises an error about the valid range."""
    import pytest
    from fastmcp.exceptions import ToolError

    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match="current_step must be"):
            await client.call_tool(
                "run_sop", {"sop_name": "sop_creation_guide", "current_step": -1, "step_output": "x"}
            )


async def test_error_step_beyond_total(mcp_transport):
    """Step number exceeding total raises an error about the valid range."""
    import pytest
    from fastmcp.exceptions import ToolError

    async with Client(mcp_transport) as client:
        start = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        total = json.loads(start.content[0].text)["total_steps"]

        with pytest.raises(ToolError, match="current_step must be"):
            await client.call_tool(
                "run_sop", {"sop_name": "sop_creation_guide", "current_step": total + 1, "step_output": "x"}
            )


async def test_error_step_output_too_large(mcp_transport):
    """step_output above 50 KB raises an error naming the byte limit."""
    import pytest
    from fastmcp.exceptions import ToolError

    oversized = "x" * (50 * 1024 + 1)

    async with Client(mcp_transport) as client:
        with pytest.raises(ToolError, match=r"exceeds 51200 bytes"):
            await client.call_tool(
                "run_sop",
                {"sop_name": "sop_creation_guide", "current_step": 1, "step_output": oversized},
            )


# ---------------------------------------------------------------------------
# Full walkthrough
# ---------------------------------------------------------------------------


async def test_full_walkthrough(mcp_transport):
    """Walking through all steps reaches completion."""
    async with Client(mcp_transport) as client:
        start = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        total = json.loads(start.content[0].text)["total_steps"]
        assert total > 1

        for step in range(1, total):
            result = await client.call_tool(
                "run_sop", {"sop_name": "sop_creation_guide", "current_step": step, "step_output": f"Step {step}"}
            )
            data = json.loads(result.content[0].text)
            assert "instruction" in data

        final = await client.call_tool(
            "run_sop", {"sop_name": "sop_creation_guide", "current_step": total, "step_output": "Final"}
        )
        data = json.loads(final.content[0].text)
        assert "complete" in data["instruction"].lower()
