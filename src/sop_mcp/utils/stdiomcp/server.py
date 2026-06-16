# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Lightweight MCP server — stdio transport only, zero C-dependencies.

Implements JSON-RPC 2.0 over stdin/stdout per the MCP specification.
Provides the same public API as ``fastmcp.FastMCP`` so tool modules
can be used without changes.  The class is called ``StdioMCP``.
"""

from __future__ import annotations

import importlib.metadata
import inspect
import json
import logging
import sys
from collections.abc import Callable
from typing import Any, get_type_hints

logger = logging.getLogger(__name__)

# Distribution name as declared in pyproject.toml ``[project] name``. Used to
# resolve the advertised ``serverInfo.version`` from installed package metadata.
_DISTRIBUTION_NAME = "sample-sop-mcp"

# Sentinel returned when the package isn't installed (editable/source runs
# where metadata can't be resolved). Clearly marks an unknown version rather
# than advertising a stale literal.
_UNKNOWN_VERSION = "0+unknown"


def _resolve_server_version() -> str:
    """Resolve the advertised server version from installed package metadata.

    Falls back to ``_UNKNOWN_VERSION`` when the distribution isn't installed,
    so ``initialize`` never fails on a source/editable checkout.
    """
    try:
        return importlib.metadata.version(_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return _UNKNOWN_VERSION


# Resolved once at import time; the installed version doesn't change within a
# running process.
SERVER_VERSION = _resolve_server_version()

# MCP protocol versions this server is willing to speak.
# When the client requests one of these during ``initialize``, we echo it
# back. Otherwise we fall back to ``PROTOCOL_VERSION``. The list is ordered
# newest-first for human readability; order doesn't affect negotiation.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2024-11-05")

# Default version advertised when the client doesn't send one we recognise.
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

# JSON schema type mapping
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _build_input_schema(fn: Callable) -> dict[str, Any]:
    """Build a JSON Schema ``inputSchema`` from a function's signature."""
    sig = inspect.signature(fn)
    hints = get_type_hints(fn, include_extras=True)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        hint = hints.get(name, str)
        description: str | None = None

        # Extract metadata from Annotated types.
        if hasattr(hint, "__metadata__"):
            for meta in hint.__metadata__:
                if isinstance(meta, str):
                    description = meta
                elif hasattr(meta, "description") and meta.description:
                    description = meta.description
            # Unwrap Annotated to get the base type.
            hint = hint.__args__[0] if hasattr(hint, "__args__") else hint

        # Handle Optional (Union with None) / UnionType (3.10+).
        origin = getattr(hint, "__origin__", None)
        args = getattr(hint, "__args__", ())
        is_optional = False
        if origin is type(int | str):  # types.UnionType (3.10+)
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                hint = non_none[0]
                is_optional = True

        json_type = _TYPE_MAP.get(hint, "string")
        prop: dict[str, Any] = {"type": json_type}
        if description:
            prop["description"] = description

        properties[name] = prop
        if param.default is inspect.Parameter.empty and not is_optional:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _tool_descriptor(t: _ToolInfo) -> dict[str, Any]:
    """Build the wire-format descriptor for a registered tool.

    ``annotations`` (the optional MCP tool hints) is emitted only when
    non-empty — the spec treats it as optional, so omitting it keeps the
    payload clean and backward-compatible for clients that ignore hints.
    """
    descriptor: dict[str, Any] = {
        "name": t.name,
        "description": t.description,
        "inputSchema": t.input_schema,
    }
    if t.annotations:
        descriptor["annotations"] = t.annotations
    return descriptor


def _resource_descriptor(r: _ResourceInfo) -> dict[str, Any]:
    """Build the wire-format descriptor for a registered resource.

    Optional fields (``title``, ``size``, ``annotations``) are emitted only
    when populated — the MCP spec treats them as optional, and omitting
    them keeps the payload small for clients that don't consume them.
    """
    descriptor: dict[str, Any] = {
        "uri": r.uri,
        "name": r.name,
        "description": r.description,
        "mimeType": r.mime_type,
    }
    if r.title:
        descriptor["title"] = r.title
    if r.size is not None:
        descriptor["size"] = r.size
    if r.annotations:
        descriptor["annotations"] = r.annotations
    return descriptor


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

# Default page size for list operations. Clients MUST NOT assume a fixed
# value — the spec deliberately hides it behind an opaque cursor so we can
# tune this without a protocol bump. Overridable via ``SOP_MCP_PAGE_SIZE``
# so tests (and operators) can shrink the page to exercise the cursor
# round-trip without needing a huge catalog.
DEFAULT_PAGE_SIZE = 50


def _configured_page_size() -> int:
    """Resolve the effective page size at request time.

    Read the env var fresh on each call so tests that set it after
    import pick up the override. Bad values fall back silently to the
    compile-time default; this is a knob, not an input we want to fail
    the server over.
    """
    import os

    raw = os.environ.get("SOP_MCP_PAGE_SIZE")
    if not raw:
        return DEFAULT_PAGE_SIZE
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid SOP_MCP_PAGE_SIZE=%r; using default %d", raw, DEFAULT_PAGE_SIZE)
        return DEFAULT_PAGE_SIZE
    if value < 1:
        logger.warning("SOP_MCP_PAGE_SIZE must be >= 1; using default %d", DEFAULT_PAGE_SIZE)
        return DEFAULT_PAGE_SIZE
    return value


def _encode_cursor(offset: int) -> str:
    """Encode a zero-based offset into an opaque base64url cursor."""
    import base64

    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> int:
    """Decode an opaque cursor back to a zero-based offset.

    Raises ``ValueError`` for anything the cursor encoder didn't emit,
    so the dispatcher can map it to JSON-RPC ``-32602`` per the spec.
    """
    import base64

    if not cursor:
        raise ValueError("Empty cursor")
    # Restore base64 padding stripped by the encoder.
    padding = (-len(cursor)) % 4
    try:
        raw = base64.urlsafe_b64decode(cursor + ("=" * padding))
        offset = int(raw.decode("ascii"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed cursor: {cursor!r}") from exc
    if offset < 0:
        raise ValueError(f"Cursor offset cannot be negative: {offset}")
    return offset


def _paginate(
    items: list[Any],
    cursor: str | None,
    page_size: int | None = None,
) -> tuple[list[Any], str | None]:
    """Slice ``items`` into a single page starting at the cursor offset.

    Returns ``(page, next_cursor)``. ``next_cursor`` is ``None`` on the
    last page. The caller is responsible for surfacing a ``ValueError``
    from ``_decode_cursor`` as ``-32602``.
    """
    if page_size is None:
        page_size = _configured_page_size()
    offset = _decode_cursor(cursor) if cursor else 0
    # A cursor pointing at or past the end is only valid when the list
    # is exactly that length (i.e. we handed it out on the previous page
    # boundary). Anything beyond is a stale or fabricated cursor.
    if offset > len(items):
        raise ValueError(f"Cursor offset {offset} exceeds item count {len(items)}")
    page = items[offset : offset + page_size]
    next_offset = offset + len(page)
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return page, next_cursor


class _ToolInfo:
    """Internal tool registration."""

    __slots__ = ("annotations", "description", "fn", "input_schema", "name")

    def __init__(
        self,
        name: str,
        description: str,
        fn: Callable,
        input_schema: dict[str, Any],
        annotations: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.fn = fn
        self.input_schema = input_schema
        self.annotations = annotations or {}


class _ResourceInfo:
    """Internal resource registration."""

    __slots__ = (
        "annotations",
        "description",
        "fn",
        "is_binary",
        "mime_type",
        "name",
        "size",
        "title",
        "uri",
    )

    def __init__(
        self,
        uri: str,
        name: str,
        description: str,
        mime_type: str,
        fn: Callable,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type
        self.fn = fn
        meta = meta or {}
        self.is_binary = bool(meta.get("is_binary", False))
        self.title = meta.get("title")
        self.size = meta.get("size")
        self.annotations = meta.get("annotations") or {}


class StdioMCP:
    """Lightweight MCP server — stdio only, zero C-dependencies."""

    def __init__(
        self, name: str = "MCP Server", resources_as_tools: bool = True, instructions: str = "", **kwargs: Any
    ) -> None:
        self.name = name
        self.instructions = instructions
        self._tools: dict[str, _ToolInfo] = {}
        self._resources: dict[str, _ResourceInfo] = {}
        self._subscriptions: set[str] = set()
        self._resources_as_tools = resources_as_tools
        self._resource_tools_registered = False

    # ------------------------------------------------------------------
    # Registration API (matches fastmcp)
    # ------------------------------------------------------------------

    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
        annotations: dict[str, Any] | None = None,
    ) -> Callable:
        """Register a function as an MCP tool (decorator factory).

        ``annotations`` carries the optional MCP tool hints
        (``readOnlyHint``, ``destructiveHint``, ``idempotentHint``,
        ``openWorldHint``). Emitted in ``tools/list`` only when non-empty.
        """

        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            desc = description
            if desc is None and hasattr(fn, "_tool_meta"):
                desc = fn._tool_meta.get("description")
            if desc is None:
                desc = (fn.__doc__ or "").strip().split("\n")[0]
            schema = _build_input_schema(fn)
            self._tools[tool_name] = _ToolInfo(tool_name, desc or "", fn, schema, annotations)
            return fn

        return decorator

    def resource(
        self,
        uri: str,
        name: str = "",
        description: str = "",
        mime_type: str = "text/plain",
        is_binary: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> Callable:
        """Register a function as an MCP resource (decorator factory).

        ``meta`` carries MCP-spec optional fields (``title``, ``size``,
        ``annotations``). Packed into a single dict to keep the signature
        narrow.
        """
        merged = {**(meta or {}), "is_binary": is_binary}

        def decorator(fn: Callable) -> Callable:
            self._resources[uri] = _ResourceInfo(
                uri,
                name,
                description,
                mime_type,
                fn,
                meta=merged,
            )
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Programmatic access (used by tests)
    # ------------------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a registered tool by name. Returns JSON-serialisable result."""
        self._ensure_resource_tools()
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        tool = self._tools[name]
        args = arguments or {}
        result = tool.fn(**args)
        return json.dumps(result)

    async def list_tools(self) -> list[Any]:
        """Return tool descriptors (used by tests)."""
        self._ensure_resource_tools()
        return [
            type(
                "Tool",
                (),
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                    "annotations": t.annotations or None,
                },
            )()
            for t in self._tools.values()
        ]

    async def list_resources(self) -> list[Any]:
        """Return resource descriptors (used by tests)."""
        return [
            type(
                "Resource",
                (),
                {
                    "uri": r.uri,
                    "name": r.name,
                    "title": r.title,
                    "description": r.description,
                    "mimeType": r.mime_type,
                    "size": r.size,
                    "annotations": r.annotations or None,
                },
            )()
            for r in self._resources.values()
        ]

    async def read_resource(self, uri: str) -> str:
        """Read a resource by URI."""
        if uri not in self._resources:
            raise ValueError(f"Unknown resource: {uri}")
        return self._resources[uri].fn()

    def notify_resources_list_changed(self) -> None:
        """Emit a ``notifications/resources/list_changed`` message to the client."""
        self._emit_notification({"jsonrpc": "2.0", "method": "notifications/resources/list_changed"})

    def notify_resource_updated(self, uri: str) -> None:
        """Emit ``notifications/resources/updated`` for a subscribed URI only."""
        if uri not in self._subscriptions:
            return
        self._emit_notification(
            {
                "jsonrpc": "2.0",
                "method": "notifications/resources/updated",
                "params": {"uri": uri},
            }
        )

    def _emit_notification(self, notification: dict[str, Any]) -> None:
        """Write a notification to stdout (best-effort)."""
        try:
            sys.stdout.write(json.dumps(notification) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, ValueError):
            logger.debug("Could not emit notification")

    # ------------------------------------------------------------------
    # JSON-RPC stdio transport
    # ------------------------------------------------------------------

    def run(self, transport: str = "stdio") -> None:
        """Start the MCP server on stdio."""
        if transport != "stdio":
            raise ValueError(f"Only stdio transport is supported, got: {transport}")
        self._ensure_resource_tools()
        logger.info("Starting %s (lite stdio)", self.name)
        self._stdio_loop()

    def _ensure_resource_tools(self) -> None:
        """Register resource tools if enabled and not yet registered."""
        if self._resources_as_tools and not self._resource_tools_registered and self._resources:
            self._register_resource_tools()
            self._resource_tools_registered = True

    def _stdio_loop(self) -> None:
        """Read JSON-RPC requests from stdin, write responses to stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                self._write_error(None, -32700, "Parse error")
                continue

            req_id = request.get("id")
            method = request.get("method", "")
            params = request.get("params", {})

            if req_id is None:
                continue

            response = self._dispatch(method, params, req_id)
            if response is not None:
                self._write(response)

    # ------------------------------------------------------------------
    # Method dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, method: str, params: dict[str, Any], req_id: Any) -> dict[str, Any] | None:
        """Dispatch a JSON-RPC method to the appropriate handler."""
        dispatch_table: dict[str, Callable] = {
            "initialize": self._handle_initialize,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tool_call,
            "resources/list": self._handle_resources_list,
            "resources/templates/list": self._handle_resource_templates_list,
            "resources/read": self._handle_resource_read,
            "resources/subscribe": self._handle_subscribe,
            "resources/unsubscribe": self._handle_unsubscribe,
        }
        handler = dispatch_table.get(method)
        if handler is None:
            return self._rpc_error(req_id, -32601, f"Method not found: {method}")
        return handler(params, req_id)

    # Keep backward-compat alias for tests that call _handle_request directly
    _handle_request = _dispatch

    def _handle_initialize(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        # Echo the client's requested protocol version when we support it;
        # otherwise advertise the newest version we speak. The MCP spec
        # requires client and server to agree on a single version for the
        # session — clients that can't speak our fallback will disconnect.
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        result: dict[str, Any] = {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": True, "listChanged": True},
            },
            "serverInfo": {"name": self.name, "version": SERVER_VERSION},
        }
        if self.instructions:
            result["instructions"] = self.instructions
        return self._rpc_result(req_id, result)

    def _handle_ping(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        return self._rpc_result(req_id, {})

    def _handle_tools_list(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        tools = [_tool_descriptor(t) for t in self._tools.values()]
        return self._paginated_result(req_id, params, tools, "tools")

    def _handle_tool_call(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if name not in self._tools:
            return self._rpc_error(req_id, -32602, f"Unknown tool: {name}")

        import asyncio

        try:
            result = asyncio.run(self.call_tool(name, arguments))
            content = [{"type": "text", "text": result}]
            return self._rpc_result(req_id, {"content": content})
        except Exception as e:
            content = [{"type": "text", "text": json.dumps({"error": str(e)})}]
            return self._rpc_result(req_id, {"content": content, "isError": True})

    def _handle_resources_list(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        resources = [_resource_descriptor(r) for r in self._resources.values()]
        return self._paginated_result(req_id, params, resources, "resources")

    def _handle_resource_templates_list(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        # We don't expose parameterised resources yet, but the spec requires
        # a conformant handler so compliant clients don't trip on -32601.
        return self._paginated_result(req_id, params, [], "resourceTemplates")

    def _handle_resource_read(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        uri = params.get("uri", "")
        if uri not in self._resources:
            # Spec-defined "Resource not found" code — distinct from generic
            # invalid-params (-32602) so clients can branch on it.
            return self._rpc_error(req_id, -32002, f"Resource not found: {uri}")

        resource = self._resources[uri]
        try:
            payload = resource.fn()
        except Exception as e:
            return self._rpc_error(req_id, -32603, str(e))

        content: dict[str, Any] = {"uri": uri, "mimeType": resource.mime_type}
        if resource.is_binary:
            import base64

            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            content["blob"] = base64.b64encode(payload).decode("ascii")
        else:
            content["text"] = payload
        return self._rpc_result(req_id, {"contents": [content]})

    def _handle_subscribe(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        uri = params.get("uri", "")
        if not uri:
            return self._rpc_error(req_id, -32602, "Missing 'uri' parameter")
        self._subscriptions.add(uri)
        return self._rpc_result(req_id, {})

    def _handle_unsubscribe(self, params: dict[str, Any], req_id: Any) -> dict[str, Any]:
        uri = params.get("uri", "")
        self._subscriptions.discard(uri)
        return self._rpc_result(req_id, {})

    # ------------------------------------------------------------------
    # JSON-RPC helpers
    # ------------------------------------------------------------------

    def _paginated_result(
        self,
        req_id: Any,
        params: dict[str, Any],
        items: list[Any],
        list_key: str,
    ) -> dict[str, Any]:
        """Build a paginated JSON-RPC result for a list endpoint.

        Reads ``params["cursor"]`` (if present), slices ``items`` via
        ``_paginate``, and surfaces ``_decode_cursor`` errors as the
        spec-mandated ``-32602 (Invalid params)``.
        """
        cursor = params.get("cursor") if isinstance(params, dict) else None
        try:
            page, next_cursor = _paginate(items, cursor)
        except ValueError as exc:
            return self._rpc_error(req_id, -32602, f"Invalid cursor: {exc}")
        result: dict[str, Any] = {list_key: page}
        if next_cursor is not None:
            result["nextCursor"] = next_cursor
        return self._rpc_result(req_id, result)

    @staticmethod
    def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _write(response: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    @staticmethod
    def _write_error(req_id: Any, code: int, message: str) -> None:
        resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

    def _register_resource_tools(self) -> None:
        """Auto-register list_resources and read_resource as tools."""
        resources = self._resources

        def _list() -> dict:
            return {"resources": [_resource_descriptor(r) for r in resources.values()]}

        def _read(uri: str) -> dict:
            if uri not in resources:
                raise ValueError(f"Unknown resource URI: {uri}. Use list_resources to see available URIs.")
            r = resources[uri]
            return {"uri": uri, "mimeType": r.mime_type, "content": r.fn()}

        self.tool(
            name="list_resources",
            description="List all available resources with their URIs and descriptions.",
            annotations={"readOnlyHint": True},
        )(_list)
        self.tool(
            name="read_resource",
            description="Read a resource by its URI.",
            annotations={"readOnlyHint": True},
        )(_read)
