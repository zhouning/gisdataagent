# GIS Data Agent Windows 裸机离线部署包

这个目录定义的是宁夏现场的可交付包格式。现场主机可以完全没有 Python、GIS、数据库、
Java、对象存储或模型服务；安装器从 ZIP 内的真实 Windows x64 制品安装它们，并在启动前
执行完整性和能力预检。

## 给 Windows 机器的最短执行路径

整个过程分成两个阶段：联网的 Windows x64 **staging 机**负责准备制品并生成 ZIP；物理隔离的
**现场机**只接收 ZIP、安装和验收。现场机不需要 Git、Node.js、npm、Python 或互联网。

在 staging 机执行：

```powershell
git clone -b feat/windows-standalone-offline-bundle `
  https://github.com/zhouning/gisdataagent.git
Set-Location gisdataagent
git rev-parse HEAD

Set-Location frontend
npm ci
npm run build
Set-Location ..

python -m pip download --only-binary=:all: --platform win_amd64 --python-version 311 `
  --implementation cp --abi cp311 `
  --dest deploy\windows-standalone\vendor\wheelhouse\core `
  -r deploy\windows-standalone\requirements-windows-core.txt
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 311 `
  --implementation cp --abi cp311 `
  --dest deploy\windows-standalone\vendor\wheelhouse\production `
  -r deploy\windows-standalone\requirements-windows-production.txt

python deploy\windows-standalone\build_offline_bundle.py `
  --profile native-lite `
  --vendor-root deploy\windows-standalone\vendor `
  --output deploy\windows-standalone\out\GIS-Data-Agent-Windows-native-lite.zip

$zip = Resolve-Path .\deploy\windows-standalone\out\GIS-Data-Agent-Windows-native-lite.zip
$sha256 = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$sha256  $([IO.Path]::GetFileName($zip))" | Set-Content -LiteralPath "$zip.sha256" -Encoding ASCII
```

构建器会在缺少任何必需 Windows 制品时返回 `blocked`，这时应补齐 `vendor/` 后重试，不能把
不完整 ZIP 带到现场。只需要文件湖、GIS 入湖、质检、血缘和本体结构浏览时，可把最后一条的
`native-lite` 换成 `core`；native-lite 档位还需要 PostgreSQL/PostGIS/pgvector、MinIO、Jena/Fuseki 和
Paper9 制品，并在安装时配置可访问的内网 LM Studio，详见下面的目录约定。

记录 `git rev-parse HEAD` 和 ZIP 的外部 SHA-256。移动硬盘必须复制三个文件：最终 ZIP、同名
`.sha256` 和构建器生成的 `GIS-Data-Agent-Windows-native-lite-PRE-INSTALL.txt`。现场人员先阅读
外置 TXT，完成哈希和 LM Studio 前置检查后再解压；ZIP 内的 `README.md` 继续作为解压后的详细
安装与运维文档。现场机不要运行 `npm`、`pip download` 或尝试联网拉模型。

## 两个安装档位

| 档位 | 包含 | 可提供的能力 | 生产门禁 |
|---|---|---|---|
| `core` | Python 3.11、GIS wheelhouse、应用、DuckDB、文件湖、日志、断点续传采集器、本体 2.3、宁夏字段基线 | FileGDB/SHP/TIFF 入湖、画像、治理、质检、血缘、GeoParquet/COG/STAC、本体结构查询 | 每个数据集按字段、CRS、几何和值域质量决定是否可发布 |
| `native-lite` | `core` + PostgreSQL 16/PostGIS/pgvector、MinIO、JRE 17 + Jena/Fuseki/TDB2、Paper9；外部依赖内网 LM Studio 的 Qwen 与 768 维 embedding 模型 | 单机在线空间查询、对象存储、本体查询投影、内网模型语义问数、Paper9 运行 | LM Studio 两个模型必须可调用；包内字段基线必须存在；每个数据集和 Paper9 输入仍须通过各自质量门禁 |

`production` 仅作为旧命令的兼容别名保留，能力和制品集合与 `native-lite` 相同。`native-lite` 是单机原生部署，不等同于包含 Spark、Flink、DolphinScheduler、Temporal、OpenMetadata 或 Gravitino 的完整分布式生产平台。

`Prometheus` 和 `Grafana` 是可选组件；本次 native-lite ZIP 未携带它们，构建和验收会明确记录
warning，但不会把它们计入 required artifact。Redis、DolphinScheduler、Spark/Flink、
OpenMetadata、Compose 的 CV/CAD/reference-data、Martin tiles 和 AlphaEarth 演示服务没有被
伪装成 Windows 原生必需件：它们在仓库中对应的是可选容器/Linux 或独立演示形态。
裸机核心用 DuckDB、文件日志和 Windows Task Scheduler；如现场必须启用这些系统，需要另配
受支持的 Linux 节点并走单独的部署变更。

## 目录约定

联网 staging 机准备 `vendor/`，目录和 `bundle-manifest.json` 中的 glob 对齐。构建器不下载
任何文件，只会复制并计算 SHA-256。推荐先从官方来源取得介质，再由安全人员登记供应商哈希。

```text
vendor/python/python-3.11.9-amd64.exe
vendor/wheelhouse/core/*.whl
vendor/wheelhouse/production/*.whl
vendor/middleware/postgresql/postgresql-16.*-windows-x64.exe
vendor/middleware/postgis/postgis-bundle-pg16x64-setup-3.*.exe
vendor/middleware/pgvector/*
vendor/middleware/minio/minio.exe
vendor/middleware/minio/mc.exe
vendor/middleware/java/OpenJDK17U-jre_x64_windows_hotspot_*.msi
vendor/middleware/jena/apache-jena-*.zip
vendor/middleware/fuseki/apache-jena-fuseki-*.zip
vendor/paper9/source/*
vendor/paper9/wheelhouse/*.whl
vendor/paper9/models/*
```

## 在联网 staging 机制作 ZIP

staging 机应为 Windows x64，并使用与现场相同的 Python 3.11 小版本。先准备 wheelhouse：

```powershell
# 前端构建只发生在联网 staging 机；现场 ZIP 不需要 Node.js。
# Node.js 20 LTS（或更高的受支持 LTS）和 npm 必须可用。
Set-Location frontend
npm ci
npm run build
Set-Location ..

python -m pip download --only-binary=:all: --platform win_amd64 --python-version 311 `
  --implementation cp --abi cp311 --dest deploy\windows-standalone\vendor\wheelhouse\core `
  -r deploy\windows-standalone\requirements-windows-core.txt
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 311 `
  --implementation cp --abi cp311 --dest deploy\windows-standalone\vendor\wheelhouse\production `
  -r deploy\windows-standalone\requirements-windows-production.txt
```

`npm run build` 必须生成 `frontend\dist`，否则构建器会阻断。上面的 pip 命令只准备 Python 包，
PostgreSQL/PostGIS、pgvector、MinIO、JRE、Fuseki 和 Paper9 必须从批准的离线制品库放入 `vendor/`。
Qwen 和 embedding 模型由内网 LM Studio 提供，不进入 `vendor/`。随后构建：

```powershell
python deploy\windows-standalone\build_offline_bundle.py `
  --profile core `
  --vendor-root deploy\windows-standalone\vendor `
  --output deploy\windows-standalone\out\GIS-Data-Agent-Windows-core.zip

python deploy\windows-standalone\build_offline_bundle.py `
  --profile native-lite `
  --vendor-root deploy\windows-standalone\vendor `
  --output deploy\windows-standalone\out\GIS-Data-Agent-Windows-native-lite.zip
```

构建器缺少任意 required artifact、wheelhouse 直接依赖或最小文件数时返回 `blocked`，不产生
ZIP。生成的 ZIP 内含 `manifest.json`、`SHA256SUMS` 和安装脚本；它们应与介质一起登记到交付单。
生产 wheelhouse 还必须包含 `litellm`，否则 LM Studio 的 OpenAI-compatible 路由无法工作。

## 内网安装

把 ZIP 复制到现场临时目录后，使用管理员 PowerShell 解压并执行：

```powershell
Expand-Archive .\GIS-Data-Agent-Windows-native-lite.zip -DestinationPath D:\GDA_STAGING
Set-Location D:\GDA_STAGING\GIS-Data-Agent-23.0.0-windows-standalone.2-native-lite
.\install_offline_bundle.ps1 `
  -Profile native-lite `
  -InstallRoot D:\GDA `
  -DataRoot D:\GDA_DATA `
  -Inbox D:\NX_INCOMING `
  -LogRoot D:\GDA_LOGS `
  -LmStudioBaseUrl 'http://LM-STUDIO-SERVER:1234/v1' `
  -LmStudioChatModel '<QWEN_MODEL_ID>' `
  -LmStudioEmbeddingModel '<EMBEDDING_MODEL_ID>' `
  -LmStudioApiKey $env:LM_STUDIO_API_KEY

.\register_tasks.ps1 -InstallRoot D:\GDA -RunAs SYSTEM
.\start_gda.ps1 -InstallRoot D:\GDA
```

安装器会检查 Windows x64、管理员权限、路径长度、磁盘空间和 ZIP 内哈希，静默安装 Python，
使用 `pip --no-index --find-links` 安装 wheel，创建 `D:\GDA_DATA\file_lake`、`D:\NX_INCOMING`、
`D:\GDA_LOGS` 和诊断目录，复制本体/合同模板，生成随机 Chainlit 密钥，并把安装状态写入
`D:\GDA\runtime\install-state.json`。native-lite 档位还会安装并初始化 PostgreSQL/PostGIS/pgvector、
创建 `gis_agent` 数据库和 `agent_user`，执行项目 migration；随后安装 MinIO 和 Java/Fuseki。
它不会安装 Ollama，也不会复制 Gemma4 或 embedding 权重。安装器把 LM Studio 地址、Qwen model ID、
embedding model ID 和可选 API key 写入受保护的 `gda.env`，调用 `/v1/models` 与 `/v1/embeddings`
验收两个模型，并要求 embedding 返回 768 维；应用启动后还会执行一次最小 `/v1/chat/completions` 验收。
请把示例中的 `LM-STUDIO-SERVER` 和两个 model ID 替换为内网 LM Studio 实际值。

PostgreSQL 安装与 PostGIS 扩展安装全程不需要人工输入密码。默认随机生成的 PostgreSQL 超级用户密码保存在
`D:\GDA\runtime\postgres-superpassword.txt`，应用连接密码和 MinIO 密码保存在 `D:\GDA\config\gda.env`；
这两个位置安装后只允许 SYSTEM 和本机 Administrators 读取。需要预设 PostgreSQL 密码时，在安装前设置
`GDA_POSTGRES_PASSWORD`，不要修改脚本或把密码写入移动硬盘。

宁夏两份 Excel 及 EA 对齐产物会被复制为
`natural_resource_standard_baseline.json`，作为系统启动和字段匹配基线。预检只检查基线文件
是否存在、可解析；真实 FileGDB/SHP/TIFF 到达后，系统按数据集执行字段、类型、CRS、几何、值域
和质量校验。通过校验的治理产物可以进入本体引用和语义问数，失败的数据集单独停在 `review`
或 `blocked`，不会拖住整个系统。需要行政发布留痕时，仍可另外生成 `authority=ea_standard`
的审核版本，但这不是安装启动前置条件。

当前基线 JSON 已包含 EA/角色对象、两份宁夏工作簿和自然资源标准共同形成的 49 个运行时合同，
以及至少 893 条直接字段证据（SHP 字段表 765 条 + 第一份 Excel 专题页 116 条 + 标准补齐 12 条；
重合代码并列保留）；不是只保存工作簿哈希或只覆盖 DLTB 等少数对象。

现场不需要另外提供 `natural_resource_standard_contracts.json`。安装器会把 ZIP 内置的
`natural_resource_standard_baseline.json` 复制成运行时文件；后续真实数据仍按数据集执行字段、CRS、几何、值域和质量校验。

## 启停与任务计划

```powershell
.\start_gda.ps1 -InstallRoot D:\GDA
.\stop_gda.ps1 -InstallRoot D:\GDA
.\register_tasks.ps1 -InstallRoot D:\GDA -RunAs SYSTEM
.\unregister_tasks.ps1 -InstallRoot D:\GDA
.\collect_diagnostics.ps1 -InstallRoot D:\GDA -OutputDirectory D:\GDA_DIAGNOSTICS
```

`start_gda.ps1` 按顺序启动本地中间件、Chainlit 应用和 `windows_ingest_worker.py`，每个进程的
标准输出/错误都落到 `GDA_LOG_DIR`；它不会在预检 `blocked` 时强行启动。Task Scheduler 是
断电自动恢复的默认机制，任务动作以 `-Supervise` 持续运行并监控应用/采集 worker，子进程异常退出
会让任务失败并触发重启；`stop_gda.ps1` 使用显式停止标记避免被自动拉起。任务使用固定的安装目录和
环境文件，不依赖用户登录会话。
诊断脚本会收集安装状态、预检/运行报告、磁盘信息和日志，并自动脱敏密码、密钥和 token，
生成可通过受控介质带出内网的 ZIP。

## Windows 验收与 GitHub 反馈

请把本目录所在分支检出到联网 staging 机，只在 staging 机准备 `vendor/` 并构建 ZIP；不要把
真实数据、密码、模型权重或最终 ZIP 提交到 GitHub。现场主机安装后，至少保存以下文件：

```text
D:\GDA_DATA\file_lake\diagnostics\windows-ingest-preflight.json
D:\GDA_DATA\file_lake\diagnostics\bundle-verify.json
D:\GDA_LOGS\bundle-runtime-verify.json
D:\GDA\runtime\install-state.json
```

安装或启动失败时执行：

```powershell
.\collect_diagnostics.ps1 -InstallRoot D:\GDA -OutputDirectory D:\GDA_DIAGNOSTICS
```

然后在 GitHub 仓库新建 Issue，标题使用 `[Windows offline] 阶段 - 错误摘要`，正文至少填写：

```text
分支：feat/windows-standalone-offline-bundle
Commit SHA：
阶段：staging 构建 / 现场安装 / 启动 / 数据入湖 / 治理 / 问数 / Paper9
Profile：core / native-lite（production 仅为兼容别名）
Windows 版本：
CPU / 内存 / 数据盘剩余空间：
执行的完整命令：
预期结果：
实际错误全文：
bundle-verify.json 状态及 reasons：
windows-ingest-preflight.json 状态及 reasons：
诊断 ZIP 文件名和 SHA-256：
```

附上脱敏后的 `bundle-verify.json`、`windows-ingest-preflight.json`、安装器/启动器错误文本。诊断
ZIP 可以通过受控介质交给项目组，
但不要上传数据湖原件、FileGDB/TIFF、`.env`、密码、token、私钥或模型权重。若需要修改脚本，
请从该分支建立修复分支并提交最小复现日志，便于在 GitHub 上追踪。

升级时使用新的版本目录（例如 `D:\GDA-23.0.1`），通过验收后再注销旧任务并注册新任务；
不要覆盖旧目录或数据盘。回滚只需停止新目录进程并把 Task Scheduler 动作切回旧目录，Raw、
DuckDB/PostgreSQL、对象存储和日志数据盘保持不变。删除旧版本前必须先完成备份和变更审批。

## 现场真实数据到达

供应方把完整 FileGDB 目录、SHP sidecar 或 TIFF 放到 `GDA_LOCAL_INGEST_DIRS` 指定的 inbox，
或使用页面/API 创建分片上传 session。worker 等待源签名稳定后才计算 hash；每个 run 持久化
`run.json`、`manifest.json`、`quality_report.json`、`lineage.json` 和 `events.jsonl`。同名不同
hash 形成新版本，Raw 原件不覆盖。字段合同不完整、CRS/几何/值域质量不合格的数据停在
`review/blocked`，不会被误绑定到本体或进入权威问数。

## 明确的交付边界

交付物必须是实际构建并通过哈希和解压验收的 `GIS-Data-Agent-Windows-native-lite.zip`、同名
`.sha256` 和外置 `GIS-Data-Agent-Windows-native-lite-PRE-INSTALL.txt` 三个文件，不能只交构建器或
安装脚本。ZIP 包含 Windows x64 wheel、PostgreSQL/PostGIS/pgvector、MinIO、JRE/Jena/Fuseki 和
Paper9 制品；不包含 Ollama、Gemma4 或文本 embedding 权重。构建器缺少任一 required artifact 时会
阻断，不会生成可误带入现场的不完整包。该包不包含容器平台和分布式数据平台组件；内网 LM Studio
是明确的外部运行依赖。
