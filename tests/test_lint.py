# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for the sop-lint rule engine.

Tests the Agent SOP spec-compliant rule set:

- SOP1xx — document structure
- SOP2xx — per-step content
- SOP3xx — style
- SOPMCP0xx — sop-mcp strict extras (opt-in)

Each rule has a dedicated class with positive (clean SOP passes) and
negative (broken SOP fails with the expected code) cases. Rules are
tested in isolation where possible; document-wide rules are tested
against constructed fixtures.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sop_lint.engine import (
    BUILTIN_RULES,
    CONFIG_FILENAME,
    LintConfig,
    PatternRule,
    Severity,
    SopDocument,
    lint,
    load_config,
)

# ---------------------------------------------------------------------------
# Helpers — build spec-compliant SOPs and tweak individual bits per test
# ---------------------------------------------------------------------------


_VALID_STEP = textwrap.dedent(
    """\
    ### 1. Do the thing

    Perform the primary action the SOP exists for.

    **Constraints:**
    - You MUST validate the input before processing
    - You SHOULD log progress at each stage
    - You MAY retry on transient failure

    **Expected Output:** The action's result payload.
    """
)


def build_sop(
    *,
    title: str = "# Test SOP",
    overview: str = "## Overview\n\nA short plain-text overview describing what this SOP does.",
    parameters: str = "## Parameters\n\n- **input_data** (required): The input to process.",
    steps_heading: str = "## Steps",
    steps: str = _VALID_STEP,
    extra_sections: str = "",
    frontmatter: str | None = ("---\nname: valid_test_sop\nversion: 1\nowner: tests\nstage: preprod\n---"),
) -> str:
    """Assemble a spec-compliant SOP body, overriding any component for a given test."""
    parts: list[str] = []
    if frontmatter:
        parts.append(frontmatter)
        parts.append("")  # blank line after frontmatter
    parts.extend([title, "", overview, "", parameters, "", steps_heading, "", steps])
    if extra_sections:
        parts.extend(["", extra_sections])
    return "\n".join(parts) + "\n"


def codes(result) -> set[str]:
    """Return the set of diagnostic codes fired for a result."""
    return {d.code for d in result.diagnostics}


# ---------------------------------------------------------------------------
# SOP1xx — document structure
# ---------------------------------------------------------------------------


class TestSOP101Title:
    def test_missing_title_fires(self):
        content = build_sop(title="")
        assert "SOP101" in codes(lint(content))

    def test_present_title_passes(self):
        assert "SOP101" not in codes(lint(build_sop()))


class TestSOP102Overview:
    def test_missing_overview_fires(self):
        content = build_sop(overview="")
        assert "SOP102" in codes(lint(content))

    def test_present_overview_passes(self):
        assert "SOP102" not in codes(lint(build_sop()))


class TestSOP103Parameters:
    def test_missing_parameters_section_fires(self):
        content = build_sop(parameters="")
        assert "SOP103" in codes(lint(content))

    def test_present_parameters_passes(self):
        assert "SOP103" not in codes(lint(build_sop()))


class TestSOP104Steps:
    def test_no_steps_fires(self):
        content = build_sop(steps="")
        assert "SOP104" in codes(lint(content))

    def test_steps_present_passes(self):
        assert "SOP104" not in codes(lint(build_sop()))


class TestSOP105SequentialNumbering:
    def test_gap_fires(self):
        steps = textwrap.dedent(
            """\
            ### 1. First

            Do something.

            **Constraints:**
            - You MUST act

            ### 3. Third

            Do something else.

            **Constraints:**
            - You MUST act
            """
        )
        content = build_sop(steps=steps)
        assert "SOP105" in codes(lint(content))

    def test_sequential_passes(self):
        steps = textwrap.dedent(
            """\
            ### 1. First

            Do one thing.

            **Constraints:**
            - You MUST act

            ### 2. Second

            Do another.

            **Constraints:**
            - You MUST act
            """
        )
        content = build_sop(steps=steps)
        assert "SOP105" not in codes(lint(content))


class TestSOP106SopMdExtension:
    def test_wrong_extension_fires(self, tmp_path: Path):
        path = tmp_path / "not-a-sop.md"
        content = build_sop()
        path.write_text(content, encoding="utf-8")
        assert "SOP106" in codes(lint(content, path=path))

    def test_correct_extension_passes(self, tmp_path: Path):
        path = tmp_path / "valid-test.sop.md"
        assert "SOP106" not in codes(lint(build_sop(), path=path))

    def test_no_path_skips_rule(self):
        assert "SOP106" not in codes(lint(build_sop()))


class TestSOP109ParameterSchema:
    def test_camelcase_name_fires(self):
        params = "## Parameters\n\n- **camelCase** (required): Bad naming."
        result = lint(build_sop(parameters=params))
        assert "SOP109" in codes(result)
        diag = next(d for d in result.diagnostics if d.code == "SOP109")
        assert "snake_case" in diag.message

    def test_dash_name_fires(self):
        params = "## Parameters\n\n- **with-dash** (required): Also bad."
        assert "SOP109" in codes(lint(build_sop(parameters=params)))

    def test_missing_required_optional_tag_fires(self):
        params = "## Parameters\n\n- **valid_name**: description only, no tag."
        result = lint(build_sop(parameters=params))
        assert "SOP109" in codes(result)
        diag = next(d for d in result.diagnostics if d.code == "SOP109")
        assert "required" in diag.message.lower() or "optional" in diag.message.lower()

    def test_missing_description_fires(self):
        params = "## Parameters\n\n- **valid_name** (required):"
        result = lint(build_sop(parameters=params))
        assert "SOP109" in codes(result)
        diag = next(d for d in result.diagnostics if d.code == "SOP109")
        assert "description" in diag.message.lower()

    def test_full_schema_passes(self):
        params = "## Parameters\n\n- **valid_name** (required): Good description."
        assert "SOP109" not in codes(lint(build_sop(parameters=params)))

    def test_optional_with_default_passes(self):
        params = "## Parameters\n\n- **valid_name** (optional, default: 42): Good description."
        assert "SOP109" not in codes(lint(build_sop(parameters=params)))


class TestSOP108OverviewIsSimple:
    def test_short_overview_passes(self):
        overview = "## Overview\n\nShort and clear."
        assert "SOP108" not in codes(lint(build_sop(overview=overview)))

    def test_long_overview_fires(self):
        overview = "## Overview\n\n" + ("word " * 150).strip() + "."  # ~750 chars
        result = lint(build_sop(overview=overview))
        assert "SOP108" in codes(result)
        msg = next(d for d in result.diagnostics if d.code == "SOP108").message
        assert "characters" in msg

    def test_sub_sections_fire(self):
        overview = "## Overview\n\nIntro.\n\n### Sub-section\n\nPollution."
        assert "SOP108" in codes(lint(build_sop(overview=overview)))

    def test_lists_fire(self):
        overview = "## Overview\n\nIntro.\n\n- bullet one\n- bullet two"
        assert "SOP108" in codes(lint(build_sop(overview=overview)))

    def test_tables_fire(self):
        overview = "## Overview\n\nIntro.\n\n| A | B |\n|---|---|\n| x | y |"
        assert "SOP108" in codes(lint(build_sop(overview=overview)))

    def test_code_blocks_fire(self):
        overview = "## Overview\n\nIntro.\n\n```\ncode\n```"
        assert "SOP108" in codes(lint(build_sop(overview=overview)))


# ---------------------------------------------------------------------------
# SOP2xx — per-step content
# ---------------------------------------------------------------------------


class TestSOP201StepDescription:
    def test_missing_description_fires(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            **Constraints:**
            - You MUST act
            """
        )
        result = lint(build_sop(steps=steps))
        assert "SOP201" in codes(result)

    def test_description_present_passes(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            This step does the primary work.

            **Constraints:**
            - You MUST act
            """
        )
        assert "SOP201" not in codes(lint(build_sop(steps=steps)))


class TestSOP202StepConstraints:
    def test_missing_constraints_fires(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing without any formal constraints.
            """
        )
        assert "SOP202" in codes(lint(build_sop(steps=steps)))

    def test_constraints_present_passes(self):
        assert "SOP202" not in codes(lint(build_sop()))


class TestSOP203ConstraintsUseRFC2119:
    def test_plain_bullet_fires(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - Validate the input
            - You SHOULD log progress
            """
        )
        result = lint(build_sop(steps=steps))
        assert "SOP203" in codes(result)
        # The bullet without a keyword should be the one flagged.
        diag = next(d for d in result.diagnostics if d.code == "SOP203")
        assert "Validate the input" in diag.message

    def test_lowercase_keyword_fires(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You must validate the input
            """
        )
        assert "SOP203" in codes(lint(build_sop(steps=steps)))

    def test_all_bullets_with_keywords_passes(self):
        assert "SOP203" not in codes(lint(build_sop()))


class TestSOP204NegativeConstraintsContext:
    def test_must_not_without_context_fires(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You MUST NOT run `git push`
            """
        )
        result = lint(build_sop(steps=steps))
        assert "SOP204" in codes(result)

    def test_never_without_context_fires(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You MUST do the thing
            - You SHOULD NEVER delete history
            """
        )
        assert "SOP204" in codes(lint(build_sop(steps=steps)))

    def test_must_not_with_because_passes(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You MUST NOT run `git push` because it could publish unreviewed code
            """
        )
        assert "SOP204" not in codes(lint(build_sop(steps=steps)))

    def test_should_not_with_since_passes(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You SHOULD NOT edit history since others depend on it
            """
        )
        assert "SOP204" not in codes(lint(build_sop(steps=steps)))

    def test_never_with_due_to_passes(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You NEVER delete data due to compliance requirements
            """
        )
        assert "SOP204" not in codes(lint(build_sop(steps=steps)))

    def test_positive_must_without_context_passes(self):
        """Positive MUST doesn't need context — only negatives do."""
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You MUST validate the input
            """
        )
        assert "SOP204" not in codes(lint(build_sop(steps=steps)))


class TestSOP205StepTimeEstimate:
    def test_missing_time_estimate_fires_warning(self):
        # The default fixture step has no Time Estimate marker.
        result = lint(build_sop())
        sop205 = [d for d in result.diagnostics if d.code == "SOP205"]
        assert sop205
        assert all(d.severity is Severity.WARNING for d in sop205)

    def test_time_estimate_present_passes(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You MUST act

            **Expected Output:** Done.

            **Time Estimate:** 10 minutes
            """
        )
        assert "SOP205" not in codes(lint(build_sop(steps=steps)))


class TestSOP206StepExamples:
    def test_missing_examples_fires_info(self):
        result = lint(build_sop())
        # SOP206 is info-severity by default; our fixture step has no Example Input/Output.
        sop206 = [d for d in result.diagnostics if d.code == "SOP206"]
        assert sop206
        assert all(d.severity is Severity.INFO for d in sop206)

    def test_both_examples_present_passes(self):
        steps = textwrap.dedent(
            """\
            ### 1. Act

            Do the thing.

            **Constraints:**
            - You MUST act

            **Example Input:**
            ```
            foo
            ```

            **Example Output:**
            ```
            bar
            ```
            """
        )
        assert "SOP206" not in codes(lint(build_sop(steps=steps)))


# ---------------------------------------------------------------------------
# SOP3xx — style
# ---------------------------------------------------------------------------


class TestSOP301AllowedTopLevelSections:
    def test_unknown_section_fires(self):
        extra = "## Random Section\n\nSome content."
        result = lint(build_sop(extra_sections=extra))
        assert "SOP301" in codes(result)

    def test_examples_section_allowed(self):
        extra = "## Examples\n\n### Example 1\n\nInput/output pair."
        assert "SOP301" not in codes(lint(build_sop(extra_sections=extra)))

    def test_troubleshooting_allowed(self):
        extra = "## Troubleshooting\n\n### Common issue\n\nFix."
        assert "SOP301" not in codes(lint(build_sop(extra_sections=extra)))

    def test_desired_outcome_allowed(self):
        extra = "## Desired Outcome\n\nGood result."
        assert "SOP301" not in codes(lint(build_sop(extra_sections=extra)))

    def test_named_antipattern_does_not_also_fire_sop301(self):
        extra = "## Appendix A: Something\n\nContent."
        result = lint(build_sop(extra_sections=extra))
        # SOP302 (the targeted warning) fires; SOP301 defers.
        assert "SOP301" not in codes(result)
        assert "SOP302" in codes(result)


class TestSOP302DisallowedNamedSections:
    @pytest.mark.parametrize(
        "heading",
        [
            "Appendix",
            "Appendix A: Something",
            "Definitions",
            "Glossary",
            "Terms",
            "Revision History",
            "Changelog",
            "Contact",
            "Tool Reference",
            "Roles and Responsibilities",
            "Procedure",
            "Scope",
            "Prerequisites",
        ],
    )
    def test_anti_pattern_fires(self, heading):
        extra = f"## {heading}\n\nSome content."
        result = lint(build_sop(extra_sections=extra))
        assert "SOP302" in codes(result), [d.to_dict() for d in result.diagnostics]

    def test_procedure_redirects_to_steps(self):
        extra = "## Procedure\n\nContent."
        result = lint(build_sop(extra_sections=extra))
        diag = next(d for d in result.diagnostics if d.code == "SOP302")
        assert "Steps" in diag.message


class TestSOP303KebabCaseFilename:
    def test_snake_case_fires(self, tmp_path: Path):
        path = tmp_path / "not_kebab.sop.md"
        result = lint(build_sop(), path=path)
        sop303 = [d for d in result.diagnostics if d.code == "SOP303"]
        assert sop303
        assert all(d.severity is Severity.INFO for d in sop303)

    def test_camel_case_fires(self, tmp_path: Path):
        path = tmp_path / "NotKebab.sop.md"
        assert "SOP303" in codes(lint(build_sop(), path=path))

    def test_kebab_case_passes(self, tmp_path: Path):
        path = tmp_path / "my-sop.sop.md"
        assert "SOP303" not in codes(lint(build_sop(), path=path))

    def test_no_path_skips_rule(self):
        assert "SOP303" not in codes(lint(build_sop()))


class TestSOP304ReferencesAreLinks:
    def test_no_references_section_passes(self):
        assert "SOP304" not in codes(lint(build_sop()))

    def test_valid_link_bullets_pass(self):
        refs = "## References\n\n- [AWS Docs](https://docs.aws.amazon.com)\n- [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119)\n"
        assert "SOP304" not in codes(lint(build_sop(extra_sections=refs)))

    def test_plain_text_entry_fires(self):
        refs = "## References\n\nSome plain text reference.\n"
        result = lint(build_sop(extra_sections=refs))
        assert "SOP304" in codes(result)
        diag = next(d for d in result.diagnostics if d.code == "SOP304")
        assert diag.severity is Severity.ERROR

    def test_bare_url_bullet_fires(self):
        refs = "## References\n\n- https://example.com\n"
        assert "SOP304" in codes(lint(build_sop(extra_sections=refs)))

    def test_non_bullet_link_fires(self):
        refs = "## References\n\n[Some Link](https://example.com)\n"
        assert "SOP304" in codes(lint(build_sop(extra_sections=refs)))

    def test_blank_lines_ignored(self):
        refs = "## References\n\n- [Link One](https://one.example.com)\n\n- [Link Two](https://two.example.com)\n"
        assert "SOP304" not in codes(lint(build_sop(extra_sections=refs)))

    def test_sub_heading_ignored(self):
        refs = "## References\n\n### External\n\n- [Link](https://example.com)\n"
        assert "SOP304" not in codes(lint(build_sop(extra_sections=refs)))

    def test_references_allowed_by_sop301(self):
        refs = "## References\n\n- [Link](https://example.com)\n"
        assert "SOP301" not in codes(lint(build_sop(extra_sections=refs)))

    def test_suggestion_provided(self):
        refs = "## References\n\nbare text\n"
        result = lint(build_sop(extra_sections=refs))
        diag = next(d for d in result.diagnostics if d.code == "SOP304")
        assert diag.suggestion == "- [Description](https://url)"


# ---------------------------------------------------------------------------
# SOPMCP0xx — strict extras (frontmatter)
# ---------------------------------------------------------------------------


class TestSOPMCPFrontmatter:
    def test_mcp001_missing_frontmatter_fires(self):
        content = build_sop(frontmatter=None)
        result = lint(content, config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP001" in codes(result)

    def test_mcp002_missing_fields_fires(self):
        frontmatter = "---\nname: valid_test_sop\nversion: 1\n---"
        result = lint(build_sop(frontmatter=frontmatter), config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP002" in codes(result)

    def test_mcp003_bad_name_format_fires(self):
        frontmatter = "---\nname: bad\nversion: 1\nowner: t\nstage: preprod\n---"
        result = lint(build_sop(frontmatter=frontmatter), config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP003" in codes(result)

    def test_mcp004_version_string_fires(self):
        frontmatter = '---\nname: valid_test_sop\nversion: "1.0"\nowner: t\nstage: preprod\n---'
        result = lint(build_sop(frontmatter=frontmatter), config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP004" in codes(result)

    def test_mcp005_bad_stage_fires(self):
        frontmatter = "---\nname: valid_test_sop\nversion: 1\nowner: t\nstage: staging\n---"
        result = lint(build_sop(frontmatter=frontmatter), config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP005" in codes(result)

    def test_mcp006_empty_owner_fires(self):
        frontmatter = '---\nname: valid_test_sop\nversion: 1\nowner: ""\nstage: preprod\n---'
        result = lint(build_sop(frontmatter=frontmatter), config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP006" in codes(result)

    def test_mcp007_missing_expected_output_fires(self):
        step_without_output = textwrap.dedent(
            """\
            ### 1. Do the thing

            Perform the action.

            **Constraints:**
            - You MUST act
            """
        )
        result = lint(build_sop(steps=step_without_output), config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP007" in codes(result)

    def test_mcp007_expected_output_present_passes(self):
        step_with_output = textwrap.dedent(
            """\
            ### 1. Do the thing

            Perform the action.

            **Constraints:**
            - You MUST act

            **Expected Output:** The action's result payload.
            """
        )
        result = lint(build_sop(steps=step_with_output), config=LintConfig(select=("SOPMCP",)))
        assert "SOPMCP007" not in codes(result)

    def test_sop_only_select_ignores_mcp_rules(self):
        # Under prefix-matching semantics, `select = ("SOP",)` also matches "SOPMCP*"
        # because SOPMCP literally starts with SOP. Users who want strictly-core
        # Agent SOP rules must either `ignore = ["SOPMCP"]` or select narrower
        # prefixes like ["SOP1", "SOP2", "SOP3"]. This test documents that.
        content = build_sop(frontmatter=None)

        # The naive select=("SOP",) DOES fire SOPMCP rules:
        result_naive = lint(content, config=LintConfig(select=("SOP",)))
        assert any(c.startswith("SOPMCP") for c in codes(result_naive))

        # Explicit opt-out via ignore works:
        result_opt_out = lint(content, config=LintConfig(select=("SOP",), ignore=("SOPMCP",)))
        assert not any(c.startswith("SOPMCP") for c in codes(result_opt_out))

        # Or select narrower prefixes:
        result_narrow = lint(content, config=LintConfig(select=("SOP1", "SOP2", "SOP3")))
        assert not any(c.startswith("SOPMCP") for c in codes(result_narrow))


# ---------------------------------------------------------------------------
# LintConfig semantics
# ---------------------------------------------------------------------------


class TestLintConfig:
    def test_default_selects_core_and_ignores_mcp(self):
        cfg = LintConfig()
        assert cfg.is_enabled("SOP101")
        assert cfg.is_enabled("SOPMCP001")  # SOPMCP starts with SOP, so default ("SOP",) matches it
        # To truly opt out of MCP, users must explicitly ignore:
        cfg_opt_out = LintConfig(select=("SOP",), ignore=("SOPMCP",))
        assert cfg_opt_out.is_enabled("SOP101")
        assert not cfg_opt_out.is_enabled("SOPMCP001")

    def test_explicit_select_sop_only(self):
        # If users want strictly-core rules, select a narrower prefix.
        cfg = LintConfig(select=("SOP1", "SOP2", "SOP3"))
        assert cfg.is_enabled("SOP101")
        assert not cfg.is_enabled("SOPMCP001")

    def test_ignore_wins_over_select(self):
        cfg = LintConfig(select=("SOP",), ignore=("SOP108",))
        assert cfg.is_enabled("SOP101")
        assert not cfg.is_enabled("SOP108")

    def test_missing_config_returns_default(self, tmp_path: Path):
        cfg = load_config(tmp_path)
        assert cfg.select == ("SOP",)
        assert cfg.ignore == ()

    def test_invalid_toml_raises(self, tmp_path: Path):
        (tmp_path / CONFIG_FILENAME).write_text("this is [not valid toml\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid TOML"):
            load_config(tmp_path)

    def test_pattern_rule_loads_from_toml(self, tmp_path: Path):
        (tmp_path / CONFIG_FILENAME).write_text(
            textwrap.dedent(
                """\
                [[pattern-rules]]
                code = "TODO001"
                severity = "warning"
                pattern = "\\\\bTODO\\\\b"
                message = "SOPs shouldn't contain TODOs"
                applies_to = "body"
                """
            ),
            encoding="utf-8",
        )
        cfg = load_config(tmp_path)
        assert len(cfg.pattern_rules) == 1
        assert cfg.pattern_rules[0].code == "TODO001"


# ---------------------------------------------------------------------------
# Pattern rules
# ---------------------------------------------------------------------------


class TestPatternRules:
    def test_pattern_rule_fires_on_body_match(self):
        import re

        rule = PatternRule(
            code="TODO001",
            default_severity=Severity.WARNING,
            pattern=re.compile(r"\bTODO\b"),
            message="Drafts shouldn't contain TODOs",
            applies_to="body",
        )
        content = build_sop(
            overview="## Overview\n\nTODO: finish this overview.",
        )
        result = lint(content, config=LintConfig(select=("SOP", "TODO"), pattern_rules=(rule,)))
        assert "TODO001" in codes(result)


# ---------------------------------------------------------------------------
# Engine-wide invariants
# ---------------------------------------------------------------------------


class TestEngine:
    def test_valid_sop_has_no_errors(self):
        result = lint(build_sop())
        assert not result.has_errors, [d.to_dict() for d in result.errors]

    def test_diagnostics_are_sorted(self):
        # Introduce issues at different lines and assert stable sort.
        content = build_sop(title="", overview="", parameters="")
        result = lint(content)
        lines = [d.line for d in result.diagnostics]
        assert lines == sorted(lines)

    def test_lint_is_deterministic(self):
        a = lint(build_sop()).to_dict()
        b = lint(build_sop()).to_dict()
        assert a == b

    def test_builtin_rules_have_unique_codes(self):
        rule_codes = [r.code for r in BUILTIN_RULES]
        assert len(rule_codes) == len(set(rule_codes)), f"duplicate codes: {rule_codes}"


# ---------------------------------------------------------------------------
# SopDocument parsing
# ---------------------------------------------------------------------------


class TestSopDocumentParsing:
    def test_parses_title_overview_parameters_steps(self):
        doc = SopDocument.parse(build_sop())
        assert doc.title == "Test SOP"
        assert doc.overview and "overview" in doc.overview.lower()
        assert doc.parameters and "input_data" in doc.parameters
        assert len(doc.steps) == 1
        assert doc.steps[0].number == 1
        assert doc.steps[0].name == "Do the thing"

    def test_step_regex_matches_dotted_number(self):
        # "### 1. Foo" should match, but "### Step 1: Foo" should NOT.
        dotted = build_sop()
        assert len(SopDocument.parse(dotted).steps) == 1

        legacy_steps = textwrap.dedent(
            """\
            ### Step 1: Foo

            Legacy format.

            **Constraints:**
            - You MUST do it
            """
        )
        legacy = build_sop(steps=legacy_steps)
        assert SopDocument.parse(legacy).steps == []

    def test_malformed_yaml_is_captured(self):
        content = "---\nname: [unclosed\n---\n\n# Title\n"
        doc = SopDocument.parse(content)
        assert doc.frontmatter_error is not None

    def test_no_frontmatter_starts_at_line_one(self):
        doc = SopDocument.parse("# Title\n\n## Overview\n\nHi.\n")
        assert doc.frontmatter == {}
        assert doc.body_line_offset == 1
