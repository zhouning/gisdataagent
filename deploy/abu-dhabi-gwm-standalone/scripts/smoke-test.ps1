param(
  [Parameter(Mandatory = $true)]
  [ValidateLength(32, 4096)]
  [string]$ApiToken,
  [string]$BaseUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"
$headers = @{ Authorization = "Bearer ${ApiToken}" }

$live = Invoke-RestMethod -Uri "${BaseUrl}/health/live"
if ($live.status -ne "alive") {
  throw "Liveness check failed."
}

$ready = Invoke-RestMethod -Uri "${BaseUrl}/health/ready"
if ($ready.status -ne "ready") {
  throw "Readiness check failed."
}

$model = Invoke-RestMethod -Uri "${BaseUrl}/v1/model" -Headers $headers
if ($model.model.releaseId -ne "GWM-R1-20260914") {
  throw "Unexpected model release: $($model.model.releaseId)"
}

$body = @{
  totalRainfallMm = 100
  durationHours = 24
} | ConvertTo-Json
$rolloutHeaders = @{
  Authorization = "Bearer ${ApiToken}"
  "Idempotency-Key" = "acceptance-gwm-r1-100mm-24h"
}
$run = Invoke-RestMethod `
  -Uri "${BaseUrl}/v1/rollouts" `
  -Method Post `
  -Headers $rolloutHeaders `
  -ContentType "application/json" `
  -Body $body

if ($run.status -ne "completed") {
  throw "Rollout did not complete."
}
if ($run.metrics.periodCount -ne 385 -or $run.metrics.simulationDurationHours -ne 32) {
  throw "Unexpected 100 mm / 24 h timeline metrics."
}
if ([Math]::Abs([double]$run.metrics.maximumDepthM - 4.843380928039551) -gt 0.000001) {
  throw "Unexpected 100 mm / 24 h maximum depth."
}

$receipt = Invoke-RestMethod -Uri "${BaseUrl}/v1/runs/$($run.runId)" -Headers $headers
if ($receipt.runId -ne $run.runId) {
  throw "Persisted run receipt could not be read back."
}

$timeSlice = Invoke-RestMethod `
  -Uri "${BaseUrl}/v1/runs/$($run.runId)/timeseries?timeIndex=1" `
  -Headers $headers
if ($timeSlice.metadata.time_index -ne 1) {
  throw "Time-slice endpoint returned an unexpected index."
}

Write-Host "PASS: GWM-R1-20260914 API, persistence, and 100 mm / 24 h rollout verified."
Write-Host "Run ID: $($run.runId)"
