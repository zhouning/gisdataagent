[CmdletBinding()]
param([string]$TaskName = 'GIS Data Agent')

$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "已注销 Windows Task Scheduler 任务：$TaskName"
