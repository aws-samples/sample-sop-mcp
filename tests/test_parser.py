# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for SOP parser module.

Tests cover:
- SOP class: title, overview, steps extraction
- SOP.from_content() classmethod
- Error handling for missing files and invalid content
- list_available_sops() function
"""

import string

import pytest
from hypothesis import strategies as st

from sop_mcp.utils.sop_parser import SOP, list_available_sops


class TestSopTitleExtraction:
    """Test that SOP extracts the correct title."""

    def test_extracts_title_from_sop(self):
        sop = SOP("sop_creation_guide")
        assert sop.title == "Standard Operating Procedure: Creating Standard Operating Procedures"

    def test_title_is_string(self):
        sop = SOP("sop_creation_guide")
        assert isinstance(sop.title, str)
        assert len(sop.title) > 0


class TestSopOverviewExtraction:
    """Test that SOP extracts the overview content."""

    def test_extracts_overview_from_sop(self):
        sop = SOP("sop_creation_guide")
        assert isinstance(sop.overview, str)
        assert len(sop.overview) > 0

    def test_overview_contains_expected_content(self):
        sop = SOP("sop_creation_guide")
        assert "SOP" in sop.overview


class TestSopStepExtraction:
    """Test that SOP extracts all steps correctly."""

    def test_extracts_all_steps(self):
        sop = SOP("sop_creation_guide")
        assert isinstance(sop.steps, list)
        assert len(sop.steps) == 7

    def test_steps_are_strings(self):
        sop = SOP("sop_creation_guide")
        for step in sop.steps:
            assert isinstance(step, str)
            assert len(step) > 0

    def test_steps_contain_step_headings(self):
        sop = SOP("sop_creation_guide")
        # SOP spec format: `### N. Step Name`
        assert "1. " in sop.steps[0]
        assert "2. " in sop.steps[1]
        assert "7. " in sop.steps[6]

    def test_first_step_orients_the_author(self):
        sop = SOP("sop_creation_guide")
        assert "Orient the Author" in sop.steps[0]

    def test_total_steps_property(self):
        sop = SOP("sop_creation_guide")
        assert sop.total_steps == 7


class TestSopProperties:
    """Test SOP convenience properties."""

    def test_path_is_set(self):
        sop = SOP("sop_creation_guide")
        assert sop.path is not None
        assert sop.path.exists()

    def test_truncated_overview_short(self):
        sop = SOP("sop_creation_guide")
        assert len(sop.truncated_overview) <= 150

    def test_name_is_set(self):
        sop = SOP("sop_creation_guide")
        assert sop.name == "sop_creation_guide"

    def test_tool_name_derived_from_folder(self):
        sop = SOP("sop_creation_guide")
        assert sop.tool_name == "sop_creation_guide"


class TestSopFromContent:
    """Test SOP.from_content() classmethod."""

    def test_parses_valid_content(self):
        content = (
            "---\n"
            "name: my_test_sop\n"
            "version: 1\n"
            "owner: tests\n"
            "stage: preprod\n"
            "---\n\n"
            "# Test SOP\n\n"
            "## Overview\n\nThis is a test SOP.\n\n"
            "### 1. Do something\n\nDo the thing.\n"
        )
        sop = SOP.from_content(content)
        assert sop.name == "my_test_sop"
        assert sop.tool_name == "my_test_sop"
        assert sop.total_steps == 1
        assert sop.path is None

    def test_raises_for_missing_sop_name(self):
        content = "# Some Title\n\n## Overview\n\nHello\n\n### 1. Do\n\nStuff\n"
        with pytest.raises(ValueError, match="Could not extract SOP name"):
            SOP.from_content(content)

    def test_raises_for_missing_title(self):
        content = (
            "---\n"
            "name: bad_test_sop\n"
            "version: 1\n"
            "owner: tests\n"
            "stage: preprod\n"
            "---\n\n"
            "no heading\n\n"
            "## Overview\n\nHello\n\n"
            "### 1. Do\n\nStuff\n"
        )
        with pytest.raises(ValueError, match="missing a title"):
            SOP.from_content(content)


class TestSopErrorHandling:
    """Test error handling for missing or invalid files."""

    def test_raises_file_not_found_for_missing_sop(self):
        with pytest.raises(FileNotFoundError):
            SOP("nonexistent-sop-name")

    def test_error_message_includes_path(self):
        with pytest.raises(FileNotFoundError, match="SOP file not found"):
            SOP("nonexistent-sop-name")


class TestListAvailableSops:
    """Test the list_available_sops function."""

    def test_returns_list(self):
        result = list_available_sops()
        assert isinstance(result, list)

    def test_returns_sop_name(self):
        result = list_available_sops()
        assert "sop_creation_guide" in result

    def test_returns_names_without_md_extension(self):
        result = list_available_sops()
        for name in result:
            assert not name.endswith(".md")


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------

# --- Strategies ---

# Server names: lowercase letters, digits, underscores (like my_server_1)
_server_name_segment = st.text(
    alphabet=string.ascii_lowercase + string.digits + "_",
    min_size=1,
    max_size=12,
).filter(lambda s: s[0].isalpha())  # must start with a letter

server_names = _server_name_segment

# Description text: arbitrary printable text without newlines or leading dashes
description_text = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z"), exclude_characters="\n\r"),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip() and not s.strip().startswith("-"))

# Separator between server name and description
separator = st.sampled_from([" — ", " - ", " – "])

# A single list item: either bare name or name + separator + description
server_entry = st.one_of(
    server_names.map(lambda n: (n, f"- {n}")),
    st.tuples(server_names, separator, description_text).map(lambda t: (t[0], f"- {t[0]}{t[1]}{t[2]}")),
)

# Whether to include the (should) marker
should_marker = st.sampled_from(["", " (should)"])


def _build_sop_with_servers(entries: list[tuple[str, str]], marker: str) -> str:
    """Build a minimal valid SOP markdown with a Required MCP Servers field."""
    items = "\n".join(line for _, line in entries)
    return (
        "# Test SOP Title\n\n"
        "## Document Information\n"
        "- **Document ID**: some_test_sop\n\n"
        "## Overview\n\nThis is a test SOP overview.\n\n"
        "- Some general prerequisite\n\n"
        f"**Required MCP Servers**{marker}:\n"
        f"{items}\n\n"
        "### Step 1: Do something\n\nDo the thing.\n"
    )


def _build_sop_without_servers() -> str:
    """Build a minimal valid SOP markdown without a Required MCP Servers field."""
    return (
        "# Test SOP Title\n\n"
        "## Document Information\n"
        "- **Document ID**: some_test_sop\n\n"
        "## Overview\n\nThis is a test SOP overview.\n\n"
        "- Some general prerequisite\n\n"
        "### Step 1: Do something\n\nDo the thing.\n"
    )
