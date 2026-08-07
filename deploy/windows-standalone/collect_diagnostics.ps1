[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\GDA',
    [string]$OutputDirectory = 'D:\GDA_DIAGNOSTICS'
)

$ErrorActionPreference = 'Stop'
$InstallRoot = (Resolve-Path $InstallRoot).Path
$state = Get-Content -LiteralPath (Join-Path $InstallRoot 'runtime\install-state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stage = Join-Path $env:TEMP "gda-diagnostics-$timestamp"
New-Item -ItemType Directory -Path $stage, $OutputDirectory -Force | Out-Null
try {
    foreach ($source in @(
        (Join-Path $InstallRoot 'runtime\install-state.json'),
        (Join-Path $state.data_root 'file_lake\diagnostics'),
        $state.log_root
    )) {
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $stage -Recurse -Force }
    }
    $envFile = Join-Path $InstallRoot 'config\gda.env'
    if (Test-Path -LiteralPath $envFile) {
        Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
            if ($_ -match '(PASSWORD|SECRET|TOKEN|KEY)=') { ($_ -split '=', 2)[0] + '=<redacted>' } else { $_ }
        } | Set-Content -LiteralPath (Join-Path $stage 'gda.env.redacted') -Encoding UTF8
    }
    Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, OSArchitecture, LastBootUpTime | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage 'host.json') -Encoding UTF8
    Get-PSDrive -PSProvider FileSystem | Select-Object Name, Used, Free, Root | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage 'drives.json') -Encoding UTF8
    $zip = Join-Path $OutputDirectory "gda-diagnostics-$timestamp.zip"
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
    Write-Host "诊断包已生成：$zip"
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
