---
name: code_review_process
description: Standard process for conducting code reviews to keep code quality, consistency, and knowledge sharing across the team.
version: 1
owner: Engineering Team
stage: preprod
---

# Standard Operating Procedure: Code Review Process

## Overview

Standard process for conducting code reviews to keep code quality, consistency, and knowledge sharing across the team.

## Parameters

- **code_review_id** (required): The identifier of the code review being prepared, reviewed, or merged.
- **reviewer** (optional): Slack handle or email of the assigned reviewer. Defaults to the team's on-call reviewer.

## Steps

### 1. Prepare Changes for Review

Ensure code changes are ready for peer review. Run unit tests and the linter locally, write a clear commit message following conventional commits, and open the review with a descriptive title and summary.

**Constraints:**
- You MUST run all tests before submitting for review
- You MUST include a description of what changed and why
- You SHOULD keep changes focused on a single concern
- You MAY include screenshots for UI changes

**Expected Output:** The review identifier, a confirmation that all tests passed locally, the conventional-commit subject line, and the list of assigned reviewers.

**Time Estimate:** 10-15 minutes

### 2. Conduct the Review

Review code changes for correctness, readability, and adherence to standards. Read the CR description first, then walk each file for correctness and style, check edge cases and error handling, verify test coverage, and leave constructive comments with specific suggestions.

**Constraints:**
- You MUST review within 24 hours of being assigned
- You MUST provide actionable feedback with specific suggestions
- You SHOULD approve only when all critical issues are resolved
- You MAY suggest improvements that are not blocking

**Expected Output:** A review verdict (approve / request changes / comment-only) and a list of the comments posted, each linked to a specific file and line.

**Time Estimate:** 20-45 minutes

### 3. Address Feedback and Merge

Resolve review feedback and merge the changes. Address every critical comment, respond to each with the resolution, request re-review if significant changes were made, and merge once approved.

**Constraints:**
- You MUST address all blocking comments before merging
- You MUST obtain at least one approval before merging
- You SHOULD squash commits for a clean history
- You MAY merge without re-review for minor fixes

**Expected Output:** The merge commit hash, the count of review comments resolved, and the final state of the CR (merged).

**Time Estimate:** 10-20 minutes
