[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\GDA',
    [ValidateSet('SYSTEM', 'CURRENTUSER')]
    [string]$RunAs = 'SYSTEM'
)

$ErrorActionPreference = 'Stop'
$InstallRoot = (Resolve-Path $InstallRoot).Path
$start = Join-Path $InstallRoot 'start_gda.ps1'
if (-not (Test-Path -LiteralPath $start)) { throw "未找到：$start" }
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$start`" -InstallRoot `"$InstallRoot`" -Supervise"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = if ($RunAs -eq 'SYSTEM') {
    New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
} else {
    New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType InteractiveToken -RunLevel Highest
}
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName 'GIS Data Agent' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host '已注册 Windows Task Scheduler 任务：GIS Data Agent'
