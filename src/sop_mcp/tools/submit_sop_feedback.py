# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Submit SOP feedback tool."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from sop_mcp.utils import SOP
from sop_mcp.utils.storage import LocalFilesystemBackend

logger = logging.getLogger(__name__)


backend = LocalFilesystemBackend.from_env()

NAME = "submit_sop_feedback"
DESCRIPTION = (
    "Submit improvement feedback for a specific SOP.\n\n"
    "Feedback is appended as a single JSON line to\n"
    "{sop_name}.feedback.jsonl inside the SOP's folder. Each entry\n"
    "captures the SOP version, a UTC timestamp, and the feedback text — ready\n"
    "for review when the SOP is next revised."
)

# Hard cap on feedback text size. Mirrors the input caps on run_sop
# (step_output, 50 KB) and publish_sop (content, 1 MB). Feedback is an
# append-only log on disk, so unbounded text lets a caller grow the
# *.feedback.jsonl file without limit — a local disk-exhaustion vector.
# 50 KB is far larger than any genuine review note.
MAX_FEEDBACK_BYTES = 50 * 1024


def handler(
    sop_name: Annotated[str, "Name of the SOP to submit feedback for"],
    feedback: Annotated[str, "Improvement feedback text — what worked, what needs fixing"],
) -> dict[str, Any]:
    """Record feedback for an SOP as a JSON line in the feedback log."""
    logger.info("Invoking submit_sop_feedback: sop_name=%s, feedback=<%s chars>", sop_name, len(feedback))

    if not backend.sop_exists(sop_name):
        raise ValueError(f"SOP '{sop_name}' not found. Available: {', '.join(backend.list_sops())}")

    feedback_bytes = len(feedback.encode("utf-8"))
    if feedback_bytes > MAX_FEEDBACK_BYTES:
        raise ValueError(
            f"feedback exceeds {MAX_FEEDBACK_BYTES} bytes ({feedback_bytes} received). "
            "Summarise the feedback instead of including full logs or artifacts."
        )

    sop = SOP.from_content(backend.read_sop(sop_name))
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry = {
        "timestamp": timestamp,
        "sop_version": sop.version,
        "stage": sop.stage,
        "feedback": feedback,
    }

    try:
        backend.append_feedback(sop_name, entry)
    except OSError as e:
        logger.warning("Failed to write feedback for %s: %s", sop_name, e)
        return {"error": f"Failed to write feedback file: {e}"}

    logger.info("Feedback recorded for %s v%s at %s", sop_name, sop.version, timestamp)
    return {
        "success": True,
        "sop_name": sop_name,
        "sop_version": sop.version,
        "timestamp": timestamp,
        "message": f"Feedback recorded for '{sop_name}'.",
    }
