# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""``sop-lint`` — standalone CLI for the SOP lint engine.

Runs the same rule engine that the ``sop_mcp`` server's ``publish_sop``
tool uses for pre-write validation, so a SOP that passes ``sop-lint``
at commit time will also pass ``publish_sop`` at runtime.

Usage::

    sop-lint path/to/file.sop.md           # lint one file
    sop-lint dir/                           # lint every *.sop.md under dir
    sop-lint file1.sop.md file2.sop.md      # multiple explicit paths
    sop-lint --config /custom/sop-lint.toml file.sop.md
    sop-lint --format json file.sop.md      # machine-readable output
    sop-lint --select SOP0 --select SOP1 .  # override select at the CLI
    sop-lint --ignore SOP204 .

Exit codes follow ruff / flake8 conventions:

- 0 — no diagnostics, or only ``info``-level diagnostics
- 1 — at least one ``error``-severity diagnostic
- 2 — at least one ``warning``-severity diagnostic (but no errors)
- 3 — usage error (bad arguments, path not found, config invalid)

pre-commit integration: see ``.pre-commit-hooks.yaml`` at the repo root.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from sop_lint.engine import (
    CONFIG_FILENAME,
    LintConfig,
    LintResult,
    Severity,
    lint,
    load_config,
    load_config_file,
)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sop-lint",
        description="Lint Agent SOP markdown files using the same rule engine as the MCP server.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="File or directory paths. Directories are walked recursively for *.sop.md files.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            f"Path to a {CONFIG_FILENAME} file. When omitted, the CLI looks for "
            "the file in the first ancestor directory containing it (starting from "
            "the first path argument) and falls back to defaults if none is found."
        ),
    )
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="CODE",
        help="Enable a rule family by prefix (e.g. `--select SOP0`). Repeatable. Overrides config.",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="CODE",
        help="Ignore a rule code or prefix. Repeatable. Overrides config. Wins over --select.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. `text` (default) is human-readable; `json` is machine-parseable.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output when every file passes. Useful in pre-commit.",
    )
    return parser


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


SOP_SUFFIX = ".sop.md"


def _collect_files(paths: list[str]) -> list[Path]:
    """Resolve user-provided paths into a sorted list of ``*.sop.md`` files.

    Directories are walked recursively; individual file paths are kept
    as-is. Raises ``FileNotFoundError`` for paths that don't exist so
    the CLI can exit with a usage error.
    """
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {raw}")
        if p.is_file():
            files.append(p)
        else:
            files.extend(sorted(p.rglob(f"*{SOP_SUFFIX}")))
    # Deduplicate while preserving order.
    seen: set[Path] = set()
    deduped: list[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(f)
    return deduped


def _discover_config(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a ``sop-lint.toml`` file.

    Mirrors ruff's config discovery: search from the target's parent
    directory upward until a config is found or the filesystem root is
    reached.
    """
    current = start.resolve() if start.is_dir() else start.resolve().parent
    for candidate_dir in (current, *current.parents):
        candidate = candidate_dir / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Config loading for the CLI
# ---------------------------------------------------------------------------


def _load_cli_config(args: argparse.Namespace, files: list[Path]) -> LintConfig:
    """Resolve the config file, then layer CLI overrides on top."""
    if args.config is not None:
        if not args.config.is_file():
            raise FileNotFoundError(f"--config path not found: {args.config}")
        base_config = load_config_file(args.config)
    elif files:
        discovered = _discover_config(files[0])
        base_config = load_config(discovered.parent) if discovered is not None else LintConfig()
    else:
        base_config = LintConfig()

    # Apply CLI overrides. CLI --select fully replaces config select
    # (ruff behaviour); --ignore extends the existing list.
    select = tuple(args.select) if args.select else base_config.select
    ignore = base_config.ignore + tuple(args.ignore)
    return replace(base_config, select=select, ignore=ignore)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


_SEVERITY_LABEL = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}


def _format_text(file: Path, result: LintResult) -> str:
    lines: list[str] = []
    for d in result.diagnostics:
        lines.append(f"{file}:{d.line}: {_SEVERITY_LABEL[d.severity]} [{d.code}] {d.message}")
        if d.suggestion:
            lines.append(f"    suggestion: {d.suggestion}")
    return "\n".join(lines)


def _format_json(per_file: list[tuple[Path, LintResult]]) -> str:
    payload = [
        {
            "path": str(file),
            "summary": result.summary(),
            "diagnostics": [d.to_dict() for d in result.diagnostics],
        }
        for file, result in per_file
    ]
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _exit_code_for(results: list[LintResult]) -> int:
    """0 clean / 1 errors / 2 warnings only."""
    if any(r.has_errors for r in results):
        return 1
    if any(r.warnings for r in results):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns an exit code so callers can ``sys.exit(main(...))``."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        files = _collect_files(args.paths)
    except FileNotFoundError as exc:
        print(f"sop-lint: {exc}", file=sys.stderr)
        return 3

    if not files:
        print("sop-lint: no *.sop.md files found in the given paths", file=sys.stderr)
        return 3

    try:
        config = _load_cli_config(args, files)
    except (FileNotFoundError, ValueError) as exc:
        print(f"sop-lint: {exc}", file=sys.stderr)
        return 3

    per_file: list[tuple[Path, LintResult]] = []
    for file in files:
        try:
            content = file.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"sop-lint: cannot read {file}: {exc}", file=sys.stderr)
            return 3
        result = lint(content, config=config, path=file)
        per_file.append((file, result))

    exit_code = _exit_code_for([r for _, r in per_file])

    # Output
    if args.format == "json":
        print(_format_json(per_file))
    else:
        has_any_diagnostic = any(r.diagnostics for _, r in per_file)
        if has_any_diagnostic:
            chunks = [_format_text(f, r) for f, r in per_file if r.diagnostics]
            print("\n".join(chunks))
            totals = _aggregate_totals(per_file)
            print(
                f"\nChecked {len(files)} file(s): "
                f"{totals['errors']} error(s), {totals['warnings']} warning(s), "
                f"{totals['infos']} info(s)"
            )
        elif not args.quiet:
            print(f"sop-lint: {len(files)} file(s) clean.")

    return exit_code


def _aggregate_totals(per_file: list[tuple[Path, LintResult]]) -> dict[str, int]:
    totals = {"errors": 0, "warnings": 0, "infos": 0}
    for _, result in per_file:
        summary = result.summary()
        for key in totals:
            totals[key] += summary[key]
    return totals


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
