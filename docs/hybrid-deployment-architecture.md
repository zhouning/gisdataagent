# 混合部署架构指南：GCP公有云与本地私有化双向支持

## 1. 背景与目标
本系统的商业模式决定了我们需要同时支持两种交付形态：
1. **公有云 SaaS (基于 Google Cloud)**：追求极致的弹性伸缩、高可用性（HA）以及免运维，服务海量用户。
2. **本地私有化部署 (On-Premises)**：满足大型政企客户对数据隐私的合规要求，甚至支持断网（Air-gapped）环境下的物理隔离部署。

本文档阐述了如何通过**云原生设计原则与适配器模式**相结合的策略，实现“一套代码，双向部署”，在不增加显著维护心智负担的前提下达成以上目标。

---

## 2. 核心架构解耦策略

### 2.1 部署编排层：基于 Kustomize 的“基座 + 覆盖”模式
**痛点**：维护多套差异巨大的 Kubernetes YAML 文件极易导致配置漂移和版本不一致。
**方案**：重构现有的 `k8s/` 目录，使用 Kustomize 实现组件复用。核心业务容器定义放在 `base` 中，GCP 和本地环境只需在 `overlays` 里拼装不同的底层依赖（如数据库是自建还是用云服务）。

**目录结构示例**：
```text
k8s/
├── base/                   # 核心基础组件 (应用 Deployment, 内部 Service)
│   ├── app-deployment.yaml
│   └── kustomization.yaml
└── overlays/
    ├── gcp/                # GCP 专有配置
    │   ├── ingress-gce.yaml        # 使用 GCP LoadBalancer + Managed Certs
    │   ├── service-account.yaml    # Workload Identity 联邦身份绑定
    │   └── kustomization.yaml      # 移除本地 DB/Redis，注入云数据库连接串
    └── on-prem/            # 本地私有化配置
        ├── postgres-statefulset.yaml # 启用本地 PostGIS 容器
        ├── redis-deployment.yaml     # 启用本地 Redis 容器
        ├── ingress-nginx.yaml      # 使用开源 Nginx Ingress
        └── kustomization.yaml
```

### 2.2 存储层：标准化 S3 协议，抽象底层实现
**痛点**：应用需要处理大量的 GIS 文件（Shapefile、Excel），公有云通常使用对象存储，本地常使用持久化卷。
**方案**：统一使用 **S3 兼容协议** 作为系统的唯一文件 I/O 标准。
*   **本地环境**：在本地 Docker Compose 或 K8s 中旁路部署 **MinIO**（轻量级 S3 兼容存储）。
*   **GCP 环境**：使用 **Google Cloud Storage (GCS)**，GCS 原生提供 S3 互操作性（Interoperability）接口。
*   **代码实现**：Python 代码层面统一使用 `boto3`，仅需通过环境变量切换 Endpoint：
    *   本地配置：`ENDPOINT=http://minio:9000`
    *   GCP配置：`ENDPOINT=https://storage.googleapis.com`

### 2.3 模型层：大模型的网关化解耦 (LLM Gateway)
**痛点**：公有云依赖 Vertex AI，而本地离线环境可能需要调用开源本地模型（如 Qwen、DeepSeek 等）。
**方案**：引入 LLM 代理网关（如 **LiteLLM** 或 **OneAPI**），将所有模型调用抽象为标准的 OpenAI API 格式。
*   应用层代码：只面向统一的网关地址发起请求，不写 `if IS_GCP else IS_LOCAL` 的判断逻辑。
*   GCP 部署：网关将请求无缝翻译并转发给底层的 Vertex AI (Gemini)。
*   本地部署：在本地 GPU 节点上部署 Ollama 或 vLLM 提供模型推理，网关负责将请求路由至本地端点。

### 2.4 代码层的适配器模式 (Adapter Pattern)
针对必须存在差异的服务（如极端情况下的本地磁盘读写 vs 对象存储读写），在业务逻辑与底层基础设施之间建立防腐层。

**Python 示例**：
```python
from abc import ABC, abstractmethod
import os

class StorageBackend(ABC):
    @abstractmethod
    def upload(self, filepath: str, object_name: str): pass

# 具体实现
class S3Storage(StorageBackend): 
    # 适用于 GCP GCS 或 本地 MinIO
    pass

class LocalDiskStorage(StorageBackend): 
    # 适用于极简的单机 Docker 挂载盘部署
    pass

# 工厂注入
def get_storage_backend() -> StorageBackend:
    storage_type = os.getenv("STORAGE_TYPE", "local")
    if storage_type == "s3":
        return S3Storage()
    return LocalDiskStorage()
```

### 2.5 配置与机密管理 (Secrets Management)
**方案**：严格遵循 12-Factor App 原则，禁止在代码中硬编码任何认证方式（如 API Keys、JSON 密钥文件）。
*   所有外部依赖、凭证必须通过环境变量读取 (`os.getenv()`)。
*   **GCP 环境**：使用 GCP Secret Manager，结合 GKE 的 Workload Identity 或 External Secrets Operator，将云端机密自动且安全地注入为 Pod 环境变量。无需挂载任何 JSON 密钥文件。
*   **本地环境**：通过标准的 `.env` 文件或 K8s Native 的 Secret 资源进行管理和注入。

---

## 3. 总结
通过上述架构设计，GIS Data Agent 可以做到核心业务逻辑与运行环境的完全解耦。无论是交付给对安全要求极高的政府/军工单位进行断网部署，还是在 Google Cloud 上提供面向全球的弹性 SaaS 平台，都能共享同一套代码基线，最大化研发效能并降低交付成本。