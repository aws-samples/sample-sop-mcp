# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sop-lint — rule-based static analysis for Agent SOP markdown.

Sibling package to ``sop_mcp``. The two live in the same repository
but are intentionally import-isolated:

- ``sop_lint`` has no dependency on ``sop_mcp`` — the CLI and
  pre-commit hook work standalone.
- ``sop_mcp`` imports ``sop_lint`` at one narrow boundary
  (``publish_sop``) so publishing an SOP runs the same rule set as
  the CLI and pre-commit hook, preventing drift.

Usage as a library::

    from sop_lint import lint, load_config

    result = lint(open("my.sop.md").read())
    for d in result.errors:
        print(d.code, d.message)

Usage as a CLI::

    # ad-hoc, from the sample-sop-mcp repo (sop-lint ships inside it)
    uvx --from git+https://github.com/aws-samples/sample-sop-mcp sop-lint path/to/file.sop.md
    # from a clone / local dev checkout
    uv run sop-lint dir/ --format json

Usage as a pre-commit hook — see ``.pre-commit-hooks.yaml``.
"""

from .engine import (
    BUILTIN_RULES,
    CONFIG_FILENAME,
    Diagnostic,
    LintConfig,
    LintResult,
    PatternRule,
    Severity,
    SopDocument,
    lint,
    load_config,
    load_config_file,
)

__all__ = [
    "BUILTIN_RULES",
    "CONFIG_FILENAME",
    "Diagnostic",
    "LintConfig",
    "LintResult",
    "PatternRule",
    "Severity",
    "SopDocument",
    "lint",
    "load_config",
    "load_config_file",
]
