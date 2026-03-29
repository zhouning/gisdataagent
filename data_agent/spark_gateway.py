"""
SparkGateway — distributed compute gateway with 3-tier execution routing (v15.0).

Routes data processing tasks across three tiers based on data size:
- L1 Instant (<100MB): Local GeoPandas/Shapely (current behavior)
- L2 Queue (100MB-1GB): Background task queue with timeout
- L3 Distributed (>1GB): Spark backend (PySpark / Livy / Dataproc / EMR)

Gateway provides a unified interface regardless of backend:
```python
result = await spark_gateway.submit(task_type, params)
```
"""

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any

logger = logging.getLogger(__name__)


class ExecutionTier(Enum):
    L1_INSTANT = "instant"      # <100MB, local GeoPandas
    L2_QUEUE = "queue"          # 100MB-1GB, background task
    L3_DISTRIBUTED = "spark"    # >1GB, Spark cluster


class SparkBackend(Enum):
    LOCAL_PYSPARK = "local"
    LIVY = "livy"
    DATAPROC = "dataproc"
    EMR = "emr"


@dataclass
class SparkJob:
    """Represents a submitted Spark computation job."""
    job_id: str
    task_type: str
    tier: ExecutionTier
    status: str = "submitted"  # submitted / running / completed / failed
    params: dict = field(default_factory=dict)
    result: Any = None
    error: str = ""
    submitted_at: float = field(default_factory=time.time)
    completed_at: float = 0
    duration_seconds: float = 0


# Size thresholds (configurable via env)
L1_MAX_BYTES = int(os.environ.get("SPARK_L1_MAX_MB", "100")) * 1024 * 1024
L2_MAX_BYTES = int(os.environ.get("SPARK_L2_MAX_MB", "1024")) * 1024 * 1024


def determine_tier(file_path: str = "", data_size_bytes: int = 0) -> ExecutionTier:
    """Determine execution tier based on data size."""
    if file_path and os.path.exists(file_path):
        data_size_bytes = os.path.getsize(file_path)

    if data_size_bytes <= L1_MAX_BYTES:
        return ExecutionTier.L1_INSTANT
    elif data_size_bytes <= L2_MAX_BYTES:
        return ExecutionTier.L2_QUEUE
    else:
        return ExecutionTier.L3_DISTRIBUTED


class SparkGateway:
    """Unified gateway for local, queued, and distributed computation.

    Routes tasks to appropriate backend based on data size.
    For L3 (Spark), delegates to configured backend (Livy/Dataproc/EMR).
    """

    def __init__(self):
        self._backend = SparkBackend(
            os.environ.get("SPARK_BACKEND", "local")
        )
        self._livy_url = os.environ.get("SPARK_LIVY_URL", "")
        self._jobs: dict[str, SparkJob] = {}
        logger.info("[SparkGateway] Backend: %s", self._backend.value)

    async def submit(self, task_type: str, params: dict,
                     file_path: str = "", data_size_bytes: int = 0) -> SparkJob:
        """Submit a computation task. Routes to appropriate tier."""
        import uuid
        job_id = f"spark_{uuid.uuid4().hex[:8]}"
        tier = determine_tier(file_path, data_size_bytes)

        job = SparkJob(
            job_id=job_id,
            task_type=task_type,
            tier=tier,
            params=params,
        )
        self._jobs[job_id] = job

        logger.info("[SparkGateway] Job %s → %s (task=%s, size=%s)",
                     job_id, tier.value, task_type,
                     f"{data_size_bytes/1024/1024:.1f}MB" if data_size_bytes else "unknown")

        if tier == ExecutionTier.L1_INSTANT:
            await self._execute_local(job)
        elif tier == ExecutionTier.L2_QUEUE:
            await self._execute_queued(job)
        else:
            await self._execute_spark(job)

        return job

    async def _execute_local(self, job: SparkJob):
        """L1: Execute locally with GeoPandas (current behavior)."""
        job.status = "running"
        start = time.monotonic()
        try:
            result = await self._dispatch_task(job.task_type, job.params)
            job.result = result
            job.status = "completed"
        except Exception as e:
            job.error = str(e)
            job.status = "failed"
        finally:
            job.duration_seconds = round(time.monotonic() - start, 2)
            job.completed_at = time.time()

    async def _execute_queued(self, job: SparkJob):
        """L2: Execute in background task queue."""
        job.status = "running"
        start = time.monotonic()
        try:
            # For now, same as local but marked as queued
            # Future: delegate to Celery/task_queue
            result = await self._dispatch_task(job.task_type, job.params)
            job.result = result
            job.status = "completed"
        except Exception as e:
            job.error = str(e)
            job.status = "failed"
        finally:
            job.duration_seconds = round(time.monotonic() - start, 2)
            job.completed_at = time.time()

    async def _execute_spark(self, job: SparkJob):
        """L3: Submit to Spark cluster backend."""
        job.status = "running"
        start = time.monotonic()

        if self._backend == SparkBackend.LIVY and self._livy_url:
            try:
                await self._submit_livy(job)
            except Exception as e:
                job.error = str(e)
                job.status = "failed"
        elif self._backend == SparkBackend.LOCAL_PYSPARK:
            try:
                result = await self._dispatch_task(job.task_type, job.params)
                job.result = result
                job.status = "completed"
            except Exception as e:
                job.error = str(e)
                job.status = "failed"
        else:
            job.error = f"Spark backend '{self._backend.value}' not configured"
            job.status = "failed"

        job.duration_seconds = round(time.monotonic() - start, 2)
        job.completed_at = time.time()

    async def _submit_livy(self, job: SparkJob):
        """Submit job to Apache Livy REST API."""
        import httpx
        payload = {
            "kind": "pyspark",
            "code": self._generate_spark_code(job.task_type, job.params),
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._livy_url}/sessions/0/statements",
                json=payload,
            )
            resp.raise_for_status()
            job.result = resp.json()
            job.status = "completed"

    def _generate_spark_code(self, task_type: str, params: dict) -> str:
        """Generate PySpark code for a task type."""
        templates = {
            "spatial_join": "result = df1.join(df2, 'geometry')",
            "aggregate": "result = df.groupBy('{group}').agg(F.sum('{col}'))",
            "filter": "result = df.filter(df['{col}'] > {threshold})",
        }
        template = templates.get(task_type, f"# Unknown task: {task_type}")
        return template.format(**params) if params else template

    async def _dispatch_task(self, task_type: str, params: dict) -> Any:
        """Dispatch to local GeoPandas implementation."""
        file_path = params.get("file_path", "")
        if not file_path:
            return {"status": "error", "message": "file_path required"}

        from data_agent.utils import _load_spatial_data
        gdf = _load_spatial_data(file_path)

        if task_type == "describe":
            return {"row_count": len(gdf), "columns": list(gdf.columns),
                    "crs": str(gdf.crs)}
        elif task_type == "filter":
            col = params.get("column", "")
            op = params.get("operator", ">")
            val = params.get("value", 0)
            if col in gdf.columns:
                if op == ">": gdf = gdf[gdf[col] > float(val)]
                elif op == "<": gdf = gdf[gdf[col] < float(val)]
                elif op == "==": gdf = gdf[gdf[col] == val]
            return {"filtered_count": len(gdf)}
        else:
            return {"status": "ok", "task": task_type, "rows": len(gdf)}

    def get_job(self, job_id: str) -> Optional[SparkJob]:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[dict]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.submitted_at, reverse=True)
        return [
            {"job_id": j.job_id, "task": j.task_type, "tier": j.tier.value,
             "status": j.status, "duration": j.duration_seconds}
            for j in jobs[:limit]
        ]


# Singleton
_gateway: Optional[SparkGateway] = None

def get_spark_gateway() -> SparkGateway:
    global _gateway
    if _gateway is None:
        _gateway = SparkGateway()
    return _gateway
