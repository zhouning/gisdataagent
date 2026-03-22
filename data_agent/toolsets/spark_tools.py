"""SparkToolset — distributed compute tools for large dataset processing (v15.0)."""

import json
import logging

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

logger = logging.getLogger(__name__)


async def spark_submit_task(
    file_path: str,
    task_type: str = "describe",
    params: str = "{}",
) -> str:
    """提交分布式计算任务。自动根据数据大小选择执行层级 (L1 本地 / L2 队列 / L3 Spark)。

    Args:
        file_path: 数据文件路径。
        task_type: 任务类型 — describe(画像) | filter(过滤) | aggregate(聚合) | spatial_join(空间连接)。
        params: JSON 格式的任务参数（如 '{"column":"area","operator":">","value":1000}'）。

    Returns:
        JSON 格式的任务结果，含执行层级、耗时、结果摘要。
    """
    try:
        from ..spark_gateway import get_spark_gateway
        gateway = get_spark_gateway()
        task_params = json.loads(params) if isinstance(params, str) else params
        task_params["file_path"] = file_path

        job = await gateway.submit(task_type, task_params, file_path=file_path)
        return json.dumps({
            "status": job.status,
            "job_id": job.job_id,
            "tier": job.tier.value,
            "duration": job.duration_seconds,
            "result": job.result if not isinstance(job.result, Exception) else str(job.result),
            "error": job.error,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def spark_check_tier(file_path: str) -> str:
    """检查数据文件的执行层级 (L1 本地 <100MB / L2 队列 <1GB / L3 Spark >1GB)。

    Args:
        file_path: 数据文件路径。

    Returns:
        JSON 格式的层级判断结果。
    """
    try:
        import os
        from ..spark_gateway import determine_tier
        from ..gis_processors import _resolve_path
        resolved = _resolve_path(file_path)
        size = os.path.getsize(resolved) if os.path.exists(resolved) else 0
        tier = determine_tier(data_size_bytes=size)
        return json.dumps({
            "status": "ok",
            "file": file_path,
            "size_mb": round(size / 1024 / 1024, 2),
            "tier": tier.value,
            "description": {
                "instant": "L1 本地执行 (<100MB) — GeoPandas 直接处理",
                "queue": "L2 队列执行 (100MB-1GB) — 后台任务处理",
                "spark": "L3 分布式执行 (>1GB) — Spark 集群处理",
            }.get(tier.value, tier.value),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def spark_list_jobs() -> str:
    """列出最近的分布式计算任务。

    Returns:
        JSON 格式的任务列表（job_id、任务类型、层级、状态、耗时）。
    """
    try:
        from ..spark_gateway import get_spark_gateway
        gateway = get_spark_gateway()
        jobs = gateway.list_jobs()
        return json.dumps({"status": "ok", "jobs": jobs}, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


_ALL_FUNCS = [
    spark_submit_task,
    spark_check_tier,
    spark_list_jobs,
]


class SparkToolset(BaseToolset):
    """Distributed compute tools — auto-routes tasks across L1/L2/L3 tiers."""

    def __init__(self, *, tool_filter=None):
        super().__init__(tool_filter=tool_filter)

    async def get_tools(self, readonly_context=None) -> list:
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
