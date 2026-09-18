param(
  [Parameter(Mandatory = $true)]
  [string]$ApiToken,
  [string]$BaseUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"
$headers = @{ Authorization = "Bearer ${ApiToken}" }
$body = @{
  totalRainfallMm = 100
  durationHours = 24
} | ConvertTo-Json

$result = Invoke-RestMethod `
  -Uri "${BaseUrl}/v1/rollouts" `
  -Method Post `
  -Headers ($headers + @{ "Idempotency-Key" = "acceptance-100mm-24h-v1" }) `
  -ContentType "application/json" `
  -Body $body

$result | ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri "${BaseUrl}/v1/runs/$($result.runId)" -Headers $headers | ConvertTo-Json -Depth 8
