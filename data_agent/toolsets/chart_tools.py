"""
ChartToolset — 9 interactive chart tools producing Apache ECharts JSON configs (v14.4).

Each tool reads data from CSV/Excel/Shapefile and returns an ECharts option dict
that the frontend renders interactively via echarts-for-react.
"""
import os

import numpy as np
import pandas as pd

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..gis_processors import _resolve_path

# ---------------------------------------------------------------------------
# Theme colours (Teal / Amber, matching the app palette)
# ---------------------------------------------------------------------------

CHART_COLORS = [
    '#0d9488', '#f59e0b', '#6366f1', '#ec4899', '#10b981',
    '#8b5cf6', '#ef4444', '#3b82f6', '#14b8a6', '#f97316',
]


# ---------------------------------------------------------------------------
# Data-loading helper
# ---------------------------------------------------------------------------

def _load_dataframe(file_path: str) -> pd.DataFrame:
    """Load data from CSV/Excel/Shapefile into a pandas DataFrame."""
    resolved = _resolve_path(file_path)
    ext = os.path.splitext(resolved)[1].lower()
    if ext == '.csv':
        return pd.read_csv(resolved)
    elif ext in ('.xlsx', '.xls'):
        return pd.read_excel(resolved)
    elif ext in ('.shp', '.geojson', '.gpkg', '.kml'):
        import geopandas as gpd
        gdf = gpd.read_file(resolved)
        return pd.DataFrame(gdf.drop(columns='geometry', errors='ignore'))
    else:
        return pd.read_csv(resolved)  # fallback


# ---------------------------------------------------------------------------
# Shared ECharts helpers
# ---------------------------------------------------------------------------

def _base_option(title: str, tooltip_trigger: str = "axis") -> dict:
    """Return a base ECharts option dict with common settings."""
    return {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": tooltip_trigger},
        "color": CHART_COLORS,
        "grid": {"left": "10%", "right": "10%", "bottom": "15%"},
        "toolbox": {
            "feature": {
                "saveAsImage": {"title": "保存"},
                "dataView": {"title": "数据", "readOnly": True},
            }
        },
    }


def _safe_list(series: pd.Series) -> list:
    """Convert a pandas Series to a JSON-safe Python list."""
    return [None if pd.isna(v) else v for v in series.tolist()]


def _is_datetime_like(series: pd.Series) -> bool:
    """Heuristic: check if a string series looks like dates."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    try:
        sample = series.dropna().head(20).astype(str)
        pd.to_datetime(sample)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 1. Bar chart
# ---------------------------------------------------------------------------

def create_bar_chart(
    file_path: str,
    x_column: str,
    y_column: str,
    title: str = "",
    group_column: str = None,
    orientation: str = "vertical",
) -> dict:
    """柱状图：按类别展示数值对比，支持分组和水平/垂直方向。"""
    try:
        df = _load_dataframe(file_path)
        option = _base_option(title or "柱状图")
        horizontal = orientation.lower().startswith("h")

        if group_column and group_column in df.columns:
            groups = df[group_column].dropna().unique().tolist()
            categories = df[x_column].dropna().unique().tolist()
            series = []
            for g in groups:
                sub = df[df[group_column] == g]
                agg = sub.groupby(x_column)[y_column].sum().reindex(categories, fill_value=0)
                series.append({
                    "name": str(g),
                    "type": "bar",
                    "data": _safe_list(agg),
                })
            option["legend"] = {"data": [str(g) for g in groups], "top": "bottom"}
        else:
            categories = _safe_list(df[x_column])
            series = [{
                "name": y_column,
                "type": "bar",
                "data": _safe_list(df[y_column]),
            }]

        cat_axis = {"type": "category", "data": [str(c) for c in categories]}
        val_axis = {"type": "value", "name": y_column}

        if horizontal:
            option["xAxis"] = val_axis
            option["yAxis"] = cat_axis
        else:
            option["xAxis"] = cat_axis
            option["yAxis"] = val_axis

        option["series"] = series
        return {"chart_type": "bar", "option": option}
    except Exception as e:
        return {"chart_type": "bar", "error": str(e)}


# ---------------------------------------------------------------------------
# 2. Line chart
# ---------------------------------------------------------------------------

def create_line_chart(
    file_path: str,
    x_column: str,
    y_columns: str,
    title: str = "",
    smooth: bool = True,
) -> dict:
    """折线图：展示趋势变化，支持多系列和平滑曲线。"""
    try:
        df = _load_dataframe(file_path)
        option = _base_option(title or "折线图")

        cols = [c.strip() for c in y_columns.split(",") if c.strip()]
        x_data = _safe_list(df[x_column])

        # Format time axis when x looks like dates
        if _is_datetime_like(df[x_column]):
            option["xAxis"] = {"type": "time"}
            x_data_formatted = pd.to_datetime(df[x_column]).dt.strftime("%Y-%m-%d").tolist()
        else:
            option["xAxis"] = {"type": "category", "data": [str(v) for v in x_data]}
            x_data_formatted = None

        option["yAxis"] = {"type": "value"}

        series = []
        for col in cols:
            s = {
                "name": col,
                "type": "line",
                "smooth": smooth,
            }
            if x_data_formatted:
                s["data"] = list(zip(x_data_formatted, _safe_list(df[col])))
            else:
                s["data"] = _safe_list(df[col])
            series.append(s)

        if len(cols) > 1:
            option["legend"] = {"data": cols, "top": "bottom"}

        option["series"] = series
        return {"chart_type": "line", "option": option}
    except Exception as e:
        return {"chart_type": "line", "error": str(e)}


# ---------------------------------------------------------------------------
# 3. Pie chart (doughnut)
# ---------------------------------------------------------------------------

def create_pie_chart(
    file_path: str,
    category_column: str,
    value_column: str = None,
    title: str = "",
) -> dict:
    """饼图（环形）：展示占比分布，支持按类别计数或求和。"""
    try:
        df = _load_dataframe(file_path)
        option = _base_option(title or "饼图", tooltip_trigger="item")

        if value_column and value_column in df.columns:
            agg = df.groupby(category_column)[value_column].sum()
        else:
            agg = df[category_column].value_counts()

        data = [{"name": str(k), "value": float(v)} for k, v in agg.items()]

        option["series"] = [{
            "name": category_column,
            "type": "pie",
            "radius": ["40%", "70%"],
            "data": data,
            "emphasis": {
                "itemStyle": {
                    "shadowBlur": 10,
                    "shadowOffsetX": 0,
                    "shadowColor": "rgba(0,0,0,0.5)",
                }
            },
        }]
        option["legend"] = {"orient": "vertical", "left": "left", "top": "middle"}
        # Pie charts don't need grid
        option.pop("grid", None)
        return {"chart_type": "pie", "option": option}
    except Exception as e:
        return {"chart_type": "pie", "error": str(e)}


# ---------------------------------------------------------------------------
# 4. Scatter chart
# ---------------------------------------------------------------------------

def create_scatter_chart(
    file_path: str,
    x_column: str,
    y_column: str,
    color_column: str = None,
    size_column: str = None,
    title: str = "",
) -> dict:
    """散点图：展示两变量相关性，支持颜色和大小编码。"""
    try:
        df = _load_dataframe(file_path)
        option = _base_option(title or "散点图", tooltip_trigger="item")
        option["xAxis"] = {"type": "value", "name": x_column}
        option["yAxis"] = {"type": "value", "name": y_column}

        if color_column and color_column in df.columns:
            groups = df[color_column].dropna().unique().tolist()
            series = []
            for g in groups:
                sub = df[df[color_column] == g]
                pts = []
                for _, row in sub.iterrows():
                    pt = [row[x_column], row[y_column]]
                    if size_column and size_column in df.columns:
                        pt.append(float(row[size_column]) if pd.notna(row[size_column]) else 5)
                    pts.append(pt)
                s = {"name": str(g), "type": "scatter", "data": pts}
                if size_column and size_column in df.columns:
                    s["symbolSize"] = {"__js__": "function(val){return Math.max(val[2]/5,4);}"}
                series.append(s)
            option["legend"] = {"data": [str(g) for g in groups], "top": "bottom"}
        else:
            pts = []
            for _, row in df.iterrows():
                pt = [row[x_column], row[y_column]]
                if size_column and size_column in df.columns:
                    pt.append(float(row[size_column]) if pd.notna(row[size_column]) else 5)
                pts.append(pt)
            series = [{"name": f"{x_column} vs {y_column}", "type": "scatter", "data": pts}]
            if size_column and size_column in df.columns:
                series[0]["symbolSize"] = {"__js__": "function(val){return Math.max(val[2]/5,4);}"}

        option["series"] = series
        return {"chart_type": "scatter", "option": option}
    except Exception as e:
        return {"chart_type": "scatter", "error": str(e)}


# ---------------------------------------------------------------------------
# 5. Histogram
# ---------------------------------------------------------------------------

def create_histogram(
    file_path: str,
    column: str,
    bins: int = 20,
    title: str = "",
) -> dict:
    """直方图：展示数值分布频率。"""
    try:
        df = _load_dataframe(file_path)
        values = df[column].dropna().values.astype(float)
        counts, edges = np.histogram(values, bins=bins)

        # Build category labels from bin edges
        categories = [
            f"{edges[i]:.2f}-{edges[i+1]:.2f}" for i in range(len(counts))
        ]

        option = _base_option(title or f"{column} 分布直方图")
        option["xAxis"] = {"type": "category", "data": categories, "name": column,
                           "axisLabel": {"rotate": 30}}
        option["yAxis"] = {"type": "value", "name": "频数"}
        option["series"] = [{
            "name": "频数",
            "type": "bar",
            "data": counts.tolist(),
            "barWidth": "95%",
            "itemStyle": {"borderRadius": [2, 2, 0, 0]},
        }]
        return {"chart_type": "histogram", "option": option}
    except Exception as e:
        return {"chart_type": "histogram", "error": str(e)}


# ---------------------------------------------------------------------------
# 6. Box plot
# ---------------------------------------------------------------------------

def create_box_plot(
    file_path: str,
    value_column: str,
    group_column: str = None,
    title: str = "",
) -> dict:
    """箱线图：展示数值分布的四分位和离群点。"""
    try:
        df = _load_dataframe(file_path)
        option = _base_option(title or f"{value_column} 箱线图", tooltip_trigger="item")

        def _box_stats(arr):
            arr = arr.dropna().values.astype(float)
            if len(arr) == 0:
                return [0, 0, 0, 0, 0]
            q1, median, q3 = np.percentile(arr, [25, 50, 75])
            iqr = q3 - q1
            lower = float(max(arr.min(), q1 - 1.5 * iqr))
            upper = float(min(arr.max(), q3 + 1.5 * iqr))
            return [lower, float(q1), float(median), float(q3), upper]

        if group_column and group_column in df.columns:
            groups = df[group_column].dropna().unique().tolist()
            box_data = [_box_stats(df[df[group_column] == g][value_column]) for g in groups]
            categories = [str(g) for g in groups]
        else:
            box_data = [_box_stats(df[value_column])]
            categories = [value_column]

        option["xAxis"] = {"type": "category", "data": categories}
        option["yAxis"] = {"type": "value", "name": value_column}
        option["series"] = [{
            "name": value_column,
            "type": "boxplot",
            "data": box_data,
        }]
        return {"chart_type": "boxplot", "option": option}
    except Exception as e:
        return {"chart_type": "boxplot", "error": str(e)}


# ---------------------------------------------------------------------------
# 7. Heatmap (correlation matrix)
# ---------------------------------------------------------------------------

def create_heatmap_chart(
    file_path: str,
    columns: str = None,
    title: str = "",
) -> dict:
    """热力图：展示变量间相关系数矩阵。"""
    try:
        df = _load_dataframe(file_path)

        if columns:
            cols = [c.strip() for c in columns.split(",") if c.strip()]
        else:
            cols = df.select_dtypes(include=[np.number]).columns.tolist()

        if len(cols) < 2:
            return {"chart_type": "heatmap", "error": "至少需要2个数值列来计算相关矩阵"}

        corr = df[cols].corr()
        data = []
        for i, c1 in enumerate(cols):
            for j, c2 in enumerate(cols):
                val = corr.iloc[i, j]
                data.append([i, j, round(float(val), 3) if pd.notna(val) else 0])

        option = _base_option(title or "相关系数热力图", tooltip_trigger="item")
        option["xAxis"] = {"type": "category", "data": cols, "splitArea": {"show": True}}
        option["yAxis"] = {"type": "category", "data": cols, "splitArea": {"show": True}}
        option["visualMap"] = {
            "min": -1,
            "max": 1,
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": "0%",
            "inRange": {
                "color": ["#3b82f6", "#ffffff", "#ef4444"],
            },
        }
        option["series"] = [{
            "name": "相关系数",
            "type": "heatmap",
            "data": data,
            "label": {"show": True, "fontSize": 10},
            "emphasis": {
                "itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0,0,0,0.5)"},
            },
        }]
        # Heatmap needs more bottom space for visualMap
        option["grid"] = {"left": "15%", "right": "10%", "bottom": "20%", "top": "15%"}
        return {"chart_type": "heatmap", "option": option}
    except Exception as e:
        return {"chart_type": "heatmap", "error": str(e)}


# ---------------------------------------------------------------------------
# 8. Treemap
# ---------------------------------------------------------------------------

def create_treemap(
    file_path: str,
    category_column: str,
    value_column: str,
    title: str = "",
) -> dict:
    """树图：展示层级占比关系。"""
    try:
        df = _load_dataframe(file_path)
        agg = df.groupby(category_column)[value_column].sum()
        tree_data = [{"name": str(k), "value": float(v)} for k, v in agg.items() if pd.notna(v)]

        option = _base_option(title or "树图", tooltip_trigger="item")
        option["series"] = [{
            "name": category_column,
            "type": "treemap",
            "data": tree_data,
            "label": {"show": True, "formatter": "{b}: {c}"},
            "breadcrumb": {"show": True},
            "levels": [
                {
                    "itemStyle": {"borderColor": "#fff", "borderWidth": 2, "gapWidth": 2},
                },
            ],
        }]
        # Treemap doesn't use axis/grid
        option.pop("grid", None)
        return {"chart_type": "treemap", "option": option}
    except Exception as e:
        return {"chart_type": "treemap", "error": str(e)}


# ---------------------------------------------------------------------------
# 9. Radar chart
# ---------------------------------------------------------------------------

def create_radar_chart(
    file_path: str,
    dimensions: str,
    value_columns: str,
    title: str = "",
) -> dict:
    """雷达图：展示多维指标综合对比。"""
    try:
        df = _load_dataframe(file_path)
        dim_labels = [d.strip() for d in dimensions.split(",") if d.strip()]
        val_cols = [c.strip() for c in value_columns.split(",") if c.strip()]

        # Collect raw values for each dimension across all value columns
        all_values = []
        for col in val_cols:
            all_values.extend(df[col].dropna().values.tolist())

        # Build per-dimension max for radar indicator (normalize to 0-100)
        indicators = []
        for dim in dim_labels:
            indicators.append({"name": dim, "max": 100})

        # Compute normalized data for each value column
        series_data = []
        for col in val_cols:
            raw = df[col].dropna().values.astype(float)
            if len(raw) == 0:
                series_data.append({"name": col, "value": [0] * len(dim_labels)})
                continue
            col_min, col_max = raw.min(), raw.max()
            rng = col_max - col_min if col_max != col_min else 1.0
            # Take first N values matching dimension count, normalize to 0-100
            vals = raw[:len(dim_labels)]
            normalized = [round(float((v - col_min) / rng * 100), 2) for v in vals]
            # Pad if fewer values than dimensions
            while len(normalized) < len(dim_labels):
                normalized.append(0)
            series_data.append({"name": col, "value": normalized})

        option = _base_option(title or "雷达图", tooltip_trigger="item")
        option["radar"] = {"indicator": indicators, "shape": "polygon"}
        option["series"] = [{
            "name": title or "雷达图",
            "type": "radar",
            "data": series_data,
            "areaStyle": {"opacity": 0.15},
        }]
        if len(val_cols) > 1:
            option["legend"] = {"data": val_cols, "top": "bottom"}
        # Radar doesn't use axis/grid
        option.pop("grid", None)
        return {"chart_type": "radar", "option": option}
    except Exception as e:
        return {"chart_type": "radar", "error": str(e)}


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    create_bar_chart,
    create_line_chart,
    create_pie_chart,
    create_scatter_chart,
    create_histogram,
    create_box_plot,
    create_heatmap_chart,
    create_treemap,
    create_radar_chart,
]


class ChartToolset(BaseToolset):
    """交互式数据图表工具集 — 柱状/折线/饼图/散点/直方/箱线/热力/树图/雷达"""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
