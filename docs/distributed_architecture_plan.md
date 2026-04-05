# GIS Data Agent 分布式/高可用/高性能架构升级方案

## 背景与目标

### 当前架构现状

**优势**:
- 完整的数据生命周期覆盖(汇聚→质检→清洗→治理→分析→展示→分发)
- 深度智能化能力(DRL优化、因果推断、质检自动化、多模态融合)
- 可扩展架构(MCP Hub、Custom Skills、User Tools、Workflow DAG)
- 基础容器化(Docker Compose + K8s + Helm)

**软肋**:
1. **单点故障风险**: 单节点PostgreSQL、单进程任务队列、单节点缓存
2. **水平扩展受限**: ReadWriteOnce PVC、进程内状态、同步数据库驱动
3. **性能瓶颈**: 连接池过小(5)、无读写分离、无分布式计算
4. **数据生命周期缺口**: 无冷存储归档、跨系统血缘不完整
5. **可观测性不足**: 无分布式追踪、日志未集中、告警渠道单一

### 升级目标

1. **分布式**: 多节点水平扩展、分布式任务执行、跨Pod状态一致性
2. **高可用**: 无单点故障、自动故障转移、零停机部署
3. **高性能**: 异步I/O、连接池优化、缓存层、批处理、并行执行
4. **生产级**: API网关、服务网格、分布式追踪、集中日志

---

## 架构设计原则

1. **渐进式升级**: 每个阶段独立可部署,不破坏现有功能
2. **向后兼容**: 单节点部署仍可工作(开发/小规模场景)
3. **优雅降级**: 分布式组件不可用时自动回退到单机模式
4. **国产化适配**: 考虑国内云厂商(阿里云PolarDB、腾讯云TDSQL、华为云GaussDB)

---

## 总体架构图(目标状态)

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway (Kong/APISIX)                 │
│              (限流、认证、路由、熔断、灰度发布)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
│  App Pod 1     │  │  App Pod 2     │  │  App Pod N     │
│  (Chainlit)    │  │  (Chainlit)    │  │  (Chainlit)    │
│  + ADK Agent   │  │  + ADK Agent   │  │  + ADK Agent   │
└───────┬────────┘  └───────┬────────┘  └───────┬────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
        ┌────────────────────┼────────────────────────────────┐
        │                    │                                 │
┌───────▼────────┐  ┌───────▼────────┐  ┌──────────────────▼─────┐
│ Celery Worker  │  │ Celery Worker  │  │   Redis Cluster        │
│ Pool (任务执行) │  │ Pool (任务执行) │  │ (缓存+队列+会话)        │
└───────┬────────┘  └───────┬────────┘  └────────────────────────┘
        │                    │
        └────────────────────┼────────────────────┐
                             │                    │
        ┌────────────────────▼─────┐   ┌─────────▼──────────┐
        │  PostgreSQL Primary      │   │  MinIO Cluster     │
        │  (写入 + 强一致性读)      │   │  (对象存储)         │
        └────────┬─────────────────┘   └────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
┌───────▼────────┐ ┌─────▼──────────┐
│ PG Read Replica│ │ PG Read Replica│
│ (分析查询)      │ │ (报表查询)      │
└────────────────┘ └────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              可观测性栈 (Observability Stack)                     │
│  OpenTelemetry Collector → Jaeger (追踪) + Loki (日志)          │
│                          + Prometheus (指标)                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 分阶段实施计划

### Phase 1: 数据库高可用与连接优化 (2-3周)

**目标**: 消除数据库单点故障,优化连接池

**关键变更**:

1. **PostgreSQL主从复制**
   - 部署1主2从架构(流复制)
   - 主库: 写入 + 强一致性读
   - 从库: 分析查询 + 报表查询
   - 自动故障转移(Patroni或云厂商托管)

2. **连接池代理(PgBouncer)**
   - 部署PgBouncer作为连接池中间层
   - Transaction模式(每个事务一个连接)
   - 连接池配置: default_pool_size=25, max_client_conn=200

3. **异步数据库驱动迁移**
   - 替换SQLAlchemy sync → asyncpg
   - 保留同步接口兼容性(通过asyncio.run包装)

**文件变更**:

#### 1. 新增 `data_agent/db_engine_async.py`
```python
"""异步数据库引擎 - asyncpg驱动"""
import asyncpg
from typing import Optional
import os

_async_pool: Optional[asyncpg.Pool] = None

async def get_async_pool() -> asyncpg.Pool:
    """获取异步连接池(单例)"""
    global _async_pool
    if _async_pool is None:
        _async_pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "agent_user"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DB", "gis_agent"),
            min_size=10,
            max_size=50,
            command_timeout=60,
        )
    return _async_pool

async def close_async_pool():
    """关闭连接池"""
    global _async_pool
    if _async_pool:
        await _async_pool.close()
        _async_pool = None
```

#### 2. 修改 `data_agent/db_engine.py`
```python
# 添加读写分离支持
import os
from sqlalchemy import create_engine

# 主库(写入)
_engine = create_engine(
    os.getenv("DATABASE_URL"),
    pool_size=10,  # 从5增加到10
    max_overflow=20,  # 从10增加到20
    pool_recycle=1800,
    pool_pre_ping=True,
)

# 读库(查询) - 通过PgBouncer
_read_engine = create_engine(
    os.getenv("DATABASE_READ_URL", os.getenv("DATABASE_URL")),  # 回退到主库
    pool_size=20,
    max_overflow=40,
    pool_recycle=1800,
    pool_pre_ping=True,
)

def get_engine(readonly: bool = False):
    """获取数据库引擎
    Args:
        readonly: True=读库, False=主库
    """
    return _read_engine if readonly else _engine
```

#### 3. 新增 K8s 配置 `k8s/pgbouncer-deployment.yaml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pgbouncer
  namespace: gis-agent
spec:
  replicas: 2
  selector:
    matchLabels:
      app: pgbouncer
  template:
    metadata:
      labels:
        app: pgbouncer
    spec:
      containers:
      - name: pgbouncer
        image: edoburu/pgbouncer:1.21.0
        ports:
        - containerPort: 5432
        env:
        - name: DATABASE_URL
          value: "postgres://agent_user:password@postgres-primary:5432/gis_agent"
        - name: POOL_MODE
          value: "transaction"
        - name: DEFAULT_POOL_SIZE
          value: "25"
        - name: MAX_CLIENT_CONN
          value: "200"
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: pgbouncer
  namespace: gis-agent
spec:
  selector:
    app: pgbouncer
  ports:
  - port: 5432
    targetPort: 5432
```

#### 4. 新增 `k8s/postgres-replication.yaml`
```yaml
# PostgreSQL主从复制配置(使用Patroni或云厂商托管)
# 示例: 阿里云PolarDB、腾讯云TDSQL、AWS RDS
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-replication-config
  namespace: gis-agent
data:
  # 主库连接
  PRIMARY_HOST: "postgres-primary.gis-agent.svc.cluster.local"
  # 读库连接(负载均衡到多个从库)
  REPLICA_HOST: "postgres-replica.gis-agent.svc.cluster.local"
```

**数据库迁移**:

新增 `data_agent/migrations/056_add_read_replica_support.sql`:
```sql
-- 为读库创建只读用户
CREATE ROLE agent_reader WITH LOGIN PASSWORD 'reader_password';
GRANT CONNECT ON DATABASE gis_agent TO agent_reader;
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_reader;

-- 为分析查询创建物化视图(减轻主库压力)
CREATE MATERIALIZED VIEW mv_pipeline_analytics AS
SELECT 
    DATE_TRUNC('hour', created_at) as hour,
    pipeline_type,
    COUNT(*) as run_count,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration_seconds
FROM agent_workflow_runs
WHERE completed_at IS NOT NULL
GROUP BY 1, 2;

CREATE INDEX idx_mv_pipeline_analytics_hour ON mv_pipeline_analytics(hour);

-- 定时刷新(每15分钟)
CREATE EXTENSION IF NOT EXISTS pg_cron;
SELECT cron.schedule('refresh-pipeline-analytics', '*/15 * * * *', 
    'REFRESH MATERIALIZED VIEW CONCURRENTLY mv_pipeline_analytics');
```

**验证步骤**:

1. 部署PgBouncer: `kubectl apply -f k8s/pgbouncer-deployment.yaml`
2. 配置主从复制(云厂商控制台或Patroni)
3. 更新应用环境变量:
   ```bash
   DATABASE_URL=postgresql://agent_user:password@pgbouncer:5432/gis_agent
   DATABASE_READ_URL=postgresql://agent_reader:password@postgres-replica:5432/gis_agent
   ```
4. 运行迁移: `python -m data_agent.migrations.run 056`
5. 测试读写分离:
   ```python
   # 写入测试
   engine = get_engine(readonly=False)
   # 读取测试
   read_engine = get_engine(readonly=True)
   ```
6. 故障转移测试: 停止主库,观察Patroni自动提升从库

---

### Phase 2: 分布式任务队列与缓存 (3-4周)

**目标**: 替换进程内任务队列为Celery,部署Redis集群

**关键变更**:

1. **Celery分布式任务队列**
   - Broker: Redis Cluster(或RabbitMQ)
   - Backend: Redis(结果存储)
   - Worker池: 3-5个worker进程,每个4-8并发

2. **Redis Cluster部署**
   - 3主3从架构(最小HA配置)
   - 用途: Celery broker + 分布式缓存 + 会话存储

3. **任务队列迁移**
   - 保留 `TaskQueue` 类接口不变
   - 底层实现切换到Celery

**文件变更**:

#### 1. 新增 `data_agent/celery_app.py`
```python
"""Celery应用配置"""
from celery import Celery
import os

# Celery实例
celery_app = Celery(
    'gis_agent',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://redis-cluster:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://redis-cluster:6379/1'),
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1小时超时
    task_soft_time_limit=3300,  # 55分钟软超时
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=100,  # 防止内存泄漏
)

# 任务自动发现
celery_app.autodiscover_tasks(['data_agent.tasks'])
```

#### 2. 新增 `data_agent/tasks/__init__.py`
```python
"""Celery任务定义"""
from .pipeline_tasks import run_pipeline_task
from .workflow_tasks import execute_workflow_task
from .fusion_tasks import run_fusion_task

__all__ = ['run_pipeline_task', 'execute_workflow_task', 'run_fusion_task']
```

#### 3. 新增 `data_agent/tasks/pipeline_tasks.py`
```python
"""管道执行任务"""
from data_agent.celery_app import celery_app
from data_agent.pipeline_runner import run_pipeline_headless
import asyncio

@celery_app.task(bind=True, name='gis_agent.run_pipeline')
def run_pipeline_task(self, user_id, session_id, prompt, pipeline_type, **kwargs):
    """异步执行管道任务"""
    try:
        # 更新任务状态
        self.update_state(state='PROGRESS', meta={'status': 'starting'})
        
        # 运行管道(同步包装异步)
        result = asyncio.run(run_pipeline_headless(
            user_id=user_id,
            session_id=session_id,
            prompt=prompt,
            pipeline_type=pipeline_type,
            **kwargs
        ))
        
        return {
            'status': 'completed',
            'result': result.to_dict(),
        }
    except Exception as e:
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise
```

#### 4. 修改 `data_agent/task_queue.py`
```python
"""任务队列 - Celery适配器"""
from data_agent.celery_app import celery_app
from data_agent.tasks import run_pipeline_task
from celery.result import AsyncResult

class TaskQueue:
    """任务队列(Celery后端)"""
    
    def __init__(self, max_concurrent: int = None):
        # max_concurrent由Celery worker配置控制
        pass
    
    async def submit(self, user_id, session_id, prompt, pipeline_type, priority=5):
        """提交任务"""
        # 转换为Celery任务
        task = run_pipeline_task.apply_async(
            args=[user_id, session_id, prompt, pipeline_type],
            priority=priority,  # 0-9, 9最高
            queue='default',
        )
        
        # 记录到数据库
        await self._record_task(task.id, user_id, pipeline_type, priority)
        
        return task.id
    
    async def get_status(self, task_id: str):
        """查询任务状态"""
        result = AsyncResult(task_id, app=celery_app)
        return {
            'task_id': task_id,
            'state': result.state,  # PENDING/STARTED/SUCCESS/FAILURE
            'info': result.info,
        }
    
    async def cancel(self, task_id: str):
        """取消任务"""
        celery_app.control.revoke(task_id, terminate=True)
```

#### 5. 新增 `k8s/redis-cluster.yaml`
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
  namespace: gis-agent
spec:
  serviceName: redis-cluster
  replicas: 6  # 3主3从
  selector:
    matchLabels:
      app: redis-cluster
  template:
    metadata:
      labels:
        app: redis-cluster
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
          name: client
        - containerPort: 16379
          name: gossip
        command:
        - redis-server
        - /conf/redis.conf
        volumeMounts:
        - name: conf
          mountPath: /conf
        - name: data
          mountPath: /data
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 1Gi
      volumes:
      - name: conf
        configMap:
          name: redis-cluster-config
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

#### 6. 新增 `k8s/celery-worker-deployment.yaml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-worker
  namespace: gis-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: celery-worker
  template:
    metadata:
      labels:
        app: celery-worker
    spec:
      containers:
      - name: worker
        image: gis-agent:latest
        command:
        - celery
        - -A
        - data_agent.celery_app
        - worker
        - --loglevel=info
        - --concurrency=4
        - --max-tasks-per-child=100
        env:
        - name: CELERY_BROKER_URL
          value: redis://redis-cluster:6379/0
        - name: CELERY_RESULT_BACKEND
          value: redis://redis-cluster:6379/1
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2
            memory: 4Gi
```

#### 7. 修改 `data_agent/semantic_layer.py` - 使用Redis缓存
```python
import redis.asyncio as aioredis
import json

_redis_client = None

async def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            os.getenv('REDIS_URL', 'redis://redis-cluster:6379/2'),
            decode_responses=True
        )
    return _redis_client

async def get_semantic_sources(use_cache=True):
    """获取语义源(带Redis缓存)"""
    if not use_cache:
        return await _fetch_from_db()
    
    redis = await get_redis()
    cache_key = "semantic:sources"
    
    # 尝试从Redis获取
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # 从数据库加载
    sources = await _fetch_from_db()
    
    # 写入Redis(5分钟TTL)
    await redis.setex(cache_key, 300, json.dumps(sources))
    
    return sources
```

**验证步骤**:

1. 部署Redis Cluster: `kubectl apply -f k8s/redis-cluster.yaml`
2. 初始化集群: `redis-cli --cluster create ...`
3. 部署Celery Worker: `kubectl apply -f k8s/celery-worker-deployment.yaml`
4. 测试任务提交:
   ```python
   from data_agent.task_queue import TaskQueue
   queue = TaskQueue()
   task_id = await queue.submit(user_id, session_id, prompt, 'general')
   status = await queue.get_status(task_id)
   ```
5. 监控Celery: `celery -A data_agent.celery_app inspect active`

---

### Phase 3: 对象存储与文件共享 (2-3周)

**目标**: 解决多Pod文件共享问题,实现冷存储归档

**关键变更**:

1. **MinIO对象存储集群**
   - 4节点分布式部署
   - 用途: 用户上传文件、生成结果、数据版本快照

2. **文件存储迁移**
   - 从本地 `uploads/{user_id}/` 迁移到 MinIO
   - 保留本地缓存(LRU,最近访问的文件)

3. **冷存储归档策略**
   - 30天未访问 → 归档到S3 Glacier/阿里云归档存储
   - 数据版本快照自动归档

**文件变更**:

#### 1. 新增 `data_agent/storage/object_storage.py`
```python
"""对象存储抽象层"""
from minio import Minio
from minio.error import S3Error
import os
from typing import BinaryIO

class ObjectStorage:
    """对象存储客户端(MinIO/S3兼容)"""
    
    def __init__(self):
        self.client = Minio(
            os.getenv('MINIO_ENDPOINT', 'minio:9000'),
            access_key=os.getenv('MINIO_ACCESS_KEY'),
            secret_key=os.getenv('MINIO_SECRET_KEY'),
            secure=os.getenv('MINIO_SECURE', 'false').lower() == 'true'
        )
        self.bucket = os.getenv('MINIO_BUCKET', 'gis-agent')
        self._ensure_bucket()
    
    def _ensure_bucket(self):
        """确保bucket存在"""
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
    
    def upload_file(self, object_name: str, file_path: str, metadata: dict = None):
        """上传文件"""
        self.client.fput_object(
            self.bucket,
            object_name,
            file_path,
            metadata=metadata
        )
    
    def download_file(self, object_name: str, file_path: str):
        """下载文件"""
        self.client.fget_object(self.bucket, object_name, file_path)
    
    def get_presigned_url(self, object_name: str, expires_seconds: int = 3600):
        """生成预签名URL(用于前端直接下载)"""
        return self.client.presigned_get_object(
            self.bucket,
            object_name,
            expires=expires_seconds
        )
    
    def list_objects(self, prefix: str):
        """列出对象"""
        return self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
    
    def delete_object(self, object_name: str):
        """删除对象"""
        self.client.remove_object(self.bucket, object_name)
```

#### 2. 修改 `data_agent/user_context.py` - 文件路径解析
```python
from data_agent.storage.object_storage import ObjectStorage

_object_storage = None

def get_object_storage():
    global _object_storage
    if _object_storage is None:
        _object_storage = ObjectStorage()
    return _object_storage

def get_user_upload_path(filename: str) -> str:
    """获取用户上传文件路径(对象存储)"""
    user_id = current_user_id.get('anonymous')
    return f"uploads/{user_id}/{filename}"

async def save_user_file(filename: str, file_data: BinaryIO):
    """保存用户文件到对象存储"""
    object_name = get_user_upload_path(filename)
    storage = get_object_storage()
    
    # 先保存到临时本地文件
    temp_path = f"/tmp/{filename}"
    with open(temp_path, 'wb') as f:
        f.write(file_data.read())
    
    # 上传到MinIO
    storage.upload_file(object_name, temp_path, metadata={
        'user_id': current_user_id.get(),
        'uploaded_at': datetime.utcnow().isoformat()
    })
    
    # 删除临时文件
    os.remove(temp_path)
    
    return object_name
```

#### 3. 新增 `k8s/minio-statefulset.yaml`
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: minio
  namespace: gis-agent
spec:
  serviceName: minio
  replicas: 4
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      containers:
      - name: minio
        image: minio/minio:latest
        args:
        - server
        - http://minio-{0...3}.minio.gis-agent.svc.cluster.local/data
        - --console-address
        - ":9001"
        env:
        - name: MINIO_ROOT_USER
          value: admin
        - name: MINIO_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: minio-secret
              key: password
        ports:
        - containerPort: 9000
        - containerPort: 9001
        volumeMounts:
        - name: data
          mountPath: /data
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1
            memory: 2Gi
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

#### 4. 新增 `data_agent/archival/cold_storage.py`
```python
"""冷存储归档策略"""
import boto3
from datetime import datetime, timedelta

class ColdStorageArchiver:
    """冷存储归档器"""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            endpoint_url=os.getenv('S3_ENDPOINT'),
            aws_access_key_id=os.getenv('S3_ACCESS_KEY'),
            aws_secret_access_key=os.getenv('S3_SECRET_KEY')
        )
        self.archive_bucket = os.getenv('S3_ARCHIVE_BUCKET', 'gis-agent-archive')
    
    async def archive_old_files(self, days_threshold: int = 30):
        """归档超过N天未访问的文件"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
        
        # 查询待归档文件
        engine = get_engine(readonly=True)
        with engine.connect() as conn:
            result = conn.execute("""
                SELECT asset_uuid, storage_path, last_accessed_at
                FROM agent_data_assets
                WHERE storage_backend = 'minio'
                  AND last_accessed_at < %s
                  AND archived = FALSE
            """, (cutoff_date,))
            
            for row in result:
                await self._archive_file(row['asset_uuid'], row['storage_path'])
    
    async def _archive_file(self, asset_uuid: str, storage_path: str):
        """归档单个文件到S3 Glacier"""
        # 从MinIO下载
        minio = get_object_storage()
        temp_path = f"/tmp/{asset_uuid}"
        minio.download_file(storage_path, temp_path)
        
        # 上传到S3 Glacier
        with open(temp_path, 'rb') as f:
            self.s3_client.upload_fileobj(
                f,
                self.archive_bucket,
                storage_path,
                ExtraArgs={'StorageClass': 'GLACIER'}
            )
        
        # 更新数据库
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("""
                UPDATE agent_data_assets
                SET archived = TRUE,
                    archive_backend = 's3_glacier',
                    archive_path = %s,
                    archived_at = NOW()
                WHERE asset_uuid = %s
            """, (storage_path, asset_uuid))
        
        # 从MinIO删除
        minio.delete_object(storage_path)
```

**数据库迁移**:

新增 `data_agent/migrations/057_add_archival_support.sql`:
```sql
-- 添加归档字段
ALTER TABLE agent_data_assets
ADD COLUMN archived BOOLEAN DEFAULT FALSE,
ADD COLUMN archive_backend VARCHAR(50),
ADD COLUMN archive_path TEXT,
ADD COLUMN archived_at TIMESTAMPTZ,
ADD COLUMN last_accessed_at TIMESTAMPTZ DEFAULT NOW();

-- 创建归档任务表
CREATE TABLE IF NOT EXISTS agent_archival_jobs (
    job_id SERIAL PRIMARY KEY,
    job_type VARCHAR(30),  -- 'archive' | 'restore'
    asset_uuid UUID REFERENCES agent_data_assets(asset_uuid),
    status VARCHAR(20) DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX idx_archival_jobs_status ON agent_archival_jobs(status);
```

**验证步骤**:

1. 部署MinIO: `kubectl apply -f k8s/minio-statefulset.yaml`
2. 配置MinIO客户端: `mc alias set myminio http://minio:9000 admin password`
3. 测试文件上传:
   ```python
   storage = get_object_storage()
   storage.upload_file('test.txt', '/tmp/test.txt')
   ```
4. 配置归档定时任务(Celery Beat):
   ```python
   @celery_app.task
   def archive_old_files_task():
       archiver = ColdStorageArchiver()
       asyncio.run(archiver.archive_old_files(days_threshold=30))
   ```

---

### Phase 4: API网关与服务网格 (2-3周)

**目标**: 统一入口、限流熔断、灰度发布

**关键变更**:

1. **API网关(Kong或APISIX)**
   - 统一入口: 所有请求经过网关
   - 限流: 按用户/IP限流
   - 熔断: 后端服务不可用时快速失败
   - 认证: JWT验证前置到网关

2. **服务网格(可选,Istio)**
   - 服务间通信加密(mTLS)
   - 流量管理(金丝雀发布)
   - 可观测性增强

**文件变更**:

#### 1. 新增 `k8s/kong-gateway.yaml`
```yaml
apiVersion: v1
kind: Service
metadata:
  name: kong-proxy
  namespace: gis-agent
spec:
  type: LoadBalancer
  ports:
  - name: proxy
    port: 80
    targetPort: 8000
  - name: proxy-ssl
    port: 443
    targetPort: 8443
  selector:
    app: kong
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kong
  namespace: gis-agent
spec:
  replicas: 2
  selector:
    matchLabels:
      app: kong
  template:
    metadata:
      labels:
        app: kong
    spec:
      containers:
      - name: kong
        image: kong:3.4
        env:
        - name: KONG_DATABASE
          value: postgres
        - name: KONG_PG_HOST
          value: postgres-primary
        - name: KONG_PROXY_ACCESS_LOG
          value: /dev/stdout
        - name: KONG_ADMIN_ACCESS_LOG
          value: /dev/stdout
        - name: KONG_PROXY_ERROR_LOG
          value: /dev/stderr
        - name: KONG_ADMIN_ERROR_LOG
          value: /dev/stderr
        ports:
        - containerPort: 8000
          name: proxy
        - containerPort: 8443
          name: proxy-ssl
        - containerPort: 8001
          name: admin
```

#### 2. 新增 `k8s/kong-plugins.yaml` - 限流配置
```yaml
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: rate-limiting
  namespace: gis-agent
config:
  minute: 100
  hour: 1000
  policy: redis
  redis_host: redis-cluster
  redis_port: 6379
plugin: rate-limiting
---
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: jwt-auth
  namespace: gis-agent
plugin: jwt
---
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: circuit-breaker
  namespace: gis-agent
config:
  failure_threshold: 5
  recovery_timeout: 30
plugin: circuit-breaker
```

#### 3. 新增 `k8s/kong-ingress.yaml`
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: gis-agent-ingress
  namespace: gis-agent
  annotations:
    konghq.com/plugins: rate-limiting,jwt-auth,circuit-breaker
    konghq.com/strip-path: "true"
spec:
  ingressClassName: kong
  rules:
  - host: gis-agent.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: gis-agent-app
            port:
              number: 8000
      - path: /
        pathType: Prefix
        backend:
          service:
            name: gis-agent-app
            port:
              number: 8000
```

#### 4. 修改 `data_agent/auth.py` - 网关JWT集成
```python
"""认证模块 - 支持Kong JWT"""

def verify_kong_jwt(token: str) -> dict:
    """验证Kong签发的JWT"""
    try:
        # Kong在请求头中注入 X-Consumer-Username
        # 直接信任Kong的验证结果
        return {'username': token}
    except Exception as e:
        raise ValueError(f"Invalid JWT: {e}")

async def get_user_from_kong_headers(request):
    """从Kong注入的请求头获取用户信息"""
    username = request.headers.get('X-Consumer-Username')
    user_id = request.headers.get('X-Consumer-Custom-Id')
    
    if not username:
        raise ValueError("Missing Kong authentication headers")
    
    return {
        'username': username,
        'user_id': user_id,
    }
```

**验证步骤**:

1. 部署Kong: `kubectl apply -f k8s/kong-gateway.yaml`
2. 配置插件: `kubectl apply -f k8s/kong-plugins.yaml`
3. 配置Ingress: `kubectl apply -f k8s/kong-ingress.yaml`
4. 测试限流:
   ```bash
   for i in {1..150}; do curl http://gis-agent.example.com/api/health; done
   # 前100个成功,后50个返回429 Too Many Requests
   ```
5. 测试熔断: 停止后端服务,观察Kong快速返回503

---

### Phase 5: 分布式追踪与可观测性 (2-3周)

**目标**: 完整的分布式追踪、集中日志、统一监控

**关键变更**:

1. **OpenTelemetry全链路追踪**
   - 自动注入trace_id到所有日志
   - Span覆盖: HTTP请求、数据库查询、Celery任务、工具调用

2. **Jaeger追踪后端**
   - 存储trace数据
   - UI查询和可视化

3. **Loki集中日志**
   - 替代stdout日志
   - 与trace_id关联

4. **Grafana统一看板**
   - Prometheus指标 + Jaeger追踪 + Loki日志

**文件变更**:

#### 1. 修改 `data_agent/observability.py` - OpenTelemetry集成
```python
"""可观测性 - OpenTelemetry完整集成"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor

def setup_tracing():
    """初始化分布式追踪"""
    # Jaeger导出器
    jaeger_exporter = JaegerExporter(
        agent_host_name=os.getenv('JAEGER_AGENT_HOST', 'jaeger-agent'),
        agent_port=int(os.getenv('JAEGER_AGENT_PORT', '6831')),
    )
    
    # TracerProvider
    provider = TracerProvider()
    processor = BatchSpanProcessor(jaeger_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    
    # 自动注入
    FastAPIInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument(engine=get_engine())
    RedisInstrumentor().instrument()
    CeleryInstrumentor().instrument()

def get_current_trace_id() -> str:
    """获取当前trace_id"""
    span = trace.get_current_span()
    if span:
        return format(span.get_span_context().trace_id, '032x')
    return ''
```

#### 2. 新增 `k8s/observability-stack.yaml`
```yaml
# Jaeger All-in-One部署
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
  namespace: gis-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jaeger
  template:
    metadata:
      labels:
        app: jaeger
    spec:
      containers:
      - name: jaeger
        image: jaegertracing/all-in-one:1.50
        ports:
        - containerPort: 5775
          protocol: UDP
        - containerPort: 6831
          protocol: UDP
        - containerPort: 6832
          protocol: UDP
        - containerPort: 5778
        - containerPort: 16686  # UI
        - containerPort: 14268
        env:
        - name: COLLECTOR_ZIPKIN_HOST_PORT
          value: ":9411"
---
# Loki日志聚合
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: loki
  namespace: gis-agent
spec:
  serviceName: loki
  replicas: 1
  selector:
    matchLabels:
      app: loki
  template:
    metadata:
      labels:
        app: loki
    spec:
      containers:
      - name: loki
        image: grafana/loki:2.9.0
        ports:
        - containerPort: 3100
        volumeMounts:
        - name: data
          mountPath: /loki
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 50Gi
---
# Grafana可视化
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: gis-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
      - name: grafana
        image: grafana/grafana:10.0.0
        ports:
        - containerPort: 3000
        env:
        - name: GF_SECURITY_ADMIN_PASSWORD
          value: admin
```

#### 3. 新增 `data_agent/logging/loki_handler.py`
```python
"""Loki日志处理器"""
import logging
import httpx
import json

class LokiHandler(logging.Handler):
    """Loki日志推送"""
    
    def __init__(self, url: str, labels: dict):
        super().__init__()
        self.url = url
        self.labels = labels
        self.client = httpx.AsyncClient()
    
    def emit(self, record: logging.LogRecord):
        """发送日志到Loki"""
        try:
            log_entry = {
                'streams': [{
                    'stream': self.labels,
                    'values': [[
                        str(int(record.created * 1e9)),  # 纳秒时间戳
                        self.format(record)
                    ]]
                }]
            }
            
            # 异步推送
            asyncio.create_task(
                self.client.post(f"{self.url}/loki/api/v1/push", json=log_entry)
            )
        except Exception:
            self.handleError(record)
```

**验证步骤**:

1. 部署可观测性栈: `kubectl apply -f k8s/observability-stack.yaml`
2. 配置Grafana数据源:
   - Prometheus: http://prometheus:9090
   - Jaeger: http://jaeger:16686
   - Loki: http://loki:3100
3. 测试追踪: 发起请求,在Jaeger UI查看完整trace
4. 测试日志关联: 从trace跳转到对应日志

---

### Phase 6: 跨系统血缘与数据治理增强 (2周)

**目标**: 完善数据血缘追踪,支持跨系统集成

**关键变更**:

1. **血缘图谱增强**
   - 支持外部系统资产(通过external_id关联)
   - 血缘可视化API

2. **数据质量持续监控**
   - 定时质量检查任务
   - 质量趋势分析

**文件变更**:

#### 1. 修改 `data_agent/data_catalog.py` - 跨系统血缘
```python
async def register_external_asset(
    external_system: str,
    external_id: str,
    asset_name: str,
    asset_type: str,
    metadata: dict
):
    """注册外部系统资产"""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute("""
            INSERT INTO agent_data_assets (
                asset_uuid, asset_name, asset_type,
                external_system, external_id,
                technical_metadata
            ) VALUES (gen_random_uuid(), %s, %s, %s, %s, %s)
            ON CONFLICT (external_system, external_id) DO UPDATE
            SET technical_metadata = EXCLUDED.technical_metadata
        """, (asset_name, asset_type, external_system, external_id, json.dumps(metadata)))

async def link_external_lineage(
    internal_asset_id: str,
    external_system: str,
    external_id: str,
    relationship: str  # 'upstream' | 'downstream'
):
    """关联内外部资产血缘"""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute("""
            INSERT INTO agent_asset_lineage (
                source_asset_id, target_asset_id, relationship_type
            )
            SELECT %s, asset_uuid, %s
            FROM agent_data_assets
            WHERE external_system = %s AND external_id = %s
        """, (internal_asset_id, relationship, external_system, external_id))
```

**数据库迁移**:

新增 `data_agent/migrations/058_cross_system_lineage.sql`:
```sql
-- 添加外部系统字段
ALTER TABLE agent_data_assets
ADD COLUMN external_system VARCHAR(100),
ADD COLUMN external_id VARCHAR(255);

CREATE UNIQUE INDEX idx_external_asset 
ON agent_data_assets(external_system, external_id) 
WHERE external_system IS NOT NULL;

-- 血缘关系表
CREATE TABLE IF NOT EXISTS agent_asset_lineage (
    lineage_id SERIAL PRIMARY KEY,
    source_asset_id UUID REFERENCES agent_data_assets(asset_uuid),
    target_asset_id UUID REFERENCES agent_data_assets(asset_uuid),
    relationship_type VARCHAR(20),  -- 'upstream' | 'downstream' | 'derived'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_lineage_source ON agent_asset_lineage(source_asset_id);
CREATE INDEX idx_lineage_target ON agent_asset_lineage(target_asset_id);
```

---

## 部署架构对比

### 单节点部署(开发/小规模)
```
Docker Compose:
- app (1容器)
- postgres (1容器)
- redis (可选)

适用场景: 开发环境、演示、<10用户
```

### 高可用部署(生产)
```
Kubernetes:
- app (3-5 Pod, HPA)
- celery-worker (3 Pod)
- postgres (1主2从 + PgBouncer)
- redis-cluster (6节点)
- minio (4节点)
- kong-gateway (2 Pod)
- jaeger + loki + grafana

适用场景: 生产环境、>50用户、高并发
```

---

## 性能指标目标

| 指标 | 当前 | 目标(Phase 6完成后) |
|------|------|---------------------|
| 并发用户 | 10 | 500+ |
| 请求延迟(P95) | 2s | <500ms |
| 数据库连接数 | 5 | 50(主) + 100(从) |
| 任务并发数 | 3 | 50+ |
| 文件存储 | 本地5GB | MinIO 10TB+ |
| 可用性 | 单点 | 99.9% |
| RTO(恢复时间) | 手动 | <5分钟 |
| RPO(数据丢失) | 未知 | <1分钟 |

---

## 成本估算(云厂商)

### 阿里云(华东2)
- ECS (4C8G × 5): ¥3000/月
- PolarDB MySQL (2C4G): ¥1500/月
- Redis集群 (4G × 3): ¥1200/月
- OSS存储 (10TB): ¥2000/月
- SLB负载均衡: ¥300/月
- **总计**: ~¥8000/月

### 自建K8s(本地机房)
- 服务器 (32C64G × 3): 一次性¥60000
- 存储 (20TB): 一次性¥30000
- 网络设备: 一次性¥20000
- **总计**: ~¥110000(一次性) + 电费/运维

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Celery任务积压 | 响应变慢 | 监控队列长度,自动扩容worker |
| Redis集群脑裂 | 数据不一致 | 使用Sentinel,配置合理超时 |
| MinIO单节点故障 | 文件不可用 | 4节点分布式,纠删码 |
| 数据库主库故障 | 服务中断 | Patroni自动故障转移 |
| 网关单点故障 | 全站不可用 | Kong 2副本 + K8s Service |

---

## 验证清单

### Phase 1验证
- [ ] PgBouncer连接池正常
- [ ] 主从复制延迟<1s
- [ ] 读写分离路由正确
- [ ] 故障转移<30s

### Phase 2验证
- [ ] Celery任务提交成功
- [ ] Worker并发执行
- [ ] Redis缓存命中率>70%
- [ ] 任务失败自动重试

### Phase 3验证
- [ ] MinIO文件上传/下载
- [ ] 多Pod共享文件
- [ ] 冷存储归档成功
- [ ] 预签名URL有效

### Phase 4验证
- [ ] Kong限流生效
- [ ] JWT认证通过
- [ ] 熔断器触发
- [ ] 灰度发布成功

### Phase 5验证
- [ ] Jaeger显示完整trace
- [ ] Loki聚合所有日志
- [ ] Grafana看板正常
- [ ] trace_id关联日志

### Phase 6验证
- [ ] 跨系统血缘查询
- [ ] 质量监控告警
- [ ] 血缘图谱可视化

---

## 总结

本方案通过6个阶段,渐进式地将GIS Data Agent从单节点架构升级为分布式/高可用/高性能的生产级平台:

1. **Phase 1**: 数据库HA,消除最大单点
2. **Phase 2**: 分布式任务队列,支持水平扩展
3. **Phase 3**: 对象存储,解决文件共享和归档
4. **Phase 4**: API网关,统一入口和流量管理
5. **Phase 5**: 可观测性,全链路追踪和监控
6. **Phase 6**: 数据治理增强,跨系统集成

每个阶段独立可部署,向后兼容,优雅降级。完成后,平台可支持500+并发用户、99.9%可用性、<500ms响应延迟。

**关键文件清单**:
- 新增: 15个Python模块, 12个K8s YAML, 3个数据库迁移
- 修改: 8个核心模块(db_engine, task_queue, semantic_layer等)
- 配置: Docker Compose, Helm Chart, 环境变量

**下一步行动**:
1. 评审本方案,确认技术选型
2. 准备Phase 1环境(PolarDB/RDS + PgBouncer)
3. 开发分支: `feat/distributed-architecture`
4. 里程碑: 每个Phase 2-3周,总计12-18周

