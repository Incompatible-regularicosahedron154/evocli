---
name: evocli-mcp-integration
description: "Use when connecting external MCP servers to EvoCLI or using EvoCLI as an MCP server for external AI clients."
---
# EvoCLI MCP Integration

EvoCLI fully supports the Model Context Protocol (MCP), allowing it to act as both an MCP Client (consuming tools from other servers) and an MCP Server (exposing its 117+ tools to other AI clients like Claude Desktop or Cursor).

## EvoCLI as an MCP Client

You can extend EvoCLI's capabilities by connecting it to any MCP-compliant server.

### Connecting a Server
Use the `evocli mcp connect` command:
```bash
evocli mcp connect postgres npx -y @modelcontextprotocol/server-postgres postgres://localhost:5432/mydb
```

### Tool Discovery
Once connected, the tools from the external server are prefixed with the server name and made available to the AI agent:
- `postgres.query_data`
- `postgres.list_tables`

### Managing Connections
- `evocli mcp list`: Show all connected MCP servers and their status.
- `evocli mcp disconnect <name>`: Remove a server.
- `evocli mcp refresh <name>`: Re-scan for new tools or resources.

## EvoCLI as an MCP Server

You can use EvoCLI's powerful Rust-backed tools inside other AI editors.

### Serving Tools
Run the following command to start the EvoCLI MCP server:
```bash
evocli mcp serve
```
This starts a stdio-based MCP server. You can then add this to your `claude_desktop_config.json` or Cursor settings.

### Configuration Example (Claude Desktop)
```json
{
  "mcpServers": {
    "evocli": {
      "command": "evocli",
      "args": ["mcp", "serve"]
    }
  }
}
```

## Resources and Prompts

EvoCLI also exposes its memory system and skill library as MCP Resources and Prompts.

- **Resources**: You can "read" the project's P1 memory as a resource: `mcp://evocli/memory/p1`.
- **Prompts**: EvoCLI provides pre-configured prompts for common tasks: `mcp://evocli/prompts/code-review`.

## Security in MCP

When acting as a client, EvoCLI applies its standard security model to external tools:
- **Confirmation**: Tools marked as "destructive" by the MCP server will trigger a user confirmation prompt in EvoCLI.
- **Logging**: All external tool calls are recorded in the episodic memory.
- **Isolation**: External MCP servers run in their own processes, isolated from the EvoCLI Host.

## Troubleshooting

- **Connection Refused**: Ensure the external server command is correct and all dependencies (like `npx`) are installed.
- **Tool Name Collisions**: EvoCLI automatically prefixes tools to avoid collisions. If two servers provide a `read_file` tool, they will be `server1.read_file` and `server2.read_file`.
- **Timeout**: Large MCP operations may timeout. You can adjust the timeout in `~/.evocli/config.toml`.
