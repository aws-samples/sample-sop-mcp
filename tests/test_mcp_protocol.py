# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP protocol conformance tests.

Connects to the server with the FastMCP ``Client`` over the shared
``mcp_transport`` fixture — the same path the other tool/resource tests
use — and validates that the server speaks valid MCP. No hand-rolled
subprocess piping.

The single raw-protocol edge case (an unknown JSON-RPC method, which the
typed client refuses to send) is exercised in-process against the server's
dispatcher.
"""

from __future__ import annotations

import importlib.metadata
import json

import pytest
from fastmcp import Client
from mcp.shared.exceptions import McpError

PROTOCOL_VERSION = "2025-06-18"


class TestMCPInitialize:
    async def test_initialize_returns_protocol_version(self, mcp_transport):
        async with Client(mcp_transport) as client:
            assert client.initialize_result.protocolVersion == PROTOCOL_VERSION

    async def test_initialize_returns_capabilities(self, mcp_transport):
        async with Client(mcp_transport) as client:
            assert client.initialize_result.capabilities.tools is not None

    async def test_initialize_returns_server_info(self, mcp_transport):
        async with Client(mcp_transport) as client:
            assert client.initialize_result.serverInfo.name == "SOP MCP Server"

    async def test_initialize_server_info_version_is_dynamic(self, mcp_transport):
        """serverInfo.version is derived from package metadata, not a stale literal.

        It must be present, non-empty, and never the old hardcoded "1.0.0".
        When the distribution is installed it equals the resolved package
        version; otherwise it's the clearly-marked source-run sentinel.
        """
        async with Client(mcp_transport) as client:
            version = client.initialize_result.serverInfo.version
        assert isinstance(version, str)
        assert version != ""
        assert version != "1.0.0"

        try:
            expected = importlib.metadata.version("sample-sop-mcp")
        except importlib.metadata.PackageNotFoundError:
            expected = "0+unknown"
        assert version == expected


class TestMCPToolsList:
    async def test_tools_list_returns_tools(self, mcp_transport):
        async with Client(mcp_transport) as client:
            tools = await client.list_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 3  # run_sop, publish_sop, submit_sop_feedback

    async def test_tools_have_required_fields(self, mcp_transport):
        async with Client(mcp_transport) as client:
            tools = await client.list_tools()
        for tool in tools:
            assert tool.name
            assert tool.description
            assert tool.inputSchema["type"] == "object"

    async def test_core_tools_present(self, mcp_transport):
        async with Client(mcp_transport) as client:
            names = [t.name for t in await client.list_tools()]
        assert "run_sop" in names
        assert "publish_sop" in names
        assert "submit_sop_feedback" in names


class TestMCPToolAnnotations:
    """Tool annotations (readOnlyHint / destructiveHint) appear in tools/list.

    Per the MCP spec, ``annotations`` is an optional per-tool object. The
    read-only tools (run_sop, lint_sop, list_resources, read_resource) carry
    ``readOnlyHint: true``; the writing-but-non-destructive tools (publish_sop,
    submit_sop_feedback) carry ``readOnlyHint: false`` + ``destructiveHint: false``.
    """

    async def _tools_by_name(self, mcp_transport) -> dict:
        async with Client(mcp_transport) as client:
            return {t.name: t for t in await client.list_tools()}

    async def test_read_only_tools_have_read_only_hint(self, mcp_transport):
        tools = await self._tools_by_name(mcp_transport)
        for name in ("run_sop", "lint_sop", "list_resources", "read_resource"):
            assert name in tools, f"{name} missing from tools/list"
            assert tools[name].annotations is not None, f"{name} has no annotations"
            assert tools[name].annotations.readOnlyHint is True, f"{name} not marked read-only"

    async def test_writing_tools_are_non_read_only_and_non_destructive(self, mcp_transport):
        tools = await self._tools_by_name(mcp_transport)
        for name in ("publish_sop", "submit_sop_feedback"):
            assert name in tools, f"{name} missing from tools/list"
            assert tools[name].annotations is not None, f"{name} has no annotations"
            assert tools[name].annotations.readOnlyHint is False, f"{name} should not be read-only"
            assert tools[name].annotations.destructiveHint is False, f"{name} should be non-destructive"


class TestMCPToolsCall:
    async def test_tools_call_returns_content(self, mcp_transport):
        async with Client(mcp_transport) as client:
            result = await client.call_tool("run_sop", {"sop_name": "sop_creation_guide"})
        data = json.loads(result.content[0].text)
        assert "sop_name" in data
        assert "instruction" in data

    async def test_tools_call_error_returns_is_error(self, mcp_transport):
        async with Client(mcp_transport) as client:
            result = await client.call_tool_mcp("run_sop", {"sop_name": "nonexistent_sop_xyz"})
        assert result.isError is True

    async def test_unknown_tool_raises_error(self, mcp_transport):
        async with Client(mcp_transport) as client:
            with pytest.raises(McpError):
                await client.call_tool_mcp("nonexistent_tool", {})


class TestMCPResourcesList:
    async def test_resources_list_returns_array(self, mcp_transport):
        async with Client(mcp_transport) as client:
            resources = await client.list_resources()
        assert isinstance(resources, list)

    async def test_resources_have_required_fields(self, mcp_transport):
        async with Client(mcp_transport) as client:
            resources = await client.list_resources()
        assert len(resources) >= 1
        for res in resources:
            assert res.uri
            assert res.name
            assert res.mimeType


class TestMCPResourcesRead:
    async def test_resources_read_returns_contents(self, mcp_transport):
        async with Client(mcp_transport) as client:
            contents = await client.read_resource("sop://sop_creation_guide")
        assert len(contents) == 1
        assert contents[0].mimeType == "text/markdown"
        assert "### 1." in contents[0].text


class TestMCPPing:
    async def test_ping_succeeds(self, mcp_transport):
        async with Client(mcp_transport) as client:
            await client.ping()  # raises on failure


class TestMCPUnknownMethod:
    """An unknown JSON-RPC method returns -32601 (Method not found).

    The typed FastMCP client can't send an arbitrary method name, so this
    raw-protocol case is checked in-process against the server's dispatcher —
    the same code path the stdio loop invokes per request.
    """

    def test_unknown_method_returns_error(self):
        from sop_mcp.server import mcp

        response = mcp._dispatch("foo/bar", {}, req_id=100)
        assert response["error"]["code"] == -32601


class TestMCPPagination:
    """Pagination conformance for resources/list.

    Per the spec (https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination):
    - Cursors are opaque tokens; clients don't parse them
    - Missing ``nextCursor`` means last page
    - Invalid cursors SHOULD return -32602 (Invalid params)
    - Cursor + remaining-list must reconstruct the full set with no duplicates
    """

    async def test_invalid_cursor_rejected_with_invalid_params(self, mcp_transport):
        async with Client(mcp_transport) as client:
            with pytest.raises(McpError) as exc:
                await client.list_resources_mcp(cursor="not-a-real-cursor")
        assert exc.value.error.code == -32602

    async def test_tiny_page_exposes_next_cursor(self, monkeypatch, tmp_path):
        """Drop the page size to 1 to exercise a real cursor round-trip.

        The page size is read from ``SOP_MCP_PAGE_SIZE`` at request time on
        the server side, so it must be set in the spawned server's env.
        """
        import os
        import sys

        from fastmcp.client.transports import StdioTransport

        transport = StdioTransport(
            command=sys.executable,
            args=["-c", "from sop_mcp.server import run; run()"],
            env={**os.environ, "SOP_STORAGE_DIR": str(tmp_path), "SOP_MCP_PAGE_SIZE": "1"},
        )

        async with Client(transport) as client:
            page1 = await client.list_resources_mcp()
            assert page1.nextCursor is not None, "first page should advertise nextCursor"
            assert len(page1.resources) == 1
            uris_seen = {str(r.uri) for r in page1.resources}

            cursor = page1.nextCursor
            pages = 1
            while cursor is not None and pages < 50:  # safety bound
                page = await client.list_resources_mcp(cursor=cursor)
                for r in page.resources:
                    assert str(r.uri) not in uris_seen, "duplicate URI across pages"
                    uris_seen.add(str(r.uri))
                cursor = page.nextCursor
                pages += 1

        assert cursor is None, "pagination never terminated"
        assert len(uris_seen) > 1, "only one page materialised"

    async def test_single_page_has_no_cursor(self, mcp_transport):
        """When the full set fits in one page, no cursor is emitted.

        Default page size is 50; the bundled set is far smaller.
        """
        async with Client(mcp_transport) as client:
            page = await client.list_resources_mcp()
        assert page.nextCursor is None
