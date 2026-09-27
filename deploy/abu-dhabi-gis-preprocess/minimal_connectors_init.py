"""Small connector contract used by the source-data compiler.

The complete application registers many optional connectors.  The compiler
only needs the ArcGIS REST module's base classes, so keeping this contract
small prevents database, cloud, and ML dependencies from entering the image.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

HTTP_TIMEOUT = 30
logger = logging.getLogger(__name__)


def build_auth_headers(auth_config: dict) -> dict:
    if not auth_config:
        return {}
    atype = auth_config.get("type", "none")
    if atype == "bearer":
        return {"Authorization": f"Bearer {auth_config.get('token', '')}"}
    if atype == "basic":
        import base64

        value = base64.b64encode(
            f"{auth_config.get('username', '')}:{auth_config.get('password', '')}".encode()
        ).decode()
        return {"Authorization": f"Basic {value}"}
    if atype == "apikey":
        return {auth_config.get("header", "X-API-Key"): auth_config.get("key", "")}
    return {}


class BaseConnector(abc.ABC):
    SOURCE_TYPE = ""

    @abc.abstractmethod
    async def query(self, endpoint_url: str, auth_config: dict, query_config: dict, **kwargs: Any) -> Any:
        ...

    @abc.abstractmethod
    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        ...

    @abc.abstractmethod
    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        ...


class ConnectorRegistry:
    _connectors: dict[str, BaseConnector] = {}

    @classmethod
    def register(cls, connector: BaseConnector) -> None:
        cls._connectors[connector.SOURCE_TYPE] = connector

    @classmethod
    def get(cls, source_type: str) -> BaseConnector | None:
        return cls._connectors.get(source_type)
