---
name: sop-mcp-usage
description: How to use the SOP-MCP server to execute, create, and improve Standard Operating Procedures
version: 1
author: Amazon Web Services
tags: [mcp, sop, execution, workflow]
activation: manual
---

# Using SOP-MCP

## When to Use This Skill

Use this skill when you need to:
- Execute an existing SOP step by step
- Create and publish a new SOP
- Submit feedback to improve an SOP
- Discover what SOPs are available

## Prerequisites

Before using this skill, ensure:
- SOP-MCP server is installed and running (see [`sop-mcp-configuration`](../sop-mcp-configuration/SKILL.md))
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
3. **Follow RFC 2119 keywords** — MUST = mandatory, SHOULD = recommended, MAY = optional
4. **One step at a time** — you cannot see ahead or batch steps

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

| Tool                  | Purpose                        |
| --------------------- | ------------------------------ |
| `run_sop`             | Execute an SOP step by step    |
| `publish_sop`         | Create or update an SOP        |
| `submit_sop_feedback` | Record improvement suggestions |
| `list_resources`      | Discover available SOPs        |
| `read_resource`       | Read an SOP's full content     |

---

## Tips

- Start with `list_resources` to see what's available
- Use `read_resource(uri="sop://name")` to preview an SOP before executing
- After completing an SOP, offer to submit feedback
- When creating SOPs, use the `sop_creation_guide` SOP itself as a guide
