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


# ---------------------------------------------------------------------------
# LoopAgent exit tool: quality approval
# ---------------------------------------------------------------------------

def approve_quality(verdict: str, tool_context) -> dict:
    """Quality checker calls this when analysis passes validation.

    Sets ``tool_context.actions.escalate = True`` so the enclosing
    ``LoopAgent`` exits the review loop and proceeds to the next pipeline
    stage.

    Args:
        verdict: A short summary of the quality assessment (e.g.
            "所有指标通过验证").
        tool_context: Injected automatically by ADK at runtime.
    """
    tool_context.actions.escalate = True
    return {"status": "approved", "verdict": verdict}


# ---------------------------------------------------------------------------
# Upload preview helpers (v4.1.3)
# ---------------------------------------------------------------------------

def _format_file_size(size_bytes: int) -> str:
    """Convert bytes to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _dtype_label(dtype) -> str:
    """Map pandas dtype to a Chinese-labeled category."""
    s = str(dtype)
    if "int" in s or "float" in s:
        return "数值"
    elif "datetime" in s:
        return "日期"
    elif "geometry" in s:
        return "几何"
    elif "bool" in s:
        return "布尔"
    return "文本"


def _preview_file_info(file_path: str, gdf) -> list:
    """Section: file format, size, feature count."""
    ext = os.path.splitext(file_path)[1].lower()
    _FMT = {
        ".shp": "Shapefile", ".geojson": "GeoJSON", ".json": "GeoJSON",
        ".gpkg": "GeoPackage", ".kml": "KML", ".kmz": "KMZ",
        ".csv": "CSV", ".xlsx": "Excel", ".xls": "Excel",
    }
    fmt = _FMT.get(ext, ext.upper().lstrip(".") or "未知")
    try:
        size_str = _format_file_size(os.path.getsize(file_path))
    except OSError:
        size_str = "未知"
    return [
        f"- **文件格式**: {fmt} | **文件大小**: {size_str}",
        f"- **要素数量**: {len(gdf)} 条记录",
    ]


def _preview_spatial_info(gdf) -> list:
    """Section: CRS, geometry types, bounds, area/length summary."""
    lines = []
    lines.append(f"- **坐标系**: {gdf.crs or '未定义'}")

    has_geom = "geometry" in gdf.columns and not gdf.geometry.isna().all()
    if not has_geom:
        lines.append("- **几何**: 无空间数据")
        return lines

    valid_geom = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    geom_types = valid_geom.geometry.geom_type.unique().tolist() if len(valid_geom) > 0 else []

    if geom_types:
        lines.append(f"- **几何类型**: {', '.join(geom_types)}")

    if len(valid_geom) > 0:
        bounds = valid_geom.total_bounds
        lines.append(
            f"- **空间范围**: [{bounds[0]:.4f}, {bounds[1]:.4f}] ~ "
            f"[{bounds[2]:.4f}, {bounds[3]:.4f}]"
        )

    # Area/length summary
    if len(valid_geom) > 0 and geom_types:
        type_set = set(geom_types)
        poly_types = {"Polygon", "MultiPolygon"}
        line_types = {"LineString", "MultiLineString"}
        point_types = {"Point", "MultiPoint"}

        if type_set & poly_types:
            try:
                calc = valid_geom.to_crs(epsg=3857) if (
                    valid_geom.crs and valid_geom.crs.is_geographic
                ) else valid_geom
                areas = calc.geometry.area
                lines.append(
                    f"- **面积统计**: 最小 {areas.min():.1f} m² | "
                    f"最大 {areas.max():.1f} m² | 平均 {areas.mean():.1f} m²"
                )
            except Exception:
                pass
        elif type_set & line_types:
            try:
                calc = valid_geom.to_crs(epsg=3857) if (
                    valid_geom.crs and valid_geom.crs.is_geographic
                ) else valid_geom
                lengths = calc.geometry.length
                lines.append(
                    f"- **长度统计**: 最小 {lengths.min():.1f} m | "
                    f"最大 {lengths.max():.1f} m | 平均 {lengths.mean():.1f} m"
                )
            except Exception:
                pass
        elif type_set <= point_types:
            lines.append(f"- **点要素数**: {len(valid_geom)} 个点")

    return lines


def _preview_column_info(gdf) -> list:
    """Section: column names, dtypes, null counts as table."""
    non_geom = [c for c in gdf.columns if c != "geometry"]
    if not non_geom:
        return []

    lines = [f"\n#### 字段概览 ({len(non_geom)} 个字段)\n"]
    display = non_geom[:12]
    lines.append("| 字段名 | 类型 | 空值 | 空值率 |")
    lines.append("| --- | --- | --- | --- |")
    total = len(gdf)
    for col in display:
        dtype = _dtype_label(gdf[col].dtype)
        n_null = int(gdf[col].isna().sum())
        pct = f"{n_null / total * 100:.1f}%" if total > 0 else "0%"
        lines.append(f"| {col} | {dtype} | {n_null} | {pct} |")
    if len(non_geom) > 12:
        lines.append(f"\n> 还有 {len(non_geom) - 12} 个字段未显示")
    return lines


def _preview_quality_indicators(gdf) -> list:
    """Section: quick data health check."""
    lines = ["\n#### 数据质量\n"]
    issues = []
    has_geom = "geometry" in gdf.columns and not gdf.geometry.isna().all()

    non_geom = [c for c in gdf.columns if c != "geometry"]
    total_cells = len(gdf) * len(non_geom)
    total_nulls = sum(int(gdf[c].isna().sum()) for c in non_geom)
    if total_nulls > 0:
        pct = total_nulls / total_cells * 100 if total_cells > 0 else 0
        issues.append(f"缺失值: {total_nulls} 个 ({pct:.1f}%)")

    if has_geom:
        n_null_geom = int(gdf.geometry.isna().sum())
        n_empty = int(gdf.geometry.is_empty.sum()) if n_null_geom < len(gdf) else 0
        if n_null_geom + n_empty > 0:
            issues.append(f"空几何: {n_null_geom + n_empty} 个")

        if len(gdf) <= 100_000:
            valid_mask = gdf.geometry.notna() & ~gdf.geometry.is_empty
            if valid_mask.any():
                n_invalid = int((~gdf[valid_mask].geometry.is_valid).sum())
                if n_invalid > 0:
                    issues.append(f"无效几何: {n_invalid} 个")

    if not issues:
        lines.append("数据质量良好，无明显问题。")
    else:
        for issue in issues:
            lines.append(f"- {issue}")
    return lines


def _preview_numeric_stats(gdf) -> list:
    """Section: min/max/mean for numeric columns."""
    numeric_cols = gdf.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_cols:
        return []

    display = numeric_cols[:10]
    lines = ["\n#### 数值统计\n"]
    lines.append("| 字段 | 最小值 | 最大值 | 平均值 |")
    lines.append("| --- | --- | --- | --- |")
    for col in display:
        if gdf[col].isna().all():
            lines.append(f"| {col} | - | - | - |")
            continue
        lines.append(f"| {col} | {gdf[col].min():.4g} | {gdf[col].max():.4g} | {gdf[col].mean():.4g} |")
    if len(numeric_cols) > 10:
        lines.append(f"\n> 还有 {len(numeric_cols) - 10} 个数值字段未显示")
    return lines


def _preview_sample_rows(gdf, max_rows: int = 5, max_cols: int = 8) -> list:
    """Section: first N rows as markdown table."""
    non_geom = [c for c in gdf.columns if c != "geometry"]
    if not non_geom or len(gdf) == 0:
        return []

    display = non_geom[:max_cols]
    n_rows = min(max_rows, len(gdf))
    preview_df = gdf[display].head(n_rows)

    lines = [f"\n**前 {n_rows} 行预览**:\n"]
    lines.append("| " + " | ".join(str(c) for c in display) + " |")
    lines.append("| " + " | ".join("---" for _ in display) + " |")
    for _, row in preview_df.iterrows():
        vals = [str(row[c])[:30] for c in display]
        lines.append("| " + " | ".join(vals) + " |")
    return lines


def _generate_upload_preview(file_path: str) -> str:
    """Generate a rich markdown preview of uploaded spatial/tabular data.

    Pure function: returns a markdown string. No side effects.
    """
    try:
        gdf = _load_spatial_data(file_path)

        lines = ["### 数据预览 (Data Preview)\n"]

        if len(gdf) == 0:
            lines.append("空数据集 (0 条记录)")
            return "\n".join(lines)

        lines.extend(_preview_file_info(file_path, gdf))
        lines.extend(_preview_spatial_info(gdf))
        lines.extend(_preview_column_info(gdf))
        lines.extend(_preview_quality_indicators(gdf))
        lines.extend(_preview_numeric_stats(gdf))
        lines.extend(_preview_sample_rows(gdf))

        return "\n".join(lines)
    except Exception as e:
        return f"数据预览失败: {str(e)}"
