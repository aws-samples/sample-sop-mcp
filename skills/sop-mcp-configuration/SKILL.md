---
name: sop-mcp-configuration
description: Configure SOP-MCP server for step-by-step SOP execution in any MCP client
version: 1
author: Amazon Web Services
tags: [mcp, automation, sop, configuration]
activation: manual
---

# SOP-MCP Configuration Skill

## When to Use This Skill
Use this skill when you need to:
- Configure SOP-MCP server in any MCP client
- Set up custom SOP storage locations
- Troubleshoot MCP server configuration

## Quick Start

### Basic Configuration
Add this to your MCP client's configuration file:

```json
{
  "mcpServers": {
    "sop-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/aws-samples/sample-sop-mcp", "sop-mcp"]
    }
  }
}
```

### With Custom Storage
```json
{
  "mcpServers": {
    "sop-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/aws-samples/sample-sop-mcp", "sop-mcp"],
      "env": {
        "SOP_STORAGE_DIR": "/path/to/your/sops"
      }
    }
  }
}
```

---

## Environment Variables

| Variable          | Purpose                   | Default                                              |
| ----------------- | ------------------------- | ---------------------------------------------------- |
| `SOP_STORAGE_DIR` | Directory for SOP storage | `~/.sop_mcp` (seeded from bundled SOPs on first run) |

---

## Verification

After configuring, test with:
```
run_sop(sop_name="sop_creation_guide")
```

Expected output:
```
Step 1 of 7: [instructions...]
```

---

## Troubleshooting

### Server won't start
- Check `uvx` is installed: `which uvx`
- Verify Python 3.11+: `python --version`

### Tools not appearing
- Verify JSON syntax in your configuration
- Restart your MCP client after config changes

---

## References
- [Project README](../../README.md)
