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
