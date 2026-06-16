# Security Policy

## Reporting a Vulnerability

If you discover a potential security issue in this project, we ask that you notify AWS Security via our [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/).

Please do **not** create a public GitHub issue for security vulnerabilities.

## Security Model

sop-mcp is a local MCP server that communicates via stdio (stdin/stdout).

### Core Transport

- **No network exposure**: The server does not listen on any port or accept network connections.
- **No authentication required**: As a local subprocess, authentication is handled by the parent MCP client.
- **No credentials stored**: sop-mcp does not store, manage, or require any secrets or AWS credentials.
- **File system access**: Limited to the configured SOP storage directory (`SOP_STORAGE_DIR`, defaults to `~/.sop_mcp`).
- **No elevated privileges**: Runs with the same permissions as the invoking user process.
- **No subprocess execution**: The server does not spawn shell commands or make outbound network calls during normal operation.

### Content Trust & Input Limits

- **SOP content is untrusted**: The server serves SOP markdown to the agent verbatim and cannot distinguish a legitimate instruction from a malicious one. A crafted SOP in a shared or synced `SOP_STORAGE_DIR` could attempt to steer the executing agent (prompt injection). Review SOPs you did not author before running them, and keep a human in the loop for steps with real-world side effects.
- **Path containment**: User-supplied subdirectory and attachment paths are resolved and checked with `relative_to()` so they cannot escape `SOP_STORAGE_DIR`. SOP discovery and attachment listing also skip any symlinked file that resolves outside the storage root, so a symlink planted in a shared directory cannot redirect reads to out-of-tree files.
- **Input size limits**: `run_sop` caps `step_output` at 50 KB, `publish_sop` caps SOP content at 1 MB, and `submit_sop_feedback` caps feedback text at 50 KB; the storage scan stops after 10,000 SOP files. These bound memory/CPU/disk use against accidental or hostile oversized input.

### Dependencies

All dependencies are open-source and pinned in `uv.lock`:

| Package  | Purpose                        |
| -------- | ------------------------------ |
| pyyaml   | YAML parsing (SOP frontmatter) |
| pydantic | Data validation                |

### Static Analysis & Scanning

- **Ruff** with flake8-bandit (`S` rules) + debugger detection (`T10`) on every commit
- **Pre-commit hooks**: `detect-aws-credentials`, `detect-private-key`, `check-merge-conflict`
- **CI**: AWS Automated Security Helper (ASH) runs on every push/PR — aggregate SAST, secrets, dependency-CVE scanning
