# Peak10 Live Ops MCP

Small local MCP server for live Azure and HTTP operations from Codex.

It exposes two tools:

- `run_powershell`: runs a PowerShell command in the local user environment
- `http_request`: sends an HTTP request directly from the local machine

The server automatically points Azure CLI at this repo's `.azure-codex` cache when present, so it can reuse the same project-scoped Azure auth context.

## Files

- `server.py`: stdio MCP server
- `http_server.py`: local HTTP MCP server
- `start_http_server.ps1`: starts the HTTP MCP server in the background
- `install_http_codex_config.ps1`: points Codex at the local HTTP MCP URL
- `install_startup_task.ps1`: registers a per-user Windows logon task, or falls back to a Startup shortcut
- `remove_startup_task.ps1`: removes that Windows logon task or Startup shortcut
- `codex-config-snippet.toml`: legacy stdio config block for Codex

## One-time setup

Option 1:

1. Run `install_codex_config.ps1`
2. Restart Codex

Option 2:

1. Add the contents of `codex-config-snippet.toml` to `C:\Users\kdmcq\.codex\config.toml`
2. Restart Codex

## HTTP setup

Recommended path:

1. Run `install_http_codex_config.ps1`
2. Run `start_http_server.ps1`
3. Restart Codex

Optional convenience:

1. Run `install_startup_task.ps1`
2. The HTTP MCP server will auto-start at Windows logon or via your Startup folder fallback

To remove the auto-start behavior later, run `remove_startup_task.ps1`.

## What this unlocks

- `az` and `func` commands from inside Codex without manual relay
- live Function App health checks
- iterative API validation against deployed endpoints

## Notes

- This server is intentionally tiny and dependency-free.
- It is designed for local/private use, not network exposure.
- `run_powershell` is broad by design because the goal is live ops flexibility.
