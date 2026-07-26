# GIS Data Agent — kind 本地 K8s 部署指南

面向 macOS Docker Desktop + kind 集群的完全本地部署。**不依赖任何外部服务**——
PostgreSQL/PostGIS/pgvector、Redis、MinIO 全部在集群内自给自足，仅需 LLM API key（Vertex AI 或 Gemini API）注入到 Secret 即可。

## 一句话部署

使用 Docker Desktop 内置 kind 集群（`docker-desktop` context）：

```bash
cd /path/to/adk
./scripts/k8s-docker-desktop-bootstrap.sh up
./scripts/k8s-docker-desktop-bootstrap.sh forward
```

使用独立 `kind` CLI 创建和管理集群：

```bash
cd /path/to/adk
./scripts/k8s-kind-bootstrap.sh up         # 创建 kind 集群 + 构建镜像 + 部署
./scripts/k8s-kind-bootstrap.sh forward    # 端口转发到 localhost
```

打开 `http://localhost:8080` 登录（默认 `admin` / `admin123`）。

---

## 1. 前置条件

| 工具 | 最低版本 | 验证 |
|---|---|---|
| Docker Desktop | 4.30+ | `docker --version` |
| kind（仅独立集群路径） | 0.23+ | `kind --version` |
| kubectl | 1.28+ | `kubectl version --client` |

机器要求：**16GB RAM 起步，推荐 32GB+**（你有 128GB，绰绰有余）。

### 1.1 Docker Desktop kind 版本兼容性

Docker Desktop overlay 使用 `alpine/k8s:1.35.5` 作为带 shell 的 `kubectl`
辅助镜像，供 migration 和 app init container 等待 Kubernetes 资源。该
overlay 已在 Docker Desktop kind server `v1.35.5` 上验证，并支持 Kubernetes
`kubectl` 与 API server 相差不超过一个 minor 版本的官方版本偏差规则。

启用内置集群后先确认：

```bash
kubectl config current-context   # docker-desktop
kubectl version                  # server 建议为 1.34–1.36
kubectl get nodes                # 所有节点应为 Ready
```

bootstrap 脚本会从当前集群动态发现 control-plane 和 worker 节点，
因此 Docker Desktop 中调整 worker 数量后无需修改脚本。

Docker Desktop overlay 还会把 Paper9 WorldModel v2.1 的最小演示包复制到
每个节点的 `/paper9-demo`：`farmland_mpc` 包、Buchanan prepared 数据和
`ensemble_seed0`。脚本默认查找与主仓库同级的 `arcgis-farmland-mpc`；
其他位置可显式指定：

```bash
PAPER9_DEMO_SOURCE=/absolute/path/to/arcgis-farmland-mpc \
  ./scripts/k8s-docker-desktop-bootstrap.sh deploy
```

如果没有 Paper9 数据，脚本仍会创建空 HostPath，保证主平台正常启动，
但会明确警告 WorldModel v2.1 不可用。

---

## 2. 部署架构

```
┌────────────────────────── kind cluster (control-plane) ──────────────────────────┐
│                                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ postgres │   │  redis   │   │  minio   │   │  martin  │   │  cv-service  │    │
│  │ (PostGIS │   │ (cache + │   │(uploads, │   │ (vector  │   │ (port 8001)  │    │
│  │  +pgvec  │   │   queue) │   │  s3-api) │   │  tiles)  │   │              │    │
│  │  +ltree) │   └──────────┘   └──────────┘   └──────────┘   └──────────────┘    │
│  └─────┬────┘         ▲              ▲              ▲              ▲             │
│        │              │              │              │              │             │
│        │  ┌───────────┴──────────────┴──────────────┘              │             │
│        │  │                                                        │             │
│        ▼  ▼                                                        │             │
│  ┌───────────────┐    ┌────────────────────────────┐    ┌──────────┴──────────┐  │
│  │ migrations    │ -> │ gis-agent-app (Chainlit)   │ -> │ cad-parser (8002)   │  │
│  │ Job (1-shot)  │    │ HPA 1-8 replicas           │    └─────────────────────┘  │
│  └───────────────┘    └────────────────────────────┘    ┌─────────────────────┐  │
│                                  │                       │ reference-data      │  │
│                                  ▼                       │ (port 8004)         │  │
│                       ┌────────────────────┐             └─────────────────────┘  │
│                       │ gis-agent-outbox-  │                                      │
│                       │ worker (1 replica) │                                      │
│                       └────────────────────┘                                      │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │ kubectl port-forward
                                      ▼
                          ┌──────────────────────┐
                          │  macOS host (Browser)│
                          │  localhost:8080      │
                          └──────────────────────┘
```

资源占用估算（满载，replicas=1）：

| 组件 | CPU req / limit | Mem req / limit |
|---|---|---|
| postgres | 1 / 8 | 4Gi / 16Gi |
| redis | 0.25 / 2 | 1Gi / 4Gi |
| minio | 0.5 / 4 | 2Gi / 8Gi |
| martin | 0.1 / 0.5 | 128Mi / 512Mi |
| cv-service | 0.5 / 4 | 2Gi / 8Gi |
| cad-parser | 0.25 / 2 | 1Gi / 4Gi |
| reference-data | 0.25 / 2 | 0.5Gi / 2Gi |
| app | 1 / 4 | 2Gi / 8Gi |
| outbox-worker | 0.25 / 2 | 1Gi / 4Gi |
| **合计 limits** | **~28 cores** | **~54 GiB** |

128GB 内存的机器跑这套绰绰有余。HPA 在 local-kind overlay 里被压成 minReplicas=maxReplicas=1。

---

## 3. 目录结构

```
k8s/
├── base/                              # 通用资源（生产/staging/local 共享）
│   ├── namespace.yaml
│   ├── configmap.yaml                 # 非敏感 env (host/port/url)
│   ├── secret.yaml                    # 敏感 env (密码/API key)
│   ├── postgres-statefulset.yaml      # PostgreSQL 16 + PostGIS 3.4 + pgvector + ltree
│   ├── postgres-service.yaml
│   ├── redis-statefulset.yaml         # Redis 7 + AOF persistence + LRU 3GB
│   ├── minio.yaml                     # MinIO + bucket-init Job
│   ├── migrations-job.yaml            # 一次性 schema migration
│   ├── app-deployment.yaml            # Chainlit + HPA-aware
│   ├── app-service.yaml
│   ├── outbox-worker.yaml             # Standards Platform 异步消费者
│   ├── dolphinscheduler-command-worker.yaml # 默认零副本的 provider command worker
│   ├── qc-subsystems.yaml             # cv-service / cad-parser / reference-data
│   ├── martin-deployment.yaml
│   ├── martin-service.yaml
│   ├── ingress.yaml                   # 仅生产用
│   ├── hpa.yaml                       # HorizontalPodAutoscaler
│   ├── networkpolicy.yaml             # 5 个 NetworkPolicy
│   └── kustomization.yaml             # base 总入口
└── overlays/
    └── local-kind/                    # 本地 kind 专用变体
        ├── kustomization.yaml         # 引用 ../../base + 本地 patch
        ├── secret-patch.yaml          # 本地 dev 凭据
        └── minio-secret-patch.yaml
```

---

## 4. 完整部署流程

### 4.1 一键 `up`

```bash
./scripts/k8s-kind-bootstrap.sh up
```

`up` 自动执行：
1. **创建 kind 集群** `gis-agent`（如已存在则跳过）
2. **构建 4 个镜像并 load 到 kind**：
   - `gis-data-agent:dev`（主应用，~3 GB，含 GDAL + Python + Chainlit）
   - `gis-cv-service:dev`（YOLO/CV 检测）
   - `gis-cad-parser:dev`（DXF/3D 模型解析）
   - `gis-reference-data:dev`（参考数据 API）
3. **`kubectl apply -k k8s/overlays/local-kind`** 部署所有 manifest
4. **等待**：postgres → redis → minio → migration Job → app deployment

DolphinScheduler command worker 在 base 中固定为零副本，local-kind 不会启动它，也不要求本地提供 provider ConfigMap/Secret。只有 staging/production 环境 overlay 完成外部 provider 与数据库凭据配置后才能显式扩容。

部署脚本会等待 migration Job 提供运维反馈；App 和 Outbox Worker 自身不访问 Kubernetes API，而是以普通应用数据库角色读取 checksummed migration ledger。两者都禁用 ServiceAccount token automount，ledger 未达到 `in_sync` 时运行容器不会启动。

整套流程约 **15-25 分钟**（首次构建主镜像 ~10min，后续增量 <2min）。

### 4.2 端口转发（kind 没有 Ingress）

```bash
./scripts/k8s-kind-bootstrap.sh forward
```

转发以下端口：

| 服务 | URL | 用途 |
|---|---|---|
| App | http://localhost:8080 | 主应用（admin/admin123） |
| Martin | http://localhost:3000 | 矢量切片调试 |
| MinIO Console | http://localhost:9001 | 对象存储管理（minio_admin / local_dev_minio_secret） |
| PostgreSQL | localhost:5432 | 直连数据库（agent_user / local_dev_pg_password） |

`Ctrl-C` 停止所有转发。

### 4.3 状态检查

```bash
./scripts/k8s-kind-bootstrap.sh status
```

输出 pods + services + 最近 events + migration Job 状态。

---

## 5. 本地 LLM（Ollama，默认配置）

本地部署默认走宿主 macOS 上运行的 Ollama，**无需 Google API key**。架构：

```
macOS host
├── Docker Desktop
│   ├── Ollama 容器 (Metal GPU, port 11434)
│   │   ├── gemma3:27b (主力 LLM)
│   │   └── nomic-embed-text (embedding)
│   └── kind 集群
│       └── gis-agent pod
│           └── http://ollama:11434  ──► host.docker.internal:11434
```

`k8s/base/ollama-service.yaml` 是一个 ExternalName Service，把集群内的
`ollama` DNS 名解析到 `host.docker.internal`，pod 直接访问宿主 Ollama 容器。

### 5.1 准备宿主 Ollama 容器

确保 Docker Desktop 里跑着 Ollama 容器（你已经在跑）：

```bash
# 在宿主 macOS 上拉模型
docker exec -it ollama ollama pull gemma3:27b
docker exec -it ollama ollama pull nomic-embed-text

# 验证模型
docker exec -it ollama ollama list
# 应看到 gemma3:27b 和 nomic-embed-text
```

### 5.2 ConfigMap 已默认走 Ollama

`k8s/base/configmap.yaml` 已经配好：

```yaml
OLLAMA_API_BASE: "http://ollama:11434"
ROUTER_MODEL: "gemma-4-31b-it-ollama"     # 走 LiteLLM ollama_chat/ 后端
EMBEDDING_MODEL: "nomic-embed-text"
GOOGLE_GENAI_USE_VERTEXAI: "FALSE"        # 关闭 Vertex AI
```

### 5.3 模型选择（按你机器配比调整）

| 主力模型 | 显存/RAM 占用 | 适用场景 | 修改位置 |
|---|---|---|---|
| `gemma3:27b`（默认推荐） | ~20 GB | NL2SQL / 报告生成 / 标准平台 Agent | configmap.yaml `ROUTER_MODEL` |
| `gemma2:9b` | ~6 GB | 轻量 routing / 分类（不够 NL2SQL） | 同上 |
| `qwen2.5:32b` | ~22 GB | 中文场景更强 | 同上 |
| `llama3.3:70b` | ~45 GB | 顶配（M2 Max 128GB 跑得动） | 同上 |

如果切到 `gemma2:9b`，把 `model_gateway.py` 的 builtin entry 改成：
```python
"gemma-2-9b-ollama": {
    "backend": "litellm",
    "model_id": "ollama_chat/gemma2:9b",
    ...
}
```
或在 `conf/models.yaml` 里直接添加新条目（已有 vLLM 注释模板可仿照）。

### 5.4 验证 LLM 链路

部署后，进 app pod 测一下：

```bash
kubectl -n gis-agent exec -it deployment/gis-agent-app -- bash -lc '
python -c "
import litellm
r = litellm.completion(
    model=\"ollama_chat/gemma3:27b\",
    api_base=\"http://ollama:11434\",
    messages=[{\"role\":\"user\",\"content\":\"reply with OK\"}],
    max_tokens=10,
)
print(r.choices[0].message.content)
"
'
```

应输出 `OK`。如果挂在 `ConnectError` —— 检查宿主 Ollama 容器是否监听 `0.0.0.0:11434`（不是 `127.0.0.1`），以及防火墙：

```bash
# 在宿主上检查
docker logs ollama | tail -20
nc -zv host.docker.internal 11434  # 从 kind 容器外测试
```

### 5.5 退到云端 LLM（可选）

如果想暂时切回 Gemini API：

```bash
# 编辑 secret-patch.yaml 加 GOOGLE_API_KEY
# 改 configmap.yaml: ROUTER_MODEL=gemini-2.0-flash, GOOGLE_GENAI_USE_VERTEXAI=TRUE
./scripts/k8s-kind-bootstrap.sh deploy
kubectl -n gis-agent rollout restart deployment/gis-agent-app
```

---

## 6. （旧 Google API 章节）切回云端 Gemini API

`secret-patch.yaml` 默认 `GOOGLE_API_KEY` 留空（因为本地 Ollama 不需要）。
如要切回 Gemini API：

### 方式 A：直接编辑 patch

```bash
# k8s/overlays/local-kind/secret-patch.yaml
stringData:
  GOOGLE_API_KEY: "AIzaSy..."
```

然后重新 deploy：

```bash
./scripts/k8s-kind-bootstrap.sh deploy
kubectl -n gis-agent rollout restart deployment/gis-agent-app
```

### 方式 B：用 kubectl 临时 patch

```bash
kubectl -n gis-agent patch secret gis-agent-secret \
    --type=json \
    -p='[{"op":"replace","path":"/data/GOOGLE_API_KEY","value":"'$(echo -n "AIzaSy..." | base64)'"}]'
kubectl -n gis-agent rollout restart deployment/gis-agent-app
```

---

## 6. 增量调试

### 6.1 仅重新构建并重启 app

```bash
./scripts/k8s-kind-bootstrap.sh build
kubectl -n gis-agent rollout restart deployment/gis-agent-app deployment/gis-agent-outbox-worker
```

### 6.2 进入 pod

```bash
kubectl -n gis-agent exec -it deployment/gis-agent-app -- bash
kubectl -n gis-agent exec -it postgres-0 -- psql -U agent_user gis_agent
```

### 6.3 看日志

```bash
kubectl -n gis-agent logs -f deployment/gis-agent-app
kubectl -n gis-agent logs -f deployment/gis-agent-outbox-worker
kubectl -n gis-agent logs job/gis-agent-migrate
```

### 6.4 重置干净状态

```bash
./scripts/k8s-kind-bootstrap.sh reset    # 删除集群 + 重新部署
```

或仅删 PVC 重新初始化数据库：

```bash
kubectl -n gis-agent delete statefulset postgres
kubectl -n gis-agent delete pvc pgdata-postgres-0
kubectl apply -k k8s/overlays/local-kind
```

---

## 7. 常见问题

### 7.1 `migrations-job.yaml` 失败

```bash
kubectl -n gis-agent logs job/gis-agent-migrate
```

最常见：postgres 启动慢、`agent_user` 还未创建。等 30 秒重试：

```bash
kubectl -n gis-agent delete job gis-agent-migrate
kubectl apply -k k8s/overlays/local-kind
```

### 7.2 app pod `CrashLoopBackOff`

```bash
kubectl -n gis-agent logs deployment/gis-agent-app --previous
```

通常是 `CHAINLIT_AUTH_SECRET` 太短（< 32 字符）或 `GOOGLE_API_KEY` 没设。修 secret-patch 后重启。

### 7.3 镜像没加载

```bash
docker exec gis-agent-control-plane crictl images | grep gis-
```

如果没看到 `gis-data-agent:dev` 等，重跑：

```bash
./scripts/k8s-kind-bootstrap.sh build
```

### 7.4 MinIO bucket 初始化失败

```bash
kubectl -n gis-agent logs job/minio-bucket-init
```

最常见：MinIO pod 还在启动。Job `backoffLimit: 6`，会自动重试。手动重启：

```bash
kubectl -n gis-agent delete job minio-bucket-init
kubectl apply -k k8s/overlays/local-kind
```

---

## 8. 与 Compose 的取舍

| 维度 | Docker Compose | kind K8s |
|---|---|---|
| 启动时间 | ~3min | ~15min（首次） |
| 镜像分发 | bind mount + build | `kind load` 注入 |
| 多副本 | 不支持 | 支持（HPA 1→8） |
| 资源隔离 | 弱 | 强（cgroup + limits） |
| 网络策略 | 无 | NetworkPolicy（kindnet 不强制） |
| 适用场景 | 日常开发、demo | 生产前演练、混沌测试 |

如果只是"跑起来 demo 一下"，仍然推荐 `docker compose up -d`。kind 部署的价值在于**验证生产部署形态**——同一套 manifest 可以原样用到真实集群（仅替换 overlay 即可）。

---

## 9. 生产化路径（未来扩展 overlays）

```
k8s/overlays/
├── local-kind/        # 本指南
├── staging/           # 上游集群 + cert-manager + ServiceMonitor
└── prod/              # 生产 + Velero 备份 + GPU 节点选择器
```

`prod` overlay 应该补：

1. **真实 Ingress**：`cert-manager` ClusterIssuer + Let's Encrypt
2. **External Secrets**：从 AWS Secrets Manager / Vault 拉，不再走 stringData
3. **Backup CronJob**：`pg_dump` → MinIO 或 S3
4. **ServiceMonitor**：`kube-prometheus-stack` 接管 metrics scrape
5. **GPU 节点亲和**：`cv-service` 用 nvidia.com/gpu 资源
6. **PriorityClass**：postgres > app > outbox-worker
7. **Velero 备份策略**：volume snapshot
8. **DolphinScheduler Worker**：创建专用 ConfigMap/Secret、固定镜像 digest，再将默认零副本 Deployment 显式扩容

---

## 附录：手动 kustomize 渲染

```bash
# 验证 base
kubectl kustomize k8s/base/ | less

# 验证默认关闭的 DolphinScheduler worker 部署合同
python -m data_agent.dolphinscheduler_worker_deployment validate

# 验证 overlay
kubectl kustomize k8s/overlays/local-kind/ | less

# 仅看资源数
kubectl kustomize k8s/overlays/local-kind/ | grep -cE '^kind:'
```
