---
name: sop_creation_guide
description: An interactive, guided walkthrough that helps a human author a lint-clean Agent SOP step by step — gathering details, drafting, linting, reviewing, and publishing via publish_sop.
version: 3
owner: sop-mcp
stage: preprod
---

# Standard Operating Procedure: Creating Standard Operating Procedures

## Overview

A guided, interactive walkthrough for authoring an Agent SOP from scratch. It turns SOP creation into a conversation: at each stage you explain what is happening to the author, ask clarifying questions, wait for their answers, and validate the result against the sop-mcp format before moving on. The end product is a lint-clean SOP that passes publish_sop, has been reviewed by real people, and is ready to run.

## Parameters

- **process_name** (required): Short descriptive name of the process the SOP will describe. Used to derive the SOP's `name` frontmatter field.
- **process_owner** (required): Team or alias that owns the process. Populates the `owner` frontmatter field.
- **interaction_mode** (optional, default: guided): How much to pause for the author. `guided` confirms after every step; `express` batches questions and confirms less often.

## Steps

### 1. Orient the Author and Confirm Readiness

Open the session by setting expectations. Tell the author this is a collaborative walkthrough, name the stages you will move through together (gather, draft, lint, review, publish, feedback), and make sure they have the two required inputs. This step builds shared context — no drafting happens yet.

**Constraints:**
- You MUST greet the author and explain, in plain language, the stages this guide will move through so they know what to expect.
- You MUST confirm the `process_name` and `process_owner` parameters with the author, asking for either one that was not supplied.
- You MUST ask whether the process is a genuine fit for an SOP — repeatable and multi-step — and wait for the answer before continuing.
- You MUST NOT begin drafting the SOP in this step because its only job is to establish shared context and scope.
- You SHOULD restate your understanding of the process in one or two sentences and ask the author to confirm or correct it.
- You MAY propose a snake_case `name` derived from `process_name` for the author to approve.

**Expected Output:** A confirmed process name, owner, and one-line scope statement, plus the author's explicit go-ahead to start gathering details.

**Time Estimate:** 5-10 minutes

### 2. Interview the Author and Gather Source Material

Collect the raw material the SOP will be built from. Ask focused questions one cluster at a time, listen, and reflect answers back so nothing is lost. The goal is a faithful picture of how the process actually runs, not how someone imagines it runs.

**Constraints:**
- You MUST ask who performs the process, how often, and what triggers it, then wait for the responses before asking the next cluster of questions.
- You MUST collect any existing documentation, tickets, or screenshots the author can point you to.
- You MUST identify explicit scope boundaries (what is in scope and what is out) and read them back for confirmation.
- You SHOULD ask the author to narrate one real end-to-end run so no implicit step is missed.
- You SHOULD capture the concrete output or success signal of the overall process.
- You MUST NOT invent steps the author did not describe because fabricated steps make the SOP misleading and unsafe to follow.

**Expected Output:** A structured process summary covering actors, frequency, trigger, in-scope and out-of-scope boundaries, an end-to-end narrative, and the overall success signal.

**Time Estimate:** 30-60 minutes

### 3. Draft the SOP Together

Translate the summary into a draft that follows the sop-mcp format, building it with the author rather than for them. Show each part as you write it and fold in their corrections — their domain knowledge is the source of truth and yours is the format.

**Constraints:**
- You MUST structure the file with `# Title`, `## Overview`, `## Parameters`, and `## Steps`, using `### N. Step Name` headings (number-dot-space, no "Step" keyword).
- You MUST give every step a description paragraph, a `**Constraints:**` block using RFC 2119 keyword levels (MUST, SHOULD, MAY and their negative forms), and an `**Expected Output:**` marker.
- You MUST end every negative constraint with a `because …` or `since …` clause so the author and future readers understand the restriction.
- You MUST write each step to stand alone because the executor sees only one step at a time and cannot rely on earlier context.
- You MUST show the author each drafted step and ask for corrections before drafting the next, since their knowledge is what makes the SOP accurate.
- You SHOULD keep 3–7 constraints per step and split anything larger into multiple steps.
- You MAY add `## Examples` or `## Troubleshooting` sections when they add real value.

**Expected Output:** A complete draft SOP markdown file, reviewed section by section with the author and saved to a path you can lint.

**Time Estimate:** 30-90 minutes

### 4. Lint the Draft and Resolve Findings

Validate the draft with the `lint_sop` MCP tool and work through the findings with the author. Treat each finding as a teaching moment: explain what it means, propose a fix, and confirm before changing their words. `lint_sop` runs the exact engine that `publish_sop` enforces at write time, so a clean result here means a clean publish later.

**Constraints:**
- You MUST call the `lint_sop` MCP tool with the draft content and read every diagnostic it returns.
- You MUST resolve all errors before proceeding because publish_sop runs the same engine and will reject a draft that still has errors.
- You MUST explain each finding to the author in plain language and confirm the fix rather than silently rewriting their content.
- You MUST NOT dismiss SOP204 negative-constraint-context findings because a constraint without a rationale cannot be audited or justified.
- You SHOULD resolve warnings as well, since they signal drift from the format conventions.
- You SHOULD re-run `lint_sop` after edits to confirm the fixes landed and introduced no new findings.
- You MAY leave a specific warning unresolved only when you and the author agree on a documented reason.

**Expected Output:** A `lint_sop` result reporting `passed: true` (zero errors) and a short note listing any warnings intentionally left and why.

**Time Estimate:** 10-20 minutes

### 5. Review with Real People

Put the draft in front of people before it ships. Get a technical check from someone who knows the process and a clarity check from someone who does not. Loop any material feedback back into the draft and re-lint, because edits can reintroduce errors.

**Constraints:**
- You MUST arrange at least one subject-matter-expert review for technical accuracy.
- You MUST arrange at least one end-user review for clarity from someone who has not performed the process before.
- You MUST feed material review feedback back into the draft and re-run sop-lint because edits can reintroduce lint errors.
- You SHOULD run a dry run where a reviewer follows only the SOP, with no extra help, to surface hidden gaps.
- You MUST NOT publish while a reviewer's blocking concern is open because shipping an inaccurate SOP can cause downstream errors.

**Expected Output:** Documented SME and end-user approvals, a list of resolved feedback items, and confirmation the draft still lints clean.

**Time Estimate:** 1-3 days (elapsed; ~30 min active)

### 6. Publish the SOP

Publish the reviewed draft through the MCP tool and confirm the result with the author. Publishing is the point of no easy return for `prod`, so confirm the stage explicitly before you call the tool.

**Constraints:**
- You MUST publish using the `publish_sop` MCP tool, which re-runs sop-lint and rejects any draft that still has errors.
- You MUST confirm the target `stage` (preprod or prod) with the author before publishing, since stage controls the SOP's visibility and priority.
- You MUST NOT publish to `prod` without the owner's explicit approval because production SOPs are treated as authoritative by everyone who runs them.
- You SHOULD agree a review cadence with the owner, for example quarterly for new processes and annually for stable ones.
- You MAY notify stakeholders once the publish succeeds.

**Expected Output:** The published SOP's name, assigned version, stage, and storage path returned by publish_sop, shared back with the author.

**Time Estimate:** 5 minutes

### 7. Capture Feedback and Close the Loop

Finish by reflecting on the experience while it is fresh. Ask the author what helped and what was awkward, record it, and confirm it was saved so the next revision can build on it.

**Constraints:**
- You MUST ask the author what worked well and what was awkward about the authoring experience.
- You SHOULD record the feedback via `submit_sop_feedback` with specific, actionable observations.
- You SHOULD include both strengths and improvement areas so future revisions stay balanced.
- You MUST NOT end the session before confirming submit_sop_feedback accepted the entry because unsubmitted feedback is silently lost.
- You MAY link downstream artefacts such as wiki pages or tickets that now reference the SOP.

**Expected Output:** Confirmation that submit_sop_feedback accepted the entry, naming the SOP and version, plus a one-line summary of the author's experience.

**Time Estimate:** 5-10 minutes
