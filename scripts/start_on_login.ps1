<#
    Starts the Yesterday Timeline server at login and opens the page.

    Registered as a Scheduled Task by `install_autostart.ps1`. Kept idempotent
    so running it twice does not leave two servers fighting over port 8000:
    if something already answers on the port, this reuses it.

    Writes a rolling log to logs/startup.log. Nothing here prints a token.
#>

[CmdletBinding()]
param(
    # Skip opening a browser window (useful when testing the task).
    [switch]$NoBrowser,
    # Wait this long for the API to answer before giving up.
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'server\.venv\Scripts\python.exe'
$logDir = Join-Path $root 'logs'
$log = Join-Path $logDir 'startup.log'
$serverLog = Join-Path $logDir 'server.log'
$port = 8000
$url = "http://127.0.0.1:$port"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

function Write-Log([string]$message) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Output $line
}

# Keep the log from growing without bound across months of logins.
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) {
    Move-Item $log "$log.old" -Force
}

Write-Log '--- login trigger ---'

if (-not (Test-Path $python)) {
    Write-Log "ERROR: no virtualenv at $python. Run 'make install' once, then re-run this."
    exit 1
}

function Test-Api {
    try {
        $response = Invoke-WebRequest -Uri "$url/api/health" -TimeoutSec 3 -UseBasicParsing
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-Api) {
    Write-Log 'Server already running; reusing it.'
} else {
    Write-Log 'Starting server...'
    $arguments = @(
        '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1', '--port', "$port",
        '--app-dir', (Join-Path $root 'server')
    )
    # WindowStyle Hidden keeps a console from flashing up at every login.
    Start-Process -FilePath $python -ArgumentList $arguments `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput $serverLog -RedirectStandardError "$serverLog.err"

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (Test-Api)) {
        if ((Get-Date) -gt $deadline) {
            Write-Log "ERROR: server did not answer within $TimeoutSeconds s. See $serverLog.err"
            exit 1
        }
        Start-Sleep -Milliseconds 750
    }
    Write-Log 'Server is up.'
}

# Pull yesterday now, so the page is populated rather than syncing on first
# view. A day that was cached while still in progress is re-fetched by the
# service itself, so this does not need to force a refresh.
try {
    $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 10
    Write-Log "Fetching $($health.yesterday)..."
    $day = Invoke-RestMethod -Uri "$url/api/yesterday" -TimeoutSec 600
    $coverage = [math]::Round($day.summary.coverage.overallFraction * 100)
    Write-Log ("Ready: {0} - {1} events, {2}% coverage, {3} raw records." -f `
        $day.date, $day.summary.normalizedEventCount, $coverage, $day.summary.rawRecordCount)
    foreach ($problem in $day.summary.errors) { Write-Log "  source error: $problem" }
} catch {
    # A source being unreachable at login is normal and not fatal: the page
    # still opens and says which lane has nothing.
    Write-Log "WARNING: could not pre-fetch yesterday: $($_.Exception.Message)"
}

if (-not $NoBrowser) {
    Write-Log "Opening $url"
    Start-Process $url
}
