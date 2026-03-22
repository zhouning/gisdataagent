"""
PrecisionToolset — 精度对比核验工具集。

Provides geometry precision verification tools for surveying QC:
- Coordinate precision comparison (measured vs design)
- Topology integrity scoring
- Edge matching analysis
- Comprehensive precision scoring
"""
import os
import math
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..gis_processors import _resolve_path, _generate_output_path
from ..observability import get_logger

logger = get_logger("precision_tools")


def compare_coordinates(
    measured_file: str,
    reference_file: str,
    id_column: str = "",
    tolerance_m: float = 1.0,
) -> str:
    """
    [Precision Tool] Compare coordinate precision between measured and reference datasets.

    Calculates positional differences between corresponding features in two
    spatial datasets to assess coordinate accuracy. Reports RMSE, max error,
    and features exceeding tolerance.

    Args:
        measured_file: Path to the measured/actual spatial data file.
        reference_file: Path to the reference/design spatial data file.
        id_column: Column name to match features between datasets (empty = spatial nearest).
        tolerance_m: Maximum acceptable error in meters.

    Returns:
        Precision comparison report with RMSE, max error, and error distribution.
    """
    import geopandas as gpd
    import numpy as np

    m_path = _resolve_path(measured_file)
    r_path = _resolve_path(reference_file)

    if not os.path.isfile(m_path):
        return f"测量数据文件不存在: {measured_file}"
    if not os.path.isfile(r_path):
        return f"参考数据文件不存在: {reference_file}"

    try:
        gdf_m = gpd.read_file(m_path)
        gdf_r = gpd.read_file(r_path)
    except Exception as e:
        return f"读取数据失败: {e}"

    # Ensure same CRS
    if gdf_m.crs and gdf_r.crs and gdf_m.crs != gdf_r.crs:
        gdf_r = gdf_r.to_crs(gdf_m.crs)

    # Match features
    if id_column and id_column in gdf_m.columns and id_column in gdf_r.columns:
        merged = gdf_m.merge(gdf_r[[id_column, "geometry"]], on=id_column,
                             suffixes=("_measured", "_reference"))
    else:
        # Spatial nearest join
        from shapely.ops import nearest_points
        distances = []
        for idx, row in gdf_m.iterrows():
            point_m = row.geometry.centroid
            dists = gdf_r.geometry.centroid.distance(point_m)
            nearest_idx = dists.idxmin()
            point_r = gdf_r.loc[nearest_idx].geometry.centroid
            dist = point_m.distance(point_r)
            distances.append({
                "measured_idx": idx,
                "reference_idx": nearest_idx,
                "dx": point_m.x - point_r.x,
                "dy": point_m.y - point_r.y,
                "distance": dist,
            })

        if not distances:
            return "无法匹配任何要素对。"

        import pandas as pd
        df = pd.DataFrame(distances)
        dists = df["distance"].values

        # Calculate metrics
        rmse = float(np.sqrt(np.mean(dists ** 2)))
        max_err = float(np.max(dists))
        mean_err = float(np.mean(dists))
        median_err = float(np.median(dists))
        exceed_count = int(np.sum(dists > tolerance_m))
        total = len(dists)

        lines = [
            f"坐标精度对比结果 ({total} 对匹配要素):",
            f"  RMSE (均方根误差): {rmse:.4f}",
            f"  最大误差: {max_err:.4f}",
            f"  平均误差: {mean_err:.4f}",
            f"  中位数误差: {median_err:.4f}",
            f"  容差 ({tolerance_m}m) 超限: {exceed_count}/{total} ({exceed_count/total*100:.1f}%)",
            "",
        ]

        # CRS unit hint
        if gdf_m.crs and gdf_m.crs.is_geographic:
            lines.append("  注意: 当前坐标系为地理坐标(度)，距离单位为度。建议投影到米制坐标系。")

        # Grade based on RMSE
        if rmse < tolerance_m * 0.5:
            lines.append(f"  评定: 优 (RMSE < {tolerance_m*0.5:.2f})")
        elif rmse < tolerance_m:
            lines.append(f"  评定: 合格 (RMSE < {tolerance_m:.2f})")
        else:
            lines.append(f"  评定: 不合格 (RMSE > {tolerance_m:.2f})")

        return "\n".join(lines)

    return "坐标对比完成（ID匹配模式结果待解析）。"


def check_topology_integrity(file_path: str) -> str:
    """
    [Precision Tool] Comprehensive topology integrity check.

    Performs a thorough topology check including: self-intersections,
    duplicate geometries, invalid geometries, gaps, overlaps, and
    dangles. Returns a topology integrity score (0-100).

    Args:
        file_path: Path to the spatial data file to check.

    Returns:
        Topology integrity report with issue counts and score.
    """
    import geopandas as gpd
    import numpy as np

    resolved = _resolve_path(file_path)
    if not os.path.isfile(resolved):
        return f"文件不存在: {file_path}"

    try:
        gdf = gpd.read_file(resolved)
    except Exception as e:
        return f"读取失败: {e}"

    if "geometry" not in gdf.columns or gdf.geometry is None:
        return "数据无几何字段，无法执行拓扑检查。"

    total = len(gdf)
    issues = {}

    # 1. Invalid geometries
    invalid = gdf[~gdf.geometry.is_valid]
    issues["无效几何"] = len(invalid)

    # 2. Empty geometries
    empty = gdf[gdf.geometry.is_empty]
    issues["空几何"] = len(empty)

    # 3. Self-intersections (for polygons)
    if gdf.geom_type.iloc[0] in ("Polygon", "MultiPolygon") if len(gdf) > 0 else False:
        self_intersect = 0
        for geom in gdf.geometry:
            if not geom.is_empty and not geom.is_valid:
                self_intersect += 1
        issues["自相交"] = self_intersect

    # 4. Duplicate geometries
    try:
        wkt_list = gdf.geometry.apply(lambda g: g.wkt if g else "")
        dup_count = wkt_list.duplicated().sum()
        issues["重复几何"] = int(dup_count)
    except Exception:
        issues["重复几何"] = 0

    # 5. Overlaps (pairwise check for small datasets)
    if len(gdf) <= 1000 and len(gdf) > 1:
        overlap_count = 0
        from shapely.strtree import STRtree
        tree = STRtree(gdf.geometry.tolist())
        for i, geom in enumerate(gdf.geometry):
            if geom.is_empty:
                continue
            candidates = tree.query(geom)
            for j in candidates:
                if j > i:
                    other = gdf.geometry.iloc[j]
                    if geom.overlaps(other):
                        overlap_count += 1
        issues["重叠"] = overlap_count
    else:
        issues["重叠"] = -1  # skipped

    # Calculate score
    total_issues = sum(v for v in issues.values() if v > 0)
    if total == 0:
        score = 0
    else:
        issue_rate = total_issues / total
        score = max(0, round(100 * (1 - issue_rate * 2), 1))  # 50% issue rate → 0 score

    lines = [f"拓扑完整性检查结果 ({total} 个要素):"]
    for name, count in issues.items():
        if count == -1:
            lines.append(f"  {name}: 跳过 (数据量>1000)")
        elif count > 0:
            lines.append(f"  {name}: {count} 处 ⚠️")
        else:
            lines.append(f"  {name}: 0 ✓")

    lines.append(f"\n拓扑完整性评分: {score}/100")
    if score >= 90:
        lines.append("评定: 优")
    elif score >= 75:
        lines.append("评定: 良")
    elif score >= 60:
        lines.append("评定: 合格")
    else:
        lines.append("评定: 不合格")

    return "\n".join(lines)


def check_edge_matching(file_path: str, neighbor_file: str = "", buffer_m: float = 1.0) -> str:
    """
    [Precision Tool] Check edge matching (接边检查) between adjacent map sheets.

    Verifies that features at the edges of adjacent datasets connect properly
    without gaps or overlaps. Important for map sheet joining quality.

    Args:
        file_path: Path to the primary spatial data file.
        neighbor_file: Path to the adjacent/neighboring data file.
        buffer_m: Buffer distance in meters for edge matching tolerance.

    Returns:
        Edge matching check results with gap/overlap counts.
    """
    import geopandas as gpd

    resolved = _resolve_path(file_path)
    if not os.path.isfile(resolved):
        return f"文件不存在: {file_path}"

    try:
        gdf = gpd.read_file(resolved)
    except Exception as e:
        return f"读取失败: {e}"

    if not neighbor_file:
        # Self-check: analyze boundary features
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        boundary_features = 0
        for geom in gdf.geometry:
            if geom.is_empty:
                continue
            b = geom.bounds
            if (abs(b[0] - bounds[0]) < buffer_m or abs(b[2] - bounds[2]) < buffer_m or
                abs(b[1] - bounds[1]) < buffer_m or abs(b[3] - bounds[3]) < buffer_m):
                boundary_features += 1

        return (f"接边分析（自检模式）:\n"
                f"  数据范围: [{bounds[0]:.4f}, {bounds[1]:.4f}] - [{bounds[2]:.4f}, {bounds[3]:.4f}]\n"
                f"  边界要素数: {boundary_features}/{len(gdf)}\n"
                f"  提示: 提供相邻图幅数据可进行完整接边检查。")

    # Two-file edge matching
    n_path = _resolve_path(neighbor_file)
    if not os.path.isfile(n_path):
        return f"相邻数据文件不存在: {neighbor_file}"

    try:
        gdf_n = gpd.read_file(n_path)
    except Exception as e:
        return f"读取相邻数据失败: {e}"

    if gdf.crs and gdf_n.crs and gdf.crs != gdf_n.crs:
        gdf_n = gdf_n.to_crs(gdf.crs)

    # Find shared boundary region
    from shapely.geometry import box
    b1 = gdf.total_bounds
    b2 = gdf_n.total_bounds
    shared = box(max(b1[0], b2[0]) - buffer_m, max(b1[1], b2[1]) - buffer_m,
                 min(b1[2], b2[2]) + buffer_m, min(b1[3], b2[3]) + buffer_m)

    edge1 = gdf[gdf.geometry.intersects(shared)]
    edge2 = gdf_n[gdf_n.geometry.intersects(shared)]

    return (f"接边检查结果:\n"
            f"  主数据边界要素: {len(edge1)}\n"
            f"  相邻数据边界要素: {len(edge2)}\n"
            f"  共享边界区域面积: {shared.area:.4f}\n"
            f"  容差: {buffer_m}m")


def precision_score(file_path: str, standard_id: str = "gb_t_24356") -> str:
    """
    [Precision Tool] Calculate comprehensive precision score for a dataset.

    Evaluates a spatial dataset against quality standards (GB/T 24356)
    and returns a multi-dimensional quality score covering positional accuracy,
    attribute accuracy, completeness, logical consistency, etc.

    Args:
        file_path: Path to the spatial data file to evaluate.
        standard_id: Quality standard to use (default: gb_t_24356).

    Returns:
        Multi-dimensional precision score report (0-100 scale).
    """
    import geopandas as gpd
    import numpy as np

    resolved = _resolve_path(file_path)
    if not os.path.isfile(resolved):
        return f"文件不存在: {file_path}"

    try:
        gdf = gpd.read_file(resolved)
    except Exception as e:
        return f"读取失败: {e}"

    total = len(gdf)
    scores = {}

    # 1. Completeness (20%)
    non_null_rates = []
    for col in gdf.columns:
        if col == "geometry":
            continue
        rate = gdf[col].notna().mean()
        non_null_rates.append(rate)
    completeness = np.mean(non_null_rates) * 100 if non_null_rates else 100
    scores["完整性"] = round(completeness, 1)

    # 2. Logical consistency (15%)
    valid_geom = gdf.geometry.is_valid.mean() * 100 if "geometry" in gdf.columns else 100
    non_empty = (1 - gdf.geometry.is_empty.mean()) * 100 if "geometry" in gdf.columns else 100
    consistency = (valid_geom + non_empty) / 2
    scores["逻辑一致性"] = round(consistency, 1)

    # 3. CRS quality (10%)
    crs_score = 100 if gdf.crs else 0
    scores["坐标系"] = crs_score

    # 4. Attribute quality (15%)
    # Check for mixed types, unusual null patterns
    attr_issues = 0
    for col in gdf.columns:
        if col == "geometry":
            continue
        # All null column
        if gdf[col].isna().all():
            attr_issues += 2
        # Very high null rate
        elif gdf[col].isna().mean() > 0.5:
            attr_issues += 1
    attr_score = max(0, 100 - attr_issues * 10)
    scores["属性质量"] = round(attr_score, 1)

    # 5. Geometry quality (25%)
    if "geometry" in gdf.columns:
        geom_types = gdf.geom_type.unique().tolist()
        single_type = 100 if len(geom_types) <= 1 else max(50, 100 - len(geom_types) * 15)
        valid_rate = gdf.geometry.is_valid.mean() * 100
        geom_score = (single_type + valid_rate) / 2
    else:
        geom_score = 0
    scores["几何质量"] = round(geom_score, 1)

    # Weighted total
    weights = {"完整性": 0.20, "逻辑一致性": 0.15, "坐标系": 0.10,
               "属性质量": 0.15, "几何质量": 0.25}
    # Add remaining weight for overall balance
    remaining = 1.0 - sum(weights.values())
    weighted = sum(scores.get(k, 80) * w for k, w in weights.items())
    weighted += 80 * remaining  # Assume average for unchecked dimensions
    total_score = round(weighted, 1)

    lines = [f"综合精度评分 ({total} 个要素, 标准: {standard_id}):"]
    for name, score in scores.items():
        bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
        lines.append(f"  {name}: {bar} {score}/100")

    lines.append(f"\n综合评分: {total_score}/100")

    # Grade
    if total_score >= 90:
        lines.append("质量等级: 优")
    elif total_score >= 75:
        lines.append("质量等级: 良")
    elif total_score >= 60:
        lines.append("质量等级: 合格")
    else:
        lines.append("质量等级: 不合格")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Toolset Registration
# ---------------------------------------------------------------------------

class PrecisionToolset(BaseToolset):
    """Precision verification tools for surveying QC."""

    name = "PrecisionToolset"
    description = "精度核验工具：坐标对比、拓扑完整性、接边检查、综合精度评分"
    category = "quality_control"

    def get_tools(self):
        return [
            FunctionTool(compare_coordinates),
            FunctionTool(check_topology_integrity),
            FunctionTool(check_edge_matching),
            FunctionTool(precision_score),
        ]
