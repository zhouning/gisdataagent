"""
底座调用层 — 数据资产/数据服务 API 封装
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class AssetInfo:
    """数据资产信息"""

    asset_id: str
    name: str
    asset_code: str = ""
    quality_level: str = ""
    source_dataset_id: str = ""


@dataclass
class ServiceInfo:
    """数据服务信息"""

    service_id: str
    name: str
    service_type: str = ""  # API / WFS / WMS / tile / file
    url: str = ""
    status: str = "draft"


class AssetAPI(Protocol):
    """数据资产/服务 API 接口定义"""

    async def register_asset(self, name: str, dataset_id: str, metadata: dict) -> str:
        ...

    async def publish_service(self, asset_id: str, service_type: str) -> ServiceInfo:
        ...

    async def get_asset(self, asset_id: str) -> AssetInfo:
        ...


class AssetAPIMock:
    """Mock 实现"""

    def __init__(self):
        self._assets: dict[str, AssetInfo] = {}

    async def register_asset(self, name: str, dataset_id: str, metadata: dict) -> str:
        asset_id = f"mock-asset-{len(self._assets) + 1:03d}"
        self._assets[asset_id] = AssetInfo(
            asset_id=asset_id, name=name, source_dataset_id=dataset_id,
        )
        logger.info("[MOCK] register_asset: %s → %s", name, asset_id)
        return asset_id

    async def publish_service(self, asset_id: str, service_type: str) -> ServiceInfo:
        logger.info("[MOCK] publish_service: %s as %s", asset_id, service_type)
        return ServiceInfo(
            service_id=f"mock-svc-{asset_id}",
            name=f"Service for {asset_id}",
            service_type=service_type,
            url=f"http://mock/{asset_id}",
            status="published",
        )

    async def get_asset(self, asset_id: str) -> AssetInfo:
        if asset_id not in self._assets:
            raise KeyError(f"Mock asset not found: {asset_id}")
        return self._assets[asset_id]


class AssetAPIReal:
    """真实实现"""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def register_asset(self, name: str, dataset_id: str, metadata: dict) -> str:
        raise NotImplementedError("待底座环境就绪后实现")

    async def publish_service(self, asset_id: str, service_type: str) -> ServiceInfo:
        raise NotImplementedError("待底座环境就绪后实现")

    async def get_asset(self, asset_id: str) -> AssetInfo:
        raise NotImplementedError("待底座环境就绪后实现")
