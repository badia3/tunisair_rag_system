$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$runner = Join-Path $projectRoot "run_weekly_sync.ps1"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument $arguments `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At ([datetime]::Today.AddHours(3))
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "YourFlightSupportBot-TunisairSync" `
    -Description "Weekly sync of the explicitly allowlisted Tunisair public pages." `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Output "Weekly sync scheduled for Sundays at 03:00, when this Windows user is signed in."
