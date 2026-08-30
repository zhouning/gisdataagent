# GIS Data Agent — Deployment Guide

Enterprise deployment documentation for GIS Data Agent v4.0.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Docker Compose Quickstart](#2-docker-compose-quickstart)
3. [Production Docker Compose](#3-production-docker-compose)
4. [Kubernetes Deployment](#4-kubernetes-deployment)
5. [Air-Gapped Deployment](#5-air-gapped-deployment)
6. [SSL/TLS Configuration](#6-ssltls-configuration)
7. [Database Backup & Restore](#7-database-backup--restore)
8. [Monitoring](#8-monitoring)
9. [Upgrade Procedures](#9-upgrade-procedures)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB | 50+ GB SSD |
| Network | 1 Mbps | 10+ Mbps |

### Software Requirements

- **Docker** 24.0+ with Docker Compose v2
- **Kubernetes** 1.28+ (for K8s deployment)
- **PostgreSQL** 16 + PostGIS 3.4 (or use the bundled container)
- Google AI API key or Vertex AI service account

### Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GOOGLE_API_KEY` | Google Gemini API key | Yes (or Vertex AI) |
| `POSTGRES_PASSWORD` | Application DB user password | Yes |
| `POSTGRES_ADMIN_PASSWORD` | PostgreSQL admin password | Yes |
| `CHAINLIT_AUTH_SECRET` | JWT signing secret | Yes |
| `GAODE_API_KEY` | Amap geocoding API key | Recommended |

---

## 2. Docker Compose Quickstart

```bash
# 1. Clone the repository
git clone <repo-url> gis-agent && cd gis-agent

# 2. Create environment file
cp .env.example .env
# Edit .env with your API keys

# 3. Start services
docker compose up -d

# 4. Check status
docker compose ps
docker compose logs -f app

# 5. Access the application
# Open http://localhost:8000
# Login: admin / admin123 (change immediately)
```

---

## 3. Production Docker Compose

Use the production override for resource limits, log rotation, and automated backups:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Production additions:
- **Resource limits**: CPU and memory caps for all services
- **Log rotation**: JSON file driver with max size/count
- **Automated backups**: Daily `pg_dump` with configurable retention
- **Restart policy**: `always` (auto-restart on failure)

### Verify Configuration

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
```

---

## 4. Kubernetes Deployment

### 4.1 Build and Push Image

```bash
# Build the application image
docker build -t gis-data-agent:latest .

# Tag for your registry
docker tag gis-data-agent:latest your-registry.com/gis-data-agent:v4.0

# Push
docker push your-registry.com/gis-data-agent:v4.0
```

### 4.2 Configure Secrets

Edit `k8s/secret.yaml` with base64-encoded values:

```bash
# Generate base64 values
echo -n "your_strong_password" | base64
echo -n "your_api_key" | base64
```

### 4.3 Deploy with Kustomize

```bash
# Preview
kubectl apply --dry-run=client -k k8s/

# Deploy
kubectl apply -k k8s/

# Check status
kubectl -n gis-agent get pods
kubectl -n gis-agent get svc
```

### 4.4 Update Ingress

Edit `k8s/ingress.yaml`:
- Replace `gis-agent.example.com` with your domain
- Uncomment TLS section if using cert-manager

### 4.5 Verify

```bash
# Check pods
kubectl -n gis-agent get pods -w

# Check logs
kubectl -n gis-agent logs -f deployment/gis-agent-app

# Port-forward for testing
kubectl -n gis-agent port-forward svc/gis-agent-app 8080:80
```

---

## 5. Air-Gapped Deployment

For environments without internet access:

### 5.1 Export Images (on connected machine)

```bash
# Build the local multi-arch PostGIS + pgvector image, or pull the same tag
# from your internal registry if you publish it there.
docker build -t gis-postgis-pgvector:16-3.4 docker/postgis-pgvector
docker pull gis-data-agent:latest

docker save gis-postgis-pgvector:16-3.4 -o gis-postgis-pgvector-16-3.4.tar
docker save gis-data-agent:latest -o gis-data-agent.tar
```

### 5.2 Transfer and Load (on air-gapped machine)

```bash
# Load images
docker load -i gis-postgis-pgvector-16-3.4.tar
docker load -i gis-data-agent.tar

# Start services
docker compose up -d
```

### 5.3 K8s Air-Gapped

```bash
# Push to local registry
docker tag gis-data-agent:latest localhost:5000/gis-data-agent:latest
docker push localhost:5000/gis-data-agent:latest

# Update k8s/app-deployment.yaml image field
# image: localhost:5000/gis-data-agent:latest
```

---

## 6. SSL/TLS Configuration

### 6.1 cert-manager (K8s, recommended)

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

# Create ClusterIssuer
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v2.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: nginx
EOF
```

Then uncomment the cert-manager annotations in `k8s/ingress.yaml`.

### 6.2 Self-Signed Certificate (Docker)

```bash
# Generate self-signed cert
openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout ssl/server.key \
  -out ssl/server.crt \
  -subj "/CN=gis-agent.local"
```

Use an nginx reverse proxy container with the certificate mounted.

### 6.3 Enterprise CA

Place your CA-signed certificate and key in a directory and mount them into the reverse proxy or ingress controller.

---

## 7. Database Backup & Restore

### Manual Backup

```bash
bash scripts/backup-db.sh
```

该命令生成 PostgreSQL custom-format `.dump`，不再对已经压缩的 `-Fc` 输出重复 gzip。
未显式提供 `POSTGRES_ADMIN_PASSWORD` 时由 `.pgpass` 或交互式认证负责，不使用脚本内
默认密码。

### Automated Backup (Docker)

The `docker-compose.prod.yml` includes a `db-backup` service that runs daily.

```bash
# Check backup status
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs db-backup

# List backups
docker compose exec db-backup ls -lh /backups/
```

### Restore

禁止在仍承载流量的 `gis_agent` 上直接执行 `--clean`。每次备份方案变更和正式恢复前，
先运行隔离演练：

```bash
uv run python scripts/rehearse_compose_recovery.py \
  --profile config/deployment_profiles/main-compose-dev.json \
  --output /tmp/gda-recovery-report.json
```

仓库内的单次开发环境观测可独立复核：

```bash
uv run python scripts/verify_recovery_sli_baseline.py
```

校验器同时绑定 DeploymentProfile、Compose config、脱敏恢复报告、数据库逻辑身份和
对象内容 inventory。通过只代表该次 SLI 观测可重建；SLO/RPO/RTO 仍需独立审批，
`promotion_ready` 保持 false。

PostgreSQL 的有界 physical PITR 使用独立命令，并可离线复核其版本化 seal：

```bash
uv run python scripts/rehearse_compose_pitr.py \
  --profile config/deployment_profiles/main-compose-dev.json \
  --output /tmp/gda-pitr-report.json

uv run python scripts/verify_pitr_evidence.py
```

runner 通过临时 physical slot 在 base backup 结束后继续接收 WAL，并恢复到 target
transaction、排除 later transaction。临时 client 使用数据库容器 loopback replication，
不修改 HBA；恢复目标为 `--network none`。当前 `archive_mode=off`，该证据不能替代持续
archive provider、slot 监控、加密/异地、RPO/RTO 或跨 PostgreSQL/MinIO 一致性验收。

该入口把 PostGIS dump 恢复到 `template0` 创建的临时数据库，并将 MinIO 对象恢复到
临时 bucket；迁移、标准、真实 TWM 表计数和逐对象内容 SHA-256 全部一致才通过。
临时容器、匿名 volume、bucket 和本地介质在结束时清理，不修改现有 volume/bucket。

正式灾难恢复必须在批准的替代实例或替代数据库中执行，完成同一套验证并切换流量；
不能把以下命令指向当前生产数据库：

```bash
pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
  --dbname <replacement_database> backups/gis_agent_20260101_000000.dump
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_RETENTION_DAYS` | 7 | Days to keep backup files |
| `BACKUP_DIR` | `./backups` | Backup output directory |

---

## 8. Monitoring

### Health Check

The application exposes liveness and readiness endpoints:

```bash
curl -f http://localhost:8000/health
curl -f http://localhost:8000/ready
```

### Docker Compose

```bash
docker compose ps          # Service status
docker compose logs -f app # Application logs
docker compose top         # Running processes
```

### Kubernetes

```bash
kubectl -n gis-agent get pods                    # Pod status
kubectl -n gis-agent top pods                    # Resource usage
kubectl -n gis-agent describe hpa                # Autoscaler status
kubectl -n gis-agent logs -f deploy/gis-agent-app  # App logs
```

### Audit Logs

Admin users can view audit logs at `/admin/audit` or via the API:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8080/api/admin/audit
```

---

## 9. Upgrade Procedures

### Docker Compose

```bash
# 1. Pull latest code
git pull origin main

# 2. Rebuild image
docker compose build app

# 3. Rolling restart
docker compose up -d app

# 4. Run migrations
docker compose exec app bash -c 'for f in /app/data_agent/migrations/*.sql; do
  psql -h db -U postgres -d gis_agent -f "$f" --set ON_ERROR_STOP=0 -q 2>/dev/null
done'

# 5. Verify
docker compose logs -f app
```

### Kubernetes

```bash
# 1. Build and push new image
docker build -t your-registry.com/gis-data-agent:v4.1 .
docker push your-registry.com/gis-data-agent:v4.1

# 2. Update deployment image
kubectl -n gis-agent set image deployment/gis-agent-app \
  app=your-registry.com/gis-data-agent:v4.1

# 3. Watch rollout
kubectl -n gis-agent rollout status deployment/gis-agent-app

# 4. Rollback if needed
kubectl -n gis-agent rollout undo deployment/gis-agent-app
```

---

## 10. Troubleshooting

### Application Won't Start

```bash
# Check logs
docker compose logs app

# Common issues:
# - GOOGLE_API_KEY not set → "LLM configuration error"
# - PostgreSQL not ready → "connection refused" (wait for healthcheck)
# - Port conflict → change ports in docker-compose.yml
```

### Database Connection Errors

```bash
# Verify PostgreSQL is running
docker compose exec db pg_isready -U postgres

# Test connection from app
docker compose exec app psql -h db -U agent_user -d gis_agent -c "SELECT 1"
```

### Migrations Fail

```bash
# Run migrations manually
bash scripts/migrate.sh

# Check for migration errors
docker compose exec db psql -U postgres -d gis_agent -c "\dt"
```

### Out of Memory

- Increase `memory` limits in `docker-compose.prod.yml` or K8s deployment
- Check for large file uploads consuming disk
- Review HPA settings for auto-scaling

### WebSocket Connection Issues

For Kubernetes deployments behind nginx-ingress, ensure the ingress annotations include WebSocket upgrade headers (included by default in `k8s/ingress.yaml`).
