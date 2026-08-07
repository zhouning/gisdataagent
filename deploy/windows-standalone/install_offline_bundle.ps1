[CmdletBinding()]
param(
    [ValidateSet('core', 'production')]
    [string]$Profile = 'core',
    [string]$InstallRoot = 'C:\GDA',
    [string]$DataRoot = 'D:\GDA_DATA',
    [string]$Inbox = 'D:\NX_INCOMING',
    [string]$LogRoot = 'D:\GDA_LOGS',
    [double]$MinFreeGb = 20,
    [switch]$AllowExisting
)

$ErrorActionPreference = 'Stop'
$script:GdaPostgresPassword = ''
$script:GdaMinioPassword = [guid]::NewGuid().ToString('N') + 'Mm1!'
$script:JavaHome = ''
$script:OllamaExe = ''
$BundleRoot = (Resolve-Path $PSScriptRoot).Path
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$Inbox = [IO.Path]::GetFullPath($Inbox)
$LogRoot = [IO.Path]::GetFullPath($LogRoot)

function Fail([string]$Message) {
    throw "[GDA offline install] $Message"
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail '请使用管理员 PowerShell 运行安装器。'
    }
}

function Assert-Host {
    if (-not [Environment]::Is64BitOperatingSystem) { Fail '只支持 Windows x64。' }
    if ($env:OS -ne 'Windows_NT') { Fail '安装器只能在 Windows 主机执行。' }
    $drive = [IO.Path]::GetPathRoot($DataRoot)
    $usage = Get-PSDrive -Name $drive.Substring(0, 1)
    if (($usage.Free / 1GB) -lt $MinFreeGb) {
        Fail ("数据盘可用空间 {0:N1} GiB，小于要求 {1:N1} GiB。" -f ($usage.Free / 1GB), $MinFreeGb)
    }
    foreach ($path in @($InstallRoot, $DataRoot, $Inbox, $LogRoot)) {
        if ($path.Length -gt 220) { Fail "路径过长（Windows MAX_PATH 风险）：$path" }
    }
}

function Read-Manifest {
    $path = Join-Path $BundleRoot 'manifest.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "缺少 $path" }
    $manifest = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.profile -ne $Profile) { Fail "包 profile=$($manifest.profile)，但参数要求 $Profile。" }
    return $manifest
}

function Assert-Checksums {
    $sumFile = Join-Path $BundleRoot 'SHA256SUMS'
    if (-not (Test-Path -LiteralPath $sumFile -PathType Leaf)) { Fail "缺少 $sumFile" }
    $failed = @()
    foreach ($line in Get-Content -LiteralPath $sumFile -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $parts = $line -split '\s{2,}', 2
        if ($parts.Count -ne 2) { Fail "SHA256SUMS 格式错误：$line" }
        $expected = $parts[0].Trim().ToLowerInvariant()
        $relative = $parts[1].Trim().Replace('/', '\')
        if ($relative.Contains('..')) { Fail "SHA256SUMS 含非法相对路径：$relative" }
        $path = Join-Path $BundleRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $failed += "$relative (missing)"
            continue
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { $failed += "$relative (hash mismatch)" }
    }
    if ($failed.Count -gt 0) { Fail "校验和失败：$($failed -join ', ')" }
}

function Assert-RequiredArtifacts($Manifest) {
    $required = @($Manifest.profiles.$Profile.required_artifacts)
    foreach ($artifact in @($Manifest.artifacts)) {
        if ($required -notcontains $artifact.id) { continue }
        $target = Join-Path $BundleRoot ($artifact.target.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $target)) { Fail "缺少 required artifact $($artifact.id)：$target" }
    }
}

function New-Directories {
    foreach ($path in @(
        $InstallRoot,
        (Join-Path $InstallRoot 'runtime'),
        (Join-Path $InstallRoot 'middleware'),
        (Join-Path $InstallRoot 'runtime\logs'),
        $DataRoot,
        (Join-Path $DataRoot 'control'),
        (Join-Path $DataRoot 'file_lake\inbox'),
        (Join-Path $DataRoot 'file_lake\raw'),
        (Join-Path $DataRoot 'file_lake\runs'),
        (Join-Path $DataRoot 'file_lake\standardized'),
        (Join-Path $DataRoot 'file_lake\materialized'),
        (Join-Path $DataRoot 'file_lake\diagnostics'),
        (Join-Path $DataRoot 'file_lake\sessions'),
        $Inbox,
        $LogRoot
    )) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
}

function Configure-Firewall {
    $rule = Get-NetFirewallRule -DisplayName 'GIS Data Agent 8000' -ErrorAction SilentlyContinue
    if (-not $rule) {
        New-NetFirewallRule -DisplayName 'GIS Data Agent 8000' -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort 8000 -Profile Domain,Private | Out-Null
    }
}

function Protect-Configuration {
    foreach ($path in @((Join-Path $InstallRoot 'config'), (Join-Path $InstallRoot 'runtime'))) {
        & icacls.exe $path '/inheritance:r' '/grant:r' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '/T' '/C' | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "配置 ACL 设置失败：$path" }
    }
}

function Copy-Payload {
    if ((Test-Path -LiteralPath $InstallRoot) -and (Get-ChildItem -LiteralPath $InstallRoot -Force -ErrorAction SilentlyContinue | Select-Object -First 1) -and -not $AllowExisting) {
        Fail "安装目录非空：$InstallRoot。指定 -AllowExisting 才允许在已有目录旁初始化；安装器不会删除已有文件。"
    }
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    foreach ($name in @('payload', 'config', 'scripts')) {
        $source = Join-Path $BundleRoot $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $InstallRoot -Recurse -Force
        }
    }
    foreach ($name in @('install_offline_bundle.ps1', 'start_gda.ps1', 'stop_gda.ps1', 'register_tasks.ps1', 'unregister_tasks.ps1', 'collect_diagnostics.ps1', 'README.md', 'bundle-manifest.json', 'manifest.json', 'SHA256SUMS')) {
        $source = Join-Path $BundleRoot $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $InstallRoot $name) -Force
        }
    }
}

function Install-Python {
    $pythonDir = Join-Path $InstallRoot 'runtime\python'
    $python = Join-Path $pythonDir 'python.exe'
    if (Test-Path -LiteralPath $python) { return $python }
    $installer = Join-Path $InstallRoot 'payload\runtime\python-installer.exe'
    if (-not (Test-Path -LiteralPath $installer)) { Fail "缺少 Python Windows 安装介质：$installer" }
    New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null
    $pythonArgs = @('/quiet', 'InstallAllUsers=1', 'PrependPath=0', 'Include_test=0', 'Shortcuts=0', "TargetDir=$pythonDir")
    $process = Start-Process -FilePath $installer -ArgumentList $pythonArgs -Wait -PassThru
    if ($process.ExitCode -ne 0) { Fail "Python 安装失败，exit=$($process.ExitCode)" }
    if (-not (Test-Path -LiteralPath $python)) { Fail "Python 安装后找不到 $python" }
    return $python
}

function Install-Wheels([string]$Python) {
    $requirements = if ($Profile -eq 'production') { 'requirements-windows-production.txt' } else { 'requirements-windows-core.txt' }
    $requirementPath = Join-Path $InstallRoot "payload\$requirements"
    $wheelArgs = @('-m', 'pip', 'install', '--no-index', '--disable-pip-version-check', '--no-warn-script-location')
    $wheelArgs += @('--find-links', (Join-Path $InstallRoot 'payload\wheelhouse\core'))
    if ($Profile -eq 'production') {
        $wheelArgs += @('--find-links', (Join-Path $InstallRoot 'payload\wheelhouse\production'))
        $wheelArgs += @('--find-links', (Join-Path $InstallRoot 'payload\wheelhouse\paper9'))
    }
    $wheelArgs += @('-r', $requirementPath)
    & $Python @wheelArgs
    if ($LASTEXITCODE -ne 0) { Fail "离线 Python wheel 安装失败，exit=$LASTEXITCODE" }
}

function Install-Postgres {
    $installer = Join-Path $InstallRoot 'payload\middleware\postgresql-installer.exe'
    if (-not (Test-Path -LiteralPath $installer)) { Fail "缺少 PostgreSQL 安装介质。" }
    $password = if ($env:GDA_POSTGRES_PASSWORD) { $env:GDA_POSTGRES_PASSWORD } else { [guid]::NewGuid().ToString('N') + 'Aa1!' }
    if ($password -notmatch '^[A-Za-z0-9!._~-]{16,128}$') {
        Fail 'GDA_POSTGRES_PASSWORD 只能包含字母、数字和 ! . _ ~ -，长度 16-128。'
    }
    $script:GdaPostgresPassword = $password
    $prefix = Join-Path $InstallRoot 'middleware\postgresql'
    $data = Join-Path $DataRoot 'postgresql'
    New-Item -ItemType Directory -Path $prefix, $data -Force | Out-Null
    $installerArgs = if ($env:GDA_POSTGRES_INSTALL_ARGS) { $env:GDA_POSTGRES_INSTALL_ARGS } else {
        "--mode unattended --unattendedmodeui none --superpassword `"$password`" --serverport 5432 --prefix `"$prefix`" --datadir `"$data`""
    }
    $process = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru
    if ($process.ExitCode -ne 0) { Fail "PostgreSQL 安装失败，exit=$($process.ExitCode)。可用 GDA_POSTGRES_INSTALL_ARGS 覆盖供应商参数。" }
    Set-Content -LiteralPath (Join-Path $InstallRoot 'runtime\postgres-superpassword.txt') -Value $password -Encoding UTF8
    $service = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match 'postgresql' -and $_.PathName -like "*$prefix*"
    } | Select-Object -First 1
    if ($service) {
        Set-Content -LiteralPath (Join-Path $InstallRoot 'runtime\postgres-service-name.txt') -Value $service.Name -Encoding ASCII
        if ($service.State -ne 'Running') { Start-Service -Name $service.Name -ErrorAction Stop }
    }
}

function Wait-LocalPort([int]$Port, [int]$Seconds = 60) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $client = [Net.Sockets.TcpClient]::new()
            $task = $client.ConnectAsync('127.0.0.1', $Port)
            if ($task.Wait(1000) -and $client.Connected) { $client.Close(); return }
            $client.Close()
        } catch { }
    }
    Fail "127.0.0.1:$Port 未在规定时间内监听。"
}

function Initialize-MinIO {
    $minio = Join-Path $InstallRoot 'payload\middleware\minio\minio.exe'
    $mc = Join-Path $InstallRoot 'payload\middleware\minio\mc.exe'
    if (-not (Test-Path -LiteralPath $minio) -or -not (Test-Path -LiteralPath $mc)) {
        Fail 'MinIO server/client 离线制品不完整。'
    }
    $objectRoot = Join-Path $DataRoot 'object_store'
    New-Item -ItemType Directory -Path $objectRoot -Force | Out-Null
    $env:MINIO_ROOT_USER = 'gda_minio'
    $env:MINIO_ROOT_PASSWORD = $script:GdaMinioPassword
    $process = Start-Process -FilePath $minio -ArgumentList @('server', '--address', '127.0.0.1:9000', '--console-address', '127.0.0.1:9001', $objectRoot) -PassThru -WindowStyle Hidden
    try {
        Wait-LocalPort 9000
        & $mc alias set local http://127.0.0.1:9000 gda_minio $script:GdaMinioPassword
        if ($LASTEXITCODE -ne 0) { Fail 'MinIO alias 初始化失败。' }
        & $mc mb --ignore-existing local/gis-agent-uploads
        if ($LASTEXITCODE -ne 0) { Fail 'MinIO uploads bucket 初始化失败。' }
        & $mc mb --ignore-existing local/gis-agent-lakehouse
        if ($LASTEXITCODE -ne 0) { Fail 'MinIO lakehouse bucket 初始化失败。' }
    } finally {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}

function Initialize-PostgresDatabase([string]$Python) {
    $pgRoot = if ($env:GDA_PGROOT) { $env:GDA_PGROOT } else { Join-Path $InstallRoot 'middleware\postgresql' }
    $psql = Join-Path $pgRoot 'bin\psql.exe'
    if (-not (Test-Path -LiteralPath $psql)) { Fail "找不到 psql.exe：$psql；请设置 GDA_PGROOT。" }
    Wait-LocalPort 5432
    $env:PGPASSWORD = $script:GdaPostgresPassword
    $roleSql = "DO `$do`$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_user') THEN CREATE ROLE agent_user LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '$script:GdaPostgresPassword'; ELSE ALTER ROLE agent_user WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '$script:GdaPostgresPassword'; END IF; END `$do`$;"
    & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -c $roleSql
    if ($LASTEXITCODE -ne 0) { Fail '创建 agent_user 失败。' }
    $databaseExists = & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'gis_agent'"
    if ($LASTEXITCODE -ne 0) { Fail '查询 gis_agent 数据库失败。' }
    if (-not $databaseExists) {
        & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE gis_agent OWNER agent_user'
        if ($LASTEXITCODE -ne 0) { Fail '创建 gis_agent 数据库失败。' }
    }
    & $psql -h 127.0.0.1 -p 5432 -U postgres -d gis_agent -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS vector;'
    if ($LASTEXITCODE -ne 0) { Fail '创建 PostGIS/pgvector 扩展失败。' }
    $grantSql = @"
GRANT CONNECT ON DATABASE gis_agent TO agent_user;
GRANT USAGE ON SCHEMA public TO agent_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agent_user;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO agent_user;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agent_user;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO agent_user;
"@
    & $psql -h 127.0.0.1 -p 5432 -U postgres -d gis_agent -v ON_ERROR_STOP=1 -c $grantSql
    if ($LASTEXITCODE -ne 0) { Fail '初始化 agent_user 数据表默认权限失败。' }
    # The migration runner deliberately removes ledger write access from the
    # runtime role. Run it as the PostgreSQL installer superuser, while the
    # application remains connected as agent_user.
    $previousUser = $env:POSTGRES_USER
    $previousPassword = $env:POSTGRES_PASSWORD
    $env:POSTGRES_USER = 'postgres'
    $env:POSTGRES_PASSWORD = $script:GdaPostgresPassword
    $env:MIGRATION_RUNTIME_DB_ROLE = 'agent_user'
    try {
        & $Python -m data_agent.migration_runner migrate
        if ($LASTEXITCODE -ne 0) { Fail 'GIS Data Agent PostgreSQL migration 失败。' }
    } finally {
        $env:POSTGRES_USER = $previousUser
        $env:POSTGRES_PASSWORD = $previousPassword
    }
}

function Install-PostgisAndPgvector {
    $postgis = Join-Path $InstallRoot 'payload\middleware\postgis-installer.exe'
    if (Test-Path -LiteralPath $postgis) {
        $postgisArgs = if ($env:GDA_POSTGIS_INSTALL_ARGS) { $env:GDA_POSTGIS_INSTALL_ARGS } else { '/SILENT /NORESTART' }
        $process = Start-Process -FilePath $postgis -ArgumentList $postgisArgs -Wait -PassThru
        if ($process.ExitCode -ne 0) { Fail "PostGIS 安装失败，exit=$($process.ExitCode)。可用 GDA_POSTGIS_INSTALL_ARGS 覆盖供应商参数。" }
    }
    $pgvector = Join-Path $InstallRoot 'payload\middleware\pgvector'
    if (-not (Test-Path -LiteralPath $pgvector)) { Fail '缺少 pgvector Windows 扩展制品。' }
    $pgRoot = if ($env:GDA_PGROOT) { $env:GDA_PGROOT } else { Join-Path $InstallRoot 'middleware\postgresql' }
    $lib = Join-Path $pgRoot 'lib'
    $share = Join-Path $pgRoot 'share\extension'
    if (-not (Test-Path -LiteralPath $lib)) { Fail "找不到 PostgreSQL lib：$lib；请设置 GDA_PGROOT。" }
    New-Item -ItemType Directory -Path $share -Force | Out-Null
    $copied = 0
    $expanded = Join-Path $InstallRoot 'runtime\pgvector-expanded'
    if (Test-Path -LiteralPath $expanded) { Remove-Item -LiteralPath $expanded -Recurse -Force }
    New-Item -ItemType Directory -Path $expanded -Force | Out-Null
    $archives = @(Get-ChildItem -LiteralPath $pgvector -Recurse -Filter '*.zip' -File -ErrorAction SilentlyContinue)
    foreach ($archive in $archives) { Expand-Archive -LiteralPath $archive.FullName -DestinationPath $expanded -Force }
    $roots = @($pgvector, $expanded) | Where-Object { Test-Path -LiteralPath $_ }
    $files = foreach ($root in $roots) {
        Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
            $_.Name -match '^(vector\.dll|vector\.control|vector--.*\.sql)$'
        }
    }
    foreach ($file in $files | Sort-Object FullName -Unique) {
        $target = if ($file.Extension -eq '.dll') { Join-Path $lib $file.Name } else { Join-Path $share $file.Name }
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $copied++
    }
    $hasDll = Test-Path -LiteralPath (Join-Path $lib 'vector.dll')
    $hasControl = Test-Path -LiteralPath (Join-Path $share 'vector.control')
    $hasSql = [bool](Get-ChildItem -LiteralPath $share -Filter 'vector--*.sql' -File -ErrorAction SilentlyContinue)
    if (-not ($hasDll -and $hasControl -and $hasSql)) { Fail 'pgvector 制品缺少 vector.dll/control/sql 文件。' }
}

function Install-JavaAndFuseki {
    $javaInstaller = Join-Path $InstallRoot 'payload\middleware\java-installer.msi'
    $javaRoot = Join-Path $InstallRoot 'middleware\java'
    New-Item -ItemType Directory -Path $javaRoot -Force | Out-Null
    if (Test-Path -LiteralPath $javaInstaller) {
        $javaArgs = @('/i', $javaInstaller, '/qn', '/norestart', "INSTALLDIR=$javaRoot")
        $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList $javaArgs -Wait -PassThru
        if ($process.ExitCode -notin @(0, 3010)) { Fail "Java 安装失败，exit=$($process.ExitCode)" }
    }
    $java = Get-ChildItem -LiteralPath $javaRoot -Filter 'java.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $java) {
        $java = Get-ChildItem -LiteralPath ${env:ProgramFiles} -Filter 'java.exe' -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match 'Temurin|Adoptium|jdk|jre' } | Select-Object -First 1
    }
    if (-not $java) { Fail 'Java 安装后找不到 java.exe；请检查 OpenJDK 17 MSI 或设置 GDA_JAVA_HOME。' }
    $script:JavaHome = Split-Path (Split-Path $java.FullName -Parent) -Parent
    Set-Content -LiteralPath (Join-Path $InstallRoot 'runtime\java-home.txt') -Value $script:JavaHome -Encoding UTF8
    $fusekiZip = Join-Path $InstallRoot 'payload\middleware\fuseki.zip'
    if (-not (Test-Path -LiteralPath $fusekiZip)) { Fail '缺少 Fuseki ZIP。' }
    $jenaZip = Join-Path $InstallRoot 'payload\middleware\jena.zip'
    if (-not (Test-Path -LiteralPath $jenaZip)) { Fail '缺少 Apache Jena ZIP。' }
    $fusekiRoot = Join-Path $InstallRoot 'middleware\fuseki'
    $jenaRoot = Join-Path $InstallRoot 'middleware\jena'
    New-Item -ItemType Directory -Path $fusekiRoot, $jenaRoot -Force | Out-Null
    Expand-Archive -LiteralPath $fusekiZip -DestinationPath $fusekiRoot -Force
    Expand-Archive -LiteralPath $jenaZip -DestinationPath $jenaRoot -Force
}

function Initialize-Fuseki([string]$Python) {
    $ontologyGz = Join-Path $InstallRoot 'config\ontology\natural_resource_one_map\2.3.0\ontology.ttl.gz'
    $ontologyRoot = Join-Path $DataRoot 'ontology'
    $ontologyTtl = Join-Path $ontologyRoot 'ontology.ttl'
    $tdbRoot = Join-Path $ontologyRoot 'tdb2'
    New-Item -ItemType Directory -Path $ontologyRoot, $tdbRoot -Force | Out-Null
    $code = 'import gzip, shutil, sys; shutil.copyfileobj(gzip.open(sys.argv[1], "rb"), open(sys.argv[2], "wb"))'
    & $Python -c $code $ontologyGz $ontologyTtl
    if ($LASTEXITCODE -ne 0) { Fail '自然资源本体 ontology.ttl.gz 解压失败。' }
    $loader = Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'middleware\jena') -Filter 'tdb2*.bat' -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('tdb2.tdbloader.bat', 'tdb2_tdbloader.bat') } | Select-Object -First 1
    if (-not $loader) { Fail 'Fuseki/Jena 分发包缺少 tdb2.tdbloader.bat。' }
    $env:JAVA_HOME = $script:JavaHome
    & cmd.exe /d /c "`"$($loader.FullName)`" --loc=`"$tdbRoot`" `"$ontologyTtl`""
    if ($LASTEXITCODE -ne 0) { Fail 'Fuseki TDB2 本体投影初始化失败。' }
}

function Install-Ollama {
    $installer = Join-Path $InstallRoot 'payload\middleware\OllamaSetup.exe'
    if (-not (Test-Path -LiteralPath $installer)) { Fail '缺少 Ollama 安装介质。' }
    $ollamaRoot = Join-Path $InstallRoot 'middleware\ollama'
    New-Item -ItemType Directory -Path $ollamaRoot -Force | Out-Null
    $ollamaArgs = if ($env:GDA_OLLAMA_INSTALL_ARGS) {
        $env:GDA_OLLAMA_INSTALL_ARGS
    } else {
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$ollamaRoot`""
    }
    $process = Start-Process -FilePath $installer -ArgumentList $ollamaArgs -Wait -PassThru
    if ($process.ExitCode -ne 0) { Fail "Ollama 安装失败，exit=$($process.ExitCode)" }
    $modelRoot = Join-Path $InstallRoot 'payload\models\ollama\gemma4-26b'
    if (-not (Test-Path -LiteralPath $modelRoot)) { Fail '缺少 Ollama LLM 权重。' }
    $embeddingRoot = Join-Path $InstallRoot 'payload\models\embedding\nomic-embed-text-v2-moe'
    if (-not (Test-Path -LiteralPath $embeddingRoot)) { Fail '缺少 embedding 模型权重。' }
    $ollama = Join-Path $ollamaRoot 'ollama.exe'
    if (-not (Test-Path -LiteralPath $ollama)) { $ollama = (Get-Command ollama.exe -ErrorAction SilentlyContinue).Source }
    if (-not $ollama) {
        $candidate = Join-Path ${env:LOCALAPPDATA} 'Programs\Ollama\ollama.exe'
        if (Test-Path -LiteralPath $candidate) { $ollama = $candidate }
    }
    if (-not $ollama) {
        $candidate = Join-Path ${env:ProgramFiles} 'Ollama\ollama.exe'
        if (Test-Path -LiteralPath $candidate) { $ollama = $candidate }
    }
    if (-not $ollama) { Fail 'Ollama 安装后找不到 ollama.exe。' }
    $script:OllamaExe = (Resolve-Path -LiteralPath $ollama).Path
    $llmModelfile = Get-ChildItem -LiteralPath $modelRoot -Filter 'Modelfile' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    $embeddingModelfile = Get-ChildItem -LiteralPath $embeddingRoot -Filter 'Modelfile' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $llmModelfile -or -not $embeddingModelfile) {
        Fail 'Ollama LLM 或 embedding Modelfile 不完整；离线包必须包含可导入的本地模型定义。'
    }
    $env:OLLAMA_MODELS = Join-Path $DataRoot 'ollama-models'
    New-Item -ItemType Directory -Path $env:OLLAMA_MODELS -Force | Out-Null
    # The Windows installer can leave a per-user Ollama server running on
    # 11434. Stop that process so model import and the SYSTEM task use the
    # same data-disk model root.
    Get-Process -Name 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    $previousHost = $env:OLLAMA_HOST
    $env:OLLAMA_HOST = '127.0.0.1:11435'
    $process = Start-Process -FilePath $script:OllamaExe -ArgumentList @('serve') -PassThru -WindowStyle Hidden
    try {
        Wait-LocalPort 11435
        Push-Location $llmModelfile.Directory.FullName
        try {
            & $script:OllamaExe create 'Gemma4:26b' -f 'Modelfile'
            if ($LASTEXITCODE -ne 0) { Fail 'Gemma4:26b 模型离线导入失败。' }
        } finally { Pop-Location }
        Push-Location $embeddingModelfile.Directory.FullName
        try {
            & $script:OllamaExe create 'nomic-embed-text-v2-moe:latest' -f 'Modelfile'
            if ($LASTEXITCODE -ne 0) { Fail 'nomic embedding 模型离线导入失败。' }
        } finally { Pop-Location }
    } finally {
        if ($process) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
        $env:OLLAMA_HOST = $previousHost
    }
}

function Install-OptionalMonitoring {
    foreach ($name in @('prometheus', 'grafana')) {
        $archive = Join-Path $InstallRoot "payload\monitoring\$name.zip"
        if (-not (Test-Path -LiteralPath $archive)) { continue }
        $target = Join-Path $InstallRoot "middleware\$name"
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Expand-Archive -LiteralPath $archive -DestinationPath $target -Force
    }
}

function Write-Environment([string]$Python) {
    $template = Get-Content -LiteralPath (Join-Path $InstallRoot 'config\gda.env.template') -Raw -Encoding UTF8
    $secret = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    $sitePackages = Join-Path (Split-Path $Python -Parent) 'Lib\site-packages'
    $projData = Join-Path $sitePackages 'pyproj\proj_dir\share\proj'
    $gdalData = Join-Path $sitePackages 'rasterio\gdal_data'
    if (-not (Test-Path -LiteralPath $projData)) { $projData = '' }
    if (-not (Test-Path -LiteralPath $gdalData)) { $gdalData = '' }
    $values = @{
        '__DB_BACKEND__' = if ($Profile -eq 'production') { 'postgres' } else { 'duckdb' }
        '__POSTGRES_PASSWORD__' = if ($Profile -eq 'production') { $script:GdaPostgresPassword } else { '' }
        '__MINIO_PASSWORD__' = if ($Profile -eq 'production') { $script:GdaMinioPassword } else { '' }
        '__INSTALL_ROOT__' = $InstallRoot
        '__DATA_ROOT__' = $DataRoot
        '__INBOX_ROOT__' = $Inbox
        '__CONFIG_ROOT__' = (Join-Path $InstallRoot 'config')
        '__LOG_ROOT__' = $LogRoot
        '__CHAINLIT_AUTH_SECRET__' = $secret
        '__ROUTER_MODEL__' = if ($Profile -eq 'production') { 'gemma4-26b-ollama' } else { 'gemini-2.0-flash' }
        '__STANDARDIZED_VECTOR_FORMAT__' = if ($Profile -eq 'production') { 'PostgreSQL' } else { 'Parquet' }
        '__POSTGIS_DSN__' = if ($Profile -eq 'production') { "postgresql://agent_user:$script:GdaPostgresPassword@127.0.0.1:5432/gis_agent" } else { '' }
        '__JAVA_HOME__' = $script:JavaHome
        '__OLLAMA_EXE__' = $script:OllamaExe
        '__PROJ_DATA__' = $projData
        '__GDAL_DATA__' = $gdalData
    }
    foreach ($key in $values.Keys) { $template = $template.Replace($key, $values[$key]) }
    $envPath = Join-Path $InstallRoot 'config\gda.env'
    Set-Content -LiteralPath $envPath -Value $template -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $InstallRoot 'config\natural_resource_standard_contracts.candidate.json') -Destination (Join-Path $InstallRoot 'config\natural_resource_standard_contracts.json') -Force
    return $envPath
}

Assert-Administrator
Assert-Host
$manifest = Read-Manifest
Assert-Checksums
Assert-RequiredArtifacts $manifest
Copy-Payload
New-Directories
Configure-Firewall
$python = Install-Python
Install-Wheels $python
if ($Profile -eq 'production') {
    Install-Postgres
    Install-PostgisAndPgvector
    Install-JavaAndFuseki
    Initialize-Fuseki $python
    Install-Ollama
    Install-OptionalMonitoring
}
$envPath = Write-Environment $python
$env:PYTHONPATH = Join-Path $InstallRoot 'payload\app'
$env:GDA_FILE_LAKE_ROOT = Join-Path $DataRoot 'file_lake'
$env:GDA_FILE_LAKE_INBOX = $Inbox
$env:GDA_STANDARD_CONTRACTS = Join-Path $InstallRoot 'config\natural_resource_standard_contracts.json'
$env:GDA_ONTOLOGY_ACTIVE = Join-Path $InstallRoot 'config\ontology\natural_resource_one_map\active.json'
$env:GDA_LOG_DIR = $LogRoot
$env:MIGRATION_RUNTIME_DB_ROLE = 'agent_user'
$sitePackages = Join-Path (Split-Path $python -Parent) 'Lib\site-packages'
$env:GDA_PROJ_DATA = Join-Path $sitePackages 'pyproj\proj_dir\share\proj'
$env:GDA_GDAL_DATA = Join-Path $sitePackages 'rasterio\gdal_data'
if (-not (Test-Path -LiteralPath $env:GDA_PROJ_DATA)) { $env:GDA_PROJ_DATA = '' }
if (-not (Test-Path -LiteralPath $env:GDA_GDAL_DATA)) { $env:GDA_GDAL_DATA = '' }
if ($Profile -eq 'production') {
    $env:DB_BACKEND = 'postgres'
    $env:POSTGRES_HOST = '127.0.0.1'
    $env:POSTGRES_PORT = '5432'
    $env:POSTGRES_DATABASE = 'gis_agent'
    $env:POSTGRES_USER = 'agent_user'
    $env:POSTGRES_PASSWORD = $script:GdaPostgresPassword
    $env:GDA_STANDARDIZED_VECTOR_FORMAT = 'PostgreSQL'
    $env:GDA_POSTGIS_DSN = "postgresql://agent_user:$script:GdaPostgresPassword@127.0.0.1:5432/gis_agent"
    Initialize-MinIO
    Initialize-PostgresDatabase $python
} else {
    $env:DB_BACKEND = 'duckdb'
    $env:GDA_STANDARDIZED_VECTOR_FORMAT = 'Parquet'
    $env:GDA_DUCKDB_PATH = Join-Path $DataRoot 'control\gis_data_agent.duckdb'
    & $python -m data_agent.lite_mode init
    if ($LASTEXITCODE -ne 0) { Fail 'DuckDB 控制库初始化失败。' }
}

$preflight = Join-Path $InstallRoot 'scripts\preflight_windows_ingest.py'
$preflightMode = if ($Profile -eq 'production') { 'production' } else { 'development' }
& $python $preflight --mode $preflightMode --lake (Join-Path $DataRoot 'file_lake') `
    --inbox $Inbox --contracts (Join-Path $InstallRoot 'config\natural_resource_standard_contracts.json') `
    --ontology (Join-Path $InstallRoot 'config\ontology\natural_resource_one_map\active.json') `
    --create-directories --output (Join-Path $DataRoot 'file_lake\diagnostics\windows-ingest-preflight.json')
$preflightExit = $LASTEXITCODE

$verify = Join-Path $InstallRoot 'scripts\verify_windows_offline_bundle.py'
$verifyArgs = @('--bundle-root', $InstallRoot, '--profile', $Profile, '--phase', 'install', '--output', (Join-Path $DataRoot 'file_lake\diagnostics\bundle-verify.json'))
& $python $verify @verifyArgs
$verifyExit = $LASTEXITCODE

$state = [ordered]@{
    schema_version = 'gda.windows-install-state.v1'
    installed_at = (Get-Date).ToUniversalTime().ToString('o')
    profile = $Profile
    bundle_version = $manifest.bundle_version
    install_root = $InstallRoot
    data_root = $DataRoot
    inbox = $Inbox
    log_root = $LogRoot
    env_file = $envPath
    python = $python
    preflight_exit = $preflightExit
    verify_exit = $verifyExit
    status = if ($verifyExit -eq 0 -and $preflightExit -eq 0) { 'installed' } else { 'blocked_pending_contract_or_host_fix' }
}
$state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $InstallRoot 'runtime\install-state.json') -Encoding UTF8
Protect-Configuration

if ($verifyExit -ne 0 -or $preflightExit -ne 0) {
    Write-Warning "安装完成但验收状态为 blocked。请查看 $DataRoot\file_lake\diagnostics\bundle-verify.json；start_gda.ps1 会拒绝启动。"
    exit 2
}
Write-Host "GIS Data Agent $Profile 离线安装完成：$InstallRoot"
