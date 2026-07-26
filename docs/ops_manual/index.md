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

## 7. 备份与恢复

### 数据库备份
```bash
./scripts/backup-db.sh
```

### 手动备份
```bash
pg_dump -U postgres -d gis_agent -F c -f backup_$(date +%Y%m%d).dump
```

### 恢复
```bash
pg_restore -U postgres -d gis_agent -c backup_20260302.dump
```

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

## 10. DolphinScheduler 命令 Worker（当前未部署）

该进程只负责从 PostgreSQL `platform_command_outbox` 领取并投递命令；outbox、PlatformRun 和 provider instance 仍是各自领域的事实源。当前代码已具备本地运行、健康检查和默认关闭的 Kubernetes 模板，但尚未形成 staging/production 运行证据。

部署前必须满足：

- `DOLPHINSCHEDULER_COMMAND_WORKER_ENABLED=true` 时补齐 provider URL、绝对 token 文件、project code、workload/evaluator subject、command tenant 和 worker ID；
- token 文件权限为 `0600`，不把 token 放入环境快照、日志或 status JSON；
- 每个进程/Pod 使用跨副本唯一的 `DOLPHINSCHEDULER_COMMAND_WORKER_ID`，同一 ID 只能对应一个活跃进程；
- `DOLPHINSCHEDULER_COMMAND_LEASE_SECONDS` 大于 provider request timeout，health max age 至少覆盖两个 poll interval；
- status JSON 路径为本地可写绝对路径，权限为 `0600`，仅作为 liveness/readiness 投影。

常用命令：

```bash
python -m data_agent.dolphinscheduler_command_worker validate
python -m data_agent.dolphinscheduler_command_worker run
python -m data_agent.dolphinscheduler_command_worker run --once
python -m data_agent.dolphinscheduler_command_worker health
python -m data_agent.dolphinscheduler_command_worker liveness
```

`health` 用作 readiness，status 缺失、过期、worker degraded/stopped 或输入窗口非法时返回非零。`liveness` 只要求非 stopped 状态持续刷新，因此数据库短时故障不会触发无效重启。单条 command 的 terminal failure 不等于进程失活，应通过 `failed_commands` 和 outbox 告警处理；worker 收到 SIGINT/SIGTERM 后完成当前批次，再停止。

### 10.1 Kubernetes 启用合同

`k8s/base/dolphinscheduler-command-worker.yaml` 固定为 `replicas: 0`。base/local-kind 可以正常渲染，但不会运行 Worker。环境 overlay 启用前必须创建同名的专用 ConfigMap 和 Secret：

| 资源 | 必需 key |
|---|---|
| ConfigMap `gis-agent-dolphinscheduler-command-worker` | `base-url`、`project-code`、`workload-subject`、`policy-evaluator-subject`、`command-tenant-id`、`provider-tenant-code`、`provider-worker-group` |
| Secret `gis-agent-dolphinscheduler-command-worker` | `database-url`、`access-token` |

`access-token` 只投影给 init container，再复制为主容器可读的 `0600` 文件；主容器不挂载原始 Secret，也不挂载 Kubernetes API token。Worker ID 由 Pod UID 生成。环境 overlay 还必须把 `gis-data-agent:latest` 替换为不可变 image digest，然后才可把副本数设为 1 或更高。

提交 overlay 前执行：

```bash
python -m data_agent.dolphinscheduler_worker_deployment validate
kubectl kustomize k8s/base/ >/dev/null
```

扩容成功后必须留存 rollout、health、唯一 worker ID、lease 接管和重启 drain 产物；只有清单或零副本 Deployment 不算 staging 部署证据。

### 10.2 Staging activation preflight

首次扩容固定为一个副本。preflight 需要环境 overlay 的完整渲染结果、集群中带 uid/resourceVersion 的 ConfigMap YAML 快照，以及只保留 Secret key 名称、uid 和 resourceVersion 的脱敏 attestation。禁止把原始 Secret JSON 写入文件或 CI artifact。

```bash
kubectl kustomize /path/to/staging-overlay > /tmp/gda-worker-staging.yaml
kubectl -n gis-agent get configmap gis-agent-dolphinscheduler-command-worker \
  -o yaml > /tmp/gda-worker-configmap.yaml
kubectl -n gis-agent get secret gis-agent-dolphinscheduler-command-worker -o json | \
  jq '{
    schema: "gda.dolphinscheduler_worker_secret_attestation.v1",
    environment: "staging",
    namespace: .metadata.namespace,
    secret_name: .metadata.name,
    keys: (.data | keys),
    resource_uid: .metadata.uid,
    resource_version: .metadata.resourceVersion,
    observed_at: (now | todateiso8601)
  }' > /tmp/gda-worker-secret-attestation.json

python -m data_agent.dolphinscheduler_worker_activation validate \
  --manifest /tmp/gda-worker-staging.yaml \
  --config-map /tmp/gda-worker-configmap.yaml \
  --secret-attestation /tmp/gda-worker-secret-attestation.json \
  --environment staging
```

只有 `status=ready_for_activation` 才能进入扩容步骤。该结果仍固定包含 `deployed=false` 和 `live_cluster_verified=false`；随后必须另行采集 Deployment rollout、Pod readiness/liveness、worker status、唯一 Pod UID、lease 接管和重启 drain 证据。

### 10.3 Staging candidate registry publication

`.github/workflows/cd-staging.yml` 在 candidate 验证后发布同一个 application image，不做第二次 application build。它把 OCI revision/source label、candidate fingerprint、本地 image ID、GHCR repository 和远端 manifest digest 绑定到 `registry.json`，再使用 GitHub OIDC 为 `repository@digest` 请求 provenance attestation。

workflow 权限只能是 `contents: read`、`packages: write`、`id-token: write` 和 `attestations: write`。digest 必须来自 `docker buildx imagetools inspect --raw` 的远端 manifest 内容并按 `sha256` 复查，禁止从 `docker push` 输出提取。candidate artifact 使用 `if: always()`；只有 provenance action 成功后才上传 registry artifact。

截至 2026-07-26，本机 `127.0.0.1:7897` 代理已可读取公开 GitHub action 与 Buildx 元数据，但 `gh` 登录仍失效，因此该 workflow 尚未真实运行。恢复身份后的首次受控运行必须留存：

- `candidate.json` 与 `registry.json`，且 source revision、candidate fingerprint 和 local image ID 一致；
- GHCR `repository@sha256:digest`，tag 不能作为 release 输入；
- GitHub artifact attestation 及其 repository、workflow、source revision identity；
- 独立 protected runner 的 OCI attestation verify 结果。

`registry_subject_bound=true` 只表示字段内部一致；报告仍固定 `provenance_attestation_verified=false`、`registry_digest_verified=false`、`staging_deployed=false`、`live_cluster_verified=false` 和 `production_promotion_allowed=false`。publication workflow 不调用 `kubectl` 或 Helm。未完成独立 verify 时，不得把 registry subject 交给 staging apply 或解除 production 阻断。

### 10.4 Staging release bundle

公共 `k8s/overlays/staging` 不包含 Secret，也故意保留会被 gate 阻断的本地模型默认值和基础设施 image tag。受保护环境必须先提供 Secret 和环境 ConfigMap overlay，把模型入口改为非本地 HTTPS endpoint，并把所有依赖镜像 pin 到 `@sha256:` digest，再渲染 template。随后将 validated candidate、预期 live platform snapshot 和应用 registry digest 结构化绑定：

```bash
kubectl kustomize /path/to/protected-staging-overlay \
  > /tmp/gda-staging-template.yaml

python -m data_agent.staging_deployment_bundle build \
  --template-manifest /tmp/gda-staging-template.yaml \
  --candidate-evidence /path/to/candidate.json \
  --platform-snapshot /path/to/expected-live-platform.json \
  --image ghcr.io/zhouning/gisdataagent@sha256:<digest> \
  --manifest-output /tmp/gda-staging-bundle.yaml \
  --report-output /tmp/gda-staging-bundle-report.json
```

只有 `status=ready_for_staging_apply` 才会写出 manifest。该报告仍固定 `registry_digest_verified=false`、`staging_deployed=false`、`live_cluster_verified=false` 和 `production_promotion_allowed=false`；protected runner 必须另行验证 registry provenance，apply 后再执行 live observation。

### 10.5 Live staging observation

应用 Deployment 的 Pod template 必须由 staging overlay 写入以下注解；放在 Deployment metadata 而不放在 Pod template 不算 revision 绑定：

| 注解 | 值 |
|---|---|
| `org.opencontainers.image.revision` | candidate 的完整 Git SHA |
| `gisdataagent.io/candidate-evidence-fingerprint` | `candidate.json` 的 evidence fingerprint |
| `gisdataagent.io/environment` | 固定 `staging` |
| `gisdataagent.io/platform-fingerprint` | 预期 live config/runtime 组合 fingerprint |

v1 只接受单副本 staging Deployment；多副本逐 Pod config/runtime/health 采集实现前不得放宽。容器镜像必须使用 registry `@sha256:` digest。应用 Pod 必须设置 `automountServiceAccountToken: false`。运行时的 migration readiness 由 init container 以普通应用数据库角色执行 `python -m data_agent.migration_runner status` 判断，不得通过 `kubectl wait`、ServiceAccount token 或 Job RBAC 判断。受保护环境配置还要保存目标 `kube-system` namespace UID 和 `gis-agent` namespace UID，collector 观察值必须与这两个固定值一致，不能从本次采集结果反向填入 expected 参数。

collector 不读取 Secret，只输出 Deployment/Pod/ServiceAccount/EndpointSlice 白名单字段、应用角色 migration report、脱敏后的 platform fingerprint 和 health/readiness 状态：

```bash
python -m data_agent.staging_live_evidence collect \
  --output /tmp/gda-staging-live-collection.json

python -m data_agent.staging_live_evidence validate \
  --candidate-evidence /path/to/candidate.json \
  --live-collection /tmp/gda-staging-live-collection.json \
  --golden-slice /path/to/live-golden-slice.json \
  --expected-cluster-uid "$STAGING_CLUSTER_UID" \
  --expected-namespace-uid "$STAGING_NAMESPACE_UID" \
  --output /tmp/gda-staging-live-evidence.json
```

`live_staging_verified=true` 只证明 observation 内部绑定完整。v1 固定 `promotion_authority_verified=false` 和 `production_promotion_allowed=false`；在受保护 runner identity、evidence artifact attestation 和同 revision production approval 接入前，不得解除 production workflow 的固定阻断。
