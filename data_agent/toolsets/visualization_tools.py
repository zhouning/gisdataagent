"""Visualization toolset: interactive maps, choropleth, bubble maps, static exports."""
import os
import json

import numpy as np


def load_admin_boundary(
    province: str = "",
    city: str = "",
    county: str = "",
    township: str = "",
) -> str:
    """加载中国行政区划边界到地图（从 PostGIS xiangzhen 表）。

    自动构造 SQL 过滤条件，支持模糊匹配。比手动构造 sql_filter 更安全可靠。

    Args:
        province: 省份名称，如"上海市"、"重庆市"。可选。
        city: 地级市名称，如"重庆市"（直辖市可省略）。可选。
        county: 区县名称，如"松江区"、"璧山区"。必填（除非只查省级）。
        township: 乡镇/街道名称，如"方松街道"、"青杠街道"。可选。

    Returns:
        JSON 字符串，包含 map_config（前端地图配置）和 geojson_path（保存的文件路径）。

    Examples:
        - 加载上海市松江区: load_admin_boundary(province="上海市", county="松江区")
        - 加载重庆市璧山区: load_admin_boundary(city="重庆市", county="璧山区")
        - 加载方松街道: load_admin_boundary(city="上海市", county="松江区", township="方松街道")
    """
    try:
        from ..db_engine import get_engine
        from ..database_tools import _inject_user_context
        import geopandas as gpd

        # Build WHERE clause
        conditions = []
        if province:
            conditions.append(f"province LIKE '%{province.strip()}%'")
        if city:
            conditions.append(f"city LIKE '%{city.strip()}%'")
        if county:
            conditions.append(f"county LIKE '%{county.strip()}%'")
        if township:
            conditions.append(f"township LIKE '%{township.strip()}%'")

        if not conditions:
            return json.dumps({"error": "至少需要提供 province, city, county 或 township 之一"}, ensure_ascii=False)

        where_clause = " AND ".join(conditions)
        sql = f'SELECT * FROM "xiangzhen" WHERE {where_clause}'

        engine = get_engine()
        if not engine:
            return json.dumps({"error": "数据库连接不可用"}, ensure_ascii=False)
        with engine.connect() as conn:
            _inject_user_context(conn)
            gdf = gpd.read_postgis(sql, conn, geom_col="geometry")

        if gdf.empty:
            return json.dumps({
                "error": f"未找到匹配的行政区。查询条件: {where_clause}",
                "suggestion": "请检查地名拼写，或尝试只提供上级行政区（如只传 county 不传 township）"
            }, ensure_ascii=False)

        # Save to GeoJSON
        from ..user_context import current_user_id
        import uuid
        uid = current_user_id.get("admin")
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", uid)
        os.makedirs(upload_dir, exist_ok=True)
        fname = f"admin_boundary_{uuid.uuid4().hex[:8]}.geojson"
        fpath = os.path.join(upload_dir, fname)
        gdf.to_file(fpath, driver="GeoJSON")

        # Build map config
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lng = (bounds[0] + bounds[2]) / 2

        map_config = {
            "layers": [{
                "type": "geojson",
                "geojson": fname,
                "name": f"{province or ''}{city or ''}{county or ''}{township or ''}",
                "style": {"color": "#3388ff", "weight": 2, "fillOpacity": 0.2},
            }],
            "center": [center_lat, center_lng],
            "zoom": 12 if township else 11,
        }

        return json.dumps({
            "status": "ok",
            "message": f"已加载 {len(gdf)} 个行政区边界",
            "geojson_path": fpath,
            "map_config": map_config,
        }, ensure_ascii=False)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": str(e),
            "traceback": traceback.format_exc()[-500:]
        }, ensure_ascii=False)



import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import folium
from folium import plugins
import branca.colormap as cm
import mapclassify
import contextily as cx

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from .. import drl_engine
from ..gis_processors import generate_heatmap, _generate_output_path
from ..utils import _load_spatial_data, _configure_fonts, _add_basemap_layers


def _load_spatial_data_with_filter(data_path: str, sql_filter: str = None) -> gpd.GeoDataFrame:
    """Load spatial data with optional SQL WHERE filter for PostGIS tables.

    If sql_filter is provided and data_path looks like a PostGIS table name,
    applies the WHERE clause to filter data at the database level.
    Otherwise falls back to _load_spatial_data (full table load).
    """
    import re as _re
    stripped = data_path.strip().strip('"').strip("'")
    _, ext_check = os.path.splitext(stripped)

    # Safety guard: large tables MUST have sql_filter to prevent full-table download
    _LARGE_TABLES = {"xiangzhen", "admin_boundaries", "townships"}
    if not ext_check and stripped.lower() in _LARGE_TABLES and not sql_filter:
        raise ValueError(
            f"表 '{stripped}' 数据量过大，必须提供 sql_filter 参数进行过滤。"
            f"例如: sql_filter=\"city='上海市' AND county='松江区'\""
        )

    # Only apply SQL filter for PostGIS table names (no file extension)
    if sql_filter and not ext_check and _re.match(r'^[a-zA-Z0-9_]+$', stripped):
        try:
            from ..db_engine import get_engine
            from ..database_tools import _inject_user_context
            engine = get_engine()
            if engine:
                # Sanitize filter to prevent injection (basic check)
                forbidden = ['drop ', 'delete ', 'insert ', 'update ', 'alter ', '--', ';']
                filter_lower = sql_filter.lower()
                if any(f in filter_lower for f in forbidden):
                    print(f"[Warning] Rejected sql_filter for safety: {sql_filter}")
                    return _load_spatial_data(data_path)

                sql = f'SELECT * FROM "{stripped}" WHERE {sql_filter}'
                with engine.connect() as conn:
                    _inject_user_context(conn)
                    for geom_col in ['geometry', 'geom', 'the_geom', 'shape']:
                        try:
                            gdf = gpd.read_postgis(sql, conn, geom_col=geom_col)
                            if not gdf.empty:
                                print(f"[SQL Filter] Loaded {len(gdf)} rows from {stripped} WHERE {sql_filter}")
                                return gdf
                        except Exception:
                            continue
        except Exception as e:
            print(f"[Warning] SQL filter failed, falling back to full load: {e}")

    return _load_spatial_data(data_path)


def _save_map_config(html_path: str, gdf, layers: list, center: list = None,
                     zoom: int = None, pitch: int = None, bearing: int = None):
    """Save GeoJSON + mapconfig.json alongside HTML for frontend rendering.

    Args:
        html_path: Path to the saved HTML file.
        gdf: GeoDataFrame to export as GeoJSON (primary dataset).
        layers: List of layer config dicts for the frontend MapPanel.
        center: [lat, lng] map center. Auto-calculated if None.
        zoom: Zoom level. Defaults to 12 if None.
        pitch: 3D camera pitch angle (0-60). None omits from config.
        bearing: 3D camera bearing angle. None omits from config.
    """
    try:
        gdf_4326 = gdf.to_crs(epsg=4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
        geojson_path = html_path.replace('.html', '.geojson')
        gdf_4326.to_file(geojson_path, driver='GeoJSON')

        if center is None:
            center = [
                float(gdf_4326.geometry.centroid.y.mean()),
                float(gdf_4326.geometry.centroid.x.mean()),
            ]
        if zoom is None:
            zoom = 12

        geojson_filename = os.path.basename(geojson_path)
        for layer in layers:
            if 'geojson' not in layer:
                layer['geojson'] = geojson_filename

        config = {"layers": layers, "center": center, "zoom": zoom}
        if pitch is not None:
            config["pitch"] = pitch
        if bearing is not None:
            config["bearing"] = bearing
        config_path = html_path.replace('.html', '.mapconfig.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)
    except Exception as e:
        # Non-fatal: HTML still works, just no frontend map rendering
        print(f"[MapConfig] Warning: could not save map config: {e}")


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def visualize_optimization_comparison(original_data_path: str, optimized_data_path: str) -> str:
    """生成优化前后对比图。"""
    try:
        _configure_fonts()
        gdf_orig = _load_spatial_data(original_data_path)
        gdf_opt = _load_spatial_data(optimized_data_path)

        OTHER, FARMLAND, FOREST = drl_engine.OTHER, drl_engine.FARMLAND, drl_engine.FOREST

        orig_cols = {c.lower(): c for c in gdf_orig.columns}
        dlmc_col = orig_cols.get('dlmc', 'DLMC')
        if dlmc_col not in gdf_orig.columns:
             return f"Error: Column 'DLMC' not found in original data. Available: {list(gdf_orig.columns)}"

        opt_cols = {c.lower(): c for c in gdf_opt.columns}
        opt_type_col = opt_cols.get('opt_type', 'Opt_Type')

        def map_dlmc(val):
            if val in {'旱地', '水田'}: return FARMLAND
            if val in {'果园', '有林地'}: return FOREST
            return OTHER

        initial = gdf_orig[dlmc_col].apply(map_dlmc).values
        final = gdf_opt[opt_type_col].values

        cmap = {OTHER: '#D3D3D3', FARMLAND: '#FFD700', FOREST: '#228B22'}
        fig, axes = plt.subplots(1, 3, figsize=(26, 8))

        gdf_orig['c'] = [cmap[t] for t in initial]
        gdf_orig.plot(ax=axes[0], color=gdf_orig['c'], edgecolor='none')
        axes[0].set_title('优化前现状 (Before)', fontsize=16, fontweight='bold')
        axes[0].set_axis_off()

        gdf_opt['c'] = [cmap[t] for t in final]
        gdf_opt.plot(ax=axes[1], color=gdf_opt['c'], edgecolor='none')
        axes[1].set_title('优化后布局 (After)', fontsize=16, fontweight='bold')
        axes[1].set_axis_off()

        patches_type = [
            mpatches.Patch(color='#FFD700', label='耕地'),
            mpatches.Patch(color='#228B22', label='林地'),
            mpatches.Patch(color='#D3D3D3', label='其他'),
        ]
        axes[0].legend(handles=patches_type, loc='lower left', fontsize=11, title="用地类型")

        change = np.zeros(len(gdf_orig), dtype=np.int8)
        change[(initial == FARMLAND) & (final == FOREST)] = 1
        change[(initial == FOREST) & (final == FARMLAND)] = 2
        diff_colors = {0: '#F0F0F0', 1: '#FF4444', 2: '#4488FF'}
        gdf_orig['diff_c'] = [diff_colors[c] for c in change]
        gdf_orig.plot(ax=axes[2], color=gdf_orig['diff_c'], edgecolor='none')
        axes[2].set_title('空间置换差异图 (Swap Map)', fontsize=16, fontweight='bold')
        axes[2].set_axis_off()

        n_f2l = int((change == 1).sum())
        n_l2f = int((change == 2).sum())
        patches_diff = [
            mpatches.Patch(color='#F0F0F0', label='未变化'),
            mpatches.Patch(color='#FF4444', label=f'耕地 -> 林地 ({n_f2l}块)\n(退耕还林/坡度优化)'),
            mpatches.Patch(color='#4488FF', label=f'林地 -> 耕地 ({n_l2f}块)\n(宜耕资源开发)'),
        ]
        axes[2].legend(handles=patches_diff, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=11, title="置换类型说明")

        out_path = _generate_output_path("comparison", "png")
        plt.tight_layout()
        plt.savefig(out_path, dpi=300, bbox_inches='tight')
        plt.close()
        return f"Comparison visualization saved to {out_path}"
    except Exception as e: return f"Error: {str(e)}"


def visualize_interactive_map(original_data_path: str, optimized_data_path: str = None, center_lat: float = None, center_lng: float = None, zoom: int = None, sql_filter: str = None) -> str:
    """
    Generate multi-layer interactive map.
    Supports:
    1. Comparison Mode (if optimized_data_path provided): Original vs Optimized Polygons.
    2. Analysis Mode (if point data): Heatmap + Clustered Markers.

    Args:
        original_data_path: 空间数据路径或 PostGIS 表名。
        optimized_data_path: 可选，优化后的数据路径（对比模式）。
        center_lat: 可选，地图中心纬度。不指定则自动根据数据范围居中。
        center_lng: 可选，地图中心经度。不指定则自动根据数据范围居中。
        zoom: 可选，缩放级别(1-18)。不指定则自动计算。
        sql_filter: 可选，SQL WHERE 过滤条件（仅对 PostGIS 表名有效）。例如: "county LIKE '%璧山%'"
    """
    try:
        gdf_orig = _load_spatial_data_with_filter(original_data_path, sql_filter)
        # Ensure CRS is set before transforming. Assume WGS84 or project default if not set.
        if gdf_orig.crs is None:
            gdf_orig.set_crs(epsg=4326, inplace=True)
            print("[Warning] No CRS found in original data. Assuming EPSG:4326 for map rendering.")
        gdf_orig = gdf_orig.to_crs(epsg=4326)

        if center_lat is not None and center_lng is not None:
            center = [center_lat, center_lng]
        else:
            center = [gdf_orig.geometry.centroid.y.mean(), gdf_orig.geometry.centroid.x.mean()]
        zoom_start = zoom if zoom is not None else 14
        m = folium.Map(location=center, zoom_start=zoom_start, tiles='CartoDB positron', control_scale=True)

        _add_basemap_layers(m)

        is_point = any(t in ['Point', 'MultiPoint'] for t in gdf_orig.geom_type.unique())

        if is_point:
            points = gdf_orig[~gdf_orig.geometry.is_empty & gdf_orig.geometry.notna()]
            heat_data = [[p.y, p.x] for p in points.geometry]
            plugins.HeatMap(heat_data, name="热力图 (Heatmap)", show=True).add_to(m)

            cols_lower = {c.lower(): c for c in gdf_orig.columns}
            cluster_col = cols_lower.get('cluster_id')

            if cluster_col:
                import matplotlib.colors as mcolors
                base_colors = list(mcolors.TABLEAU_COLORS.values())

                def get_color(cid):
                    if cid == -1: return 'gray'
                    return base_colors[cid % len(base_colors)]

                for idx, row in gdf_orig.iterrows():
                    cid = row[cluster_col]
                    folium.CircleMarker(
                        location=[row.geometry.y, row.geometry.x],
                        radius=5,
                        color=get_color(cid),
                        fill=True,
                        fill_opacity=0.7,
                        popup=f"Cluster: {cid}",
                        tooltip=f"Cluster: {cid}"
                    ).add_to(m)
            else:
                marker_cluster = plugins.MarkerCluster(name="点位聚合 (Markers)").add_to(m)
                for idx, row in points.iterrows():
                    folium.Marker([row.geometry.y, row.geometry.x]).add_to(marker_cluster)

        elif optimized_data_path:
            gdf_opt = _load_spatial_data(optimized_data_path)
            if gdf_opt.crs is None:
                gdf_opt.set_crs(epsg=4326, inplace=True)
            gdf_opt = gdf_opt.to_crs(epsg=4326)

            orig_cols = {c.lower(): c for c in gdf_orig.columns}
            dlmc_col = orig_cols.get('dlmc', 'DLMC')
            slope_col = orig_cols.get('slope', 'Slope')
            shape_area_col = orig_cols.get('shape_area', 'Shape_Area')

            opt_cols = {c.lower(): c for c in gdf_opt.columns}
            opt_type_col = opt_cols.get('opt_type', 'Opt_Type')

            OTHER, FARMLAND, FOREST = drl_engine.OTHER, drl_engine.FARMLAND, drl_engine.FOREST

            def map_dlmc(val):
                if val in {'旱地', '水田', '耕地'}: return FARMLAND
                if val in {'果园', '有林地', '林地'}: return FOREST
                return OTHER

            if dlmc_col in gdf_orig.columns:
                gdf_orig['Type_Int'] = gdf_orig[dlmc_col].apply(map_dlmc)
            else:
                 gdf_orig['Type_Int'] = OTHER

            if opt_type_col in gdf_opt.columns:
                gdf_opt['Type_Int'] = gdf_opt[opt_type_col]
            else:
                gdf_opt['Type_Int'] = OTHER

            change_mask = np.zeros(len(gdf_orig), dtype=np.int8)
            initial = gdf_orig['Type_Int'].values
            final = gdf_opt['Type_Int'].values
            change_mask[(initial == FARMLAND) & (final == FOREST)] = 1
            change_mask[(initial == FOREST) & (final == FARMLAND)] = 2

            gdf_diff = gdf_orig.copy()
            gdf_diff['Change_Type'] = change_mask
            gdf_diff = gdf_diff[gdf_diff['Change_Type'] > 0]

            def style_type(feature):
                t = feature['properties']['Type_Int']
                color = '#808080'
                if t == FARMLAND: color = '#FFD700'
                elif t == FOREST: color = '#228B22'
                return {'fillColor': color, 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.6}

            def style_diff(feature):
                c = feature['properties']['Change_Type']
                color = 'gray'
                if c == 1: color = '#FF4444'
                elif c == 2: color = '#4488FF'
                return {'fillColor': color, 'color': color, 'weight': 1, 'fillOpacity': 0.8}

            tooltip_fields = [c for c in [dlmc_col, slope_col, shape_area_col] if c in gdf_orig.columns]

            folium.GeoJson(
                gdf_orig,
                name='优化前现状 (Before)',
                style_function=style_type,
                tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=['地类:', '坡度:', '面积:']) if tooltip_fields else None,
                show=False
            ).add_to(m)

            folium.GeoJson(
                gdf_opt,
                name='优化后布局 (After)',
                style_function=style_type,
                tooltip=folium.GeoJsonTooltip(fields=[opt_type_col, slope_col], aliases=['优化类型(1耕2林):', '坡度:']) if opt_type_col in gdf_opt.columns else None,
                show=True
            ).add_to(m)

            if not gdf_diff.empty:
                folium.GeoJson(
                    gdf_diff,
                    name='空间置换差异 (Changes)',
                    style_function=style_diff,
                    tooltip=folium.GeoJsonTooltip(fields=[dlmc_col, slope_col, 'Change_Type'],
                                                 aliases=['原类型:', '坡度:', '变化(1退耕2开垦):']) if dlmc_col in gdf_diff.columns else None,
                    show=True
                ).add_to(m)
        else:
            folium.GeoJson(gdf_orig, name="Data Layer").add_to(m)

        folium.LayerControl(collapsed=False).add_to(m)

        output_path = _generate_output_path("interactive_map", "html")
        m.save(output_path)

        # Save map config for frontend Leaflet rendering
        if is_point:
            layers_cfg = [{"name": "Points", "type": "point"}]
        elif optimized_data_path:
            # Categorized layers for per-feature coloring on the map panel
            layers_cfg = [
                {
                    "name": "优化后布局",
                    "type": "categorized",
                    "category_column": "Opt_Type",
                    "category_colors": {
                        "0": "#D3D3D3", "1": "#FFD700", "2": "#228B22",
                    },
                    "category_labels": {
                        "0": "其他", "1": "耕地", "2": "林地",
                    },
                    "style": {"fillOpacity": 0.6, "weight": 0.5},
                },
            ]
            # Save optimized data as separate GeoJSON
            try:
                gdf_opt_4326 = gdf_opt.to_crs(epsg=4326) if gdf_opt.crs and gdf_opt.crs.to_epsg() != 4326 else gdf_opt
                opt_geojson = output_path.replace('.html', '_opt.geojson')
                gdf_opt_4326.to_file(opt_geojson, driver='GeoJSON')
                layers_cfg[0]["geojson"] = os.path.basename(opt_geojson)
            except Exception:
                pass
            # Save changes diff layer
            try:
                if not gdf_diff.empty:
                    gdf_diff_4326 = gdf_diff.to_crs(epsg=4326) if gdf_diff.crs and gdf_diff.crs.to_epsg() != 4326 else gdf_diff
                    diff_geojson = output_path.replace('.html', '_diff.geojson')
                    gdf_diff_4326.to_file(diff_geojson, driver='GeoJSON')
                    layers_cfg.append({
                        "name": "空间置换差异",
                        "type": "categorized",
                        "geojson": os.path.basename(diff_geojson),
                        "category_column": "Change_Type",
                        "category_colors": {
                            "1": "#FF4444", "2": "#4488FF",
                        },
                        "category_labels": {
                            "1": "耕地→林地", "2": "林地→耕地",
                        },
                        "style": {"fillOpacity": 0.8, "weight": 1},
                    })
            except Exception:
                pass
        else:
            layers_cfg = [{"name": "Data Layer", "type": "polygon"}]

        _save_map_config(output_path, gdf_orig, layers_cfg,
                         center=center, zoom=zoom_start)

        return f"Interactive comparison map saved to {output_path}"

    except Exception as e:
        return f"Error generating interactive map: {str(e)}"


def generate_choropleth(
    file_path: str,
    value_column: str,
    color_scheme: str = "YlOrRd",
    classification_method: str = "quantile",
    num_classes: int = 5,
    legend_title: str = None,
    center_lat: float = None,
    center_lng: float = None,
    zoom: int = None
) -> str:
    """
    生成等值区域图 (Choropleth Map)。
    根据指定数值字段对多边形进行分级设色可视化。

    Args:
        file_path: 多边形矢量数据路径 (SHP/GeoJSON/GPKG) 或 PostGIS 表名。
        value_column: 用于设色的数值字段名。
        color_scheme: 颜色方案，支持: YlOrRd, YlGnBu, RdYlGn, Blues, Greens, Reds, Spectral。
        classification_method: 分级方法 - quantile(分位数), equal_interval(等间距), natural_breaks(自然断点)。
        num_classes: 分级数量，3-9之间。
        legend_title: 图例标题，默认使用 value_column 名。
        center_lat: 可选，地图中心纬度。不指定则自动根据数据范围居中。
        center_lng: 可选，地图中心经度。不指定则自动根据数据范围居中。
        zoom: 可选，缩放级别(1-18)。不指定则自动计算。

    Returns:
        生成的 HTML 交互地图路径。
    """
    try:
        gdf = _load_spatial_data(file_path).to_crs(epsg=4326)

        if value_column not in gdf.columns:
            available = [c for c in gdf.columns if c != 'geometry']
            return f"Error: 字段 '{value_column}' 不存在。可用字段: {available}"

        gdf[value_column] = pd.to_numeric(gdf[value_column], errors='coerce')
        valid = gdf[gdf[value_column].notna()]
        if len(valid) == 0:
            return f"Error: 字段 '{value_column}' 无有效数值数据"

        values = valid[value_column].values
        num_classes = max(3, min(num_classes, 9))

        if classification_method == "equal_interval":
            classifier = mapclassify.EqualInterval(values, k=num_classes)
        elif classification_method == "natural_breaks":
            classifier = mapclassify.NaturalBreaks(values, k=num_classes)
        else:
            classifier = mapclassify.Quantiles(values, k=num_classes)

        scheme_map = {
            "YlOrRd": cm.linear.YlOrRd_09,
            "YlGnBu": cm.linear.YlGnBu_09,
            "RdYlGn": cm.linear.RdYlGn_09,
            "Blues": cm.linear.Blues_09,
            "Greens": cm.linear.Greens_09,
            "Reds": cm.linear.Reds_09,
            "Spectral": cm.linear.Spectral_09,
        }
        base_cmap = scheme_map.get(color_scheme, cm.linear.YlOrRd_09)
        vmin, vmax = float(values.min()), float(values.max())
        colormap = base_cmap.scale(vmin, vmax)
        colormap.caption = legend_title or value_column

        if center_lat is not None and center_lng is not None:
            center = [center_lat, center_lng]
        else:
            center = [valid.geometry.centroid.y.mean(), valid.geometry.centroid.x.mean()]
        zoom_start = zoom if zoom is not None else 13
        m = folium.Map(location=center, zoom_start=zoom_start, tiles='CartoDB positron', control_scale=True)

        _add_basemap_layers(m)

        def style_function(feature):
            val = feature['properties'].get(value_column)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return {'fillColor': '#808080', 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.4}
            return {'fillColor': colormap(val), 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.7}

        tooltip_fields = [value_column]
        other_fields = [c for c in valid.columns if c not in ('geometry', value_column)][:3]
        tooltip_fields.extend(other_fields)

        folium.GeoJson(
            valid,
            name=f'Choropleth ({value_column})',
            style_function=style_function,
            tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=[f"{c}:" for c in tooltip_fields]),
        ).add_to(m)

        colormap.add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)

        output_path = _generate_output_path("choropleth", "html")
        m.save(output_path)

        # Save map config for frontend Leaflet rendering
        breaks = [float(b) for b in classifier.bins]
        _save_map_config(output_path, valid, [{
            "name": f"Choropleth ({value_column})",
            "type": "choropleth",
            "value_column": value_column,
            "breaks": breaks,
            "color_scheme": color_scheme,
        }], center=center, zoom=zoom_start)

        return (
            f"等值区域图已生成: {output_path}\n"
            f"分级方法: {classification_method}, 分级数: {num_classes}, 配色: {color_scheme}"
        )

    except FileNotFoundError:
        return f"Error: 文件未找到 {file_path}。Recovery: 请先调用 search_data_assets 或 list_user_files 检查可用文件"
    except Exception as e:
        err = str(e)
        recovery = ""
        if "column" in err.lower() or "not in" in err.lower() or "KeyError" in err:
            recovery = " Recovery: 请先调用 describe_geodataframe 查看可用字段列表"
        elif "CRS" in err or "crs" in err:
            recovery = " Recovery: 请先调用 reproject_spatial_data 统一坐标系"
        elif "empty" in err.lower() or "0 records" in err:
            recovery = " Recovery: 数据为空，请检查输入文件或筛选条件是否过于严格"
        return f"Error generating choropleth: {err}{recovery}"


def generate_bubble_map(
    file_path: str,
    size_column: str,
    color_column: str = None,
    color_scheme: str = "YlOrRd",
    max_radius: int = 30,
    legend_title: str = None
) -> str:
    """
    生成气泡地图 (Bubble Map)。
    根据数值字段控制圆圈大小，可选按另一字段着色。适用于点数据。

    Args:
        file_path: 点数据路径 (SHP/GeoJSON/CSV/Excel)。
        size_column: 控制气泡大小的数值字段名。
        color_column: 可选，控制气泡颜色的数值字段名。
        color_scheme: 颜色方案 (YlOrRd, YlGnBu, RdYlGn, Blues, Greens, Reds, Spectral)。
        max_radius: 最大气泡半径 (像素)，默认30。
        legend_title: 图例标题。

    Returns:
        生成的 HTML 交互地图路径。
    """
    try:
        gdf = _load_spatial_data(file_path).to_crs(epsg=4326)

        if size_column not in gdf.columns:
            available = [c for c in gdf.columns if c != 'geometry']
            return f"Error: 字段 '{size_column}' 不存在。可用字段: {available}"

        gdf[size_column] = pd.to_numeric(gdf[size_column], errors='coerce')
        valid = gdf[gdf[size_column].notna()].copy()
        if len(valid) == 0:
            return f"Error: 字段 '{size_column}' 无有效数值数据"

        min_val = valid[size_column].min()
        max_val = valid[size_column].max()
        val_range = max_val - min_val
        if val_range > 0:
            valid['_radius'] = 3 + (valid[size_column] - min_val) / val_range * (max_radius - 3)
        else:
            valid['_radius'] = (3 + max_radius) / 2

        colormap_obj = None
        if color_column and color_column in valid.columns:
            valid[color_column] = pd.to_numeric(valid[color_column], errors='coerce')
            color_vals = valid[color_column].dropna()
            if len(color_vals) > 0:
                scheme_map = {
                    "YlOrRd": cm.linear.YlOrRd_09,
                    "YlGnBu": cm.linear.YlGnBu_09,
                    "RdYlGn": cm.linear.RdYlGn_09,
                    "Blues": cm.linear.Blues_09,
                    "Greens": cm.linear.Greens_09,
                    "Reds": cm.linear.Reds_09,
                    "Spectral": cm.linear.Spectral_09,
                }
                base_cmap = scheme_map.get(color_scheme, cm.linear.YlOrRd_09)
                colormap_obj = base_cmap.scale(float(color_vals.min()), float(color_vals.max()))
                colormap_obj.caption = legend_title or color_column

        center = [valid.geometry.centroid.y.mean(), valid.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=13, tiles='CartoDB positron', control_scale=True)

        _add_basemap_layers(m)

        tooltip_cols = [size_column]
        if color_column and color_column in valid.columns:
            tooltip_cols.append(color_column)
        other_cols = [c for c in valid.columns if c not in ('geometry', '_radius', size_column, color_column)][:2]
        tooltip_cols.extend(other_cols)

        for _, row in valid.iterrows():
            radius = row['_radius']
            if colormap_obj and color_column and pd.notna(row.get(color_column)):
                fill_color = colormap_obj(row[color_column])
            else:
                fill_color = '#3388ff'

            tooltip_text = "<br>".join(f"<b>{c}</b>: {row.get(c, '')}" for c in tooltip_cols if c in row.index)

            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=radius,
                color='#333333',
                weight=0.5,
                fill=True,
                fill_color=fill_color,
                fill_opacity=0.7,
                tooltip=tooltip_text,
            ).add_to(m)

        if colormap_obj:
            colormap_obj.add_to(m)

        folium.LayerControl(collapsed=False).add_to(m)

        output_path = _generate_output_path("bubble_map", "html")
        m.save(output_path)

        # Save map config for frontend Leaflet rendering
        _save_map_config(output_path, valid, [{
            "name": f"Bubble ({size_column})",
            "type": "bubble",
            "value_column": size_column,
            "style": {"max_radius": max_radius, "min_radius": 3},
            "color_scheme": color_scheme,
        }], center=center, zoom=13)

        msg = f"气泡地图已生成: {output_path}\n大小字段: {size_column}"
        if color_column:
            msg += f", 颜色字段: {color_column}, 配色: {color_scheme}"
        return msg

    except Exception as e:
        return f"Error generating bubble map: {str(e)}"


def visualize_geodataframe(file_path: str) -> str:
    """可视化单份地理数据（静态）。"""
    try:
        _configure_fonts()
        gdf = _load_spatial_data(file_path)
        fig, ax = plt.subplots(1, 1, figsize=(10, 10))

        cols_lower = {c.lower(): c for c in gdf.columns}
        dlmc_col = cols_lower.get('dlmc', 'DLMC')

        if dlmc_col not in gdf.columns:
            gdf[dlmc_col] = 'Unknown'

        colors = gdf[dlmc_col].apply(lambda x: {'建制镇': '#87CEEB', '村庄': '#87CEEB', '旱地': '#F9FAE8', '水田': '#F9FAE8', '果园': '#FFC0CB', '有林地': '#228B22'}.get(x, '#FFFFFF'))
        gdf.plot(ax=ax, color=colors.tolist(), edgecolor='black', alpha=0.7)
        ax.set_title("土地利用现状图 (Land Use Map)", fontsize=15)
        ax.set_axis_off()
        out = _generate_output_path("visualization", "png")
        plt.savefig(out, dpi=300)
        plt.close()
        return f"Visualization saved to {out}"
    except Exception as e: return f"Error: {str(e)}"


def export_map_png(file_path: str, value_column: str = None, title: str = None) -> str:
    """
    将空间数据导出为带底图的高清 PNG 地图图片，可用于报告和分享。
    支持文件路径或 PostGIS 表名。

    Args:
        file_path: 空间数据文件路径（.shp/.geojson等）或 PostGIS 表名。
        value_column: 可选，用于着色的数值字段名。不指定则统一着色。
        title: 可选，地图标题。
    Returns:
        生成的 PNG 文件路径。
    """
    try:
        _configure_fonts()
        gdf = _load_spatial_data(file_path)

        if gdf.crs and not gdf.crs.is_geographic:
            gdf_plot = gdf.copy()
        else:
            gdf_plot = gdf.to_crs(epsg=3857)

        fig, ax = plt.subplots(1, 1, figsize=(12, 10))

        if value_column and value_column in gdf_plot.columns:
            gdf_plot.plot(
                ax=ax, column=value_column, cmap='YlOrRd',
                legend=True, legend_kwds={'label': value_column, 'shrink': 0.6},
                edgecolor='black', linewidth=0.3, alpha=0.8,
            )
        else:
            gdf_plot.plot(ax=ax, color='#4A90D9', edgecolor='black', linewidth=0.3, alpha=0.7)

        try:
            cx.add_basemap(ax, source=cx.providers.CartoDB.Positron)
        except Exception:
            pass

        ax.set_axis_off()
        if title:
            ax.set_title(title, fontsize=16, pad=12)

        out = _generate_output_path("map_export", "png")
        plt.savefig(out, dpi=200, bbox_inches='tight', pad_inches=0.1)
        plt.close()
        return f"地图已导出为 PNG: {out}"
    except Exception as e:
        return f"Error exporting map PNG: {str(e)}"


def compose_map(
    layers_json: str,
    center_lat: float = None,
    center_lng: float = None,
    zoom: int = None,
) -> str:
    """将多个数据源叠加到同一张交互地图上，每个图层可独立切换显隐。

    Args:
        layers_json: JSON 数组字符串，每个元素定义一个图层。
            必填字段:
              - data_path (str): 数据文件路径或 PostGIS 表名
              - name (str): 图层名称，显示在图层控件中
              - type (str): point(点标记) | polygon(面填充) | choropleth(分级设色) | heatmap(热力图) | bubble(气泡图)
            可选字段:
              - color (str): 填充色，默认 "#3388ff"
              - opacity (float): 透明度 0-1，默认 0.7
              - value_column (str): choropleth/bubble 必填，数值字段名
              - color_scheme (str): 配色方案，默认 "YlOrRd"。可选: YlGnBu, RdYlGn, Blues, Greens, Reds, Spectral
              - classification_method (str): choropleth 分级方法，默认 "quantile"。可选: equal_interval, natural_breaks
              - num_classes (int): choropleth 分级数，默认 5
              - radius (int): point 圆圈半径(px)，默认 6
              - max_radius (int): bubble 最大半径(px)，默认 25
              - weight_field (str): heatmap 权重字段
        center_lat: 地图中心纬度，不指定则自动计算。
        center_lng: 地图中心经度，不指定则自动计算。
        zoom: 缩放级别(1-18)，不指定则自动适配。

    Returns:
        生成的 HTML 交互地图路径，或错误信息。

    示例 layers_json:
        [{"data_path":"stores.csv","name":"门店分布","type":"point","color":"#e74c3c"},
         {"data_path":"buffer.shp","name":"服务范围","type":"polygon","color":"#3498db","opacity":0.3}]
    """
    import json

    try:
        layers = json.loads(layers_json)
    except (json.JSONDecodeError, TypeError) as e:
        return f"Error: layers_json 解析失败 — {e}"

    if not isinstance(layers, list) or len(layers) == 0:
        return "Error: layers_json 必须是非空 JSON 数组"
    if len(layers) > 10:
        return "Error: 最多支持 10 个图层"

    try:
        # --- Phase 1: Load all data and collect bounds ---
        loaded = []
        all_bounds = []

        for i, spec in enumerate(layers):
            data_path = spec.get("data_path")
            if not data_path:
                return f"Error: 第 {i+1} 个图层缺少 data_path"

            gdf = _load_spatial_data(data_path).to_crs(epsg=4326)
            if gdf.empty:
                continue

            loaded.append((spec, gdf))
            all_bounds.append(gdf.total_bounds)  # [minx, miny, maxx, maxy]

        if not loaded:
            return "Error: 所有图层均为空数据"

        # --- Phase 2: Create map with auto-center ---
        if center_lat is not None and center_lng is not None:
            center = [center_lat, center_lng]
        else:
            bounds_arr = np.array(all_bounds)
            center = [
                (bounds_arr[:, 1].min() + bounds_arr[:, 3].max()) / 2,
                (bounds_arr[:, 0].min() + bounds_arr[:, 2].max()) / 2,
            ]
        zoom_start = zoom if zoom is not None else 13

        m = folium.Map(location=center, zoom_start=zoom_start,
                       tiles="CartoDB positron", control_scale=True)
        _add_basemap_layers(m)

        # --- Phase 3: Render each layer ---
        for spec, gdf in loaded:
            layer_name = spec.get("name", "Layer")
            layer_type = spec.get("type", "polygon").lower()
            color = spec.get("color", "#3388ff")
            opacity = float(spec.get("opacity", 0.7))

            fg = folium.FeatureGroup(name=layer_name)

            if layer_type == "point":
                radius = int(spec.get("radius", 6))
                _render_point_layer(gdf, fg, color, opacity, radius, layer_name)

            elif layer_type == "polygon":
                _render_polygon_layer(gdf, fg, color, opacity)

            elif layer_type == "choropleth":
                value_column = spec.get("value_column")
                if not value_column or value_column not in gdf.columns:
                    avail = [c for c in gdf.columns if c != "geometry"]
                    return (f"Error: 图层 '{layer_name}' (choropleth) 的 value_column "
                            f"'{value_column}' 不存在。可用字段: {avail}")
                _render_choropleth_layer(gdf, fg, m, spec, layer_name)

            elif layer_type == "heatmap":
                _render_heatmap_layer(gdf, fg, spec, layer_name)

            elif layer_type == "bubble":
                value_column = spec.get("value_column")
                if not value_column or value_column not in gdf.columns:
                    avail = [c for c in gdf.columns if c != "geometry"]
                    return (f"Error: 图层 '{layer_name}' (bubble) 的 value_column "
                            f"'{value_column}' 不存在。可用字段: {avail}")
                _render_bubble_layer(gdf, fg, spec, color, opacity, layer_name)

            else:
                return f"Error: 不支持的图层类型 '{layer_type}'。支持: point, polygon, choropleth, heatmap, bubble"

            fg.add_to(m)

        # --- Phase 4: Finalize ---
        folium.LayerControl(collapsed=False).add_to(m)

        output_path = _generate_output_path("composed_map", "html")
        m.save(output_path)

        # Save map config for frontend Leaflet rendering
        frontend_layers = []
        for idx, (spec, gdf) in enumerate(loaded):
            layer_geojson = output_path.replace('.html', f'_layer{idx}.geojson')
            try:
                gdf.to_file(layer_geojson, driver='GeoJSON')
            except Exception:
                continue
            layer_cfg = {
                "name": spec.get("name", f"Layer {idx}"),
                "type": spec.get("type", "polygon"),
                "geojson": os.path.basename(layer_geojson),
                "style": {"color": spec.get("color", "#3388ff"),
                           "fillOpacity": float(spec.get("opacity", 0.7))},
            }
            if spec.get("value_column"):
                layer_cfg["value_column"] = spec["value_column"]
            if spec.get("color_scheme"):
                layer_cfg["color_scheme"] = spec["color_scheme"]
            frontend_layers.append(layer_cfg)

        if frontend_layers:
            config_data = {"layers": frontend_layers, "center": center, "zoom": zoom_start}
            config_path = output_path.replace('.html', '.mapconfig.json')
            try:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, ensure_ascii=False)
            except Exception:
                pass

        layer_summary = ", ".join(
            f"{s.get('name', 'Layer')}({s.get('type', 'polygon')})"
            for s, _ in loaded
        )
        return f"多图层地图已生成: {output_path}\n包含 {len(loaded)} 个图层: {layer_summary}"

    except Exception as e:
        return f"Error in compose_map: {str(e)}"


# --- compose_map helper renderers ---

def _render_point_layer(gdf, fg, color, opacity, radius, layer_name):
    """Render point markers into a FeatureGroup."""
    for _, row in gdf.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        pt = row.geometry.centroid
        tooltip_parts = [
            f"<b>{c}</b>: {row[c]}"
            for c in gdf.columns if c != "geometry" and pd.notna(row.get(c))
        ][:5]
        folium.CircleMarker(
            location=[pt.y, pt.x], radius=radius,
            color=color, fill=True, fill_color=color, fill_opacity=opacity,
            tooltip="<br>".join(tooltip_parts) if tooltip_parts else layer_name,
        ).add_to(fg)


def _render_polygon_layer(gdf, fg, color, opacity):
    """Render polygon fill into a FeatureGroup."""
    tooltip_fields = [c for c in gdf.columns if c != "geometry"][:4]
    folium.GeoJson(
        gdf,
        style_function=lambda feature, c=color, o=opacity: {
            "fillColor": c, "color": c, "weight": 1, "fillOpacity": o,
        },
        tooltip=(folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=[f"{c}:" for c in tooltip_fields],
        ) if tooltip_fields else None),
    ).add_to(fg)


def _render_choropleth_layer(gdf, fg, m, spec, layer_name):
    """Render classified choropleth into a FeatureGroup + map legend."""
    value_column = spec["value_column"]
    gdf[value_column] = pd.to_numeric(gdf[value_column], errors="coerce")
    valid = gdf[gdf[value_column].notna()]
    if valid.empty:
        return

    values = valid[value_column].values
    color_scheme = spec.get("color_scheme", "YlOrRd")
    classification_method = spec.get("classification_method", "quantile")
    num_classes = max(3, min(int(spec.get("num_classes", 5)), 9))

    if classification_method == "equal_interval":
        classifier = mapclassify.EqualInterval(values, k=num_classes)
    elif classification_method == "natural_breaks":
        classifier = mapclassify.NaturalBreaks(values, k=num_classes)
    else:
        classifier = mapclassify.Quantiles(values, k=num_classes)

    scheme_map = {
        "YlOrRd": cm.linear.YlOrRd_09, "YlGnBu": cm.linear.YlGnBu_09,
        "RdYlGn": cm.linear.RdYlGn_09, "Blues": cm.linear.Blues_09,
        "Greens": cm.linear.Greens_09, "Reds": cm.linear.Reds_09,
        "Spectral": cm.linear.Spectral_09,
    }
    base_cmap = scheme_map.get(color_scheme, cm.linear.YlOrRd_09)
    vmin, vmax = float(values.min()), float(values.max())
    colormap_obj = base_cmap.scale(vmin, vmax)
    colormap_obj.caption = f"{layer_name} ({value_column})"

    def choro_style(feature, vc=value_column, cmap=colormap_obj):
        val = feature["properties"].get(vc)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return {"fillColor": "#808080", "color": "black", "weight": 0.5, "fillOpacity": 0.4}
        return {"fillColor": cmap(val), "color": "black", "weight": 0.5, "fillOpacity": 0.7}

    tooltip_fields = [value_column] + [
        c for c in valid.columns if c not in ("geometry", value_column)
    ][:3]
    folium.GeoJson(
        valid, style_function=choro_style,
        tooltip=folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=[f"{c}:" for c in tooltip_fields],
        ),
    ).add_to(fg)
    colormap_obj.add_to(m)


def _render_heatmap_layer(gdf, fg, spec, layer_name):
    """Render interactive heatmap into a FeatureGroup."""
    points = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    weight_field = spec.get("weight_field")

    if weight_field and weight_field in points.columns:
        weights = pd.to_numeric(points[weight_field], errors="coerce").fillna(0).values
        w_max = weights.max()
        if w_max > 0:
            weights = weights / w_max
        heat_data = [
            [row.geometry.centroid.y, row.geometry.centroid.x, float(w)]
            for (_, row), w in zip(points.iterrows(), weights)
        ]
    else:
        heat_data = [
            [row.geometry.centroid.y, row.geometry.centroid.x]
            for _, row in points.iterrows()
        ]

    plugins.HeatMap(
        heat_data, name=layer_name,
        radius=15, blur=10, max_zoom=18,
    ).add_to(fg)


def _render_bubble_layer(gdf, fg, spec, color, opacity, layer_name):
    """Render variable-size bubble markers into a FeatureGroup."""
    size_column = spec["value_column"]
    gdf[size_column] = pd.to_numeric(gdf[size_column], errors="coerce")
    valid = gdf[gdf[size_column].notna()].copy()
    if valid.empty:
        return

    max_radius = int(spec.get("max_radius", 25))
    min_val, max_val = valid[size_column].min(), valid[size_column].max()
    val_range = max_val - min_val

    for _, row in valid.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        pt = row.geometry.centroid
        r = 3 + (row[size_column] - min_val) / val_range * (max_radius - 3) if val_range > 0 else (3 + max_radius) / 2

        tooltip_parts = [
            f"<b>{c}</b>: {row[c]}"
            for c in valid.columns if c != "geometry" and pd.notna(row.get(c))
        ][:5]
        folium.CircleMarker(
            location=[pt.y, pt.x], radius=r,
            color=color, fill=True, fill_color=color, fill_opacity=opacity,
            tooltip="<br>".join(tooltip_parts) if tooltip_parts else layer_name,
        ).add_to(fg)


def generate_3d_map(
    data_path: str,
    elevation_column: str = "",
    value_column: str = "",
    elevation_scale: float = 1.0,
    layer_name: str = "3D Layer",
    layer_type: str = "extrusion",
    pitch: int = 45,
    bearing: int = 0,
) -> str:
    """生成 3D 拉伸/柱状地图，支持多边形高度拉伸和 3D 散点。

    在前端地图面板中自动切换到 3D 视图（deck.gl + MapLibre）。

    Args:
        data_path: 空间数据文件路径（.shp/.geojson/.gpkg等）或 PostGIS 表名。
        elevation_column: 用于控制 3D 高度的数值字段名。不指定则使用固定高度。
        value_column: 用于着色的数值字段名（分级设色）。不指定则统一着色。
        elevation_scale: 高度缩放系数，默认 1.0。增大此值使高度差更明显。
        layer_name: 图层名称，显示在地图面板中。
        layer_type: 3D 图层类型 — extrusion（多边形拉伸）、column（柱状图）、arc（弧线连接）。
        pitch: 3D 视角俯仰角（0-60），默认 45。
        bearing: 3D 视角方位角（-180~180），默认 0。

    Returns:
        生成的文件路径及说明。
    """
    try:
        gdf = _load_spatial_data(data_path)
        if gdf.empty:
            return "Error: 数据为空，无法生成 3D 地图"

        gdf_4326 = gdf.to_crs(epsg=4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf

        # Validate elevation_column
        if elevation_column and elevation_column not in gdf_4326.columns:
            available = [c for c in gdf_4326.columns if c != 'geometry']
            return f"Error: 高度字段 '{elevation_column}' 不存在。可用字段: {available}"

        # Validate value_column
        if value_column and value_column not in gdf_4326.columns:
            available = [c for c in gdf_4326.columns if c != 'geometry']
            return f"Error: 着色字段 '{value_column}' 不存在。可用字段: {available}"

        # Compute choropleth breaks if value_column specified
        breaks = None
        color_scheme = "YlOrRd"
        if value_column:
            gdf_4326[value_column] = pd.to_numeric(gdf_4326[value_column], errors='coerce')
            valid_vals = gdf_4326[value_column].dropna()
            if len(valid_vals) >= 5:
                classifier = mapclassify.Quantiles(valid_vals.values, k=5)
                breaks = [float(b) for b in classifier.bins]

        # Build layer config for frontend 3D rendering
        valid_types = ("extrusion", "column", "arc")
        if layer_type not in valid_types:
            layer_type = "extrusion"

        layer_cfg = {
            "name": layer_name,
            "type": layer_type,
            "extruded": True,
            "elevation_scale": elevation_scale,
            "pitch": max(0, min(60, pitch)),
            "bearing": max(-180, min(180, bearing)),
        }
        if elevation_column:
            layer_cfg["elevation_column"] = elevation_column
        if value_column:
            layer_cfg["value_column"] = value_column
        if breaks:
            layer_cfg["breaks"] = breaks
            layer_cfg["color_scheme"] = color_scheme

        # Save GeoJSON + mapconfig
        output_path = _generate_output_path("3d_map", "html")
        # Write a minimal HTML placeholder (actual rendering is in frontend)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"<html><body><h3>{layer_name}</h3>"
                    f"<p>3D visualization rendered in the map panel.</p></body></html>")

        _save_map_config(output_path, gdf_4326, [layer_cfg], pitch=pitch, bearing=bearing)

        msg = f"3D 地图已生成: {output_path}\n图层: {layer_name}, 类型: {layer_type}"
        if elevation_column:
            msg += f", 高度字段: {elevation_column} (×{elevation_scale})"
        if value_column:
            msg += f", 着色字段: {value_column}"
        return msg

    except Exception as e:
        return f"Error generating 3D map: {str(e)}"


# ---------------------------------------------------------------------------
# Natural Language Layer Control
# ---------------------------------------------------------------------------

def control_map_layer(action: str, layer_name: str = "", color: str = "",
                      opacity: float = -1, visible: bool = True) -> dict:
    """通过自然语言控制前端地图图层的显示、隐藏、样式修改和移除。

    Args:
        action: 操作类型 — show（显示）、hide（隐藏）、style（修改样式）、remove（移除）、list（列出所有图层）。
        layer_name: 目标图层名称。list 操作时可为空。
        color: 新的颜色（仅 style 操作），如 '#e63946'。
        opacity: 新的不透明度 0~1（仅 style 操作），-1 表示不修改。
        visible: 图层是否可见（show/hide 的快捷参数）。

    Returns:
        包含 layer_control 指令和 message 的字典，前端将自动执行对应操作。
    """
    valid_actions = ("show", "hide", "style", "remove", "list")
    if action not in valid_actions:
        return {"status": "error", "message": f"无效操作: {action}，支持: {', '.join(valid_actions)}"}

    if action != "list" and not layer_name:
        return {"status": "error", "message": "请指定图层名称（layer_name）"}

    control = {"action": action, "layer_name": layer_name}

    if action == "style":
        style_updates: dict = {}
        if color:
            style_updates["fillColor"] = color
            style_updates["color"] = color
        if 0 <= opacity <= 1:
            style_updates["fillOpacity"] = opacity
            style_updates["opacity"] = opacity
        control["style"] = style_updates

    action_labels = {
        "show": f"已显示图层「{layer_name}」",
        "hide": f"已隐藏图层「{layer_name}」",
        "style": f"已更新图层「{layer_name}」的样式",
        "remove": f"已移除图层「{layer_name}」",
        "list": "请查看地图面板中的图层控制按钮了解当前图层列表",
    }

    return {
        "status": "success",
        "layer_control": control,
        "message": action_labels[action],
    }


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    load_admin_boundary,
    visualize_optimization_comparison,
    visualize_interactive_map,
    generate_choropleth,
    generate_bubble_map,
    visualize_geodataframe,
    export_map_png,
    generate_heatmap,
    compose_map,
    generate_3d_map,
    control_map_layer,
]


class VisualizationToolset(BaseToolset):
    """Geospatial visualization tools: maps, charts, exports."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
