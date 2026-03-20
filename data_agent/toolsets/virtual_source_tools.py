"""VirtualSourceToolset — ADK tools for querying remote geospatial data services."""
import json
import traceback
from typing import Optional

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..user_context import current_user_id


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def list_virtual_sources_tool() -> str:
    """列出当前用户可见的所有虚拟数据源（WFS/STAC/OGC API/自定义API），包括共享源。

    Returns:
        JSON格式的虚拟数据源列表（名称、类型、端点URL、健康状态）。
    """
    try:
        from ..virtual_sources import list_virtual_sources
        username = current_user_id.get("")
        sources = list_virtual_sources(username, include_shared=True)
        if not sources:
            return json.dumps({"status": "ok", "message": "暂无已注册的虚拟数据源", "sources": []},
                              ensure_ascii=False)
        summary = [{
            "id": s["id"], "name": s["source_name"], "type": s["source_type"],
            "url": s["endpoint_url"], "enabled": s["enabled"],
            "health": s["health_status"], "owner": s["owner_username"],
            "shared": s["is_shared"],
        } for s in sources]
        return json.dumps({"status": "ok", "count": len(summary), "sources": summary},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


async def query_virtual_source_tool(
    source_name: str,
    bbox: str = "",
    filter_expr: str = "",
    limit: str = "1000",
) -> str:
    """查询指定虚拟数据源，返回远程数据摘要。支持WFS/STAC/OGC API/自定义API。

    Args:
        source_name: 虚拟数据源名称。
        bbox: 空间范围过滤（逗号分隔：minx,miny,maxx,maxy），可选。
        filter_expr: CQL过滤条件（WFS）或时间范围（STAC），可选。
        limit: 最大返回记录数，默认1000。

    Returns:
        JSON格式的查询结果摘要（记录数、列名、前5条预览）。
    """
    try:
        from ..virtual_sources import (
            list_virtual_sources, get_virtual_source,
            query_virtual_source, apply_schema_mapping,
        )
        import geopandas as gpd

        username = current_user_id.get("")
        # Find source by name
        sources = list_virtual_sources(username)
        match = [s for s in sources if s["source_name"] == source_name]
        if not match:
            return json.dumps({"status": "error", "message": f"未找到数据源 '{source_name}'"},
                              ensure_ascii=False)

        source = get_virtual_source(match[0]["id"], username)
        if not source:
            return json.dumps({"status": "error", "message": "无法读取数据源详情"},
                              ensure_ascii=False)
        if not source.get("enabled", True):
            return json.dumps({"status": "error", "message": f"数据源 '{source_name}' 已禁用"},
                              ensure_ascii=False)

        bbox_list = [float(x) for x in bbox.split(",") if x.strip()] if bbox else None
        max_features = int(limit) if limit else 1000

        result = await query_virtual_source(
            source, bbox=bbox_list, filter_expr=filter_expr or None, limit=max_features,
        )

        # Format response based on result type
        if isinstance(result, gpd.GeoDataFrame):
            result = apply_schema_mapping(result, source.get("schema_mapping", {}))
            preview = result.head(5).drop(columns=["geometry"], errors="ignore")
            return json.dumps({
                "status": "ok",
                "source": source_name,
                "type": source["source_type"],
                "record_count": len(result),
                "columns": list(result.columns),
                "crs": str(result.crs) if result.crs else None,
                "preview": preview.to_dict(orient="records"),
            }, ensure_ascii=False, default=str)
        elif isinstance(result, list):
            return json.dumps({
                "status": "ok",
                "source": source_name,
                "type": source["source_type"],
                "item_count": len(result),
                "preview": result[:5],
            }, ensure_ascii=False, default=str)
        else:
            return json.dumps({
                "status": "ok",
                "source": source_name,
                "type": source["source_type"],
                "result": result,
            }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"status": "error", "message": str(e),
                           "trace": traceback.format_exc()[:500]}, ensure_ascii=False)


async def preview_virtual_source_tool(
    source_name: str,
    limit: str = "5",
) -> str:
    """预览虚拟数据源的前N条记录，快速了解数据结构和内容。

    Args:
        source_name: 虚拟数据源名称。
        limit: 预览记录数，默认5。

    Returns:
        JSON格式的数据预览。
    """
    return await query_virtual_source_tool(source_name, limit=limit)


def register_virtual_source_tool(
    source_name: str,
    source_type: str,
    endpoint_url: str,
    auth_type: str = "none",
    auth_token: str = "",
    query_config: str = "{}",
    default_crs: str = "EPSG:4326",
    is_shared: str = "false",
) -> str:
    """注册一个新的虚拟数据源（WFS/STAC/OGC API/自定义API）。

    Args:
        source_name: 数据源名称（唯一标识）。
        source_type: 数据源类型（wfs/stac/ogc_api/custom_api）。
        endpoint_url: 服务端点URL。
        auth_type: 认证类型（none/bearer/basic/apikey），默认none。
        auth_token: 认证凭据（bearer token、密码或API key）。
        query_config: JSON格式的查询配置（如WFS的feature_type、STAC的collection_id）。
        default_crs: 默认坐标系，默认EPSG:4326。
        is_shared: 是否共享给其他用户（true/false），默认false。

    Returns:
        JSON格式的创建结果。
    """
    try:
        from ..virtual_sources import create_virtual_source

        username = current_user_id.get("")
        if not username:
            return json.dumps({"status": "error", "message": "未登录"}, ensure_ascii=False)

        # Build auth_config
        auth_config = {}
        if auth_type and auth_type != "none":
            auth_config["type"] = auth_type
            if auth_type == "bearer":
                auth_config["token"] = auth_token
            elif auth_type == "apikey":
                auth_config["key"] = auth_token
                auth_config["header"] = "X-API-Key"

        qcfg = json.loads(query_config) if query_config else {}
        shared = is_shared.lower() == "true" if isinstance(is_shared, str) else bool(is_shared)

        result = create_virtual_source(
            source_name=source_name,
            source_type=source_type,
            endpoint_url=endpoint_url,
            owner_username=username,
            auth_config=auth_config,
            query_config=qcfg,
            default_crs=default_crs,
            is_shared=shared,
        )
        return json.dumps(result, ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "message": "query_config 不是合法的JSON"},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


async def check_virtual_source_health_tool(source_name: str) -> str:
    """测试虚拟数据源连接是否正常，检查端点可达性和认证有效性。

    Args:
        source_name: 虚拟数据源名称。

    Returns:
        JSON格式的健康检查结果（healthy/timeout/error）。
    """
    try:
        from ..virtual_sources import list_virtual_sources, check_source_health

        username = current_user_id.get("")
        sources = list_virtual_sources(username)
        match = [s for s in sources if s["source_name"] == source_name]
        if not match:
            return json.dumps({"status": "error", "message": f"未找到数据源 '{source_name}'"},
                              ensure_ascii=False)

        result = await check_source_health(match[0]["id"], username)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_TOOLS = [
    FunctionTool(list_virtual_sources_tool),
    FunctionTool(query_virtual_source_tool),
    FunctionTool(preview_virtual_source_tool),
    FunctionTool(register_virtual_source_tool),
    FunctionTool(check_virtual_source_health_tool),
]


class VirtualSourceToolset(BaseToolset):
    """Provides tools for registering and querying remote geospatial data services."""

    def __init__(self, *, tool_filter=None):
        super().__init__(tool_filter=tool_filter)

    async def get_tools(self, readonly_context=None) -> list:
        if self.tool_filter is None:
            return list(_TOOLS)
        return [t for t in _TOOLS if self._is_tool_selected(t, readonly_context)]
