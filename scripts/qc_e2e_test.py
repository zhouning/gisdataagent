"""
端到端质检测试 — 重庆市中心城区建筑物轮廓数据
测试质检智能体全链路：格式校验 → 规则审查 → 精度核验 → 缺陷分类 → 报告生成
"""
import json
import time
import sys
import os

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_agent.standard_registry import DefectTaxonomy

DATA_PATH = (
    "D:/北大MEM/00-学位论文/毕业论文原文件/"
    "规划院提供数据样例及Demo系统功能演示建议/"
    "规划院提供数据样例及Demo系统功能演示建议/"
    "01数据样例/04重庆市中心城区建筑物轮廓数据2021年/"
    "中心城区建筑数据带层高.shp"
)

HISTORY_DATA = (
    "D:/北大MEM/00-学位论文/毕业论文原文件/"
    "规划院提供数据样例及Demo系统功能演示建议/"
    "规划院提供数据样例及Demo系统功能演示建议/"
    "01数据样例/05重庆市中心城区历史文化街区数据/"
    "中心城区历史文化街区数据.shp"
)


def banner(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def step_result(name, result):
    status = result.get("status", "unknown")
    icon = "✓" if status == "ok" else "✗" if status == "error" else "?"
    print(f"  [{icon}] {name}: {status}")
    return result


# =====================================================================
#  Step 1: 数据格式校验
# =====================================================================
def step1_format_validation():
    banner("Step 1: 数据格式校验")
    import geopandas as gpd

    t0 = time.time()
    gdf = gpd.read_file(DATA_PATH)
    elapsed = time.time() - t0

    result = {
        "status": "ok",
        "file": os.path.basename(DATA_PATH),
        "record_count": len(gdf),
        "crs": str(gdf.crs),
        "geometry_type": gdf.geometry.geom_type.unique().tolist(),
        "columns": list(gdf.columns),
        "bounds": [round(x, 4) for x in gdf.total_bounds],
        "load_time_s": round(elapsed, 2),
    }

    # Check CRS compliance (should be CGCS2000 = EPSG:4490 for Chinese surveying)
    crs_str = str(gdf.crs)
    if "4490" in crs_str:
        result["crs_compliance"] = "CGCS2000 (合规)"
    elif "4326" in crs_str:
        result["crs_compliance"] = "WGS84 (需转换为CGCS2000)"
        result["crs_defect"] = "NRM-01"
    else:
        result["crs_compliance"] = f"非标准CRS: {crs_str}"
        result["crs_defect"] = "NRM-01"

    print(f"  文件: {result['file']}")
    print(f"  记录数: {result['record_count']:,}")
    print(f"  坐标系: {result['crs']} → {result['crs_compliance']}")
    print(f"  几何类型: {result['geometry_type']}")
    print(f"  字段: {result['columns']}")
    print(f"  范围: {result['bounds']}")
    print(f"  加载耗时: {result['load_time_s']}s")

    return gdf, result


# =====================================================================
#  Step 2: 几何有效性 + 拓扑检查
# =====================================================================
def step2_geometry_topology(gdf):
    banner("Step 2: 几何有效性 + 拓扑检查")
    from shapely.validation import explain_validity

    t0 = time.time()
    total = len(gdf)

    # 2a: Geometry validity
    invalid_geoms = []
    null_geoms = 0
    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            null_geoms += 1
            continue
        if not geom.is_valid:
            invalid_geoms.append({
                "index": int(idx),
                "reason": explain_validity(geom),
            })

    # 2b: Self-intersection check (sample for performance)
    sample_size = min(5000, total)
    sample = gdf.head(sample_size)
    from shapely.ops import unary_union
    try:
        _ = unary_union(sample.geometry)
        union_ok = True
    except Exception:
        union_ok = False

    # 2c: Duplicate geometry check
    geom_wkb = gdf.geometry.apply(lambda g: g.wkb if g else b"")
    dup_count = geom_wkb.duplicated().sum()

    elapsed = time.time() - t0

    defects = []
    if invalid_geoms:
        defects.append({"code": "TOP-01", "desc": "几何无效", "count": len(invalid_geoms), "samples": invalid_geoms[:5]})
    if null_geoms:
        defects.append({"code": "MIS-01", "desc": "空几何", "count": null_geoms})
    if dup_count:
        defects.append({"code": "TOP-03", "desc": "重复几何", "count": int(dup_count)})

    result = {
        "status": "ok",
        "total_features": total,
        "invalid_geometries": len(invalid_geoms),
        "null_geometries": null_geoms,
        "duplicate_geometries": int(dup_count),
        "union_test": "pass" if union_ok else "fail",
        "defects": defects,
        "elapsed_s": round(elapsed, 2),
    }

    print(f"  总要素数: {total:,}")
    print(f"  无效几何: {len(invalid_geoms)}")
    print(f"  空几何: {null_geoms}")
    print(f"  重复几何: {dup_count}")
    print(f"  Union测试: {'通过' if union_ok else '失败'}")
    print(f"  检出缺陷: {len(defects)} 类")
    for d in defects:
        print(f"    [{d['code']}] {d['desc']}: {d['count']} 处")
    print(f"  耗时: {result['elapsed_s']}s")

    return result


# =====================================================================
#  Step 3: 属性完整性 + 逻辑一致性
# =====================================================================
def step3_attribute_check(gdf):
    banner("Step 3: 属性完整性 + 逻辑一致性")

    t0 = time.time()
    total = len(gdf)
    defects = []

    # 3a: Null value check per column
    null_stats = {}
    for col in gdf.columns:
        if col == "geometry":
            continue
        null_count = int(gdf[col].isna().sum())
        if null_count > 0:
            null_stats[col] = null_count

    if null_stats:
        defects.append({
            "code": "MIS-02",
            "desc": "属性空值",
            "details": null_stats,
            "total_null_cells": sum(null_stats.values()),
        })

    # 3b: Floor value range check (if Floor column exists)
    if "Floor" in gdf.columns:
        floor_col = gdf["Floor"]
        floor_numeric = floor_col[floor_col.notna()]
        try:
            floor_vals = floor_numeric.astype(float)
            negative = int((floor_vals < 0).sum())
            extreme = int((floor_vals > 200).sum())
            zero = int((floor_vals == 0).sum())
            if negative:
                defects.append({"code": "PRE-03", "desc": "层高为负值", "count": negative})
            if extreme:
                defects.append({"code": "PRE-03", "desc": "层高异常(>200)", "count": extreme})
            if zero:
                defects.append({"code": "MIS-02", "desc": "层高为0", "count": zero})

            floor_stats = {
                "min": round(float(floor_vals.min()), 1),
                "max": round(float(floor_vals.max()), 1),
                "mean": round(float(floor_vals.mean()), 1),
                "median": round(float(floor_vals.median()), 1),
            }
        except Exception:
            floor_stats = {"error": "无法转换为数值"}
    else:
        floor_stats = {"note": "无Floor字段"}

    elapsed = time.time() - t0

    result = {
        "status": "ok",
        "total_features": total,
        "null_stats": null_stats,
        "floor_stats": floor_stats,
        "defects": defects,
        "elapsed_s": round(elapsed, 2),
    }

    print(f"  空值统计: {null_stats if null_stats else '无空值'}")
    print(f"  层高统计: {json.dumps(floor_stats, ensure_ascii=False)}")
    print(f"  检出缺陷: {len(defects)} 类")
    for d in defects:
        cnt = d.get("count", d.get("total_null_cells", ""))
        print(f"    [{d['code']}] {d['desc']}: {cnt} 处")
    print(f"  耗时: {result['elapsed_s']}s")

    return result


# =====================================================================
#  Step 4: 套合精度检查（建筑轮廓 vs 历史文化街区）
# =====================================================================
def step4_overlay_precision():
    banner("Step 4: 套合精度检查（跨数据源）")
    import geopandas as gpd
    import numpy as np
    from shapely.ops import nearest_points

    t0 = time.time()

    gdf_a = gpd.read_file(DATA_PATH)
    gdf_b = gpd.read_file(HISTORY_DATA)

    print(f"  数据A: 建筑轮廓 ({len(gdf_a):,} 要素, CRS={gdf_a.crs})")
    print(f"  数据B: 历史文化街区 ({len(gdf_b)} 要素, CRS={gdf_b.crs})")

    # CRS mismatch detection
    crs_match = str(gdf_a.crs) == str(gdf_b.crs)
    defects = []
    if not crs_match:
        defects.append({
            "code": "NRM-01",
            "desc": f"CRS不一致: A={gdf_a.crs} vs B={gdf_b.crs}",
        })
        print(f"  ⚠ CRS不一致: {gdf_a.crs} vs {gdf_b.crs}")
        # Reproject B to A's CRS for comparison
        gdf_b = gdf_b.to_crs(gdf_a.crs)
        print(f"  → 已将B重投影至 {gdf_a.crs}")

    # Spatial overlay: find buildings within historical districts
    buildings_in_districts = gpd.sjoin(gdf_a, gdf_b, how="inner", predicate="intersects")
    overlap_count = len(buildings_in_districts)

    # Boundary alignment check (sample)
    if overlap_count > 0:
        sample = buildings_in_districts.head(100)
        offsets = []
        for _, row in sample.iterrows():
            bldg_boundary = row.geometry.boundary
            # Find nearest district boundary
            for _, dist in gdf_b.iterrows():
                dist_boundary = dist.geometry.boundary
                p1, p2 = nearest_points(bldg_boundary, dist_boundary)
                offsets.append(p1.distance(p2))
                break

        if offsets:
            offsets_arr = np.array(offsets)
            offset_stats = {
                "mean_offset_deg": round(float(offsets_arr.mean()), 6),
                "max_offset_deg": round(float(offsets_arr.max()), 6),
                "min_offset_deg": round(float(offsets_arr.min()), 6),
            }
        else:
            offset_stats = {}
    else:
        offset_stats = {"note": "无重叠区域"}

    elapsed = time.time() - t0

    result = {
        "status": "ok",
        "crs_match": crs_match,
        "buildings_in_districts": overlap_count,
        "offset_stats": offset_stats,
        "defects": defects,
        "elapsed_s": round(elapsed, 2),
    }

    print(f"  CRS一致: {'是' if crs_match else '否'}")
    print(f"  重叠建筑数: {overlap_count:,}")
    print(f"  偏移统计: {json.dumps(offset_stats, ensure_ascii=False)}")
    print(f"  耗时: {result['elapsed_s']}s")

    return result


# =====================================================================
#  Step 5: 缺陷分类汇总 + 质量评分
# =====================================================================
def step5_defect_summary(results):
    banner("Step 5: 缺陷分类汇总 + 质量评分")

    all_defects = []
    for step_name, r in results.items():
        for d in r.get("defects", []):
            d["source_step"] = step_name
            all_defects.append(d)

    # Classify by taxonomy
    by_category = {}
    for d in all_defects:
        code = d.get("code", "UNKNOWN")
        cat = code.split("-")[0] if "-" in code else "OTHER"
        by_category.setdefault(cat, []).append(d)

    # Score calculation (100 - weighted deductions)
    score = 100.0
    for d in all_defects:
        code = d.get("code", "")
        count = d.get("count", 1)
        # Look up severity from taxonomy
        try:
            defect_def = DefectTaxonomy.get_defect(code)
            severity = defect_def.severity if defect_def else "B"
        except Exception:
            severity = "B"

        if severity == "A":
            score -= min(count * 2.0, 20)
        elif severity == "B":
            score -= min(count * 0.5, 10)
        else:
            score -= min(count * 0.1, 5)

    score = max(0, round(score, 1))

    if score >= 90:
        grade = "优"
    elif score >= 75:
        grade = "良"
    elif score >= 60:
        grade = "合格"
    else:
        grade = "不合格"

    result = {
        "total_defect_types": len(all_defects),
        "by_category": {k: len(v) for k, v in by_category.items()},
        "score": score,
        "grade": grade,
        "details": all_defects,
    }

    print(f"  缺陷类型数: {len(all_defects)}")
    print(f"  按分类:")
    for cat, items in by_category.items():
        cat_name = {"TOP": "拓扑", "MIS": "缺失", "PRE": "精度", "NRM": "规范", "FMT": "格式"}.get(cat, cat)
        print(f"    {cat_name}({cat}): {len(items)} 类")
        for item in items:
            print(f"      [{item['code']}] {item['desc']}: {item.get('count', '-')}")
    print(f"  质量评分: {score} / 100")
    print(f"  质量等级: {grade}")

    return result


# =====================================================================
#  Main
# =====================================================================
if __name__ == "__main__":
    banner("质检智能体 — 端到端测试")
    print(f"  目标数据: 重庆市中心城区建筑物轮廓数据(2021)")
    print(f"  参考数据: 重庆市中心城区历史文化街区数据")
    print(f"  质检标准: GB/T 24356")

    t_total = time.time()
    results = {}

    # Step 1
    gdf, r1 = step1_format_validation()
    results["format_validation"] = r1

    # Step 2
    r2 = step2_geometry_topology(gdf)
    results["geometry_topology"] = r2

    # Step 3
    r3 = step3_attribute_check(gdf)
    results["attribute_check"] = r3

    # Step 4
    r4 = step4_overlay_precision()
    results["overlay_precision"] = r4

    # Step 5
    r5 = step5_defect_summary(results)
    results["defect_summary"] = r5

    total_elapsed = round(time.time() - t_total, 2)

    banner("质检完成")
    print(f"  总耗时: {total_elapsed}s")
    print(f"  质量评分: {r5['score']} / 100 ({r5['grade']})")
    print(f"  缺陷类型: {r5['total_defect_types']}")

    # Save JSON report
    report_path = os.path.join(os.path.dirname(__file__), "qc_e2e_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"  报告已保存: {report_path}")
