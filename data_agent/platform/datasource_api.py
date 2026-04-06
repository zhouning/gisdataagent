"""
底座调用层 — 数据源管理 API 封装
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class DataSourceInfo:
    """数据源信息"""

    source_id: str
    name: str
    source_type: str  # database / file_directory / service
    connection_info: dict | None = None
    healthy: bool = True


class DataSourceAPI(Protocol):
    """数据源管理 API 接口定义"""

    async def list_sources(self) -> list[DataSourceInfo]:
        ...

    async def register_source(self, name: str, source_type: str, connection_info: dict) -> str:
        ...

    async def test_connection(self, source_id: str) -> bool:
        ...


class DataSourceAPIMock:
    """Mock 实现"""

    def __init__(self):
        self._sources: dict[str, DataSourceInfo] = {}

    async def list_sources(self) -> list[DataSourceInfo]:
        logger.info("[MOCK] list_sources")
        return list(self._sources.values())

    async def register_source(self, name: str, source_type: str, connection_info: dict) -> str:
        source_id = f"mock-src-{len(self._sources) + 1:03d}"
        self._sources[source_id] = DataSourceInfo(
            source_id=source_id, name=name, source_type=source_type,
            connection_info=connection_info, healthy=True,
        )
        logger.info("[MOCK] register_source: %s → %s", name, source_id)
        return source_id

    async def test_connection(self, source_id: str) -> bool:
        logger.info("[MOCK] test_connection: %s → True", source_id)
        return True


class DataSourceAPIReal:
    """真实实现"""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def list_sources(self) -> list[DataSourceInfo]:
        raise NotImplementedError("待底座环境就绪后实现")

    async def register_source(self, name: str, source_type: str, connection_info: dict) -> str:
        raise NotImplementedError("待底座环境就绪后实现")

    async def test_connection(self, source_id: str) -> bool:
        raise NotImplementedError("待底座环境就绪后实现")
