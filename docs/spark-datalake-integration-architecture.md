# GIS Data Agent — 分布式计算与数据湖集成架构方案

> 版本: v1.0 | 日期: 2026-03-21 | 状态: 架构规划

## 1. 背景与问题分析

### 1.1 当前系统瓶颈

GIS Data Agent v14.3 的所有计算工具均在单机 Python 进程内运行（GeoPandas、Shapely、Rasterio、PySAL 等），面对 TB 级地理数据将遇到内存和计算时间的硬墙。

| 组件 | 当前机制 | 局限 |
|------|----------|------|
| `task_queue.py` | `asyncio.Semaphore(3)` + 优先级队列 | 单机 3 并发，无分布式调度 |
| `workflow_engine.py` | Kahn 拓扑排序 + `asyncio.gather` 并行层 | DAG 层级并行，但每个节点仍是单机执行 |
| `pipeline_runner.py` | `Runner.run_async()` + SSE 流式事件 | 无超时/重试/checkpoint 恢复机制 |
| `a2a_server.py` | 内存 `_tasks` dict + `asyncio.Lock` | 最多保留 100 条，无持久化，无跨节点调度 |
| `fusion/` | 10 种融合策略 + PostGIS 下推 | 大数据量只能依赖 PostGIS，无分布式计算 |

### 1.2 目标场景

- **大规模空间连接**: 数亿级 POI 与数十万级行政区划的空间关联
- **海量栅格分析**: TB 级遥感影像的波段运算、NDVI/NDWI 计算
- **全局特征工程**: 跨省/跨国级别的土地利用变化检测
- **长周期任务**: 运行时间从分钟级到数小时级的分析任务

---

## 2. ADK 官方 Long-Running Tool 模式

ADK 官方在 Human-in-the-Loop 样例中提供了处理长任务的核心机制 —— **Long-Running FunctionResponse**。

### 2.1 核心流程

```
Agent 调用工具
  → 工具立即返回 {status: "pending", job_id: "xxx"}
  → Agent 告知用户 "任务已提交，作业 ID: xxx"
  → 外部长任务异步执行（Spark / Flink / Airflow 等）
  → 执行完成后，应用层构造更新的 FunctionResponse
  → 使用相同的 function_call.id 和 function_call.name
  → 以 role="user" 发回 Agent
  → Agent 恢复上下文，继续后续处理
```

### 2.2 ADK 官方代码模式

```python
from google.genai import types

# ===== 步骤 1: 工具立即返回 pending 状态 =====
async def submit_spark_job(query: str, dataset: str) -> dict:
    """提交分布式计算作业，立即返回作业 ID"""
    job_id = await spark_gateway.submit(query, dataset)
    return {"status": "pending", "job_id": job_id, "message": "Spark 作业已提交"}

# ===== 步骤 2: 外部任务完成后，回注结果到 Agent =====
# 必须使用原始 FunctionCall 的 id 和 name
updated_response = types.Part(
    function_response=types.FunctionResponse(
        id=original_function_call.id,      # 原始调用 ID
        name=original_function_call.name,   # 原始调用名称
        response={
            "status": "completed",
            "result_path": "s3://bucket/results/xxx.parquet",
            "row_count": 12345678,
            "duration_seconds": 847,
        },
    )
)

# 以 user 角色发回 Agent Session
async for event in runner.run_async(
    session_id=session_id,
    user_id=user_id,
    new_message=types.Content(parts=[updated_response], role="user"),
):
    # Agent 恢复执行，生成最终分析报告
    pass
```

**关键约束**: Agent 依赖后续的 `FunctionResponse`（包含在 `role="user"` 的消息中）来感知长任务的完成。如果不回注结果，Agent 将永远不知道任务结束。

---

## 3. 分层集成架构

### 3.1 总体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      Agent Layer (ADK)                            │
│                                                                    │
│   LlmAgent (意图识别 + 工具选择)                                   │
│     ├─ 小数据量 → 本地工具 (GeoPandas/PostGIS)     [L1 即时]      │
│     ├─ 中数据量 → task_queue 排队执行              [L2 队列]      │
│     └─ 大数据量 → Long-Running Tool → 提交分布式作业 [L3 分布式]   │
│                                                                    │
└────────────────────────────┬───────────────────────────────────────┘
                             │ submit job + callback
┌────────────────────────────▼───────────────────────────────────────┐
│                   Job Orchestration Layer                           │
│                                                                    │
│   Celery / Airflow / Cloud Composer / Temporal                     │
│     - 作业提交、状态跟踪、超时、重试策略                             │
│     - 作业完成 → Webhook 回调 → 构造 FunctionResponse               │
│     - 结果回注到 ADK Session，触发 Agent 恢复执行                   │
│                                                                    │
└────────────────────────────┬───────────────────────────────────────┘
                             │ spark-submit / REST API / gRPC
┌────────────────────────────▼───────────────────────────────────────┐
│                  Distributed Compute Layer                          │
│                                                                    │
│   Apache Spark (PySpark) + Apache Sedona                           │
│     - 大规模空间连接 (ST_Intersects, ST_Contains, ST_Distance)     │
│     - 栅格计算 (RasterFrames / GeoTrellis)                         │
│     - 分布式特征工程、聚合统计                                       │
│                                                                    │
│   可选替代/补充:                                                    │
│     - Dask-GeoPandas (中等规模，API 兼容 GeoPandas)                 │
│     - Ray (GPU 加速场景)                                            │
│                                                                    │
└────────────────────────────┬───────────────────────────────────────┘
                             │ read / write
┌────────────────────────────▼───────────────────────────────────────┐
│                       Data Lake Layer                               │
│                                                                    │
│   Object Storage: S3 / GCS / Huawei OBS                            │
│     + Table Format: Apache Iceberg / Delta Lake                    │
│     + Catalog: Iceberg REST Catalog / Hive Metastore               │
│     + 空间分区: Z-order / Geohash / Hilbert 曲线索引               │
│     + 格式: GeoParquet (矢量) / Cloud-Optimized GeoTIFF (栅格)    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 三层执行路由

| 层级 | 执行引擎 | 数据规模 | 响应延迟 | 用户体验 |
|------|----------|----------|----------|----------|
| **L1 即时** | GeoPandas / PostGIS | < 100 MB | 秒级 | 同步返回结果 |
| **L2 队列** | 现有 `task_queue.py` | 100 MB - 1 GB | 分钟级 | 进度条 + SSE 流式 |
| **L3 分布式** | Spark / Sedona | > 1 GB | 10 min - 数小时 | 提交确认 + 完成回调通知 |

```python
# pipeline_runner.py 中增加执行层路由
async def select_execution_tier(dataset_size_mb: float) -> str:
    """根据数据规模自动选择执行引擎"""
    if dataset_size_mb < 100:
        return "local"        # L1: GeoPandas 直接执行
    elif dataset_size_mb < 1000:
        return "queued"       # L2: task_queue 排队
    else:
        return "distributed"  # L3: Spark 提交
```

---

## 4. 核心模块设计

### 4.1 SparkToolset — 分布式计算工具集

新增 `toolsets/spark_toolset.py`:

```python
from google.adk.tools import FunctionTool
from ..base_toolset import BaseToolset


class SparkToolset(BaseToolset):
    """分布式计算工具集 — 面向 TB 级地理数据场景"""

    name = "SparkToolset"
    description = "大规模分布式地理空间分析工具，适用于数据量超过 1GB 的计算任务"

    async def submit_spatial_join(
        self,
        left_table: str,
        right_table: str,
        predicate: str = "ST_Intersects",
        output_table: str | None = None,
    ) -> dict:
        """
        提交 Spark 空间连接作业（基于 Apache Sedona）。

        Args:
            left_table: 左表名称（Iceberg 表或 GeoParquet 路径）
            right_table: 右表名称
            predicate: 空间谓词 (ST_Intersects / ST_Contains / ST_Within / ST_DWithin)
            output_table: 输出表名称，默认自动生成

        Returns:
            包含 job_id 和 status 的字典（Long-Running 模式）
        """
        gateway = get_spark_gateway()
        job_id = await gateway.submit(
            job_type="spatial_join",
            params={
                "left": left_table,
                "right": right_table,
                "predicate": predicate,
                "output": output_table,
            },
        )
        return {
            "status": "submitted",
            "job_id": job_id,
            "message": f"空间连接作业已提交 (Sedona {predicate})",
            "estimated_duration": "取决于数据量，通常 5-30 分钟",
        }

    async def submit_raster_analysis(
        self,
        raster_path: str,
        operation: str,
        params: dict | None = None,
    ) -> dict:
        """
        提交大规模栅格分析作业（RasterFrames / GeoTrellis）。

        Args:
            raster_path: 栅格数据路径（S3/GCS/OBS）
            operation: 分析操作 (ndvi / ndwi / slope / aspect / zonal_stats / reclass)
            params: 操作特定参数

        Returns:
            包含 job_id 和 status 的字典
        """
        gateway = get_spark_gateway()
        job_id = await gateway.submit(
            job_type="raster_analysis",
            params={"path": raster_path, "operation": operation, **(params or {})},
        )
        return {
            "status": "submitted",
            "job_id": job_id,
            "message": f"栅格分析作业已提交 ({operation})",
        }

    async def submit_feature_engineering(
        self,
        source_table: str,
        features: list[str],
        group_by: str | None = None,
    ) -> dict:
        """
        提交分布式特征工程作业。

        Args:
            source_table: 源数据表
            features: 需要计算的特征列表 (area / perimeter / centroid / buffer / ...)
            group_by: 分组字段

        Returns:
            包含 job_id 和 status 的字典
        """
        gateway = get_spark_gateway()
        job_id = await gateway.submit(
            job_type="feature_engineering",
            params={"source": source_table, "features": features, "group_by": group_by},
        )
        return {"status": "submitted", "job_id": job_id}

    async def check_job_status(self, job_id: str) -> dict:
        """
        查询 Spark 作业状态。

        Agent 可以调用此工具来轮询作业进度。

        Returns:
            包含 status / progress / result 的字典
        """
        gateway = get_spark_gateway()
        return await gateway.get_status(job_id)

    async def cancel_job(self, job_id: str) -> dict:
        """取消正在运行的 Spark 作业"""
        gateway = get_spark_gateway()
        return await gateway.cancel(job_id)
```

### 4.2 SparkGateway — 作业提交网关

新增 `spark_gateway.py`:

```python
import asyncio
from uuid import uuid4
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

from .db_engine import get_engine


class SparkBackend(str, Enum):
    """Spark 作业提交后端"""
    LOCAL = "local"           # 本地 PySpark（开发/测试）
    LIVY = "livy"             # Apache Livy REST API
    DATAPROC = "dataproc"     # Google Cloud Dataproc
    EMR = "emr"               # AWS EMR
    DATABRICKS = "databricks" # Databricks Jobs API


@dataclass
class SparkJobRecord:
    job_id: str
    job_type: str
    params: dict
    status: str = "submitted"           # submitted → running → completed / failed / cancelled
    progress: float = 0.0
    result: dict | None = None
    error: str | None = None
    submitted_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    spark_app_id: str | None = None     # Spark Application ID
    # ADK Long-Running 回调所需
    session_id: str | None = None
    user_id: str | None = None
    function_call_id: str | None = None
    function_call_name: str | None = None


class SparkGateway:
    """
    Spark 作业提交网关 — 屏蔽具体部署方式。

    支持多种后端（Livy / Dataproc / EMR / Databricks / 本地 PySpark），
    统一提供 submit / get_status / cancel 接口。
    """

    def __init__(self, backend: SparkBackend = SparkBackend.LOCAL, config: dict | None = None):
        self.backend = backend
        self.config = config or {}
        self._jobs: dict[str, SparkJobRecord] = {}

    async def submit(self, job_type: str, params: dict, **context) -> str:
        """提交 Spark 作业，返回 job_id"""
        job_id = f"spark-{uuid4().hex[:12]}"
        record = SparkJobRecord(
            job_id=job_id,
            job_type=job_type,
            params=params,
            session_id=context.get("session_id"),
            user_id=context.get("user_id"),
            function_call_id=context.get("function_call_id"),
            function_call_name=context.get("function_call_name"),
        )
        self._jobs[job_id] = record

        # 持久化到 PostgreSQL
        await self._persist_job(record)

        # 根据后端分发
        if self.backend == SparkBackend.LOCAL:
            asyncio.create_task(self._run_local(record))
        elif self.backend == SparkBackend.LIVY:
            await self._submit_via_livy(record)
        elif self.backend == SparkBackend.DATAPROC:
            await self._submit_via_dataproc(record)
        elif self.backend == SparkBackend.EMR:
            await self._submit_via_emr(record)
        elif self.backend == SparkBackend.DATABRICKS:
            await self._submit_via_databricks(record)

        return job_id

    async def get_status(self, job_id: str) -> dict:
        """查询作业状态"""
        record = self._jobs.get(job_id)
        if not record:
            record = await self._load_job(job_id)
        if not record:
            return {"error": f"作业 {job_id} 不存在"}

        # 如果是外部后端，可能需要轮询更新
        if self.backend != SparkBackend.LOCAL and record.status == "running":
            await self._poll_external_status(record)

        return {
            "job_id": record.job_id,
            "status": record.status,
            "progress": record.progress,
            "result": record.result,
            "error": record.error,
            "submitted_at": record.submitted_at.isoformat(),
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        }

    async def cancel(self, job_id: str) -> dict:
        """取消作业"""
        record = self._jobs.get(job_id)
        if not record:
            return {"error": f"作业 {job_id} 不存在"}
        if record.status in ("completed", "failed", "cancelled"):
            return {"error": f"作业已处于终态: {record.status}"}

        record.status = "cancelled"
        record.completed_at = datetime.utcnow()
        await self._persist_job(record)
        return {"job_id": job_id, "status": "cancelled"}

    # ──────────── 后端实现 ──────────────

    async def _run_local(self, record: SparkJobRecord):
        """本地 PySpark 执行（开发/测试模式）"""
        try:
            record.status = "running"
            record.started_at = datetime.utcnow()
            await self._persist_job(record)

            # 根据 job_type 分派到对应的 PySpark 脚本
            from .spark_jobs import execute_local_job
            result = await execute_local_job(record.job_type, record.params)

            record.status = "completed"
            record.result = result
            record.progress = 1.0
            record.completed_at = datetime.utcnow()
            await self._persist_job(record)

            # 触发 ADK 回调
            await self._notify_agent_completion(record)

        except Exception as e:
            record.status = "failed"
            record.error = str(e)
            record.completed_at = datetime.utcnow()
            await self._persist_job(record)

    async def _submit_via_livy(self, record: SparkJobRecord):
        """通过 Apache Livy REST API 提交"""
        import httpx
        livy_url = self.config.get("livy_url", "http://localhost:8998")
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{livy_url}/batches", json={
                "file": self.config.get("jar_path", "spark-jobs.jar"),
                "className": f"com.gisagent.jobs.{record.job_type}",
                "args": [json.dumps(record.params)],
            })
            data = resp.json()
            record.spark_app_id = str(data.get("id"))
            record.status = "running"
            record.started_at = datetime.utcnow()
            await self._persist_job(record)

    async def _submit_via_dataproc(self, record: SparkJobRecord):
        """通过 Google Cloud Dataproc API 提交"""
        # google-cloud-dataproc SDK
        pass

    async def _submit_via_emr(self, record: SparkJobRecord):
        """通过 AWS EMR API 提交"""
        pass

    async def _submit_via_databricks(self, record: SparkJobRecord):
        """通过 Databricks Jobs API 提交"""
        pass

    # ──────────── 回调机制 ──────────────

    async def _notify_agent_completion(self, record: SparkJobRecord):
        """
        作业完成后回注结果到 ADK Agent Session。

        使用 ADK 官方 Long-Running FunctionResponse 模式:
        构造与原始 FunctionCall 相同 id/name 的 FunctionResponse，
        以 role="user" 发回 Agent。
        """
        if not record.function_call_id:
            return  # 没有关联的 Agent 调用

        from google.genai import types
        from .agent import get_runner

        updated_response = types.Part(
            function_response=types.FunctionResponse(
                id=record.function_call_id,
                name=record.function_call_name,
                response={
                    "status": record.status,
                    "result": record.result,
                    "duration_seconds": (
                        (record.completed_at - record.started_at).total_seconds()
                        if record.completed_at and record.started_at
                        else None
                    ),
                },
            )
        )

        runner = get_runner()
        async for event in runner.run_async(
            session_id=record.session_id,
            user_id=record.user_id,
            new_message=types.Content(parts=[updated_response], role="user"),
        ):
            # Agent 恢复执行，处理后续逻辑
            pass

    # ──────────── 持久化 ──────────────

    async def _persist_job(self, record: SparkJobRecord):
        """持久化作业记录到 PostgreSQL"""
        engine = get_engine()
        if not engine:
            return
        # INSERT ... ON CONFLICT (job_id) DO UPDATE
        pass

    async def _load_job(self, job_id: str) -> SparkJobRecord | None:
        """从数据库加载作业记录"""
        pass


# ──────────── 单例 ──────────────

_gateway: SparkGateway | None = None

def get_spark_gateway() -> SparkGateway:
    global _gateway
    if _gateway is None:
        import os
        backend = SparkBackend(os.getenv("SPARK_BACKEND", "local"))
        _gateway = SparkGateway(backend=backend)
    return _gateway
```

### 4.3 作业完成回调端点

在 `frontend_api.py` 中新增:

```python
@app.post("/api/jobs/callback")
async def job_callback(request: Request):
    """
    外部计算引擎（Spark / Airflow）完成作业后的回调端点。

    请求体:
    {
        "job_id": "spark-xxxxxxxxxxxx",
        "status": "completed",
        "result": { ... }
    }
    """
    body = await request.json()
    job_id = body["job_id"]

    gateway = get_spark_gateway()
    record = await gateway._load_job(job_id)
    if not record:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    # 更新作业状态
    record.status = body.get("status", "completed")
    record.result = body.get("result")
    record.completed_at = datetime.utcnow()
    await gateway._persist_job(record)

    # 回注结果到 ADK Agent Session
    await gateway._notify_agent_completion(record)

    # 推送通知到前端
    await push_notification_to_user(record.user_id, {
        "type": "job_completed",
        "job_id": job_id,
        "status": record.status,
        "message": f"Spark 作业 {job_id} 已完成",
    })

    return JSONResponse({"ok": True})


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str, request: Request):
    """查询 Spark 作业状态"""
    gateway = get_spark_gateway()
    return JSONResponse(await gateway.get_status(job_id))


@app.get("/api/jobs")
async def list_jobs(request: Request):
    """列出当前用户的所有 Spark 作业"""
    user_id = get_current_user_id()
    # 从 DB 查询该用户的作业列表
    pass
```

### 4.4 Agent Prompt 增强

在 `prompts/data_agent.yaml` 中添加数据规模感知指令:

```yaml
# 分布式计算路由指引
distributed_computing_guidance: |
  ## 执行引擎选择规则

  你可以根据数据规模选择不同的执行方式:

  - **小数据量 (< 100 MB)**: 直接使用本地工具 (load_spatial_data, spatial_join, buffer_analysis 等)
  - **中等数据量 (100 MB - 1 GB)**: 使用本地工具，但提醒用户处理时间可能较长
  - **大数据量 (> 1 GB)**: 必须使用 Spark 分布式工具:
    - `submit_spatial_join`: 大规模空间连接
    - `submit_raster_analysis`: 大规模栅格分析
    - `submit_feature_engineering`: 分布式特征工程

  ## 长任务处理流程

  当使用 submit_* 系列工具时:
  1. 工具会返回 `{status: "submitted", job_id: "xxx"}`
  2. 告知用户作业已提交，提供作业 ID
  3. 说明预计耗时和如何查询进度
  4. 作业完成后系统会自动通知你结果
  5. 收到结果后，继续执行后续的分析和可视化步骤

  ## 数据规模判断方法

  - 查看 data_catalog 中的表/文件大小元数据
  - 用户上传文件时检查文件大小
  - 如果用户说 "全国" / "全省" / "全球" 等大范围描述，倾向使用分布式工具
```

---

## 5. Data Lake 架构集成

### 5.1 推荐技术栈

| 层 | 组件 | 作用 |
|----|------|------|
| **表格式** | Apache Iceberg | ACID 事务、Schema 演进、时间旅行、分区演进 |
| **空间引擎** | Apache Sedona on Spark | Spark 上的 ST_* 空间函数 (等价 PostGIS) |
| **矢量格式** | GeoParquet | 列式存储，谓词下推，空间 bbox 过滤 |
| **栅格格式** | Cloud-Optimized GeoTIFF (COG) | 范围请求，金字塔瓦片，HTTP Range 读取 |
| **存储** | S3 / GCS / Huawei OBS | 对象存储，无限扩展 |
| **目录** | Iceberg REST Catalog | 统一元数据管理，对接 `data_catalog.py` |
| **空间索引** | Z-order / Geohash 分区 | 空间查询裁剪，减少数据扫描量 |

### 5.2 与 data_catalog.py 的统一

```python
# data_catalog.py 扩展 — 统一管理本地文件和 Lakehouse 表
class UnifiedCatalog:
    """
    统一数据目录 — 同时管理:
    - 本地文件 (Shapefile / GeoJSON / CSV)
    - PostGIS 表
    - Iceberg Lakehouse 表
    - Cloud 对象 (S3/GCS GeoParquet / COG)
    """

    async def register_source(
        self,
        name: str,
        source_type: str,       # local / postgis / iceberg / s3_parquet / cog
        location: str,
        schema: dict | None = None,
    ):
        if source_type == "iceberg":
            # 从 Iceberg REST Catalog 拉取 schema + 统计信息
            meta = await self._iceberg_client.load_table_metadata(location)
            schema = meta["schema"]
            size_bytes = meta["total_data_files_size_in_bytes"]
        elif source_type == "s3_parquet":
            # 从 Parquet 元数据推断 schema
            schema = await self._read_parquet_schema(location)
            size_bytes = await self._get_object_size(location)
        elif source_type == "local":
            schema = self._infer_local_schema(location)
            size_bytes = os.path.getsize(location)
        else:
            size_bytes = 0

        await self._persist(name, source_type, location, schema, size_bytes)

    async def get_table_size_mb(self, name: str) -> float:
        """估算数据量 — 用于执行引擎路由"""
        record = await self._get(name)
        return record.get("size_bytes", 0) / (1024 * 1024)

    async def recommend_execution_tier(self, name: str) -> str:
        """基于数据规模推荐执行层级"""
        size_mb = await self.get_table_size_mb(name)
        if size_mb < 100:
            return "local"
        elif size_mb < 1000:
            return "queued"
        else:
            return "distributed"
```

### 5.3 空间分区策略

```
大表 (> 1GB) 写入 Iceberg 时:
  ├─ 矢量数据: Geohash 前缀分区 (geohash_3 / geohash_4)
  │   → 相邻空间对象落入同一分区文件
  │   → 空间查询时只扫描相关分区
  │
  ├─ 栅格数据: Tile Grid 分区 (zoom_level / tile_x / tile_y)
  │   → 对齐 Web 墨卡托瓦片体系
  │   → 支持按空间范围高效裁剪
  │
  └─ 时空数据: 复合分区 (year / month / geohash_3)
      → 时间 + 空间双维度裁剪
      → 适合变化检测、时序分析
```

---

## 6. 长周期任务的全链路处理

### 6.1 任务生命周期

```
用户请求 "分析全国土地利用变化"
  │
  ▼
┌─────────────────────────────────────┐
│  1. 意图识别 (intent_router.py)      │
│     → Optimization Pipeline          │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  2. Agent 评估数据规模               │
│     → data_catalog.get_table_size()  │
│     → 判定为 L3 分布式               │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  3. 调用 submit_spatial_join()       │
│     → 立即返回 {pending, job_id}     │
│     → Agent 通知用户: "已提交"       │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  4. SparkGateway 提交到 Spark 集群   │
│     → Sedona 执行空间连接            │
│     → 结果写入 Iceberg 表            │
│     → 耗时 15 分钟                   │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  5. 作业完成回调                     │
│     → POST /api/jobs/callback        │
│     → 构造 FunctionResponse          │
│     → 回注到 ADK Session             │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  6. Agent 恢复执行                   │
│     → 读取 Spark 输出结果            │
│     → 生成可视化 + 分析报告          │
│     → 推送最终结果到用户              │
└─────────────────────────────────────┘
```

### 6.2 前端任务管理 UI

DataPanel 新增 "分布式作业" 标签页:

```
┌────────────────────────────────────────────────────────┐
│  分布式作业管理                                          │
├────────────────────────────────────────────────────────┤
│  作业 ID         │ 类型        │ 状态    │ 耗时    │ 操作 │
│  spark-a1b2c3d4  │ 空间连接    │ ✅ 完成 │ 14m32s │ 查看 │
│  spark-e5f6g7h8  │ 栅格分析    │ 🔄 运行 │ 3m15s  │ 取消 │
│  spark-i9j0k1l2  │ 特征工程    │ ⏳ 排队 │ —      │ 取消 │
├────────────────────────────────────────────────────────┤
│  集群状态: 3/5 节点活跃 │ 当前负载: 62%                 │
└────────────────────────────────────────────────────────┘
```

### 6.3 与现有 task_queue.py 的整合

```python
# task_queue.py 扩展
class TaskQueue:
    """扩展任务队列 — 支持三层执行"""

    async def submit(self, pipeline_name, params, user_id, **kwargs):
        # 评估数据规模
        tier = await self._evaluate_tier(params)

        if tier == "local":
            # L1: 直接在当前进程执行
            return await self._execute_local(pipeline_name, params, user_id)

        elif tier == "queued":
            # L2: 加入 asyncio 优先级队列
            return await self._enqueue(pipeline_name, params, user_id)

        elif tier == "distributed":
            # L3: 提交到 SparkGateway
            gateway = get_spark_gateway()
            job_id = await gateway.submit(
                job_type=pipeline_name,
                params=params,
                user_id=user_id,
                session_id=kwargs.get("session_id"),
                function_call_id=kwargs.get("function_call_id"),
                function_call_name=kwargs.get("function_call_name"),
            )
            return {"tier": "distributed", "job_id": job_id}
```

---

## 7. 数据库 Schema 扩展

```sql
-- 新增 Spark 作业表
CREATE TABLE IF NOT EXISTS spark_jobs (
    job_id          TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    session_id      TEXT,
    job_type        TEXT NOT NULL,          -- spatial_join / raster_analysis / feature_engineering
    params          JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'submitted',  -- submitted/running/completed/failed/cancelled
    progress        REAL DEFAULT 0.0,
    result          JSONB,
    error           TEXT,
    spark_app_id    TEXT,                   -- Spark Application ID
    function_call_id   TEXT,               -- ADK FunctionCall ID (for Long-Running response)
    function_call_name TEXT,               -- ADK FunctionCall name
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_spark_jobs_user ON spark_jobs(user_id);
CREATE INDEX idx_spark_jobs_status ON spark_jobs(status);

-- 新增 Data Lake 源注册表（扩展现有 data_catalog）
ALTER TABLE data_catalog ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'local';
ALTER TABLE data_catalog ADD COLUMN IF NOT EXISTS size_bytes  BIGINT DEFAULT 0;
ALTER TABLE data_catalog ADD COLUMN IF NOT EXISTS partition_spec JSONB;
ALTER TABLE data_catalog ADD COLUMN IF NOT EXISTS table_format  TEXT;  -- iceberg / delta / hudi
```

---

## 8. 技术选型对比

### 8.1 分布式计算引擎

| 引擎 | 空间支持 | 生态成熟度 | 部署复杂度 | 推荐场景 |
|------|----------|-----------|-----------|---------|
| **Spark + Sedona** | ★★★★★ (原生 ST_*) | ★★★★★ | ★★★☆☆ | **首选**: 大规模矢量/栅格分析 |
| Dask-GeoPandas | ★★★★☆ (兼容 GeoPandas) | ★★★☆☆ | ★★★★★ | 中等规模，API 迁移成本最低 |
| Ray | ★★☆☆☆ (需自行封装) | ★★★★☆ | ★★★★☆ | GPU 加速场景 (DRL 训练) |
| Flink | ★★☆☆☆ | ★★★★★ | ★★☆☆☆ | 流式地理数据处理 |

**推荐**: Spark + Apache Sedona 作为主力，Dask-GeoPandas 作为中等规模的轻量替代。

### 8.2 作业编排引擎

| 引擎 | 特点 | 适合场景 |
|------|------|---------|
| **Celery + Redis** | 轻量、Python 原生 | 简单的异步任务队列 |
| **Apache Airflow** | DAG 编排、调度、监控 | 复杂的 ETL / 分析流水线 |
| **Temporal** | 持久化工作流、自动重试 | 长周期、需要可靠恢复的任务 |
| Cloud Composer | 托管 Airflow | GCP 环境 |
| Step Functions | 状态机 | AWS 环境 |

**推荐**: 初期用 Celery（与现有 Python 栈一致），中期迁移到 Temporal（持久化工作流更适合长任务场景）。

### 8.3 Data Lake 表格式

| 格式 | 特点 | 空间优化 |
|------|------|---------|
| **Apache Iceberg** | ACID、Schema 演进、分区演进、时间旅行 | Z-order 排序 + GeoParquet |
| Delta Lake | ACID、Databricks 深度集成 | Z-order 排序 |
| Apache Hudi | 增量处理、CDC | 较少空间优化 |

**推荐**: Apache Iceberg — 开放生态、分区演进能力最适合地理数据。

---

## 9. 演进路线

### Phase 1: 基础设施 (2-4 周)

```
├─ 实现 SparkGateway 抽象层（先支持 local 模式 = 本地 PySpark）
├─ 实现 SparkToolset (submit_spatial_join, submit_raster_analysis, check_job_status)
├─ frontend_api.py 新增 /api/jobs/* 端点 (callback, status, list)
├─ 新建 spark_jobs 数据库表
├─ Agent prompt 增加数据规模感知指令
└─ 单元测试 (mock Spark 提交)
```

### Phase 2: Data Lakehouse (4-6 周)

```
├─ 引入 Apache Iceberg 作为 Data Lake 表格式
├─ data_catalog.py 对接 Iceberg REST Catalog
├─ 实现 GeoParquet 读写支持
├─ 空间分区策略 (Geohash / Z-order)
├─ UnifiedCatalog: 自动路由本地 vs Lakehouse 数据源
└─ DataPanel 新增 "Data Lake 浏览器" 标签页
```

### Phase 3: 分布式执行 (4-6 周)

```
├─ SparkGateway 对接真实 Spark 集群 (Livy / Dataproc)
├─ Apache Sedona 空间连接、栅格分析 PySpark 脚本
├─ 引入 Celery 或 Temporal 作为作业编排层
├─ 实现回调链路: Spark 完成 → Webhook → FunctionResponse → Agent 恢复
├─ 前端 "分布式作业管理" 标签页
└─ 集成测试 (端到端: 用户请求 → Agent → Spark → 回调 → 报告)
```

### Phase 4: 生产就绪 (2-4 周)

```
├─ 作业重试 + 超时机制
├─ Spark 集群自动扩缩容 (Dataproc / EMR)
├─ 作业成本估算 (提交前告知用户预估费用)
├─ 监控: Prometheus 指标 + Grafana 仪表盘
├─ A2A 协议跨节点 Agent 协作（分布式 Agent 集群）
└─ 流式处理: Spark Structured Streaming 实时地理数据管道
```

---

## 10. 总结

| 维度 | 当前 | 目标 |
|------|------|------|
| 计算模型 | 单机 asyncio | 单机 + Spark 分布式 |
| 数据规模 | < 1 GB (GeoPandas) | TB 级 (Sedona on Spark) |
| 存储架构 | PostGIS + 本地文件 | PostGIS + Iceberg Data Lake |
| 长任务处理 | task_queue Semaphore(3) | ADK Long-Running FunctionResponse + 回调 |
| 元数据管理 | data_catalog (本地) | UnifiedCatalog (本地 + Iceberg + Cloud) |

**核心技术方案**: ADK 的 **Long-Running FunctionResponse** 模式是连接智能体与分布式计算的桥梁 — 工具立即返回 `{status: "pending", job_id}`，外部 Spark 作业完成后通过相同的 `function_call.id` 回注结果，Agent 无缝恢复执行。这个模式完全在应用层实现，不需要修改 ADK 框架本身。
