# GIS Data Agent — kind 本地 K8s 部署指南

面向 macOS Docker Desktop + kind 集群的完全本地部署。**不依赖任何外部服务**——
PostgreSQL/PostGIS/pgvector、Redis、MinIO 全部在集群内自给自足，仅需 LLM API key（Vertex AI 或 Gemini API）注入到 Secret 即可。

## 一句话部署

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
| kind | 0.23+ | `kind --version` |
| kubectl | 1.28+ | `kubectl version --client` |

机器要求：**16GB RAM 起步，推荐 32GB+**（你有 128GB，绰绰有余）。

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

## 5. LLM API Key 注入

`secret-patch.yaml` 把 `GOOGLE_API_KEY` / `GOOGLE_APPLICATION_CREDENTIALS` 留空。两种填充方式：

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

---

## 附录：手动 kustomize 渲染

```bash
# 验证 base
kubectl kustomize k8s/base/ | less

# 验证 overlay
kubectl kustomize k8s/overlays/local-kind/ | less

# 仅看资源数
kubectl kustomize k8s/overlays/local-kind/ | grep -cE '^kind:'
```
