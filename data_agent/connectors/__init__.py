"""
Pluggable connector architecture for virtual data sources (v14.5).

Each connector implements ``BaseConnector`` and self-registers with
``ConnectorRegistry`` at import time.  The registry replaces the former
if-elif dispatch in ``virtual_sources.py``.
"""

import abc
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = 30


def build_auth_headers(auth_config: dict) -> dict:
    """Build HTTP headers from an auth_config dict."""
    if not auth_config:
        return {}
    atype = auth_config.get("type", "none")
    if atype == "bearer":
        return {"Authorization": f"Bearer {auth_config.get('token', '')}"}
    if atype == "basic":
        import base64 as b64
        cred = b64.b64encode(
            f"{auth_config.get('username', '')}:{auth_config.get('password', '')}".encode()
        ).decode()
        return {"Authorization": f"Basic {cred}"}
    if atype == "apikey":
        header = auth_config.get("header", "X-API-Key")
        return {header: auth_config.get("key", "")}
    return {}


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseConnector(abc.ABC):
    """Abstract base class for all virtual data-source connectors."""

    SOURCE_TYPE: str = ""

    @abc.abstractmethod
    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: Optional[list[float]] = None,
        filter_expr: Optional[str] = None,
        limit: int = 1000,
        extra_params: Optional[dict] = None,
        target_crs: Optional[str] = None,
    ) -> Any:
        """Execute a data query against the remote service."""
        ...

    @abc.abstractmethod
    async def health_check(
        self,
        endpoint_url: str,
        auth_config: dict,
    ) -> dict:
        """Test connectivity.  Return ``{"health": "healthy"|"timeout"|"error", "message": ...}``."""
        ...

    @abc.abstractmethod
    async def get_capabilities(
        self,
        endpoint_url: str,
        auth_config: dict,
    ) -> dict:
        """Discover available layers / collections / feature types."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ConnectorRegistry:
    """Singleton registry mapping source_type → BaseConnector instance."""

    _connectors: dict[str, BaseConnector] = {}

    @classmethod
    def register(cls, connector: BaseConnector) -> None:
        cls._connectors[connector.SOURCE_TYPE] = connector
        logger.debug("Registered connector: %s", connector.SOURCE_TYPE)

    @classmethod
    def get(cls, source_type: str) -> Optional[BaseConnector]:
        return cls._connectors.get(source_type)

    @classmethod
    def all_types(cls) -> set[str]:
        return set(cls._connectors.keys())

    @classmethod
    def unregister(cls, source_type: str) -> None:
        cls._connectors.pop(source_type, None)


# ---------------------------------------------------------------------------
# Auto-import all built-in connectors to trigger self-registration
# ---------------------------------------------------------------------------

from . import wfs, stac, ogc_api, custom_api, wms, arcgis_rest, database, object_storage, reference_data  # noqa: E402,F401
