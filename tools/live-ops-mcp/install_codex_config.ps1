$ErrorActionPreference = "Stop"

$configPath = Join-Path $HOME ".codex\\config.toml"
$snippetPath = Join-Path $PSScriptRoot "codex-config-snippet.toml"
$marker = "[mcp_servers.peak10_live_ops]"

if (-not (Test-Path $configPath)) {
    throw "Codex config not found at $configPath"
}

if (-not (Test-Path $snippetPath)) {
    throw "Snippet not found at $snippetPath"
}

$configText = Get-Content -Raw -Path $configPath
$backupPath = "$configPath.bak.$(Get-Date -Format 'yyyyMMddHHmmss')"
Copy-Item -Path $configPath -Destination $backupPath -Force

$snippet = Get-Content -Raw -Path $snippetPath
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
Write-Output "Restart Codex to load the new MCP server."
