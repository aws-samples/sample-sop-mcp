# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Integration tests for the ``sop-lint`` CLI.

Exercises the public entry point (``sop_lint.cli.main``) with
real files on a temp filesystem — not mocked — so we verify the argv
→ exit-code behaviour that pre-commit and CI depend on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sop_lint.cli import main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


VALID_SOP = (
    "---\n"
    "name: cli_test_valid_sop\n"
    "version: 1\n"
    "owner: tests\n"
    "stage: preprod\n"
    "---\n\n"
    "# Valid CLI Test SOP\n\n"
    "## Overview\n\nThis SOP is valid and fully spec-compliant.\n\n"
    "## Parameters\n\n- **input_data** (required): The input to process.\n\n"
    "## Steps\n\n"
    "### 1. Do the thing\n\n"
    "Perform the primary action this SOP exists for.\n\n"
    "**Constraints:**\n"
    "- You MUST validate the input\n"
    "- You SHOULD log progress\n\n"
    "**Expected Output:** The action's result payload.\n\n"
    "**Time Estimate:** 5 minutes\n\n"
    "**Example Input:**\n```\nfoo\n```\n\n"
    "**Example Output:**\n```\nbar\n```\n"
)

# SOPMCP003 (frontmatter name has <3 segments) → should exit 1
INVALID_SOP_NAME = VALID_SOP.replace("cli_test_valid_sop", "bad_name")

# SOP109 (param line doesn't match schema) alone → warning, should exit 2
WARN_ONLY_SOP = VALID_SOP.replace(
    "- **input_data** (required): The input to process.",
    "- **badName** (required): Parameter with camelCase name.",
)


@pytest.fixture
def valid_file(tmp_path: Path) -> Path:
    path = tmp_path / "valid.sop.md"
    path.write_text(VALID_SOP, encoding="utf-8")
    return path


@pytest.fixture
def invalid_file(tmp_path: Path) -> Path:
    path = tmp_path / "invalid.sop.md"
    path.write_text(INVALID_SOP_NAME, encoding="utf-8")
    return path


@pytest.fixture
def warn_only_file(tmp_path: Path) -> Path:
    path = tmp_path / "warn.sop.md"
    path.write_text(WARN_ONLY_SOP, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_clean_file_exits_zero(valid_file: Path, capsys):
    assert main([str(valid_file)]) == 0
    captured = capsys.readouterr()
    assert "clean" in captured.out


def test_error_exits_one(invalid_file: Path, capsys):
    assert main([str(invalid_file)]) == 1
    captured = capsys.readouterr()
    assert "SOPMCP003" in captured.out


def test_warning_exits_two(warn_only_file: Path, capsys):
    assert main([str(warn_only_file)]) == 2
    captured = capsys.readouterr()
    assert "SOP109" in captured.out


def test_missing_path_exits_three(tmp_path: Path, capsys):
    missing = tmp_path / "does_not_exist.sop.md"
    assert main([str(missing)]) == 3
    captured = capsys.readouterr()
    assert "Path not found" in captured.err


def test_directory_with_no_sop_files_exits_three(tmp_path: Path, capsys):
    assert main([str(tmp_path)]) == 3
    captured = capsys.readouterr()
    assert "no *.sop.md files" in captured.err


# ---------------------------------------------------------------------------
# Directory walking
# ---------------------------------------------------------------------------


def test_directory_walks_recursively(tmp_path: Path, capsys):
    nested = tmp_path / "sub" / "deep"
    nested.mkdir(parents=True)
    (nested / "valid.sop.md").write_text(VALID_SOP, encoding="utf-8")

    assert main([str(tmp_path)]) == 0


def test_multiple_paths_dedup(valid_file: Path, capsys):
    # Pass the same file twice — the deduplication should prevent double-linting
    assert main([str(valid_file), str(valid_file)]) == 0
    captured = capsys.readouterr()
    # "Checked 1 file" would appear on errors/warnings; on clean we just see the "clean" message
    assert "clean" in captured.out


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


def test_json_format_emits_parseable_output(invalid_file: Path, capsys):
    main([str(invalid_file), "--format", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert len(payload) == 1
    assert payload[0]["summary"]["errors"] >= 1
    assert any(d["code"] == "SOPMCP003" for d in payload[0]["diagnostics"])


def test_quiet_suppresses_clean_output(valid_file: Path, capsys):
    assert main([str(valid_file), "--quiet"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# CLI overrides
# ---------------------------------------------------------------------------


def test_ignore_flag_silences_rule(invalid_file: Path, capsys):
    # SOPMCP003 is an error by default — ignoring it should bring us down to exit 0
    assert main([str(invalid_file), "--ignore", "SOPMCP003"]) == 0


def test_select_flag_narrows_scope(warn_only_file: Path, capsys):
    # `--select SOPMCP` enables only the frontmatter extras, excluding SOP109
    # (the parameter-schema warning fired by the warn-only fixture), so exit should be 0.
    assert main([str(warn_only_file), "--select", "SOPMCP"]) == 0


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------


def test_config_file_at_root_is_auto_discovered(tmp_path: Path, capsys):
    # Place sop-lint.toml at tmp_path and an invalid SOP in a subdirectory.
    (tmp_path / "sop-lint.toml").write_text(
        'select = ["SOP"]\nignore = ["SOPMCP003"]\n',
        encoding="utf-8",
    )
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "invalid.sop.md").write_text(INVALID_SOP_NAME, encoding="utf-8")

    # SOPMCP003 should be ignored per the discovered config → exit 0
    assert main([str(sub / "invalid.sop.md")]) == 0


def test_explicit_config_path(tmp_path: Path, capsys):
    config_path = tmp_path / "custom.toml"
    config_path.write_text('ignore = ["SOPMCP003"]\n', encoding="utf-8")
    invalid = tmp_path / "invalid.sop.md"
    invalid.write_text(INVALID_SOP_NAME, encoding="utf-8")

    assert main([str(invalid), "--config", str(config_path)]) == 0


def test_invalid_config_exits_three(tmp_path: Path, capsys):
    config_path = tmp_path / "bad.toml"
    config_path.write_text("this is not valid toml [[[", encoding="utf-8")
    valid = tmp_path / "valid.sop.md"
    valid.write_text(VALID_SOP, encoding="utf-8")

    assert main([str(valid), "--config", str(config_path)]) == 3
