# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tool decorator — API-compatible with ``fastmcp.tools.tool``."""

from __future__ import annotations

from collections.abc import Callable


def tool(description: str | None = None) -> Callable:
    """Decorator that marks a function as an MCP tool.

    Stores metadata on the function object for later registration.
    The actual JSON schema is built by the server at registration time.
    """

    def decorator(fn: Callable) -> Callable:
        fn._tool_meta = {"description": description}  # type: ignore[attr-defined]
        return fn

    return decorator
