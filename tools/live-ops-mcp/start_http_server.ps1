$ErrorActionPreference = "Stop"

$python = "C:\Users\kdmcq\Projects\Peak10-enterprise-automation\.tools\python314\python.exe"
$server = "C:\Users\kdmcq\Projects\Peak10-enterprise-automation\tools\live-ops-mcp\http_server.py"
$workdir = "C:\Users\kdmcq\Projects\Peak10-enterprise-automation"
$log = "C:\Users\kdmcq\Projects\Peak10-enterprise-automation\tools\live-ops-mcp\http.stdout.log"
$err = "C:\Users\kdmcq\Projects\Peak10-enterprise-automation\tools\live-ops-mcp\http.stderr.log"

try {
    $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/healthz" -TimeoutSec 2
    if ($health.ok) {
        Write-Output "HTTP MCP server already running at http://127.0.0.1:8765/mcp"
        exit 0
    }
} catch {
}

Start-Process `
    -FilePath $python `
    -ArgumentList $server `
    -WorkingDirectory $workdir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $log `
    -RedirectStandardError $err

Start-Sleep -Seconds 2

$health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/healthz" -TimeoutSec 5
if (-not $health.ok) {
    throw "HTTP MCP server did not start cleanly."
}

Write-Output "HTTP MCP server started at http://127.0.0.1:8765/mcp"
