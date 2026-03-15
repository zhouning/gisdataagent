"""
ArcPy Integration Bridge — optional parallel GIS engine.

Manages a persistent ArcPy subprocess (arcpy_worker.py) via JSON-line IPC.
All tool functions follow the same pattern as gis_processors.py tools.

Enable by setting ARCPY_PYTHON_EXE in .env to the ArcGIS Pro Python path.
When not configured, is_arcpy_available() returns False and all tools return errors gracefully.
"""
import subprocess
import json
import threading
import os
import atexit
from typing import Optional

from .gis_processors import _resolve_path, _generate_output_path


class ArcPyBridge:
    """
    Singleton bridge to a persistent ArcPy subprocess worker.
    Uses JSON-line protocol over stdin/stdout for IPC.
    """
    _instance: Optional['ArcPyBridge'] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> Optional['ArcPyBridge']:
        """Returns the singleton bridge, or None if ArcPy env is not configured."""
        if cls._instance is not None:
            return cls._instance
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            python_exe = os.environ.get("ARCPY_PYTHON_EXE", "")
            if not python_exe or not os.path.isfile(python_exe):
                return None
            try:
                bridge = cls(python_exe)
                bridge._start_worker()
                cls._instance = bridge
                return cls._instance
            except Exception as e:
                print(f"[ArcPyBridge] Failed to start worker: {e}")
                return None

    def __init__(self, python_exe: str):
        self._python_exe = python_exe
        self._worker_script = os.path.join(os.path.dirname(__file__), "arcpy_worker.py")
        self._process: Optional[subprocess.Popen] = None
        self._call_lock = threading.Lock()
        self._healthy = False

    def _start_worker(self):
        """Start the persistent ArcPy worker subprocess."""
        self._process = subprocess.Popen(
            [self._python_exe, self._worker_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=os.path.dirname(__file__),
        )
        # Wait for the "ready" handshake (up to 30s for ArcPy cold import)
        ready = self._read_line(timeout=30)
        if ready is None or ready.get("status") != "ready":
            self.shutdown()
            raise RuntimeError(f"ArcPy worker did not report ready. Got: {ready}")
        self._healthy = True
        version = ready.get("arcpy_version", "?")
        license_level = ready.get("license_level", "?")
        print(f"[ArcPyBridge] Worker ready. ArcPy {version}, License: {license_level}")
        atexit.register(self.shutdown)

    def shutdown(self):
        """Gracefully shut down the worker process."""
        if self._process and self._process.poll() is None:
            try:
                self._send_line({"command": "__shutdown__"})
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._healthy = False
        ArcPyBridge._instance = None

    def _send_line(self, obj: dict):
        """Write a JSON line to worker stdin."""
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _read_line(self, timeout: float = 120) -> Optional[dict]:
        """Read a JSON line from worker stdout with timeout."""
        result = [None]
        error = [None]

        def _reader():
            try:
                raw = self._process.stdout.readline()
                if raw:
                    result[0] = json.loads(raw.strip())
            except Exception as e:
                error[0] = e

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            return {"status": "error", "message": f"Worker timed out after {timeout}s"}
        if error[0]:
            return {"status": "error", "message": str(error[0])}
        return result[0]

    def call(self, command: str, params: dict, timeout: float = 120) -> dict:
        """
        Send a command to the ArcPy worker and return the result.
        Thread-safe: serializes concurrent calls via lock.
        """
        with self._call_lock:
            # Check if worker is alive; try one restart if dead
            if not self._healthy or self._process is None or self._process.poll() is not None:
                try:
                    self._start_worker()
                except Exception as e:
                    return {"status": "error", "message": f"Worker restart failed: {e}"}

            self._send_line({"command": command, "params": params})
            response = self._read_line(timeout=timeout)

            if response is None:
                self._healthy = False
                return {"status": "error", "message": "No response from ArcPy worker"}

            return response

    def is_healthy(self) -> bool:
        """Check if the worker process is alive and responsive."""
        if not self._healthy or self._process is None or self._process.poll() is not None:
            return False
        result = self.call("__ping__", {}, timeout=5)
        return result.get("status") == "pong"


def is_arcpy_available() -> bool:
    """
    Returns True if ArcPy bridge can be established.
    Called at import time in agent.py to decide whether to register ArcPy tools.
    """
    bridge = ArcPyBridge.get_instance()
    return bridge is not None and bridge.is_healthy()


# ---------------------------------------------------------------------------
# ADK Tool Functions
# ---------------------------------------------------------------------------

def arcpy_buffer(file_path: str, distance: float = 500.0, dissolve_type: str = "NONE") -> str:
    """
    [ArcPy] 使用 ArcPy 引擎创建缓冲区。与 create_buffer 功能对应，可用于结果对比。
    支持融合类型: NONE(逐要素), ALL(全融合)。

    Args:
        file_path: 输入矢量文件路径。
        distance: 缓冲距离（米）。
        dissolve_type: 融合类型，"NONE" 或 "ALL"。
    Returns:
        输出 Shapefile 路径。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return "Error: ArcPy 环境未配置或不可用"
        input_path = _resolve_path(file_path)
        output_path = _generate_output_path("arcpy_buffer", "shp")
        result = bridge.call("buffer", {
            "input_path": input_path,
            "output_path": output_path,
            "distance": distance,
            "dissolve_type": dissolve_type,
        })
        if result.get("status") == "success":
            return result.get("output_path", output_path)
        return f"Error in arcpy_buffer: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error in arcpy_buffer: {str(e)}"


def arcpy_clip(input_features: str, clip_features: str) -> str:
    """
    [ArcPy] 使用 ArcPy 引擎裁剪要素。与 pairwise_clip 功能对应。

    Args:
        input_features: 被裁剪的矢量文件路径。
        clip_features: 裁剪范围的矢量文件路径。
    Returns:
        输出 Shapefile 路径。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return "Error: ArcPy 环境未配置或不可用"
        input_path = _resolve_path(input_features)
        clip_path = _resolve_path(clip_features)
        output_path = _generate_output_path("arcpy_clipped", "shp")
        result = bridge.call("clip", {
            "input_path": input_path,
            "clip_path": clip_path,
            "output_path": output_path,
        })
        if result.get("status") == "success":
            return result.get("output_path", output_path)
        return f"Error in arcpy_clip: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error in arcpy_clip: {str(e)}"


def arcpy_dissolve(file_path: str, dissolve_field: str, statistics_fields: str = "") -> str:
    """
    [ArcPy独有] 按字段融合要素，支持多字段多统计量聚合。
    开源工具无完整对应 — GeoPandas dissolve 不支持同时计算多个字段的多种统计量。

    Args:
        file_path: 输入矢量文件路径。
        dissolve_field: 融合依据的字段名（如 'DLMC' 地类名称）。
        statistics_fields: 统计字段规格，格式: "字段名 统计类型;字段名 统计类型"。
            统计类型: SUM, MEAN, MIN, MAX, COUNT, FIRST, LAST。
            示例: "Shape_Area SUM;Slope MEAN;Parcel_ID COUNT"
    Returns:
        输出 Shapefile 路径。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return "Error: ArcPy 环境未配置或不可用"
        input_path = _resolve_path(file_path)
        output_path = _generate_output_path("arcpy_dissolved", "shp")
        result = bridge.call("dissolve", {
            "input_path": input_path,
            "output_path": output_path,
            "dissolve_field": dissolve_field,
            "statistics_fields": statistics_fields or None,
        })
        if result.get("status") == "success":
            return result.get("output_path", output_path)
        return f"Error in arcpy_dissolve: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error in arcpy_dissolve: {str(e)}"


def arcpy_project(file_path: str, target_crs: str = "EPSG:4490") -> str:
    """
    [ArcPy] 使用 ArcPy 引擎进行坐标投影转换。与 reproject_spatial_data 功能对应。

    Args:
        file_path: 输入矢量文件路径。
        target_crs: 目标坐标系，支持 EPSG 代码（如 "EPSG:4490"）或 WKID 数字。
    Returns:
        输出 Shapefile 路径。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return "Error: ArcPy 环境未配置或不可用"
        input_path = _resolve_path(file_path)
        output_path = _generate_output_path("arcpy_projected", "shp")
        result = bridge.call("project", {
            "input_path": input_path,
            "output_path": output_path,
            "target_crs": target_crs,
        })
        if result.get("status") == "success":
            return result.get("output_path", output_path)
        return f"Error in arcpy_project: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error in arcpy_project: {str(e)}"


def arcpy_check_geometry(file_path: str) -> dict:
    """
    [ArcPy增强] 使用 ArcPy 进行全面几何验证。
    比 Shapely 的 is_valid 更全面：检测短线段、未闭合环、错误环方向、自相交等。

    Args:
        file_path: 输入矢量文件路径。
    Returns:
        包含错误数量、类型分布和报告路径的 dict。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return {"status": "error", "message": "ArcPy 环境未配置或不可用"}
        input_path = _resolve_path(file_path)
        output_path = _generate_output_path("arcpy_geom_check", "csv")
        result = bridge.call("check_geometry", {
            "input_path": input_path,
            "output_path": output_path,
        })
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def arcpy_repair_geometry(file_path: str) -> str:
    """
    [ArcPy独有] 自动修复无效几何。
    修复自相交、空几何、错误环方向、未闭合环等。原始文件不被修改，输出为修复后的副本。
    开源工具无等效功能。

    Args:
        file_path: 输入矢量文件路径。
    Returns:
        修复后的 Shapefile 路径。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return "Error: ArcPy 环境未配置或不可用"
        input_path = _resolve_path(file_path)
        output_path = _generate_output_path("arcpy_repaired", "shp")
        result = bridge.call("repair_geometry", {
            "input_path": input_path,
            "output_path": output_path,
        })
        if result.get("status") == "success":
            return result.get("output_path", output_path)
        return f"Error in arcpy_repair_geometry: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error in arcpy_repair_geometry: {str(e)}"


def arcpy_slope(dem_raster: str, output_measurement: str = "DEGREE") -> str:
    """
    [ArcPy] 使用 ArcPy Spatial Analyst 计算坡度。与 surface_parameters(SLOPE) 功能对应。

    Args:
        dem_raster: 输入 DEM 栅格文件路径（GeoTIFF）。
        output_measurement: "DEGREE"（度）或 "PERCENT_RISE"（百分比坡度）。
    Returns:
        输出坡度栅格文件路径（GeoTIFF）。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return "Error: ArcPy 环境未配置或不可用"
        input_path = _resolve_path(dem_raster)
        output_path = _generate_output_path("arcpy_slope", "tif")
        result = bridge.call("slope", {
            "input_path": input_path,
            "output_path": output_path,
            "output_measurement": output_measurement,
        })
        if result.get("status") == "success":
            return result.get("output_path", output_path)
        return f"Error in arcpy_slope: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error in arcpy_slope: {str(e)}"


def arcpy_zonal_statistics(zone_vector: str, value_raster: str,
                           zone_field: str = "FID", stats_type: str = "ALL") -> str:
    """
    [ArcPy] 使用 ArcPy Spatial Analyst 计算分区统计。与 zonal_statistics_as_table 功能对应。

    Args:
        zone_vector: 定义区域的多边形矢量文件路径。
        value_raster: 用于计算统计的栅格文件路径。
        zone_field: 区域标识字段名。
        stats_type: 统计类型: "ALL", "MEAN", "SUM", "MAXIMUM", "MINIMUM", "RANGE", "STD"。
    Returns:
        输出统计表 CSV 文件路径。
    """
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return "Error: ArcPy 环境未配置或不可用"
        zone_path = _resolve_path(zone_vector)
        raster_path = _resolve_path(value_raster)
        output_path = _generate_output_path("arcpy_zonal_stats", "csv")
        result = bridge.call("zonal_statistics", {
            "zone_path": zone_path,
            "raster_path": raster_path,
            "zone_field": zone_field,
            "stats_type": stats_type,
            "output_path": output_path,
        })
        if result.get("status") == "success":
            return result.get("output_path", output_path)
        return f"Error in arcpy_zonal_statistics: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error in arcpy_zonal_statistics: {str(e)}"


def arcpy_extract_watershed(dem_path: str, pour_point_x: str = "",
                            pour_point_y: str = "", threshold: str = "1000",
                            boundary_path: str = "") -> str:
    """使用 ArcPy Spatial Analyst 进行小流域提取（专业级精度）。

    需要 ArcGIS Spatial Analyst 扩展授权。功能等同于开源版 extract_watershed，
    但使用 ArcPy 的 Fill/FlowDirection/FlowAccumulation/Watershed 引擎。

    Args:
        dem_path: DEM 文件路径(GeoTIFF)，或 PostGIS 表名（配合 boundary_path 下载 DEM）
        pour_point_x: 出口点经度（留空=自动检测汇流累积最大点）
        pour_point_y: 出口点纬度
        threshold: 河网提取阈值（汇流累积单元数，默认1000）
        boundary_path: 当需要先下载 DEM 时，提供行政区边界文件

    Returns:
        JSON 包含流域边界文件、河网文件、统计信息。
    """
    import json
    try:
        bridge = ArcPyBridge.get_instance()
        if not bridge:
            return json.dumps({"status": "error",
                               "message": "ArcPy 环境未配置或不可用。请使用开源版 extract_watershed。"})

        # Resolve DEM path — support "auto" download mode
        resolved_dem = dem_path
        if dem_path.strip().lower() == "auto" and boundary_path:
            try:
                from .remote_sensing import download_dem
                dem_result = download_dem(boundary_path)
                # Extract file path from result
                for line in str(dem_result).split("\n"):
                    if ".tif" in line.lower():
                        parts = line.split(":")
                        resolved_dem = parts[-1].strip() if len(parts) > 1 else line.strip()
                        break
            except Exception as e:
                return json.dumps({"status": "error", "message": f"DEM 下载失败: {e}"})
        else:
            resolved_dem = _resolve_path(dem_path)

        if not os.path.exists(resolved_dem):
            return json.dumps({"status": "error", "message": f"DEM 文件不存在: {resolved_dem}"})

        output_dir = os.path.dirname(_generate_output_path("arcpy_ws", "tmp"))

        result = bridge.call("extract_watershed", {
            "dem_path": resolved_dem,
            "threshold": int(threshold),
            "pour_point_x": pour_point_x if pour_point_x else None,
            "pour_point_y": pour_point_y if pour_point_y else None,
            "output_dir": output_dir,
        }, timeout=300)  # 5 min timeout for large DEMs

        if result.get("status") == "success":
            # Build report text consistent with pysheds version
            elev = result.get("elevation", {})
            report_lines = [
                "# 小流域水文分析报告 (ArcPy Spatial Analyst)",
                "",
                "## 一、分析概述",
                f"- **分析引擎**: ArcPy Spatial Analyst",
                f"- **DEM 数据**: {os.path.basename(resolved_dem)}",
                f"- **河网阈值**: {threshold}",
                "",
                "## 二、高程特征",
            ]
            if elev:
                report_lines += [
                    f"- **最低高程**: {elev.get('min', 'N/A')} m",
                    f"- **最高高程**: {elev.get('max', 'N/A')} m",
                    f"- **平均高程**: {elev.get('mean', 'N/A')} m",
                    f"- **高差**: {elev.get('range', 'N/A')} m",
                ]
            report_lines += [
                "",
                "## 三、方法说明",
                "使用 ArcPy Spatial Analyst 引擎的专业水文分析链：",
                "1. **Fill**: 填充 DEM 洼地",
                "2. **FlowDirection**: D8 流向计算",
                "3. **FlowAccumulation**: 汇流累积",
                "4. **Watershed**: 流域划分",
                "5. **StreamOrder**: Strahler 河流分级",
            ]

            result["report_text"] = "\n".join(report_lines)
            files = [f for f in [result.get("watershed_boundary"),
                                  result.get("stream_network"),
                                  result.get("flow_accumulation")] if f]
            result["files"] = files

        return json.dumps(result, default=str, ensure_ascii=False)

    except Exception as e:
        import json
        return json.dumps({"status": "error", "message": f"ArcPy 水文分析失败: {str(e)}"})
