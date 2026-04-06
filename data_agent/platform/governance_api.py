"""
底座调用层 — 治理执行 API 封装

封装时空数据治理平台的质检、汇聚、开发等治理操作 REST API。
Phase 1 提供 mock 实现，待底座环境就绪后切换为真实调用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class GovernanceTaskResult:
    """治理任务执行结果"""

    task_id: str
    status: str  # success / failed / partial
    total_records: int = 0
    passed_records: int = 0
    failed_records: int = 0
    error_message: str = ""
    details: dict | None = None


class GovernanceAPI(Protocol):
    """治理执行 API 接口定义"""

    async def import_data_model(self, model_config: dict) -> str:
        """导入数据模型到治理平台，返回 model_id"""
        ...

    async def create_quality_check(
        self, dataset_id: str, rule_set: str, parameters: dict | None = None
    ) -> str:
        """创建质检任务，返回 task_id"""
        ...

    async def get_task_result(self, task_id: str) -> GovernanceTaskResult:
        """获取任务执行结果"""
        ...

    async def execute_aggregation(
        self, source_id: str, target_model_id: str
    ) -> GovernanceTaskResult:
        """执行数据汇聚"""
        ...

    async def register_asset(self, dataset_id: str, metadata: dict) -> str:
        """登记数据资产，返回 asset_id"""
        ...


class GovernanceAPIMock:
    """Mock 实现"""

    _task_counter: int = 0

    async def import_data_model(self, model_config: dict) -> str:
        logger.info("[MOCK] import_data_model: %s", model_config.get("name", "unknown"))
        return "mock-model-001"

    async def create_quality_check(
        self, dataset_id: str, rule_set: str, parameters: dict | None = None
    ) -> str:
        GovernanceAPIMock._task_counter += 1
        task_id = f"mock-qc-{GovernanceAPIMock._task_counter:04d}"
        logger.info("[MOCK] create_quality_check: %s → %s", dataset_id, task_id)
        return task_id

    async def get_task_result(self, task_id: str) -> GovernanceTaskResult:
        logger.info("[MOCK] get_task_result: %s", task_id)
        return GovernanceTaskResult(
            task_id=task_id,
            status="success",
            total_records=1000,
            passed_records=950,
            failed_records=50,
        )

    async def execute_aggregation(
        self, source_id: str, target_model_id: str
    ) -> GovernanceTaskResult:
        GovernanceAPIMock._task_counter += 1
        task_id = f"mock-agg-{GovernanceAPIMock._task_counter:04d}"
        logger.info("[MOCK] execute_aggregation: %s → %s", source_id, task_id)
        return GovernanceTaskResult(task_id=task_id, status="success", total_records=1000, passed_records=1000, failed_records=0)

    async def register_asset(self, dataset_id: str, metadata: dict) -> str:
        logger.info("[MOCK] register_asset: %s", dataset_id)
        return f"mock-asset-{dataset_id}"


class GovernanceAPIReal:
    """真实实现 — 调用时空数据治理平台的 REST API"""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def import_data_model(self, model_config: dict) -> str:
        raise NotImplementedError("待底座环境就绪后实现")

    async def create_quality_check(
        self, dataset_id: str, rule_set: str, parameters: dict | None = None
    ) -> str:
        raise NotImplementedError("待底座环境就绪后实现")

    async def get_task_result(self, task_id: str) -> GovernanceTaskResult:
        raise NotImplementedError("待底座环境就绪后实现")

    async def execute_aggregation(
        self, source_id: str, target_model_id: str
    ) -> GovernanceTaskResult:
        raise NotImplementedError("待底座环境就绪后实现")

    async def register_asset(self, dataset_id: str, metadata: dict) -> str:
        raise NotImplementedError("待底座环境就绪后实现")
