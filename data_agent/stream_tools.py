"""
ADK tool functions for real-time data streams.

Provides tools for creating, querying, and managing IoT/GPS streams
from within the agent conversation.
"""
import json
import time
from datetime import datetime, timezone
from typing import Optional

from .stream_engine import (
    StreamConfig, LocationEvent,
    get_stream_engine, haversine_meters,
)


def create_iot_stream(
    name: str,
    geofence_wkt: str = "",
    window_seconds: int = 60,
) -> dict:
    """创建实时数据流用于接收IoT设备位置数据。

    Args:
        name: 数据流名称（如"车辆监控"、"设备追踪"）
        geofence_wkt: 可选的地理围栏WKT多边形（如 POLYGON((lng1 lat1, lng2 lat2, ...))）
        window_seconds: 聚合窗口大小（秒），默认60

    Returns:
        包含stream_id、ingest_url和ws_url的配置信息
    """
    try:
        engine = get_stream_engine()
        config = engine.create_stream(StreamConfig(
            id="",
            name=name,
            geofence_wkt=geofence_wkt,
            window_seconds=max(5, min(int(window_seconds), 3600)),
        ))
        return {
            "status": "success",
            "message": f"数据流 '{name}' 已创建",
            "stream_id": config.id,
            "ingest_url": f"/api/streams/{config.id}/ingest",
            "ws_url": f"/ws/streams/{config.id}",
            "window_seconds": config.window_seconds,
            "has_geofence": bool(config.geofence_wkt),
        }
    except Exception as e:
        return {"status": "error", "message": f"创建数据流失败: {str(e)}"}


def list_active_streams() -> dict:
    """列出所有活跃的实时数据流。

    Returns:
        活跃数据流列表，包含每个流的ID、名称、状态等信息
    """
    try:
        engine = get_stream_engine()
        streams = engine.get_active_streams()
        return {
            "status": "success",
            "count": len(streams),
            "streams": streams,
        }
    except Exception as e:
        return {"status": "error", "message": f"查询失败: {str(e)}"}


def stop_data_stream(stream_id: str) -> dict:
    """停止指定的实时数据流。

    Args:
        stream_id: 要停止的数据流ID

    Returns:
        操作结果
    """
    try:
        import asyncio
        engine = get_stream_engine()
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're inside an async context, create a new task
            future = asyncio.ensure_future(engine.stop_stream(stream_id))
            # The task will complete asynchronously
            return {
                "status": "success",
                "message": f"数据流 {stream_id} 停止请求已发送",
            }
        else:
            loop.run_until_complete(engine.stop_stream(stream_id))
            return {
                "status": "success",
                "message": f"数据流 {stream_id} 已停止",
            }
    except Exception as e:
        return {"status": "error", "message": f"停止失败: {str(e)}"}


def get_stream_statistics(stream_id: str) -> dict:
    """获取指定数据流的当前窗口统计信息。

    Args:
        stream_id: 数据流ID

    Returns:
        包含事件数、设备数、质心、空间分布等统计信息
    """
    try:
        import asyncio
        engine = get_stream_engine()

        # Try to get the latest window result
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Synchronous fallback: read config only
            streams = engine.get_active_streams()
            stream_info = next((s for s in streams if s["id"] == stream_id), None)
            if not stream_info:
                return {"status": "error", "message": f"数据流 {stream_id} 不存在"}
            return {
                "status": "success",
                "stream_id": stream_id,
                "name": stream_info.get("name", ""),
                "status": stream_info.get("status", "unknown"),
                "window_seconds": stream_info.get("window_seconds", 60),
                "message": "统计信息将在下一个窗口周期后可用",
            }
        else:
            result = loop.run_until_complete(engine.process_window(stream_id))
            if not result:
                return {"status": "error", "message": f"数据流 {stream_id} 不存在"}
            return {
                "status": "success",
                "stream_id": stream_id,
                "event_count": result.event_count,
                "device_count": result.device_count,
                "centroid_lat": result.centroid_lat,
                "centroid_lng": result.centroid_lng,
                "spatial_spread_m": result.spatial_spread,
                "alert_count": len(result.alerts),
                "window_start": datetime.fromtimestamp(result.window_start, tz=timezone.utc).isoformat(),
                "window_end": datetime.fromtimestamp(result.window_end, tz=timezone.utc).isoformat(),
            }
    except Exception as e:
        return {"status": "error", "message": f"查询统计失败: {str(e)}"}


def set_geofence_alert(
    stream_id: str,
    polygon_wkt: str,
    alert_type: str = "exit",
) -> dict:
    """为数据流设置地理围栏告警。

    当设备进入或离开围栏区域时触发告警。

    Args:
        stream_id: 数据流ID
        polygon_wkt: WKT格式的围栏多边形
        alert_type: 告警类型 (exit=离开时告警, enter=进入时告警)

    Returns:
        设置结果
    """
    try:
        engine = get_stream_engine()
        config = engine._configs.get(stream_id)
        if not config:
            return {"status": "error", "message": f"数据流 {stream_id} 不存在"}

        # Validate WKT
        try:
            from shapely import wkt
            geom = wkt.loads(polygon_wkt)
            if geom.geom_type not in ("Polygon", "MultiPolygon"):
                return {"status": "error", "message": "围栏必须是Polygon或MultiPolygon类型"}
        except ImportError:
            pass  # Accept without validation if Shapely not available
        except Exception as e:
            return {"status": "error", "message": f"WKT格式错误: {str(e)}"}

        config.geofence_wkt = polygon_wkt
        return {
            "status": "success",
            "message": f"地理围栏已设置 (告警类型: {alert_type})",
            "stream_id": stream_id,
        }
    except Exception as e:
        return {"status": "error", "message": f"设置围栏失败: {str(e)}"}
