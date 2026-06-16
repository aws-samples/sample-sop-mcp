# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared pytest fixtures for sop-mcp tests.

Provides:
- ``_isolate_bundled_sops_dir``: session-scoped autouse fixture that
  snapshots bundled SOPs and restores them at teardown.
- ``mcp_server``: function-scoped fixture that returns StdioTransport
  config for spawning the sop-mcp server. Tests open the client
  themselves following FastMCP best practices.

Best practices (from https://gofastmcp.com/development/tests):
- Single behavior per test
- Self-contained setup — runnable in any order, in parallel
- Clear intent — test names describe the verified behavior
- Don't open clients in fixtures (event loop issues)
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import pytest

from sop_mcp.utils.storage import BUNDLED_SOPS_DIR

# ---------------------------------------------------------------------------
# Session-scoped: protect bundled SOPs from test pollution
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _isolate_bundled_sops_dir() -> None:
    """Wipe any test-generated files from the bundled SOPs dir at teardown."""
    snapshot = _snapshot(BUNDLED_SOPS_DIR)
    yield
    _restore(BUNDLED_SOPS_DIR, snapshot)


def _snapshot(root: Path) -> dict[Path, bytes]:
    if not root.is_dir():
        return {}
    out: dict[Path, bytes] = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[path.relative_to(root)] = path.read_bytes()
    return out


def _restore(root: Path, snapshot: dict[Path, bytes]) -> None:
    if not root.is_dir():
        return

    kept = set(snapshot.keys())
    for path in list(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel not in kept:
            with contextlib.suppress(OSError):
                path.unlink()

    for rel, original in snapshot.items():
        target = root / rel
        if not target.exists() or target.read_bytes() != original:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)

    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            with contextlib.suppress(OSError):
                path.rmdir()


# ---------------------------------------------------------------------------
# MCP server transport fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_transport(tmp_path: Path):
    """Return a StdioTransport configured to spawn sop-mcp with isolated storage.

    Tests should open the client themselves:

        async with Client(mcp_transport) as client:
            result = await client.call_tool(...)

    This follows FastMCP best practice: don't open clients in fixtures.
    """
    from fastmcp.client.transports import StdioTransport

    return StdioTransport(
        command=sys.executable,
        args=["-c", "from sop_mcp.server import run; run()"],
        env={**os.environ, "SOP_STORAGE_DIR": str(tmp_path)},
    )
