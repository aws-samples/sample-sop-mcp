---
name: sop-mcp-usage
description: Execute, author, lint, and improve Standard Operating Procedures (SOPs) via the SOP-MCP server. Use when running an SOP step by step (run_sop), creating or validating a new SOP (lint_sop/publish_sop), submitting SOP feedback, or discovering available SOPs (list_resources / sop:// resources).
license: MIT-0
compatibility: Requires the SOP-MCP server configured in your MCP client.
metadata:
  author: Amazon Web Services
  version: "1"
---

# SOP-MCP Usage

SOP-MCP guides an agent through a Standard Operating Procedure one step at a time: each `run_sop` call returns a single step to execute before advancing. This skill covers running, authoring, linting, and improving SOPs through the server's tools.

## Usage

Use this skill when you need to:
- Execute an existing SOP step by step
- Create and publish a new SOP
- Submit feedback to improve an SOP
- Discover what SOPs are available

## Core Concepts

- **Step-gated execution** — `run_sop` returns one step at a time; you execute it and report `step_output` before the next step is released. You never see ahead.
- **RFC 2119 requirements** — each step states obligations with MUST / SHOULD / MAY.
- **SOPs are markdown + frontmatter** — identity is the frontmatter `name`; the body has an `## Overview` and `### Step` sections.
- **Tools and resources** — SOPs are exposed both as MCP resources (`sop://<name>`) and as tools (`list_resources`, `read_resource`), so discovery works in any client.
- **Lint-gated publish** — `publish_sop` runs the same rule engine as `lint_sop`; lint errors block the write.

## Prerequisites

Before using this skill, ensure:
- SOP-MCP server is installed and running (see the [project README](../../README.md))
- Your MCP client is configured to connect to the server
- You have access to the SOP-MCP tools — verify with `list_resources`

## Quick Start

### 1. Discover Available SOPs

```
list_resources
```

This returns all SOPs as `sop://` URIs with descriptions.

### 2. Execute an SOP

```
run_sop(sop_name="sop_creation_guide")
```

You'll receive Step 1 with instructions. **Execute the step**, then advance:

```
run_sop(sop_name="sop_creation_guide", current_step=1, step_output="Here's what I did...")
```

Repeat until you receive the completion message.

### 3. Create a New SOP

First validate the draft — `lint_sop` runs the exact rules `publish_sop` enforces, so a clean lint guarantees a clean publish:

```
lint_sop(content="<your full SOP markdown>")
```

When it reports `passed: true`, publish the same content:

```
publish_sop(content="---\nname: my_new_sop\nversion: 1\nowner: my-team\nstage: preprod\n---\n\n# My SOP\n\n## Overview\n\nWhat this SOP does.\n\n### Step 1: First Step\n\nInstructions here.\n", stage="preprod")
```

### 4. Submit Feedback

After completing an SOP, improve it:

```
submit_sop_feedback(sop_name="sop_creation_guide", feedback="Step 3 was unclear about...")
```

---

## Execution Rules

When executing an SOP via `run_sop`:

1. **Execute each step fully** — do not skip or summarize
2. **Provide step_output** — describe what you concretely produced
3. **Honor each step's RFC 2119 requirements** (MUST / SHOULD / MAY)
4. **One step at a time** — you cannot see ahead or batch steps

---

## Gotchas

Non-obvious facts that will trip you up if you assume otherwise:

- `run_sop` **requires `step_output` once `current_step >= 1`** — advancing without describing what you produced raises an error.
- `step_output` is **capped at 50 KB** — summarize, don't paste full logs or artifacts.
- `publish_sop` **does not trust your frontmatter**: it auto-bumps `version` server-side (max existing + 1), and the `stage` argument overrides the frontmatter `stage`. The stored file reflects those computed values; mismatches are surfaced under `warning`.
- `publish_sop` runs the linter and **lint errors block the write** (nothing is saved); warnings do not block. Run `lint_sop` first.
- An SOP `name` must be **snake_case with 3+ underscore-separated segments** (e.g. `user_onboarding_process`) or linting fails.
- The `## References` section is returned by `read_resource` but **skipped by `run_sop`** — the executing agent only sees `Overview` plus the current step.

---

## Safety

SOP content is served to the agent verbatim — the server can't tell a legitimate instruction from a malicious one. If your storage directory is shared, synced, or holds SOPs you didn't author, review an SOP before running it: a crafted SOP could steer the agent into unintended actions (prompt injection). Keep a human in the loop for any step with real-world side effects.

---

## SOP Markdown Format

SOPs use YAML frontmatter + markdown:

```markdown
---
name: my_process_name        # snake_case, 3+ segments
version: 1                   # auto-managed by publish_sop
owner: team-name             # who maintains this
stage: preprod               # preprod or prod
---

# Title

## Overview
What this SOP accomplishes.

### Step 1: Step Title

**Objective**: What this step achieves.

**Actions**:
1. Do this
2. Then this

**Requirements**:
- You MUST do X
- You SHOULD do Y
- You MAY do Z

**Expected Output**: What "done" looks like.

**Time Estimate**: 10-15 minutes
```

### Optional: Read-only References section

After all steps, you may add a `## References` section linking to source material (standards, design docs, wikis). It's served by `read_resource` so humans can trace provenance, but `run_sop` skips it — the executing agent only sees `Overview` plus the current step.

```markdown
## References

- [RFC 2119 — Key words for use in RFCs](https://www.rfc-editor.org/rfc/rfc2119)
- [Internal design doc](https://wiki.example.com/design)
```

---

## Tools Reference

| Tool                  | Purpose                                 |
| --------------------- | --------------------------------------- |
| `run_sop`             | Execute an SOP step by step             |
| `lint_sop`            | Validate a draft SOP without writing it |
| `publish_sop`         | Create or update an SOP                 |
| `submit_sop_feedback` | Record improvement suggestions          |
| `list_resources`      | Discover available SOPs                 |
| `read_resource`       | Read an SOP's full content              |

---

## Tips

- Start with `list_resources` to see what's available
- Use `read_resource(uri="sop://name")` to preview an SOP before executing
- After completing an SOP, offer to submit feedback
- When creating SOPs, use the `sop_creation_guide` SOP itself as a guide
