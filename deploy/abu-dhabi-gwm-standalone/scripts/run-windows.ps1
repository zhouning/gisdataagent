param(
  [Parameter(Mandatory = $true)]
  [ValidateLength(32, 4096)]
  [string]$ApiToken,

  [string]$RunsDirectory = "D:\AbuDhabiGWM\runs",
  [string]$Image = "abu-dhabi-gwm-api:1.0.0-model-r1-linux-amd64",
  [string]$BindAddress = "127.0.0.1",
  [int]$Port = 8080,
  [double]$MinimumFreeDiskGb = 5
)

$ErrorActionPreference = "Stop"

docker info | Out-Null
$existing = docker container inspect abu-dhabi-gwm 2>$null
if ($LASTEXITCODE -eq 0) {
  throw "Container 'abu-dhabi-gwm' already exists. Inspect it before making any replacement."
}

New-Item -ItemType Directory -Force -Path $RunsDirectory | Out-Null
$mount = "${RunsDirectory}:/data/runs"

docker run --detach `
  --name abu-dhabi-gwm `
  --platform linux/amd64 `
  --restart unless-stopped `
  --read-only `
  --tmpfs "/tmp:size=64m,mode=1777" `
  --security-opt no-new-privileges:true `
  --cap-drop ALL `
  --publish "${BindAddress}:${Port}:8080" `
  --volume $mount `
  --env "GWM_API_TOKEN=${ApiToken}" `
  --env "GWM_MIN_FREE_DISK_GB=${MinimumFreeDiskGb}" `
  --env "GWM_MAX_CONCURRENT_RUNS=1" `
  $Image

Write-Host "Container started. Check: http://127.0.0.1:${Port}/health/ready"
