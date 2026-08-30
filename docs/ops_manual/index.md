# Data Agent 运维手册

## 1. 系统要求
- **OS**: Windows 10/11, Linux (Ubuntu 20.04+), macOS
- **Runtime**: Python 3.13+ (推荐), Node.js 20+ (前端构建)
- **数据库**: PostgreSQL 16 + PostGIS 3.4
- **可选**: Redis (实时流功能), Huawei OBS (云存储)
- **GPU**: 非必需 (DRL 模型使用 CPU 推理)

## 2. 部署方式

### 2.1 Docker 部署 (推荐)
```bash
# 克隆代码
git clone <repository_url>
cd adk

# 一键启动 (含 PostGIS + Redis)
docker-compose up -d

# 生产环境
docker-compose -f docker-compose.prod.yml up -d
```

访问 `http://localhost:8000`，默认账户：`admin` / `admin123`

### 2.2 本地开发部署
```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv/Scripts/activate      # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp data_agent/.env.example data_agent/.env
# 编辑 .env 填入 PostgreSQL 连接信息和 API Key

# 4. 启动后端
chainlit run data_agent/app.py -w

# 5. 构建前端 (可选)
cd frontend && npm install && npm run build
```

### 2.3 Kubernetes 部署
项目提供 11 个 K8s 清单文件 (`k8s/` 目录)：

| 文件 | 说明 |
|------|------|
| `namespace.yaml` | 命名空间定义 |
| `configmap.yaml` | 配置管理 |
| `secret.yaml` | 密钥存储 |
| `app-deployment.yaml` | 应用 Deployment (含健康检查) |
| `app-service.yaml` | 应用 Service |
| `postgres-statefulset.yaml` | PostgreSQL StatefulSet |
| `postgres-service.yaml` | 数据库 Service |
| `ingress.yaml` | Ingress 路由 |
| `networkpolicy.yaml` | 网络策略 |
| `hpa.yaml` | 水平 Pod 自动扩展 |
| `kustomization.yaml` | Kustomize 编排 |

```bash
kubectl apply -k k8s/
```

## 3. 环境变量配置

### 必需配置
```ini
# PostgreSQL/PostGIS
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# AI 模型
GOOGLE_API_KEY=your-gemini-api-key
# 或 Vertex AI
GOOGLE_CLOUD_PROJECT=your-gcp-project
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json

# Chainlit 认证密钥
CHAINLIT_AUTH_SECRET=your-random-secret-key
```

### 可选配置
```ini
# 天地图底图
TIANDITU_TOKEN=your-tianditu-token

# 高德地图 API (地理编码)
AMAP_API_KEY=your-amap-key

# OAuth2 (Google)
OAUTH_GOOGLE_CLIENT_ID=xxx
OAUTH_GOOGLE_CLIENT_SECRET=xxx

# Huawei OBS 云存储
OBS_AK=xxx
OBS_SK=xxx
OBS_ENDPOINT=xxx
OBS_BUCKET=xxx

# Redis (实时流)
REDIS_URL=redis://localhost:6379

# 使用限额
DAILY_ANALYSIS_LIMIT=20    # 每用户每日分析次数
MONTHLY_TOKEN_LIMIT=0      # 0=无限制

# 动态规划器
DYNAMIC_PLANNER=true       # false=使用固定管道
```

## 4. 数据库迁移

项目包含 16 个 SQL 迁移脚本 (`data_agent/migrations/`)：
```bash
# 手动执行
psql -U postgres -d gis_agent -f data_agent/migrations/001_create_users.sql

# 使用脚本
./scripts/migrate.sh
```

关键迁移：
- `001`: 用户表
- `004`: 行级安全 (RLS)
- `014`: 数据湖目录
- `015`: 邮箱字段
- `016`: 地图标注表

## 5. 健康检查

| 端点 | 用途 | 认证 |
|------|------|------|
| `GET /health` | 存活探测 (始终 200) | 无 |
| `GET /ready` | 就绪探测 (数据库不可用时 503) | 无 |
| `GET /api/admin/system-info` | 系统诊断 | HMAC |

K8s 配置已在 `app-deployment.yaml` 中预设。

## 6. 监控与可观测性

### 结构化日志
所有日志使用 JSON 格式输出 (通过 `observability.py`)，包含：
- 时间戳、日志级别、模块名、用户名
- 兼容 ELK Stack / CloudWatch / Google Cloud Logging

### Prometheus 指标
`observability.py` 暴露以下指标：
- `auth_events_total` — 认证事件计数
- `pipeline_runs_total` — 管道执行计数
- 可通过 `/metrics` 端点采集

### ApprovalCase 通知投递演练

ApprovalCase 通知 worker 暴露以下低基数指标：

- `gda_approval_notification_operations_total{outcome=...}`：claim、delivery、retry、dead-letter 和 cycle error 计数。
- `gda_approval_notification_cycle_duration_seconds`：一次 claim/delivery/ack 周期耗时。
- `gda_approval_notification_last_success_timestamp_seconds`：最近一次无异常消费周期的 Unix 时间戳。

使用一次性 PostgreSQL、真实 Alertmanager v2 API 和真实 Prometheus scrape 验证 requested、decided、
expired、receiver 故障重试、稳定告警关闭和 outbox 幂等：

```bash
uv run python scripts/rehearse_approval_alertmanager_delivery.py \
  --output /tmp/gda-approval-alertmanager-rehearsal.json
```

脚本默认固定使用 `postgres:16`、`prom/alertmanager:v0.28.1` 和
`prom/prometheus:v3.5.0`。它会先准备镜像，再创建随机命名和随机宿主端口的一次性容器；失败和成功路径
都会关闭进程内 metrics server 并删除容器。只有 Alertmanager 最终只保留 expired case、approved case
被同一稳定标签关闭、数据库 outbox 状态矩阵正确、Prometheus 读到至少 4 次 delivered 和 2 次
retrying、最终 claim 为 0 且资源清理完成时，报告才会返回 `status=verified`。

该演练证明本地开发环境的真实协议互操作和故障恢复，不证明生产集群、认证/TLS、HA、告警升级策略、
dashboard 或 on-call 系统已经验收。

### ApprovalCase 生产形态监控组件

`k8s/observability/approval-notifications` 提供两副本 worker、PDB、ServiceMonitor、7 条 SLI recording
rule、5 条告警规则、AlertmanagerConfig、Grafana dashboard ConfigMap 和最小 NetworkPolicy。部署前必须满足：

- 集群已安装 Prometheus Operator 的 `ServiceMonitor`、`PrometheusRule`、`AlertmanagerConfig` CRD，并选择
  `gis-agent` namespace 中的资源。
- `gis-agent-approval-notification-runtime` Secret 已由 External Secrets/Vault 等安全流程创建，包含
  `postgres-password`、`tenant-id`、`alertmanager-url` 和 `alertmanager-token` 四个 key。
- `gis-agent-approval-oncall` Secret 已包含 `webhook-url` key。URL 和 token 不进入 Git、ConfigMap 或命令行。
- `alertmanager-url` 指向受认证的 Alertmanager gateway，URL 本身不得携带用户名或密码。
- 集群 Grafana sidecar 已配置为监听 `gis-agent` namespace 中 `grafana_dashboard=1` 的 ConfigMap；若使用
  其他 dashboard 分发机制，必须保持 UID `gda-approval-case-operations` 和只读 provisioning 语义。

先渲染并做服务端 dry-run，再在获准的环境部署：

```bash
kubectl kustomize k8s/observability/approval-notifications \
  > /tmp/gda-approval-observability.yaml
kubectl apply --dry-run=server -f /tmp/gda-approval-observability.yaml
kubectl apply -k k8s/observability/approval-notifications
```

本地验证 Prometheus 规则和真实 receiver 过滤，不需要企业 webhook：

```bash
uv run python scripts/rehearse_approval_observability_routing.py \
  --output /tmp/gda-approval-observability-routing.json
```

报告只有在 amtool/promtool 通过、真实 Alertmanager 仅把 `GDAApprovalCase` 送入 `approval-oncall`、无关
控制告警未进入 receiver 且一次性资源已清理时才返回 `status=verified`。

本地验证 recording rules、Prometheus datasource 和 Grafana dashboard 的真实 provisioning：

```bash
uv run python scripts/rehearse_approval_grafana_provisioning.py \
  --output /tmp/gda-approval-grafana-provisioning.json
```

脚本固定使用 Prometheus 3.5.0 和 Grafana 11.6.0，启动随机命名的一次性网络与容器。只有 Prometheus API
加载完整 7 条 recording rule、Grafana datasource health 为 OK、固定 UID 看板可搜索且位于固定 folder、
10 个面板均由文件 provisioning 加载，并且容器与网络全部清理后，报告才返回 `status=verified`。看板定义在
`k8s/observability/approval-notifications/dashboards/approval-case-operations.json`，Grafana provisioning 定义在
`config/grafana/provisioning`。

该演练证明本地真实二进制/API 互操作，不证明当前 Docker Desktop 已部署 Prometheus Operator/Grafana
sidecar，也不证明 staging/production 的长期存储、企业认证/TLS、paging escalation 或多集群聚合已经验收。

### SLO 定义权威与审批门

迁移 122 建立通用、租户隔离的 `SLODefinitionVersion` 权威。运维上必须区分三个状态：

- SLI observation 只陈述观测事实，不是目标。
- staged SLO version 是等待 owner/SRE 评审的不可变候选，不能生成部署规则。
- active SLO version 必须绑定 action 为 `slo_definition.activate` 的 approved ApprovalCase，且 target
  ResourceURN 和数据库计算的 SHA-256 必须完全一致。

owner、on-call、目标、窗口或 burn-rate policy 的任何变化都必须创建新版本并重新审批。禁止直接修改
`gda_control.slo_definition_version`、`slo_definition_activation` 或 `slo_definition_event`；gateway 只通过
`stage_slo_definition_version` 和 `activate_slo_definition_version` 两个受控函数写入。

平台控制面通过 `/api/platform/v1/slo-definitions/{slo_definition_id}` 提供以下操作：

- `POST /versions`：由服务端从认证上下文注入 tenant、typed actor 和创建时间，写入候选版本。
- `GET /versions`：以 `limit`/`offset` 查询不可变版本，最大页长 100。
- `POST /versions/{version}/approval-cases`：从数据库读取目标版本及 fingerprint，创建精确绑定的
  `slo_definition.activate` ApprovalCase，调用方不能提交或覆盖 fingerprint。
- `POST /versions/{version}/activation`：仅 `admin` 可调用，并必须提供当前 `activation_version` 作为 CAS；
  数据库仍会独立检查 ApprovalCase 已批准、未过期、由 human 决定且 target/action/fingerprint 完全一致。
- `GET /active`、`GET /events`：分别读取当前 active pointer 和不可变审计事件。
- `GET /versions/{version}/prometheus-rules`：只有请求版本与 exact active pointer 和 fingerprint 一致时才返回
  规则；候选版本返回 `409 slo_version_not_active`，不得将此保护转换为静态候选 YAML 回退。

建议操作顺序固定为 stage -> 创建 ApprovalCase -> 独立 human 审批 -> admin CAS activate -> 读取规则并进入后续
rollout。API 返回规则只证明控制面授权状态，不等于规则已经发布到 Prometheus；生产 rollout、回滚与多集群对账
仍需独立完成。

本地执行真实 PostgreSQL 与 promtool 认证：

```bash
uv run python scripts/certify_slo_definition_authority.py \
  --output /tmp/gda-slo-definition-authority.json
```

报告只有在 pending/rejected/错 action/错 fingerprint 审批全部拒绝、精确 approved 版本激活、幂等重放、
stale CAS、双租户隔离、不可变 trigger、最小权限和 active-only 编译全部通过，并且生成规则通过真实
Prometheus 3.5.0 校验且容器清理完成后，才返回 `status=verified`。认证中的 99% 是一次性测试数据，不是
已批准的生产 SLO。

### SLO 告警到 DataIncident 收敛

迁移 123 将 `DataIncident` 的主体扩展为恰好二选一：`run_id` 或 canonical
`subject_resource_urn`。原有 Run 事故语义和 fingerprint 保持兼容；服务 SLO 事故直接绑定获批 SLO 所属的
service ResourceURN，不创建虚假的 PlatformRun。两类事故共用不可变主体、CAS 状态迁移、顺序
`DataIncidentEvent` 和事务性 notification outbox。

Alertmanager 将 webhook v4 发送到：

```text
POST /api/platform/v1/slo-alerts/alertmanager
```

该请求必须通过平台既有认证并解析为 `WORKLOAD` principal，且认证 actor 必须与
`GDA_SLO_ALERT_DETECTOR_SUBJECT` 完全一致；tenant 只从认证上下文注入。该环境变量是 workload 标识，不是
token。生产入口仍必须在 API gateway 配置企业 TLS、workload federation 或等价认证、请求大小/速率限制和
密钥轮换，不能把示例标识当作 inbound authentication。

收敛器只接受 `GDASLOErrorBudgetBurn`，并要求 `truncatedAlerts=0`。每条 alert 的 SLO ID/version、数据库
fingerprint、service、owner、on-call、burn window、severity 和 `approval_case_ref` 必须与权威数据完全一致：

- `firing` 必须绑定 exact current active pointer；首次投递创建 resource-bound DataIncident，重放返回同一事故。
- episode identity 包含 Alertmanager fingerprint 和 `startsAt`；同一 fingerprint 的后续新一轮告警不会复用已关闭事故。
- `resolved` 必须找到同一获批版本的 immutable activation event，并只 CAS 关闭同一 episode；重放保持幂等。
- 未收到 firing 的 resolved 只记录为 `resolution_without_incident` 响应，不伪造事故。

Alertmanager 只是告警事实传输，不是事故状态权威。silence 只抑制通知，不能作为 acknowledge 或 resolved；事故
状态必须通过 DataIncident 生命周期维护，而告警恢复只能由同一 episode 的 `resolved` webhook 自动收敛。

本地执行真实 PostgreSQL 生命周期认证：

```bash
uv run python scripts/certify_slo_incident_lifecycle.py \
  --output /tmp/gda-slo-incident-lifecycle.json
```

报告只有在 firing/重放、resolved/重放、两条有序 IncidentEvent/outbox、恰好一个主体、主体不可变、双租户
RLS、approved SLO fingerprint/ApprovalCase 绑定和一次性资源清理全部通过后，才返回 `status=verified`。
这证明本地控制面与真实 PostgreSQL 的闭环，不证明 staging/production receiver、企业 TLS/认证、paging 或
多集群交付已经验收。

### 参考主数据权威与黄金记录

迁移 124 提供首期 `administrative_unit` 和 `land_use_code` 主数据域。主数据的运行真值位于
`gda_control` 控制账本：source revision、match candidate、entity version、active pointer 和 event
均为租户隔离对象。PostGIS/Iceberg 保存实体内容和可重建投影；EA、OpenMetadata、Gravitino 或 GIS
产品目录只能维护/展示模型与投影，不能直接改 active pointer。

固定操作顺序为：

```text
observe source revision -> stage entity version -> create ApprovalCase
-> independent human approve -> admin CAS activate -> read active/events
-> read generic ResourceVersion projection -> reconcile external metadata providers
```

匹配由 workload/agent 身份调用，AI 只能写不可变候选。候选的 `master-match-v1` 解释业务键、规范化名称和
真实 active parent business key；推荐阈值和置信度不能替代人工审批。source、version、candidate 和 event
禁止直接 `UPDATE`/`DELETE`，重复 source/match 请求必须使用同一 evidence，证据漂移返回 conflict。

平台 API：

- `POST /api/platform/v1/master-data/source-records`
- `POST /api/platform/v1/master-data/source-records/{source_record_key}/match-candidates`
- `POST/GET /api/platform/v1/master-data/entities/{entity_id}/versions`
- `POST /api/platform/v1/master-data/entities/{entity_id}/versions/{version}/approval-cases`
- `POST /api/platform/v1/master-data/entities/{entity_id}/versions/{version}/activation`
- `GET /api/platform/v1/master-data/entities/{entity_id}/active`
- `GET /api/platform/v1/master-data/entities/{entity_id}/events`
- `GET /api/platform/v1/master-data/entities/{entity_id}/resource-projections`

激活请求必须使用 action=`master_data.entity.activate` 的 approved ApprovalCase，并提交当前
`activation_version`；数据库会再次校验 tenant、target ResourceURN/fingerprint、human 决策、有效期、业务键
唯一和层级无环。gateway 只拥有受控函数执行和只读权限，不拥有主数据表的直接写权限。

迁移 125 使 activation 与平台通用身份原子提交：每个成功激活都会生成确定性的 `ResourceVersion`，其
`content_sha256` 和 authority evidence 精确绑定 master fingerprint/version；
`master_resource_projection` 保存 activation version、前序通用版本和 ApprovalCase。该表强制 RLS、不可修改，
gateway 只能读取。若同一 ResourceURN 已被不同 authority/evidence 占用，激活必须返回 conflict，不能绕过触发器
手工补 active pointer。OpenMetadata binding 只登记显式 UUID crosswalk；provider entity 的创建/确认由提交后的
可重试 worker 完成。没有真实 PostGIS/Iceberg technical object 时禁止登记 Gravitino binding。

迁移 126 会在 `master_resource_projection` 插入时原子写
`master_metadata_projection_outbox`。worker 运行前必须先登记真实存在的 OpenMetadata binding：
`external_object_type=glossaryTerm`、`external_object_id` 为 provider 返回的 canonical UUID，且
`external_namespace` 与 GET 响应中的 glossary FQN/name 完全一致。禁止预填猜测 UUID、用名称/FQN 反查后自动绑定，
或让 worker 自动创建 term。开发 Compose 入口为：

```bash
docker compose --profile metadata-fabric up -d \
  metadata-fabric-worker master-metadata-worker
```

两类 worker 共享 `GDA_METADATA_FABRIC_TENANT_ID`、`GDA_OPENMETADATA_URL` 和只读 token 文件，但 master worker
使用独立的 `GDA_MASTER_METADATA_WORKER_ID`、`GDA_MASTER_METADATA_BATCH_SIZE`、
`GDA_MASTER_METADATA_LEASE_SECONDS`、`GDA_MASTER_METADATA_RETRY_SECONDS` 和
`GDA_MASTER_METADATA_POLL_SECONDS`。lease 必须大于 `batch_size * 3 * HTTP timeout`。master worker 只 PATCH `displayName` 和
`description`，不得覆盖 glossary hierarchy、owner、reviewer、tag、status 或 provider identity；只有读后精确一致
才 complete，缺失/陈旧 binding 应进入 retry/dead-letter 并由 steward 修复 crosswalk。description 使用无 Markdown
标记的 provider-stable 纯文本；OpenMetadata 1.13.1 会对反引号做 HTML 实体规范化，带此类标记的 payload 无法通过
精确读回确认。

在本地一次性 PostgreSQL 16 上执行闭环认证：

```bash
uv run python scripts/certify_master_data_lifecycle.py \
  --output /tmp/gda-master-data-lifecycle.json
```

报告只有在 source revision/match 重放幂等、双时间有效期、精确 ApprovalCase、版本 CAS、active business-key
唯一、确定性 ResourceVersion/predecessor、精确 fingerprint/authority evidence、投影不可变与强制 RLS、
OpenMetadata crosswalk 可登记、metadata outbox 原子入队、lease-owner/失败重领/完成不重放、Resource 身份冲突
同时回滚 activation/projection/outbox、gateway 最小权限和一次性容器清理共 32 项全部通过时，
才返回 `status=verified`。
该认证证明控制面与真实 PostgreSQL 的开发环境行为，不代表 EA 生产仓库、staging/production、完整企业 MDM、
Gravitino 技术绑定、多渠道黄金记录分发或生产备份恢复已经验收。

真实 OpenMetadata 1.13.1 验收使用同一版本固定 topology 串行验证 lineage 与主数据投影：

```bash
./scripts/metadata-fabric-openmetadata-acceptance.sh
```

成功时分别生成
`.tmp/metadata-fabric/openmetadata-lineage-acceptance-report.json` 和
`.tmp/metadata-fabric/openmetadata-master-data-acceptance-report.json`。主数据报告必须同时证明 provider 返回 UUID
已绑定、`GET/PATCH/GET`、已提交 PATCH 响应丢失后的读回确认、重放仅 GET、glossary 内唯一 term、未认证 PATCH
被拒绝、outbox `done/attempt_count=1`，以及 term/glossary 删除后均返回 404。临时 token 使用 0600 文件且不会进入
报告，容器、网络、卷和 token 默认自动清理。

该真实 provider 证据只覆盖已存在且已显式绑定 glossary term 的 `displayName/description` 投影。验收脚本创建临时
glossary/term 不等于生产 worker 具备 provisioning 权限；生产 term 创建、steward 确认、crosswalk 登记、层级与
owner/tag/status 管理仍是独立治理流程，EA round-trip、Gravitino 和 staging/production 仍未验收。

## 7. 备份与恢复

### 数据库备份
```bash
./scripts/backup-db.sh
```

### 手动备份
```bash
pg_dump -U postgres -d gis_agent -Fc --no-owner --no-acl \
  -f backup_$(date +%Y%m%d).dump
```

### 隔离恢复演练
```bash
uv run python scripts/rehearse_compose_recovery.py \
  --profile config/deployment_profiles/main-compose-dev.json \
  --output /tmp/gda-recovery-report.json
```

复核版本化的 2026-07-31 开发环境恢复 SLI 观测：

```bash
uv run python scripts/verify_recovery_sli_baseline.py
```

该命令从版本化脱敏报告重建容量、耗时和逻辑内容身份。`technical_pass=true` 只表示观测
证据完整；输出仍必须为 `sli_status=observed_not_approved` 和
`promotion_ready=false`，不能把 459.499 秒解释为已批准 RTO。

验证 PostgreSQL physical backup 与备份结束后的 streamed-WAL 时间点恢复：

```bash
uv run python scripts/rehearse_compose_pitr.py \
  --profile config/deployment_profiles/main-compose-dev.json \
  --output /tmp/gda-pitr-report.json

uv run python scripts/verify_pitr_evidence.py
```

该演练使用独立 probe database、临时 physical slot 和 `--network none` 恢复目标，不修改
业务表或 `pg_hba.conf`。运行前至少预留一份 PGDATA 大小的临时空间。当前开发环境
`archive_mode=off`；通过只证明短窗口 streamed-WAL PITR，不表示持续归档、RPO/RTO、
异地/加密或 PostgreSQL + MinIO 联合恢复已通过。

禁止对仍承载流量的主库直接使用 `pg_restore --clean`。正式恢复先落到替代实例或
`template0` 创建的替代数据库，通过迁移、标准、真实数据和对象内容对账后再切换流量。

## 8. CI/CD 管道

GitHub Actions (`.github/workflows/ci.yml`)：
- **触发条件**: push 到 main/develop, PR 到 main
- **test job**: Ubuntu + PostGIS 服务, pytest (JUnit XML)
- **frontend job**: Node.js 20, TypeScript 编译 + Vite 构建
- **evaluate job**: 仅 main push, ADK 评估 (需要 `GOOGLE_API_KEY` secret)

## 9. 故障排查

| 错误现象 | 可能原因 | 解决方案 |
|:---|:---|:---|
| 启动报错 `ImportError: DLL load failed` | GDAL/Fiona 版本不兼容 | 重新安装对应版本 `.whl` |
| Agent 无响应 / 思考超时 | API Key 缺失或网络不通 | 检查 `.env` 中 `GOOGLE_API_KEY` |
| 图表中文乱码 | 缺失中文字体 | 安装 SimHei / Microsoft YaHei |
| 前端白屏 | 前端未构建或版本不匹配 | `cd frontend && npm run build` |
| 数据库连接失败 | PostgreSQL 未启动或配置错误 | 检查 `DATABASE_URL` 和服务状态 |
| 图层不显示 | GeoJSON 未正确生成 | 检查 `.mapconfig.json` 文件 |
| Token 限额提示 | 超过每日分析限额 | 调整 `DAILY_ANALYSIS_LIMIT` 或联系管理员 |
| 注册失败 | 密码不符合要求 | 密码需 ≥8 位且包含字母和数字 |
| OAuth 登录不可用 | 未配置 OAuth 环境变量 | 设置 `OAUTH_GOOGLE_CLIENT_ID` |
| 标注不显示 | 数据库迁移未执行 | 执行 `016_create_map_annotations.sql` |
