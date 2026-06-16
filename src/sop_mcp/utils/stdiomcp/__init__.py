# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Lightweight MCP stdio server — zero C-dependencies.

Drop-in replacement for ``fastmcp`` that implements only the stdio transport.
Provides the same decorator API (``@tool()``, ``@resource()``) and a
``StdioMCP`` server class so existing tool modules work unchanged.

Only depends on the Python standard library + pydantic.
"""

from sop_mcp.utils.stdiomcp.server import StdioMCP

__all__ = ["StdioMCP"]
