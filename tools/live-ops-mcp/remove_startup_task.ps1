$ErrorActionPreference = "Stop"

$taskName = "Peak10LiveOpsMcp"
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Peak10 Live Ops MCP.lnk"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Scheduled Task '$taskName' removed."
}

if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Output "Startup shortcut removed: $shortcutPath"
}

if (-not $existing -and -not (Test-Path $shortcutPath)) {
    Write-Output "No Scheduled Task or Startup shortcut was present."
}
