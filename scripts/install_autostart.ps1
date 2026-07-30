<#
    Registers (or removes) the login task that starts the timeline.

    Uses a Scheduled Task rather than a Startup-folder shortcut for two
    reasons: it can wait for a network connection before firing, and it can be
    inspected and disabled from Task Scheduler without hunting for a .lnk.

    Runs under the current user only, at that user's login. No elevation is
    needed and none is requested.

        .\scripts\install_autostart.ps1            # install or update
        .\scripts\install_autostart.ps1 -Uninstall # remove
        .\scripts\install_autostart.ps1 -Status    # show current state
#>

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Status,
    # Seconds to wait after login before starting, so the desktop settles and
    # the network has a chance to come up first.
    [int]$DelaySeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$taskName = 'YesterdayTimeline'
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'start_on_login.ps1'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($Status) {
    if ($null -eq $existing) {
        Write-Output "Not installed. Run this script with no arguments to install."
    } else {
        $info = Get-ScheduledTaskInfo -TaskName $taskName
        Write-Output "Task:        $taskName"
        Write-Output "State:       $($existing.State)"
        Write-Output "Last run:    $($info.LastRunTime)"
        Write-Output "Last result: $($info.LastTaskResult)  (0 = success)"
        Write-Output "Next run:    $($info.NextRunTime)"
    }
    return
}

if ($Uninstall) {
    if ($null -eq $existing) {
        Write-Output "Nothing to remove: '$taskName' is not registered."
    } else {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Output "Removed '$taskName'. The timeline will no longer start at login."
    }
    return
}

if (-not (Test-Path $launcher)) {
    throw "Launcher not found at $launcher"
}
if (-not (Test-Path (Join-Path $root 'server\.venv\Scripts\python.exe'))) {
    throw "No virtualenv yet. Run 'make install' in $root first."
}

# -WindowStyle Hidden on powershell.exe itself, so no console appears at login.
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
    '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass ' +
    "-File `"$launcher`""
) -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Task Scheduler wants an ISO 8601 duration here ("PT30S"), not a clock string;
# a "00:00:30" is rejected as out of range.
$trigger.Delay = "PT${DelaySeconds}S"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

# Home Assistant is reached over the network, so waiting for it avoids a
# first-fetch failure on machines that log in before Wi-Fi associates.
$settings.RunOnlyIfNetworkAvailable = $true

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description 'Starts the Yesterday Timeline server at login, pre-fetches yesterday, and opens the page.' | Out-Null

# Register-ScheduledTask can report a CIM error without halting the script, so
# claiming success requires actually reading the task back.
if ($null -eq (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    throw "Registration of '$taskName' failed: the task is not present afterwards."
}

Write-Output "Installed '$taskName'."
Write-Output "  Runs at:  login of $env:USERNAME, ${DelaySeconds}s after sign-in"
Write-Output "  Launcher: $launcher"
Write-Output "  Log:      $(Join-Path $root 'logs\startup.log')"
Write-Output ""
Write-Output "Test it now without rebooting:"
Write-Output "  Start-ScheduledTask -TaskName $taskName"
