<#
    Stops the timeline server.

    Works off whoever owns the port rather than off a process name. A venv
    created by `uv` has a trampoline python.exe that re-execs the real
    interpreter, so the process holding port 8000 is a *child* of the one the
    launcher started — killing by name or by the launcher's PID would leave the
    real server running and still holding the port.
#>

[CmdletBinding()]
param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Output "Nothing is listening on port $Port."
    return
}

# Not $pid: that is a read-only automatic variable holding this shell's own id.
foreach ($processId in ($listeners.OwningProcess | Sort-Object -Unique)) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) { continue }
    Write-Output "Stopping $($process.ProcessName) (PID $processId) on port $Port..."
    # Take the parent trampoline too, so it does not linger.
    $parentId = (Get-CimInstance Win32_Process -Filter "ProcessId = $processId").ParentProcessId
    Stop-Process -Id $processId -Force
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $parentId" -ErrorAction SilentlyContinue
    if ($parent -and $parent.CommandLine -like '*uvicorn*') {
        Stop-Process -Id $parentId -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Milliseconds 500
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "WARNING: port $Port is still held."
} else {
    Write-Output "Stopped."
}
