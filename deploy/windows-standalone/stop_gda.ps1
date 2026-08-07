[CmdletBinding()]
param([string]$InstallRoot = 'C:\GDA')

$ErrorActionPreference = 'Stop'
$InstallRoot = (Resolve-Path $InstallRoot).Path
Set-Content -LiteralPath (Join-Path $InstallRoot 'runtime\shutdown.request') -Value ((Get-Date).ToUniversalTime().ToString('o')) -Encoding ASCII
foreach ($name in @('gis-data-agent', 'windows-ingest-worker', 'minio', 'fuseki', 'ollama', 'prometheus', 'grafana')) {
    $pidFile = Join-Path $InstallRoot "runtime\$name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $processId -Timeout 15 -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
Write-Host "GIS Data Agent 进程已停止。PostgreSQL Windows 服务未被停止，以避免误伤其他数据库。"
