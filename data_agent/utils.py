"""
Shared helper functions for the GIS Data Agent.
Extracted from agent.py to reduce monolith size.
"""
import os
import re
import uuid

import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import folium

from .gis_processors import _generate_output_path, _resolve_path


# ---------------------------------------------------------------------------
# Font configuration
# ---------------------------------------------------------------------------

def _configure_fonts():
    """Configure Matplotlib to use Chinese-compatible fonts based on OS."""
    import platform
    system = platform.system()
    font_names = []
    if system == 'Windows':
        font_names = ['SimHei', 'Microsoft YaHei', 'SimSun']
    elif system == 'Darwin':
        font_names = ['Arial Unicode MS', 'PingFang SC']
    else:
        font_names = ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'Noto Sans CJK']

    available_fonts = set(f.name for f in fm.fontManager.ttflist)
    selected_font = next((f for f in font_names if f in available_fonts), None)
    if selected_font:
        plt.rcParams['font.sans-serif'] = [selected_font] + plt.rcParams['font.sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        print(f"Visualization font configured: {selected_font}")


# ---------------------------------------------------------------------------
# Map basemap layers
# ---------------------------------------------------------------------------

TIANDITU_TOKEN = os.environ.get("TIANDITU_TOKEN", "")

def _add_basemap_layers(m):
    """Add standard basemap tile layers to a folium Map."""
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(m)
    folium.TileLayer('CartoDB dark_matter', name='CartoDB Dark').add_to(m)
    folium.TileLayer(
        tiles='http://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
        attr='&copy; AutoNavi',
        name='Gaode Map'
    ).add_to(m)
    if TIANDITU_TOKEN:
        folium.TileLayer(
            tiles=f'http://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL={{x}}&TILEROW={{y}}&TILEMATRIX={{z}}&tk={TIANDITU_TOKEN}',
            attr='&copy; 天地图',
            name='Tianditu Vec'
        ).add_to(m)
        folium.TileLayer(
            tiles=f'http://t0.tianditu.gov.cn/cva_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=cva&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL={{x}}&TILEROW={{y}}&TILEMATRIX={{z}}&tk={TIANDITU_TOKEN}',
            attr='&copy; 天地图',
            name='Tianditu Label',
            overlay=True
        ).add_to(m)


# ---------------------------------------------------------------------------
# Universal spatial data loader
# ---------------------------------------------------------------------------

def _load_spatial_data(file_path: str) -> gpd.GeoDataFrame:
    """
    Robustly loads spatial data from SHP, GeoJSON, CSV, Excel, KML, KMZ,
    or directly from a PostGIS table name.
    For CSV/Excel, auto-detects geometry columns (lon/lat, x/y).
    """
    import re as _re
    # --- PostGIS table name detection ---
    stripped = file_path.strip().strip('"').strip("'")
    _, ext_check = os.path.splitext(stripped)
    if not ext_check and _re.match(r'^[a-zA-Z0-9_]+$', stripped):
        try:
            from data_agent.database_tools import get_db_connection_url, _inject_user_context, T_TABLE_OWNERSHIP
            from data_agent.db_engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            if engine:
                with engine.connect() as conn:
                    _inject_user_context(conn)
                    # Ownership check via table_ownership (RLS auto-filters)
                    has_registry = conn.execute(text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        f"WHERE table_schema = 'public' AND table_name = '{T_TABLE_OWNERSHIP}')"
                    )).scalar()
                    if has_registry:
                        access = conn.execute(text(
                            f"SELECT COUNT(*) FROM {T_TABLE_OWNERSHIP} WHERE table_name = :t"
                        ), {"t": stripped}).scalar()
                        if access == 0:
                            raise PermissionError(
                                f"Table '{stripped}' not found or access denied for current user."
                            )
                    # Read with user context active on this connection
                    gdf = gpd.read_postgis(
                        f'SELECT * FROM "{stripped}"',
                        conn,
                        geom_col='geometry'
                    )
                    if not gdf.empty:
                        return gdf
        except PermissionError:
            raise
        except ImportError:
            pass  # Fall through to file loading
        except Exception as e:
            # Try alternative geom column names with same connection pattern
            try:
                with engine.connect() as conn:
                    _inject_user_context(conn)
                    for geom_name in ['geom', 'the_geom', 'shape']:
                        try:
                            gdf = gpd.read_postgis(
                                f'SELECT * FROM "{stripped}"',
                                conn,
                                geom_col=geom_name
                            )
                            if not gdf.empty:
                                return gdf
                        except Exception:
                            continue
            except Exception:
                pass  # Fall through to file loading

    path = _resolve_path(file_path)
    ext = os.path.splitext(path)[1].lower()

    # --- Tabular formats: CSV and Excel ---
    if ext in ('.csv', '.xlsx', '.xls'):
        if ext == '.csv':
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)

        # Auto-detect geometry columns
        cols = [c.lower() for c in df.columns]
        x_col, y_col = None, None

        # Priority 1: lng/lat
        if 'lng' in cols and 'lat' in cols: x_col, y_col = df.columns[cols.index('lng')], df.columns[cols.index('lat')]
        elif 'lon' in cols and 'lat' in cols: x_col, y_col = df.columns[cols.index('lon')], df.columns[cols.index('lat')]
        elif 'longitude' in cols and 'latitude' in cols: x_col, y_col = df.columns[cols.index('longitude')], df.columns[cols.index('latitude')]
        # Priority 2: x/y (Projected)
        elif 'x' in cols and 'y' in cols: x_col, y_col = df.columns[cols.index('x')], df.columns[cols.index('y')]

        if x_col and y_col:
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[x_col], df[y_col]))
            if 'lat' in y_col.lower(): gdf.set_crs(epsg=4326, inplace=True)
            return gdf
        else:
            fmt = "Excel" if ext != '.csv' else "CSV"
            raise ValueError(
                f"{fmt} 文件必须包含坐标列 ('lat'/'lon', 'lng'/'lat', 'longitude'/'latitude', 'x'/'y')。"
                f"当前列: {list(df.columns)}"
            )

    # --- KMZ: extract .kml from zip ---
    elif ext == '.kmz':
        import zipfile as _zf
        extract_dir = os.path.join(os.path.dirname(path), '_kmz_' + uuid.uuid4().hex[:8])
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with _zf.ZipFile(path, 'r') as zf:
                kml_names = [n for n in zf.namelist() if n.lower().endswith('.kml')]
                if not kml_names:
                    raise ValueError("KMZ 文件中未找到 .kml 文件")
                zf.extract(kml_names[0], extract_dir)
                kml_path = os.path.join(extract_dir, kml_names[0])
            return gpd.read_file(kml_path, driver='KML')
        except _zf.BadZipFile:
            raise ValueError("KMZ 文件格式损坏，无法解压")

    # --- KML: read directly ---
    elif ext == '.kml':
        return gpd.read_file(path, driver='KML')

    # --- All other spatial formats: SHP, GeoJSON, GPKG, etc. ---
    else:
        return gpd.read_file(path)


# ---------------------------------------------------------------------------
# Quality gate: output file validation
# ---------------------------------------------------------------------------

def _quality_gate_check(tool_response: dict) -> tuple:
    """
    Validate tool output quality. Returns (status, message).
    status: 'pass' | 'warning' | 'critical'
    """
    resp_str = str(tool_response.get("result", "") or tool_response.get("message", ""))

    # Extract file paths from response
    paths = re.findall(r'[A-Za-z]:[\\\/][\w\\\/._-]+\.\w{2,5}', resp_str)
    if not paths:
        paths = re.findall(r'uploads[\\\/][\w\\\/._-]+\.\w{2,5}', resp_str)

    if not paths:
        return ("pass", "")

    for path in paths:
        if not os.path.exists(path):
            continue

        ext = os.path.splitext(path)[1].lower()
        size = os.path.getsize(path)

        if size == 0:
            return ("critical", f"输出文件 {os.path.basename(path)} 为空(0字节)。")

        if ext == '.shp':
            try:
                gdf = gpd.read_file(path)
                if len(gdf) == 0:
                    return ("critical", f"输出 Shapefile {os.path.basename(path)} 包含 0 条要素。")
                if gdf.crs is None:
                    return ("warning", f"输出 Shapefile {os.path.basename(path)} 缺少坐标系定义。")
            except Exception:
                return ("warning", f"无法验证 Shapefile {os.path.basename(path)}。")

        elif ext == '.html' and size < 1024:
            return ("warning", f"输出 HTML {os.path.basename(path)} 可能不完整({size}字节)。")

        elif ext == '.csv':
            try:
                df = pd.read_csv(path, nrows=1)
                if len(df) == 0:
                    return ("critical", f"输出 CSV {os.path.basename(path)} 没有数据行。")
            except Exception:
                return ("warning", f"无法验证 CSV {os.path.basename(path)}。")

        elif ext in ('.png', '.jpg', '.tif', '.tiff') and size < 1024:
            return ("warning", f"输出图像 {os.path.basename(path)} 可能不完整({size}字节)。")

    return ("pass", "")


# ---------------------------------------------------------------------------
# Self-correction: after_tool_callback
# ---------------------------------------------------------------------------

_tool_retry_counts = {}  # track per-invocation retries

def _self_correction_after_tool(tool, args, tool_context, tool_response):
    """
    After-tool callback: enriches error responses with actionable hints.
    Signature: (BaseTool, dict, ToolContext, dict) -> Optional[dict]
    Returns modified dict to override response, or None to keep original.
    """
    if not isinstance(tool_response, dict):
        return None

    # Check if response indicates an error
    resp_str = str(tool_response.get("error", "") or tool_response.get("result", "") or tool_response.get("message", ""))
    is_error = (
        "error" in resp_str.lower()[:30]
        or "not found" in resp_str.lower()
        or "不存在" in resp_str
        or "failed" in resp_str.lower()[:30]
    )
    if not is_error:
        # --- Quality Gate: validate output files ---
        qg_status, qg_message = _quality_gate_check(tool_response)
        if qg_status == "critical":
            tool_response["_quality_gate"] = "critical"
            tool_response["_correction_hint"] = f"质量检查失败：{qg_message} 请检查输入参数后重试。"
            return tool_response
        elif qg_status == "warning":
            tool_response["_quality_gate"] = "warning"
            tool_response["_quality_note"] = qg_message
        return None

    # Track retries to prevent infinite loops (key by invocation + tool name)
    inv_id = id(tool_context)
    key = f"{inv_id}:{tool.name}"
    _tool_retry_counts[key] = _tool_retry_counts.get(key, 0) + 1
    if _tool_retry_counts[key] > 3:
        tool_response["_hint"] = "已重试3次仍然失败。请停止重试此工具，向用户报告错误并建议替代方案。"
        return tool_response

    # Enrich with contextual hints based on error type
    hints = []
    resp_lower = resp_str.lower()

    if "column" in resp_lower or "字段" in resp_str or "not found" in resp_lower:
        hints.append("请调用 describe_table(表名) 获取真实列名后用正确的列名重试。")

    if "table" in resp_lower or "relation" in resp_lower:
        hints.append("请调用 list_tables() 确认可用的表名后重试。")

    if "file" in resp_lower or "path" in resp_lower or "文件" in resp_str:
        hints.append("请调用 list_user_files() 确认可用的文件名后重试。")

    if "crs" in resp_lower or "坐标" in resp_str or "projection" in resp_lower:
        hints.append("数据可能需要先用 reproject_spatial_data() 重投影到正确坐标系。")

    if not hints:
        hints.append("请检查参数是否正确，可尝试修改参数后重试。")

    tool_response["_correction_hint"] = " ".join(hints)
    return tool_response
