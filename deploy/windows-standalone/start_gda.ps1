[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\GDA',
    [int]$Port = 8000,
    [switch]$Supervise
)

$ErrorActionPreference = 'Stop'
$InstallRoot = (Resolve-Path $InstallRoot).Path
$statePath = Join-Path $InstallRoot 'runtime\install-state.json'
if (-not (Test-Path -LiteralPath $statePath)) { throw "未找到安装状态：$statePath" }
$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$shutdownMarker = Join-Path $InstallRoot 'runtime\shutdown.request'
if (Test-Path -LiteralPath $shutdownMarker) { Remove-Item -LiteralPath $shutdownMarker -Force -ErrorAction SilentlyContinue }

function Set-EnvFile([string]$Path) {
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { continue }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

function Ensure-LogDir {
    New-Item -ItemType Directory -Path $env:GDA_LOG_DIR -Force | Out-Null
}

function Start-LoggedProcess([string]$Name, [string]$FilePath, [string[]]$Arguments) {
    $pidFile = Join-Path $InstallRoot "runtime\$Name.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw)
        if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) { return $oldPid }
    }
    $stdout = Join-Path $env:GDA_LOG_DIR "$Name.stdout.log"
    $stderr = Join-Path $env:GDA_LOG_DIR "$Name.stderr.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $InstallRoot `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII
    return $process.Id
}

function Start-ExistingServices {
    $serviceNamePath = Join-Path $InstallRoot 'runtime\postgres-service-name.txt'
    if (Test-Path -LiteralPath $serviceNamePath) {
        $name = (Get-Content -LiteralPath $serviceNamePath -Raw).Trim()
        $service = Get-Service -Name $name -ErrorAction Stop
        if ($service.Status -ne 'Running') { Start-Service -Name $service.Name -ErrorAction Stop }
    }
}

function Wait-Tcp([string]$HostName, [int]$TargetPort, [int]$Seconds = 30) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $client = [Net.Sockets.TcpClient]::new()
            $task = $client.ConnectAsync($HostName, $TargetPort)
            if ($task.Wait(1000) -and $client.Connected) { $client.Close(); return $true }
            $client.Close()
        } catch { }
    }
    return $false
}

Set-EnvFile (Join-Path $InstallRoot 'config\gda.env')
$env:PYTHONPATH = Join-Path $InstallRoot 'payload\app'
Ensure-LogDir
$python = [string]$state.python
if (-not (Test-Path -LiteralPath $python)) { throw "Python 不存在：$python" }

$preflight = Join-Path $InstallRoot 'scripts\preflight_windows_ingest.py'
$preflightMode = if ($state.profile -eq 'production') { 'production' } else { 'development' }
& $python $preflight --mode $preflightMode --lake (Join-Path $state.data_root 'file_lake') `
    --inbox $state.inbox --contracts $env:GDA_STANDARD_CONTRACTS `
    --ontology $env:GDA_ONTOLOGY_ACTIVE --create-directories `
    --output (Join-Path $env:GDA_LOG_DIR 'windows-ingest-preflight.json')
if ($LASTEXITCODE -ne 0) { throw 'Windows 入湖预检阻断，未启动任何 GIS Data Agent 进程。' }

$verify = Join-Path $InstallRoot 'scripts\verify_windows_offline_bundle.py'
& $python $verify --bundle-root $InstallRoot --profile $state.profile --phase runtime `
    --output (Join-Path $env:GDA_LOG_DIR 'bundle-runtime-verify.json')
if ($LASTEXITCODE -ne 0) { throw '离线包运行前预检阻断，未启动任何 GIS Data Agent 进程。' }

if ($state.profile -eq 'production') {
    Start-ExistingServices
    $minio = Join-Path $InstallRoot 'payload\middleware\minio\minio.exe'
    if ((Test-Path -LiteralPath $minio) -and -not (Wait-Tcp '127.0.0.1' 9000 1)) {
        Start-LoggedProcess 'minio' $minio @('server', '--address', '127.0.0.1:9000', '--console-address', '127.0.0.1:9001', (Join-Path $state.data_root 'object_store')) | Out-Null
    }
    $java = if ($env:JAVA_HOME -and (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
        Join-Path $env:JAVA_HOME 'bin\java.exe'
    } else { (Get-Command java.exe -ErrorAction SilentlyContinue).Source }
    $fusekiJar = Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'middleware\fuseki') -Filter 'fuseki-server*.jar' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($java -and $fusekiJar -and -not (Wait-Tcp '127.0.0.1' 3030 1)) {
        Start-LoggedProcess 'fuseki' $java @('-jar', $fusekiJar.FullName, '--localhost', '127.0.0.1', '--port', '3030', '--loc', (Join-Path $state.data_root 'ontology\tdb2'), '/ontology') | Out-Null
    }
    $ollama = if ($env:OLLAMA_EXE -and (Test-Path -LiteralPath $env:OLLAMA_EXE)) {
        $env:OLLAMA_EXE
    } else { (Get-Command ollama.exe -ErrorAction SilentlyContinue).Source }
    if (-not $ollama) {
        $candidate = Join-Path ${env:ProgramFiles} 'Ollama\ollama.exe'
        if (Test-Path -LiteralPath $candidate) { $ollama = $candidate }
    }
    $llmProvider = ([string]$env:GDA_LLM_PROVIDER).Trim().ToLowerInvariant()
    $usesBundledOllama = [string]::IsNullOrWhiteSpace($llmProvider) -or $llmProvider -eq 'ollama'
    if ($ollama -and $usesBundledOllama) {
        Get-Process -Name 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        if (-not (Wait-Tcp '127.0.0.1' 11434 1)) { Start-LoggedProcess 'ollama' $ollama @('serve') | Out-Null }
    } elseif (-not $usesBundledOllama) {
        Write-Host "Skipping bundled Ollama because GDA_LLM_PROVIDER=$llmProvider; using configured OpenAI-compatible service."
    }
    $prometheus = Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'middleware\prometheus') -Filter 'prometheus.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($prometheus) {
        Start-LoggedProcess 'prometheus' $prometheus.FullName @('--config.file', (Join-Path $InstallRoot 'config\prometheus.yml'), '--storage.tsdb.path', (Join-Path $state.data_root 'prometheus')) | Out-Null
    }
    $grafana = Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'middleware\grafana') -Filter 'grafana-server.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($grafana) {
        $env:GF_PATHS_DATA = Join-Path $state.data_root 'grafana'
        $env:GF_PATHS_LOGS = Join-Path $env:GDA_LOG_DIR 'grafana'
        Start-LoggedProcess 'grafana' $grafana.FullName @('--homepath', $grafana.Directory.Parent.FullName) | Out-Null
    }
}

$configuredProvider = ([string]$env:GDA_LLM_PROVIDER).Trim().ToLowerInvariant()
if ($configuredProvider -in @('lm_studio', 'openai_compatible')) {
    $modelVerifier = Join-Path $InstallRoot 'scripts\verify_openai_compatible_models.py'
    if (-not (Test-Path -LiteralPath $modelVerifier)) {
        throw "模型预检脚本不存在：$modelVerifier"
    }
    $modelReport = Join-Path $env:GDA_LOG_DIR 'model-service-preflight.json'
    & $python $modelVerifier --output $modelReport
    $modelPreflightExitCode = $LASTEXITCODE
    if ($modelPreflightExitCode -ne 0) {
        $requiredValue = ([string]$env:GDA_MODEL_PREFLIGHT_REQUIRED).Trim().ToLowerInvariant()
        $modelPreflightRequired = [string]::IsNullOrWhiteSpace($requiredValue) -or `
            $requiredValue -in @('1', 'true', 'yes', 'on')
        if ($modelPreflightRequired) {
            throw "LM Studio/OpenAI-compatible 模型预检失败；请查看 $modelReport"
        }
        Write-Warning "模型预检失败但未配置为阻断；请查看 $modelReport"
    }
}

$app = Join-Path $InstallRoot 'payload\app\data_agent\app.py'
$worker = Join-Path $InstallRoot 'scripts\windows_ingest_worker.py'
if (-not (Test-Path -LiteralPath $app)) { throw "应用入口不存在：$app" }
if (-not (Test-Path -LiteralPath $worker)) { throw "worker 不存在：$worker" }
Start-LoggedProcess 'gis-data-agent' $python @('-m', 'chainlit', 'run', $app, '--headless', '--host', '0.0.0.0', '--port', "$Port") | Out-Null
Start-LoggedProcess 'windows-ingest-worker' $python @($worker, '--inbox', $state.inbox, '--lake', (Join-Path $state.data_root 'file_lake')) | Out-Null

if (-not (Wait-Tcp '127.0.0.1' $Port 60)) {
    throw "Chainlit 未在 $Port 端口监听；请查看 $env:GDA_LOG_DIR\gis-data-agent.stderr.log"
}
if ($state.profile -eq 'production') {
    foreach ($servicePort in @(5432, 9000, 3030, 11434)) {
        if (-not (Wait-Tcp '127.0.0.1' $servicePort 60)) {
            & (Join-Path $InstallRoot 'stop_gda.ps1') -InstallRoot $InstallRoot
            throw "生产中间件未在端口 $servicePort 监听。"
        }
    }
    & $python $verify --bundle-root $InstallRoot --profile production --phase runtime --require-running `
        --output (Join-Path $env:GDA_LOG_DIR 'bundle-running-verify.json')
    if ($LASTEXITCODE -ne 0) {
        & (Join-Path $InstallRoot 'stop_gda.ps1') -InstallRoot $InstallRoot
        throw '生产服务健康检查失败，已停止 GIS Data Agent 进程。'
    }
}
Write-Host "GIS Data Agent 已启动：http://127.0.0.1:$Port"

if ($Supervise) {
    # Keep the scheduled task alive so Windows can restart it after a child
    # process crash. stop_gda.ps1 writes a marker first to request a clean exit.
    while ($true) {
        if (Test-Path -LiteralPath $shutdownMarker) {
            Remove-Item -LiteralPath $shutdownMarker -Force -ErrorAction SilentlyContinue
            exit 0
        }
        foreach ($name in @('gis-data-agent', 'windows-ingest-worker')) {
            $pidPath = Join-Path $InstallRoot "runtime\$name.pid"
            if (-not (Test-Path -LiteralPath $pidPath)) { throw "监督进程缺少 PID 文件：$name" }
            $processId = [int](Get-Content -LiteralPath $pidPath -Raw)
            if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { throw "监督进程已退出：$name/$processId" }
        }
        Start-Sleep -Seconds 15
    }
}
