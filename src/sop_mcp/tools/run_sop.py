# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Start or advance a Standard Operating Procedure."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from sop_mcp.utils import SOP
from sop_mcp.utils.storage import LocalFilesystemBackend

logger = logging.getLogger(__name__)

backend = LocalFilesystemBackend.from_env()

NAME = "run_sop"
DESCRIPTION = (
    "Start or advance a Standard Operating Procedure step by step. "
    "Use list_resources to discover available SOPs, then call this tool with the SOP name.\n\n"
    "Each call returns one step. Execute the step, then call again with current_step "
    "incremented to advance.\n\n"
    "IMPORTANT: You MUST execute ALL actions described in the returned step content. "
    "Do NOT just read or summarize the step — perform the actions using your available tools.\n\n"
    "When continuing (current_step >= 1), you MUST provide step_output with the concrete "
    "output you produced for the completed step."
)

# Hard cap on step_output size. 50 KB fits any reasonable step summary or
# artifact reference; anything larger is almost certainly accidental log
# dumping or a malicious payload trying to bloat server-side state.
MAX_STEP_OUTPUT_BYTES = 50 * 1024


def handler(
    sop_name: Annotated[str, "Name of the SOP to execute (use list_resources to discover available SOPs)"],
    current_step: Annotated[int, "Step number to advance from. 0 to start, N to advance past step N"] = 0,
    step_output: Annotated[
        str | None, "Concrete output you produced for the completed step. Required when current_step >= 1"
    ] = None,
) -> dict[str, Any]:
    """Start or advance an SOP — returns the next step."""
    logger.info("Invoking run_sop: sop_name=%s, current_step=%s", sop_name, current_step)

    if not backend.sop_exists(sop_name):
        raise ValueError(f"SOP '{sop_name}' not found. Available: {', '.join(backend.list_sops())}")

    if current_step >= 1 and not step_output:
        raise ValueError(
            "step_output is required when current_step >= 1. "
            "Provide the concrete output you produced for the completed step."
        )

    if step_output is not None and len(step_output.encode("utf-8")) > MAX_STEP_OUTPUT_BYTES:
        raise ValueError(
            f"step_output exceeds {MAX_STEP_OUTPUT_BYTES} bytes "
            f"({len(step_output.encode('utf-8'))} received). "
            "Summarise the step output instead of including full logs or artifacts."
        )

    sop = SOP(sop_name, base_dir=backend.base_dir)
    total = sop.total_steps

    if current_step < 0 or current_step > total:
        raise ValueError(f"current_step must be 0-{total} for '{sop_name}' (v{sop.version}), got {current_step}")

    response: dict[str, Any] = {
        "sop_name": sop.name,
        "sop_version": sop.version,
        "current_step": current_step,
        "total_steps": total,
    }

    if current_step == total:
        response["instruction"] = "SOP execution complete."
        return response

    next_step = current_step + 1
    logger.info("run_sop(%s) step %d/%d", sop_name, next_step, total)

    instruction = ""
    if next_step == 1:
        instruction += f"You are executing: {sop.title}\nTotal steps: {total}\nOverview: {sop.overview}\n\n---\n\n"
    instruction += f"Step {next_step} of {total}\n\n{sop.steps[current_step]}"

    instruction += "\n\n---\n\n"
    instruction += "⚠️ EXECUTION RULES — YOU MUST FOLLOW THESE BEFORE ADVANCING:\n"
    instruction += (
        "1. You MUST fully execute ALL actions described in this step and produce the concrete expected output.\n"
    )
    instruction += "2. You MUST NOT call run_sop to advance to the next step until you have completed this step.\n"
    instruction += "3. You MUST NOT skip, summarize, or batch multiple steps together.\n"
    instruction += (
        "4. Only after you have produced the expected output for this step "
        "should you call `run_sop` with current_step incremented.\n"
    )

    response["instruction"] = instruction
    return response
