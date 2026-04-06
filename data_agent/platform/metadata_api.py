"""
底座调用层 — 元数据读取 API 封装

封装时空数据治理平台的元数据相关 REST API。
Phase 1 提供 mock 实现，待底座环境就绪后切换为真实调用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class FieldInfo:
    """数据集字段信息"""

    name: str
    chinese_name: str = ""
    data_type: str = ""
    length: int | None = None
    nullable: bool = True
    description: str = ""


@dataclass
class DatasetInfo:
    """数据集基本信息"""

    dataset_id: str
    name: str
    format: str = ""  # Shapefile / GeoJSON / 表格 / 栅格
    crs: str = ""  # 坐标系，如 EPSG:4490
    record_count: int = 0
    geometry_type: str = ""  # Point / LineString / Polygon / None
    fields: list[FieldInfo] = field(default_factory=list)


class MetadataAPI(Protocol):
    """元数据 API 接口定义"""

    async def list_datasets(self, source_id: str) -> list[DatasetInfo]:
        """列出数据源下的所有数据集"""
        ...

    async def get_dataset_info(self, dataset_id: str) -> DatasetInfo:
        """获取单个数据集的详细元数据"""
        ...

    async def get_field_list(self, dataset_id: str) -> list[FieldInfo]:
        """获取数据集的字段列表"""
        ...


class MetadataAPIMock:
    """Mock 实现 — 用于底座环境未就绪时的开发和测试"""

    def __init__(self):
        self._mock_datasets: dict[str, DatasetInfo] = {}

    def register_mock_dataset(self, dataset: DatasetInfo):
        """注册一个 mock 数据集，供测试使用"""
        self._mock_datasets[dataset.dataset_id] = dataset

    async def list_datasets(self, source_id: str) -> list[DatasetInfo]:
        logger.info("[MOCK] list_datasets source_id=%s", source_id)
        return list(self._mock_datasets.values())

    async def get_dataset_info(self, dataset_id: str) -> DatasetInfo:
        logger.info("[MOCK] get_dataset_info dataset_id=%s", dataset_id)
        if dataset_id not in self._mock_datasets:
            raise KeyError(f"Mock dataset not found: {dataset_id}")
        return self._mock_datasets[dataset_id]

    async def get_field_list(self, dataset_id: str) -> list[FieldInfo]:
        logger.info("[MOCK] get_field_list dataset_id=%s", dataset_id)
        ds = await self.get_dataset_info(dataset_id)
        return ds.fields


class MetadataAPIReal:
    """真实实现 — 调用时空数据治理平台的 REST API"""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def list_datasets(self, source_id: str) -> list[DatasetInfo]:
        # TODO: 对接底座 REST API
        raise NotImplementedError("待底座环境就绪后实现")

    async def get_dataset_info(self, dataset_id: str) -> DatasetInfo:
        raise NotImplementedError("待底座环境就绪后实现")

    async def get_field_list(self, dataset_id: str) -> list[FieldInfo]:
        raise NotImplementedError("待底座环境就绪后实现")
