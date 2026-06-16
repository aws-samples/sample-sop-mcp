# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for LocalFilesystemBackend path-containment hardening.

These exercise the backend directly (no MCP round-trip) to confirm that
SOP and attachment discovery refuses to follow symlinks that escape the
storage root — the symlink-traversal gap identified during threat
modeling.
"""

from __future__ import annotations

from pathlib import Path

from sop_mcp.utils.storage import LocalFilesystemBackend

# A minimal, lint-clean SOP body used for files we plant on disk.
_SOP_BODY = (
    "---\n"
    "name: {name}\n"
    "version: 1\n"
    "owner: tests\n"
    "stage: preprod\n"
    "---\n\n"
    "# {name}\n\n"
    "## Overview\n\nContent for {name}.\n\n"
    "## Parameters\n\n- **x** (required): x.\n\n"
    "## Steps\n\n"
    "### 1. Do\n\nAction body.\n\n"
    "**Constraints:**\n- You MUST act\n\n"
    "**Expected Output:** Done.\n"
)


def _write_sop(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SOP_BODY.format(name=name), encoding="utf-8")


def test_symlinked_sop_outside_root_is_skipped(tmp_path: Path) -> None:
    """A *.sop.md symlink whose target lives outside the storage root is ignored."""
    outside = tmp_path / "outside"
    storage = tmp_path / "storage"
    outside.mkdir()
    storage.mkdir()

    # A legitimately out-of-tree SOP file.
    secret = outside / "secret.sop.md"
    _write_sop(secret, "out_of_tree_secret")

    backend = LocalFilesystemBackend(base_dir=storage)

    # Plant a symlink inside the storage dir pointing at the outside file.
    link = storage / "evil.sop.md"
    link.symlink_to(secret)

    names = backend.list_sops()
    assert "out_of_tree_secret" not in names
    # The skip is surfaced as a warning rather than silently dropped.
    assert any("resolves outside" in w for w in backend.duplicate_name_warnings)


def test_real_sop_inside_root_still_discovered(tmp_path: Path) -> None:
    """A normal (non-symlinked) SOP inside the root is still found."""
    storage = tmp_path / "storage"
    storage.mkdir()
    _write_sop(storage / "real_inside_sop" / "real_inside_sop.sop.md", "real_inside_sop")

    backend = LocalFilesystemBackend(base_dir=storage)

    assert "real_inside_sop" in backend.list_sops()


def test_symlinked_attachment_outside_root_not_listed(tmp_path: Path) -> None:
    """An attachment symlink escaping the SOP folder is not advertised as a resource."""
    outside = tmp_path / "outside"
    storage = tmp_path / "storage"
    outside.mkdir()
    storage.mkdir()

    secret = outside / "secret.txt"
    secret.write_text("out of tree", encoding="utf-8")

    sop_dir = storage / "doc_sop"
    _write_sop(sop_dir / "doc_sop.sop.md", "doc_sop")

    backend = LocalFilesystemBackend(base_dir=storage)

    # Symlink an attachment inside the SOP folder to the outside file.
    (sop_dir / "leak.txt").symlink_to(secret)

    attachments = backend.list_attachments("doc_sop")
    assert "leak.txt" not in (attachments or [])
