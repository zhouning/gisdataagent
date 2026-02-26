"""Spatial statistics tools: Global Moran's I, LISA, Getis-Ord Gi* hotspot analysis.

Uses PySAL (libpysal + esda) for spatial autocorrelation and hotspot detection.
"""
import json
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from libpysal.weights import Queen, KNN, DistanceBand
from esda.moran import Moran, Moran_Local
from esda.getisord import G_Local

from .gis_processors import _generate_output_path, _resolve_path
from .utils import _load_spatial_data, _configure_fonts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_spatial_weights(gdf, weights_type="queen", k=8, distance_threshold=0):
    """Build spatial weights matrix; reproject to metric CRS if geographic.

    Returns:
        Tuple of (gdf_projected, weights) where gdf_projected may be
        reprojected to EPSG:3857 if the original CRS is geographic.
    """
    gdf_work = gdf.copy()
    if gdf_work.crs and gdf_work.crs.is_geographic:
        gdf_work = gdf_work.to_crs(epsg=3857)

    wt = weights_type.lower()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if wt == "queen":
            w = Queen.from_dataframe(gdf_work, use_index=False)
        elif wt == "knn":
            w = KNN.from_dataframe(gdf_work, k=k)
        elif wt == "distance":
            if distance_threshold <= 0:
                from libpysal.weights.util import min_threshold_distance
                coords = np.array(
                    [(g.centroid.x, g.centroid.y) for g in gdf_work.geometry]
                )
                distance_threshold = min_threshold_distance(coords)
            w = DistanceBand.from_dataframe(
                gdf_work, threshold=distance_threshold, binary=True
            )
        else:
            raise ValueError(
                f"Unsupported weights_type: '{weights_type}'. "
                "Use 'queen', 'knn', or 'distance'."
            )
        w.transform = "R"
    return gdf_work, w


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def spatial_autocorrelation(
    file_path: str,
    column: str,
    weights_type: str = "queen",
    k: int = 8,
    distance_threshold: float = 0,
    permutations: int = 999,
) -> str:
    """全局空间自相关分析（Moran's I 检验）。

    评估空间数据中某个属性值是否存在全局性空间聚集或分散模式。
    Moran's I > 0 表示正空间自相关（相似值聚集），< 0 表示负空间自相关（相异值分散）。

    Args:
        file_path: 空间数据文件路径（SHP/GeoJSON/GPKG）或 PostGIS 表名。
        column: 用于分析的数值属性字段名。
        weights_type: 空间权重类型。"queen"（邻接权重）、"knn"（K最近邻）、"distance"（距离带）。
        k: KNN 权重的邻居数量（默认 8）。
        distance_threshold: 距离带权重的阈值（米）。0 表示自动计算最小阈值距离。
        permutations: 置换检验次数（默认 999），用于计算 p 值。

    Returns:
        JSON 字符串，包含 Moran's I 值、期望值 E[I]、z 得分、p 值及统计解释。
    """
    try:
        res_path = _resolve_path(file_path)
        gdf = _load_spatial_data(res_path)

        if column not in gdf.columns:
            return f"Error: column '{column}' not found. Available columns: {list(gdf.columns)}"

        y = gdf[column].astype(float)
        nan_count = int(y.isna().sum())
        if nan_count > 0:
            y = y.fillna(y.mean())

        gdf_work, w = _build_spatial_weights(gdf, weights_type, k, distance_threshold)

        mi = Moran(y.values, w, permutations=permutations)

        if mi.p_sim < 0.01:
            sig = "在 1% 水平下显著"
        elif mi.p_sim < 0.05:
            sig = "在 5% 水平下显著"
        elif mi.p_sim < 0.1:
            sig = "在 10% 水平下边际显著"
        else:
            sig = "不显著（未拒绝空间随机分布假设）"

        if mi.I > mi.EI:
            pattern = "正空间自相关（相似值倾向于聚集）"
        elif mi.I < mi.EI:
            pattern = "负空间自相关（相异值倾向于相邻）"
        else:
            pattern = "随机分布"

        result = {
            "moran_I": round(float(mi.I), 6),
            "expected_I": round(float(mi.EI), 6),
            "z_score": round(float(mi.z_sim), 4),
            "p_value": round(float(mi.p_sim), 6),
            "permutations": permutations,
            "weights_type": weights_type,
            "significance": sig,
            "pattern": pattern,
            "feature_count": len(gdf),
            "column": column,
        }
        if nan_count > 0:
            result["nan_filled"] = nan_count
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Error in spatial_autocorrelation: {str(e)}"


def local_moran(
    file_path: str,
    column: str,
    weights_type: str = "queen",
    k: int = 8,
    significance: float = 0.05,
    permutations: int = 999,
) -> str:
    """局部空间自相关分析（LISA — Local Moran's I）。

    识别空间数据中每个要素的局部空间聚类类型：
    HH（高-高热点）、LL（低-低冷点）、HL（高-低异常值）、LH（低-高异常值）、NS（不显著）。
    输出带有 LISA 聚类标注的 SHP 文件和 PNG 聚类可视化图。

    Args:
        file_path: 空间数据文件路径或 PostGIS 表名。
        column: 用于分析的数值属性字段名。
        weights_type: 空间权重类型。"queen"、"knn"、"distance"。
        k: KNN 权重的邻居数量（默认 8）。
        significance: 显著性阈值（默认 0.05）。
        permutations: 置换检验次数（默认 999）。

    Returns:
        包含 SHP 文件路径和 PNG 图片路径的字典。
    """
    try:
        res_path = _resolve_path(file_path)
        gdf = _load_spatial_data(res_path)

        if column not in gdf.columns:
            return f"Error: column '{column}' not found. Available columns: {list(gdf.columns)}"

        y = gdf[column].astype(float)
        if y.isna().any():
            y = y.fillna(y.mean())

        gdf_work, w = _build_spatial_weights(gdf, weights_type, k)

        lisa = Moran_Local(y.values, w, permutations=permutations)

        # Classify: quadrant 1=HH, 2=LH, 3=LL, 4=HL
        labels = []
        for i in range(len(gdf)):
            if lisa.p_sim[i] > significance:
                labels.append("NS")
            elif lisa.q[i] == 1:
                labels.append("HH")
            elif lisa.q[i] == 2:
                labels.append("LH")
            elif lisa.q[i] == 3:
                labels.append("LL")
            elif lisa.q[i] == 4:
                labels.append("HL")
            else:
                labels.append("NS")

        gdf_out = gdf.copy()
        gdf_out["lisa_cls"] = labels
        gdf_out["lisa_I"] = lisa.Is
        gdf_out["lisa_p"] = lisa.p_sim
        gdf_out["lisa_q"] = lisa.q

        out_shp = _generate_output_path("lisa_cluster", "shp")
        gdf_out.to_file(out_shp, encoding="utf-8")

        # --- Visualization ---
        _configure_fonts()
        color_map = {
            "HH": "#d7191c", "HL": "#fdae61",
            "LH": "#abd9e9", "LL": "#2c7bb6", "NS": "#d3d3d3",
        }
        colors = [color_map.get(l, "#d3d3d3") for l in labels]

        fig, ax = plt.subplots(1, 1, figsize=(10, 10))
        gdf_out.plot(ax=ax, color=colors, edgecolor="grey", linewidth=0.3)
        ax.set_title(f"LISA \u805a\u7c7b\u56fe \u2014 {column}", fontsize=14)
        ax.set_axis_off()

        patches = [
            mpatches.Patch(color="#d7191c", label=f"HH \u9ad8-\u9ad8 ({labels.count('HH')})"),
            mpatches.Patch(color="#2c7bb6", label=f"LL \u4f4e-\u4f4e ({labels.count('LL')})"),
            mpatches.Patch(color="#fdae61", label=f"HL \u9ad8-\u4f4e ({labels.count('HL')})"),
            mpatches.Patch(color="#abd9e9", label=f"LH \u4f4e-\u9ad8 ({labels.count('LH')})"),
            mpatches.Patch(color="#d3d3d3", label=f"NS \u4e0d\u663e\u8457 ({labels.count('NS')})"),
        ]
        ax.legend(handles=patches, loc="lower right", fontsize=10)

        out_png = _generate_output_path("lisa_map", "png")
        plt.savefig(out_png, dpi=200, bbox_inches="tight")
        plt.close(fig)

        summary = (
            f"LISA \u5206\u6790\u5b8c\u6210\uff08{column}, p<{significance}\uff09\n"
            f"HH: {labels.count('HH')}, LL: {labels.count('LL')}, "
            f"HL: {labels.count('HL')}, LH: {labels.count('LH')}, "
            f"NS: {labels.count('NS')}\n"
            f"\u805a\u7c7b SHP: {out_shp}\n\u805a\u7c7b\u56fe: {out_png}"
        )
        return {"output_path": out_shp, "visualization": out_png, "summary": summary}

    except Exception as e:
        return f"Error in local_moran: {str(e)}"


def hotspot_analysis(
    file_path: str,
    column: str,
    weights_type: str = "knn",
    k: int = 8,
    significance: float = 0.05,
    permutations: int = 999,
) -> str:
    """热点分析（Getis-Ord Gi* 统计量）。

    识别具有统计显著性的高值热点（Hot Spot）和低值冷点（Cold Spot）。
    输出带有热点/冷点标注的 SHP 文件和 PNG 可视化图。

    Args:
        file_path: 空间数据文件路径或 PostGIS 表名。
        column: 用于分析的数值属性字段名。
        weights_type: 空间权重类型。"queen"、"knn"（推荐）、"distance"。
        k: KNN 权重的邻居数量（默认 8）。
        significance: 显著性阈值（默认 0.05）。
        permutations: 置换检验次数（默认 999）。

    Returns:
        包含 SHP 文件路径和 PNG 图片路径的字典。
    """
    try:
        res_path = _resolve_path(file_path)
        gdf = _load_spatial_data(res_path)

        if column not in gdf.columns:
            return f"Error: column '{column}' not found. Available columns: {list(gdf.columns)}"

        y = gdf[column].astype(float)
        if y.isna().any():
            y = y.fillna(y.mean())

        gdf_work, w = _build_spatial_weights(gdf, weights_type, k)

        g_local = G_Local(y.values, w, star=True, permutations=permutations)

        labels = []
        for i in range(len(gdf)):
            p = g_local.p_sim[i]
            z = g_local.Zs[i]
            if p <= significance:
                labels.append("Hot Spot" if z > 0 else "Cold Spot")
            else:
                labels.append("Not Significant")

        gdf_out = gdf.copy()
        gdf_out["gi_z"] = g_local.Zs
        gdf_out["gi_p"] = g_local.p_sim
        gdf_out["hotspot"] = labels

        out_shp = _generate_output_path("hotspot", "shp")
        gdf_out.to_file(out_shp, encoding="utf-8")

        # --- Visualization ---
        _configure_fonts()
        color_map = {
            "Hot Spot": "#d7191c",
            "Cold Spot": "#2c7bb6",
            "Not Significant": "#d3d3d3",
        }
        colors = [color_map.get(l, "#d3d3d3") for l in labels]

        fig, ax = plt.subplots(1, 1, figsize=(10, 10))
        gdf_out.plot(ax=ax, color=colors, edgecolor="grey", linewidth=0.3)
        ax.set_title(f"\u70ed\u70b9\u5206\u6790 (Gi*) \u2014 {column}", fontsize=14)
        ax.set_axis_off()

        patches = [
            mpatches.Patch(color="#d7191c", label=f"\u70ed\u70b9 ({labels.count('Hot Spot')})"),
            mpatches.Patch(color="#2c7bb6", label=f"\u51b7\u70b9 ({labels.count('Cold Spot')})"),
            mpatches.Patch(color="#d3d3d3", label=f"\u4e0d\u663e\u8457 ({labels.count('Not Significant')})"),
        ]
        ax.legend(handles=patches, loc="lower right", fontsize=11)

        out_png = _generate_output_path("hotspot_map", "png")
        plt.savefig(out_png, dpi=200, bbox_inches="tight")
        plt.close(fig)

        summary = (
            f"\u70ed\u70b9\u5206\u6790\u5b8c\u6210\uff08{column}, p<{significance}\uff09\n"
            f"\u70ed\u70b9: {labels.count('Hot Spot')}, "
            f"\u51b7\u70b9: {labels.count('Cold Spot')}, "
            f"\u4e0d\u663e\u8457: {labels.count('Not Significant')}\n"
            f"\u7ed3\u679c SHP: {out_shp}\n\u70ed\u70b9\u56fe: {out_png}"
        )
        return {"output_path": out_shp, "visualization": out_png, "summary": summary}

    except Exception as e:
        return f"Error in hotspot_analysis: {str(e)}"
