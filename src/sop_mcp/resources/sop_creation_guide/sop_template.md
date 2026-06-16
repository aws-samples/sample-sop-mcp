---
name: todo_replace_with_snake_case_name
description: TODO — one sentence describing what this SOP does.
version: 1
owner: todo-team-or-alias
stage: preprod
---

# TODO: SOP Title in Title Case

## Overview

TODO: 1–3 plain-prose sentences summarising what this SOP does and when to use it. Max 500 characters. Do not use lists, tables, code blocks, or sub-sections here — structured content belongs inside a step.

## Parameters

- **todo_required_param** (required): TODO — what this input is and how it gets used.
- **todo_optional_param** (optional, default: false): TODO — what this input is and how it gets used when set.

## Steps

### 1. TODO: First step name

TODO: One paragraph describing what this step accomplishes. The description is the "what"; the Constraints block below is the "how". Keep each step small enough that an agent can reason about it in isolation.

**Constraints:**
- You MUST TODO — state a positive requirement using MUST, SHOULD, or MAY.
- You MUST NOT TODO, because TODO — every negative constraint must end with a reason clause (`because …`, `since …`, `to avoid …`).
- You SHOULD TODO — state a softer recommendation the agent should follow by default.
- You MAY TODO — state an optional behaviour that's fine to skip.

**Example Input:** `todo_required_param=example_value`
**Example Output:** `TODO — what a successful invocation of this step returns.`

**Expected Output:** TODO — list the concrete fields or values this step must produce, one per line, so the next step can consume them as context.

**Time Estimate:** TODO — estimated duration, e.g. `5 minutes`.

### 2. TODO: Second step name

TODO: Describe what this step does. If you find yourself writing more than ~5 sentences, split into multiple steps — one action per step keeps the SOP easy to follow.

**Constraints:**
- You MUST TODO — positive requirement.
- You MUST NOT TODO, because TODO — reason for the prohibition.
- You SHOULD TODO — recommendation.

**Example Input:** `todo_required_param=another_example`
**Example Output:** `TODO — what a successful invocation returns.`

**Expected Output:** TODO — the concrete deliverable of this step.

**Time Estimate:** TODO — estimated duration, e.g. `10 minutes`.
