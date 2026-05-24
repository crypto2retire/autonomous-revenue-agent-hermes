# Render MCP Server Setup

Connect your AI coding tools directly to Render for natural language infrastructure management.

## What It Does

- Create/manage services with natural language
- Query your PostgreSQL database
- Analyze logs and metrics
- Auto-deploy from GitHub

## 1. Create Render API Key

1. Go to https://dashboard.render.com/u/settings?add-api-key
2. Generate new key
3. Copy it (starts with `rnd_`)

## 2. Configure Your AI Tool

### Claude Code (Recommended)

```bash
claude mcp add --transport http render https://mcp.render.com/mcp --header "Authorization: Bearer rnd_xxxxxxxxxx"
```

### Cursor

`~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "render": {
      "url": "https://mcp.render.com/mcp",
      "headers": {
        "Authorization": "Bearer rnd_xxxxxxxxxx"
      }
    }
  }
}
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "render": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://mcp.render.com/mcp",
        "--header",
        "Authorization: Bearer rnd_xxxxxxxxxx"
      ]
    }
  }
}
```

## 3. Set Workspace

In your AI tool, say:
> "Set my Render workspace to [YOUR_WORKSPACE_NAME]"

## 4. Example Commands

| Task | Prompt |
|------|--------|
| Deploy this repo | "Deploy the crypto-trading-agent repo to Render" |
| Check database | "Query my agent-db for open positions" |
| View logs | "Show recent error logs for crypto-trading-agent" |
| Scale up | "Upgrade my database to pro-4gb" |
| Check status | "Is my trading agent service healthy?" |

## Security Note

API key grants access to all workspaces/services your account can access. Only destructive operation: modifying env vars. Store key securely.
