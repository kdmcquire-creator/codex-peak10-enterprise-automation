$ErrorActionPreference = "Stop"

$configPath = Join-Path $HOME ".codex\\config.toml"
$marker = "[mcp_servers.peak10_live_ops]"
$snippet = @'
[mcp_servers.peak10_live_ops]
url = "http://127.0.0.1:8765/mcp"
'@

if (-not (Test-Path $configPath)) {
    throw "Codex config not found at $configPath"
}

$configText = Get-Content -Raw -Path $configPath
$backupPath = "$configPath.bak.$(Get-Date -Format 'yyyyMMddHHmmss')"
Copy-Item -Path $configPath -Destination $backupPath -Force

$pattern = '(?ms)^\[mcp_servers\.peak10_live_ops\]\r?\n.*?(?=^\[|\z)'
if ($configText -match $pattern) {
    $newText = [regex]::Replace($configText, $pattern, $snippet.Trim() + "`r`n`r`n")
    Write-Output "Updated peak10_live_ops MCP server in $configPath"
} else {
    $newText = $configText.TrimEnd() + "`r`n`r`n" + $snippet.Trim() + "`r`n"
    Write-Output "Added peak10_live_ops MCP server to $configPath"
}

Set-Content -Path $configPath -Value $newText -Encoding UTF8

Write-Output "Backup written to $backupPath"
Write-Output "Config now points peak10_live_ops to http://127.0.0.1:8765/mcp"
Write-Output "Run start_http_server.ps1, then restart Codex."
