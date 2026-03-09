"""Height assignment strategy — point cloud to vector."""
import geopandas as gpd
import numpy as np


def _strategy_height_assign(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Assign height values from point cloud (LAS/LAZ) to vector features.

    For each vector feature, finds point cloud points within its bounding box
    and computes height statistics (mean, median, min, max).

    Params:
        height_stat (str): Statistic to use — mean, median, min, max (default: mean).
    """
    log = []

    gdf = None
    pc_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "point_cloud" and isinstance(data, str):
            pc_path = data

    if gdf is None:
        raise ValueError("height_assign requires a vector source.")

    result = gdf.copy()
    height_stat = params.get("height_stat", "mean")

    if pc_path is None:
        result["height_m"] = 0.0
        log.append(f"Height assignment: {len(result)} features (no point cloud path)")
        return result, log

    # Try loading point cloud with laspy
    try:
        import laspy
    except ImportError:
        result["height_m"] = 0.0
        log.append(f"Height assignment: {len(result)} features (laspy not installed — fallback 0.0)")
        return result, log

    try:
        las = laspy.read(pc_path)
        pc_x = np.array(las.x)
        pc_y = np.array(las.y)
        pc_z = np.array(las.z)
    except Exception as e:
        result["height_m"] = 0.0
        log.append(f"Height assignment: point cloud read failed ({e}) — fallback 0.0")
        return result, log

    stat_funcs = {
        "mean": np.mean,
        "median": np.median,
        "min": np.min,
        "max": np.max,
    }
    stat_func = stat_funcs.get(height_stat, np.mean)

    heights = []
    matched_count = 0
    for _, row in result.iterrows():
        geom = row.geometry
        if geom is None:
            heights.append(0.0)
            continue
        minx, miny, maxx, maxy = geom.bounds
        mask = (pc_x >= minx) & (pc_x <= maxx) & (pc_y >= miny) & (pc_y <= maxy)
        pts_z = pc_z[mask]
        if len(pts_z) > 0:
            heights.append(float(stat_func(pts_z)))
            matched_count += 1
        else:
            heights.append(0.0)

    result["height_m"] = heights
    log.append(f"Height assignment: {matched_count}/{len(result)} features matched "
               f"(stat={height_stat}, {len(pc_x)} total points)")
    return result, log
