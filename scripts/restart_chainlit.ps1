# Idempotent restart of Chainlit with full .env loaded into the spawned process.
# Why: Start-Process inherits only the parent shell's env, so .env vars must be
# explicitly hoisted before launch — otherwise Vertex AI / GOOGLE_API_KEY paths
# silently fall back and embedding gateway hits 404 on v1beta.

$ErrorActionPreference = "Stop"
$projectRoot = "D:\adk"
$envFile = Join-Path $projectRoot "data_agent\.env"

# 1. Kill existing chainlit
Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*chainlit*run*data_agent/app.py*" } |
    ForEach-Object {
        Write-Host "Stopping chainlit PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

# 2. Load .env into current process env (spawned chainlit inherits)
if (-not (Test-Path $envFile)) {
    throw ".env not found at $envFile"
}
$loaded = 0
Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$") {
        $name = $matches[1]
        $value = $matches[2]
        if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") {
            $value = $matches[1]
        }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        $loaded++
    }
}
Write-Host "Loaded $loaded vars from $envFile"

# 3. Required harness vars
$env:PYTHONPATH = $projectRoot
$env:PYTHONUNBUFFERED = "1"

# 4. Sanity-check critical embedding/auth vars
$required = @("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_API_KEY", "EMBEDDING_MODEL")
foreach ($v in $required) {
    $val = [Environment]::GetEnvironmentVariable($v, 'Process')
    if (-not $val) {
        Write-Warning "$v is not set — embedding may fall back to v1beta and 404"
    } else {
        $masked = if ($v -like "*KEY*") {
            $val.Substring(0, [Math]::Min(8, $val.Length)) + "..."
        } else { $val }
        Write-Host "  $v = $masked"
    }
}

# 5. Launch
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$stdout = Join-Path $projectRoot "chainlit_stdout.log"
$stderr = Join-Path $projectRoot "chainlit_stderr.log"

Start-Process -FilePath $python `
    -ArgumentList "-m", "chainlit", "run", "data_agent/app.py", "-w" `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -NoNewWindow
Write-Host "Chainlit launched. Waiting for 'Your app is available'..."

# 6. Wait for ready signal (max 90s) — chainlit logs "Your app is available"
# to stdout, while stderr captures Python warnings/structured logs.
$timeout = 90
$elapsed = 0
while ($elapsed -lt $timeout) {
    Start-Sleep -Seconds 1
    $elapsed++
    foreach ($logFile in @($stdout, $stderr)) {
        if (-not (Test-Path $logFile)) { continue }
        $content = Get-Content $logFile -Raw -ErrorAction SilentlyContinue
        if ($content -match "Your app is available at") {
            Write-Host "READY after ${elapsed}s — http://localhost:8000"
            exit 0
        }
        if ($content -match "Address already in use") {
            Write-Error "Port 8000 still bound — old process didn't release"
            exit 1
        }
    }
}
Write-Warning "Timeout after ${timeout}s. Check $stdout / $stderr for status."
exit 1
