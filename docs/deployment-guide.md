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
# Pull and save images
docker pull postgis/postgis:16-3.4
docker pull gis-data-agent:latest

docker save postgis/postgis:16-3.4 -o postgis-16-3.4.tar
docker save gis-data-agent:latest -o gis-data-agent.tar
```

### 5.2 Transfer and Load (on air-gapped machine)

```bash
# Load images
docker load -i postgis-16-3.4.tar
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

### Automated Backup (Docker)

The `docker-compose.prod.yml` includes a `db-backup` service that runs daily.

```bash
# Check backup status
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs db-backup

# List backups
docker compose exec db-backup ls -lh /backups/
```

### Restore

```bash
# Docker Compose
docker compose exec -T db \
  pg_restore -U postgres -d gis_agent --clean --if-exists \
  < backups/gis_agent_20260101_000000.sql.gz

# Kubernetes
kubectl -n gis-agent exec -i postgres-0 -- \
  pg_restore -U postgres -d gis_agent --clean --if-exists \
  < backup.dump
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_RETENTION_DAYS` | 7 | Days to keep backup files |
| `BACKUP_DIR` | `./backups` | Backup output directory |

---

## 8. Monitoring

### Health Check

The application exposes a health endpoint at `/`:

```bash
curl -f http://localhost:8080/
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
