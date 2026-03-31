$ErrorActionPreference = "Stop"

$taskName = "Peak10LiveOpsMcp"
$repoRoot = "C:\Users\kdmcq\Projects\Peak10-enterprise-automation"
$launcher = Join-Path $repoRoot "tools\live-ops-mcp\start_http_server.ps1"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Peak10 Live Ops MCP.lnk"

if (-not (Test-Path $launcher)) {
    throw "Launcher script not found: $launcher"
}

try {
    $action = New-ScheduledTaskAction `
        -Execute $powershellExe `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable

    $principal = New-ScheduledTaskPrincipal `
        -UserId $currentUser `
        -LogonType Interactive `
        -RunLevel Limited

    $task = New-ScheduledTask `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Starts the local Peak10 live-ops HTTP MCP server at user logon."

    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

    Write-Output "Scheduled Task '$taskName' registered for $currentUser."
    Write-Output "It will start the Peak10 live-ops HTTP MCP server at logon."
    exit 0
} catch {
    Write-Warning "Scheduled Task registration failed, falling back to Startup shortcut. $($_.Exception.Message)"
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellExe
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.IconLocation = "$powershellExe,0"
$shortcut.Description = "Starts the local Peak10 live-ops HTTP MCP server."
$shortcut.Save()

Write-Output "Startup shortcut created at $shortcutPath"
Write-Output "It will start the Peak10 live-ops HTTP MCP server when $currentUser signs in."
