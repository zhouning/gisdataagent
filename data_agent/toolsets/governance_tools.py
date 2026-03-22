"""
GovernanceToolset — 12 governance audit + standard tools (v14.5).

Provides comprehensive data quality audit capabilities:
- Gap detection, completeness, attribute range, duplicates, CRS consistency
- Composite governance scoring (0-100, 6 dimensions)
- Data Standard Registry integration (list/validate/formulas/gap matrix)
- Governance plan generation
"""

import json
import logging

import geopandas as gpd
from shapely.geometry import mapping

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..utils import _load_spatial_data
from ..gis_processors import _resolve_path

logger = logging.getLogger(__name__)

# CGCS2000 family EPSG codes
_CGCS2000_EPSGS = {4490} | set(range(4526, 4555))


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def check_gaps(file_path: str, tolerance: float = 0.001) -> dict:
    """
    [治理工具] 间隙检测：检查多边形之间是否存在间隙（缝隙）。

    Args:
        file_path: 空间数据文件路径。
        tolerance: 面积阈值，小于此值的间隙忽略。
    Returns:
        包含 status、gap_count、total_gap_area 和 gaps 列表的字典。
    """
    try:
        gdf = _load_spatial_data(_resolve_path(file_path))
        valid_geom = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].geometry

        if len(valid_geom) == 0:
            return {"status": "pass", "gap_count": 0, "total_gap_area": 0.0, "gaps": []}

        union = valid_geom.unary_union
        hull = union.convex_hull
        diff = hull.difference(union)

        # Collect individual gap polygons
        gap_polygons = []
        if diff.is_empty:
            pass
        elif diff.geom_type == "Polygon":
            if diff.area > tolerance:
                gap_polygons.append(diff)
        elif diff.geom_type in ("MultiPolygon", "GeometryCollection"):
            for part in diff.geoms:
                if hasattr(part, "area") and part.area > tolerance:
                    gap_polygons.append(part)

        total_gap_area = round(sum(g.area for g in gap_polygons), 6)
        gap_centroids = []
        for g in gap_polygons[:20]:
            c = g.centroid
            gap_centroids.append({
                "x": round(c.x, 6),
                "y": round(c.y, 6),
                "area": round(g.area, 6),
            })

        status = "pass" if len(gap_polygons) == 0 else "fail"
        return {
            "status": status,
            "gap_count": len(gap_polygons),
            "total_gap_area": total_gap_area,
            "gaps": gap_centroids,
        }
    except Exception as e:
        logger.exception("check_gaps failed")
        return {"status": "error", "error_message": str(e)}


def check_completeness(file_path: str, required_fields: list = None) -> dict:
    """
    [治理工具] 属性完整性检查：统计各字段的非空率及几何完整性。

    Args:
        file_path: 空间数据文件路径。
        required_fields: 需要检查的字段列表，为 None 则检查所有列。
    Returns:
        包含 status、overall_pct、fields 完整率、geometry_completeness 的字典。
    """
    try:
        gdf = _load_spatial_data(_resolve_path(file_path))
        total = len(gdf)
        if total == 0:
            return {"status": "pass", "overall_pct": 100.0, "fields": {}, "geometry_completeness": 100.0}

        cols = required_fields if required_fields else [c for c in gdf.columns if c != "geometry"]
        field_pcts = {}
        for col in cols:
            if col not in gdf.columns:
                field_pcts[col] = 0.0
                continue
            non_null = gdf[col].notna()
            # Also treat empty strings as missing
            if gdf[col].dtype == object:
                non_empty = gdf[col].astype(str).str.strip().ne("")
                valid = (non_null & non_empty).sum()
            else:
                valid = int(non_null.sum())
            field_pcts[col] = round(valid / total * 100, 2)

        # Geometry completeness
        geom_valid = int((gdf.geometry.notna() & ~gdf.geometry.is_empty).sum())
        geom_pct = round(geom_valid / total * 100, 2)

        overall_pct = round(
            (sum(field_pcts.values()) + geom_pct) / (len(field_pcts) + 1), 2
        ) if field_pcts else geom_pct

        if overall_pct >= 95:
            status = "pass"
        elif overall_pct >= 80:
            status = "warn"
        else:
            status = "fail"

        return {
            "status": status,
            "overall_pct": overall_pct,
            "fields": field_pcts,
            "geometry_completeness": geom_pct,
        }
    except Exception as e:
        logger.exception("check_completeness failed")
        return {"status": "error", "error_message": str(e)}


def check_attribute_range(file_path: str, range_rules: dict) -> dict:
    """
    [治理工具] 属性范围校验：依据规则检查数值列是否存在越界值。

    Args:
        file_path: 空间数据文件路径。
        range_rules: 校验规则，格式如 {"column_name": {"min": 0, "max": 90, "type": "numeric"}, ...}。
    Returns:
        包含 status、violations、compliance_rate 的字典。
    """
    try:
        gdf = _load_spatial_data(_resolve_path(file_path))
        total_checks = 0
        total_violations = 0
        violations = {}

        for col, rules in range_rules.items():
            if col not in gdf.columns:
                violations[col] = {"count": len(gdf), "samples": [], "total": len(gdf),
                                   "error": f"字段 {col} 不存在"}
                total_checks += len(gdf)
                total_violations += len(gdf)
                continue

            series = gdf[col].dropna()
            col_total = len(series)
            total_checks += col_total

            outlier_mask = None
            rule_type = rules.get("type", "numeric")

            if rule_type == "numeric":
                try:
                    numeric_series = series.astype(float)
                except (ValueError, TypeError):
                    violations[col] = {"count": col_total, "samples": series.head(5).tolist(),
                                       "total": col_total, "error": "无法转换为数值"}
                    total_violations += col_total
                    continue

                conditions = []
                if "min" in rules:
                    conditions.append(numeric_series < rules["min"])
                if "max" in rules:
                    conditions.append(numeric_series > rules["max"])

                if conditions:
                    outlier_mask = conditions[0]
                    for cond in conditions[1:]:
                        outlier_mask = outlier_mask | cond

            if outlier_mask is not None:
                n_outliers = int(outlier_mask.sum())
                if n_outliers > 0:
                    outlier_values = series[outlier_mask].head(10).tolist()
                    violations[col] = {
                        "count": n_outliers,
                        "samples": outlier_values,
                        "total": col_total,
                    }
                    total_violations += n_outliers

        compliance_rate = round(1 - total_violations / total_checks, 4) if total_checks > 0 else 1.0
        if compliance_rate >= 0.95:
            status = "pass"
        elif compliance_rate >= 0.80:
            status = "warn"
        else:
            status = "fail"

        return {
            "status": status,
            "violations": violations,
            "compliance_rate": compliance_rate,
        }
    except Exception as e:
        logger.exception("check_attribute_range failed")
        return {"status": "error", "error_message": str(e)}


def check_duplicates(file_path: str, check_geometry: bool = True, check_fields: list = None) -> dict:
    """
    [治理工具] 重复检测：基于几何和/或属性字段检测重复要素。

    Args:
        file_path: 空间数据文件路径。
        check_geometry: 是否检查几何重复。
        check_fields: 用于检查属性重复的字段列表。
    Returns:
        包含 status、geometry_duplicates、attribute_duplicates、duplicate_groups 的字典。
    """
    try:
        gdf = _load_spatial_data(_resolve_path(file_path))
        geometry_duplicates = 0
        attribute_duplicates = 0
        duplicate_groups = []

        # Geometry duplicates
        if check_geometry:
            wkt_series = gdf.geometry.dropna().apply(
                lambda g: g.wkt if not g.is_empty else None
            )
            dup_mask = wkt_series.duplicated(keep=False)
            dup_wkts = wkt_series[dup_mask]
            if len(dup_wkts) > 0:
                grouped = dup_wkts.groupby(dup_wkts).apply(lambda x: x.index.tolist())
                geometry_duplicates = len(grouped)
                for idx, (wkt_val, indices) in enumerate(grouped.items()):
                    if idx >= 10:
                        break
                    duplicate_groups.append({
                        "type": "geometry",
                        "count": len(indices),
                        "indices": indices[:5],
                    })

        # Attribute duplicates
        if check_fields:
            valid_fields = [f for f in check_fields if f in gdf.columns]
            if valid_fields:
                attr_dup_mask = gdf.duplicated(subset=valid_fields, keep=False)
                attr_dups = gdf[attr_dup_mask]
                if len(attr_dups) > 0:
                    grouped_attr = attr_dups.groupby(valid_fields)
                    attribute_duplicates = len(grouped_attr)
                    for idx, (key, group) in enumerate(grouped_attr):
                        if idx >= 10:
                            break
                        duplicate_groups.append({
                            "type": "attribute",
                            "fields": valid_fields,
                            "count": len(group),
                            "indices": group.index.tolist()[:5],
                        })

        total_dups = geometry_duplicates + attribute_duplicates
        status = "pass" if total_dups == 0 else "fail"

        return {
            "status": status,
            "geometry_duplicates": geometry_duplicates,
            "attribute_duplicates": attribute_duplicates,
            "duplicate_groups": duplicate_groups,
        }
    except Exception as e:
        logger.exception("check_duplicates failed")
        return {"status": "error", "error_message": str(e)}


def check_crs_consistency(file_path: str, expected_epsg: int = 4490) -> dict:
    """
    [治理工具] CRS 一致性检查：验证数据坐标参考系是否符合预期（默认 CGCS2000 / EPSG:4490）。

    Args:
        file_path: 空间数据文件路径。
        expected_epsg: 预期 EPSG 代码，默认 4490 (CGCS2000)。
    Returns:
        包含 status、current_crs、is_compliant、recommendation 的字典。
    """
    try:
        gdf = _load_spatial_data(_resolve_path(file_path))

        current_crs = gdf.crs
        if current_crs is None:
            return {
                "status": "fail",
                "current_crs": None,
                "current_epsg": None,
                "expected_epsg": expected_epsg,
                "is_compliant": False,
                "recommendation": "数据缺少坐标参考系，请先指定 CRS（如 EPSG:4490）。",
            }

        current_epsg = current_crs.to_epsg()
        is_compliant = current_epsg == expected_epsg

        # Also accept CGCS2000 family
        is_cgcs2000_family = current_epsg in _CGCS2000_EPSGS if current_epsg else False

        if is_compliant:
            recommendation = "CRS 符合要求。"
        elif is_cgcs2000_family:
            recommendation = (
                f"当前为 CGCS2000 投影带 (EPSG:{current_epsg})，"
                f"建议确认是否需要转换至 EPSG:{expected_epsg}。"
            )
        else:
            recommendation = (
                f"当前 CRS (EPSG:{current_epsg}) 不符合要求，"
                f"建议重投影至 EPSG:{expected_epsg}。"
            )

        status = "pass" if is_compliant else "fail"

        return {
            "status": status,
            "current_crs": str(current_crs),
            "current_epsg": current_epsg,
            "expected_epsg": expected_epsg,
            "is_compliant": is_compliant,
            "recommendation": recommendation,
        }
    except Exception as e:
        logger.exception("check_crs_consistency failed")
        return {"status": "error", "error_message": str(e)}


def governance_score(audit_results: dict) -> dict:
    """
    [治理工具] 综合治理评分：基于 6 维度加权计算 0-100 治理得分。

    Args:
        audit_results: 各审计工具的结果字典，键为 topology / gaps / completeness /
                       attribute_range / duplicates / crs。
    Returns:
        包含 total_score、grade、dimensions、radar_data 的字典。
    """
    try:
        dimensions = {}

        # 1. Topology (25%)
        topo = audit_results.get("topology", {})
        if topo.get("status") == "pass":
            topo_score = 100
        else:
            overlaps = topo.get("errors", {}).get("overlaps", {}).get("count", 999)
            topo_score = 50 if overlaps < 5 else 0
        dimensions["topology"] = {"score": topo_score, "weight": 0.25}

        # 2. Gaps (15%)
        gaps = audit_results.get("gaps", {})
        gap_count = gaps.get("gap_count", 0)
        gap_score = max(0, 100 - gap_count * 10)
        dimensions["gaps"] = {"score": gap_score, "weight": 0.15}

        # 3. Completeness (20%)
        comp = audit_results.get("completeness", {})
        comp_score = comp.get("overall_pct", 0)
        dimensions["completeness"] = {"score": comp_score, "weight": 0.20}

        # 4. Attribute validity (15%)
        attr = audit_results.get("attribute_range", {})
        attr_score = attr.get("compliance_rate", 0) * 100
        dimensions["attribute_validity"] = {"score": attr_score, "weight": 0.15}

        # 5. Duplicates (10%)
        dups = audit_results.get("duplicates", {})
        dup_count = dups.get("geometry_duplicates", 0) + dups.get("attribute_duplicates", 0)
        dup_score = max(0, 100 - dup_count * 5)
        dimensions["duplicates"] = {"score": dup_score, "weight": 0.10}

        # 6. CRS (15%)
        crs = audit_results.get("crs", {})
        crs_score = 100 if crs.get("is_compliant", False) else 0
        dimensions["crs"] = {"score": crs_score, "weight": 0.15}

        # Weighted total
        total_score = round(
            sum(d["score"] * d["weight"] for d in dimensions.values()), 2
        )

        # Grade
        if total_score >= 90:
            grade = "A"
        elif total_score >= 80:
            grade = "B"
        elif total_score >= 60:
            grade = "C"
        elif total_score >= 40:
            grade = "D"
        else:
            grade = "F"

        # Radar data for ECharts
        radar_data = [
            {"name": "拓扑", "value": topo_score},
            {"name": "间隙", "value": gap_score},
            {"name": "完整性", "value": comp_score},
            {"name": "属性有效性", "value": attr_score},
            {"name": "重复", "value": dup_score},
            {"name": "坐标系", "value": crs_score},
        ]

        return {
            "status": "success",
            "total_score": total_score,
            "grade": grade,
            "dimensions": dimensions,
            "radar_data": radar_data,
        }
    except Exception as e:
        logger.exception("governance_score failed")
        return {"status": "error", "error_message": str(e)}


def governance_summary(file_path: str, audit_results: dict, score: dict) -> dict:
    """
    [治理工具] 审计摘要生成：综合所有审计结论生成结构化报告。

    Args:
        file_path: 被审计的数据文件路径。
        audit_results: 各审计工具的结果字典。
        score: governance_score 返回的评分字典。
    Returns:
        包含 summary、critical_issues、warnings、recommendations、score 的字典。
    """
    try:
        critical_issues = []
        warnings = []
        recommendations = []

        total = score.get("total_score", 0)
        grade = score.get("grade", "N/A")

        # Topology issues
        topo = audit_results.get("topology", {})
        if topo.get("status") == "fail":
            errors = topo.get("errors", {})
            if "self_intersections" in errors:
                critical_issues.append(
                    f"发现 {errors['self_intersections']['count']} 个自相交要素"
                )
            if "overlaps" in errors:
                critical_issues.append(
                    f"发现 {errors['overlaps']['count']} 处多边形重叠"
                )
            if "multi_part" in errors:
                warnings.append(
                    f"存在 {errors['multi_part']['count']} 个多部件几何，建议打散为单部件"
                )

        # Gap issues
        gaps = audit_results.get("gaps", {})
        if gaps.get("status") == "fail":
            critical_issues.append(
                f"多边形间存在 {gaps.get('gap_count', 0)} 处间隙，"
                f"总面积 {gaps.get('total_gap_area', 0)}"
            )
            recommendations.append("使用缝隙填充工具消除多边形间隙")

        # Completeness issues
        comp = audit_results.get("completeness", {})
        if comp.get("status") in ("warn", "fail"):
            low_fields = [
                f for f, pct in comp.get("fields", {}).items() if pct < 80
            ]
            if low_fields:
                msg = f"以下字段完整率低于 80%: {', '.join(low_fields[:5])}"
                if comp.get("status") == "fail":
                    critical_issues.append(msg)
                else:
                    warnings.append(msg)
            recommendations.append("补充缺失属性值或删除不完整记录")

        geom_comp = comp.get("geometry_completeness", 100)
        if geom_comp < 100:
            warnings.append(f"几何完整率 {geom_comp}%，存在空几何要素")
            recommendations.append("删除或修复空几何要素")

        # Attribute range issues
        attr = audit_results.get("attribute_range", {})
        if attr.get("status") in ("warn", "fail"):
            for col, info in attr.get("violations", {}).items():
                warnings.append(
                    f"字段 {col} 存在 {info.get('count', 0)} 个越界值"
                )
            recommendations.append("检查并修正属性值越界问题")

        # Duplicate issues
        dups = audit_results.get("duplicates", {})
        if dups.get("status") == "fail":
            geom_dups = dups.get("geometry_duplicates", 0)
            attr_dups = dups.get("attribute_duplicates", 0)
            if geom_dups:
                warnings.append(f"发现 {geom_dups} 组几何重复要素")
            if attr_dups:
                warnings.append(f"发现 {attr_dups} 组属性重复要素")
            recommendations.append("使用去重工具删除重复要素")

        # CRS issues
        crs = audit_results.get("crs", {})
        if crs.get("status") == "fail":
            rec = crs.get("recommendation", "")
            if rec:
                critical_issues.append(rec)
            recommendations.append(
                f"重投影至 EPSG:{crs.get('expected_epsg', 4490)}"
            )

        # Build summary text
        summary_lines = [
            f"数据治理审计报告 — {file_path}",
            f"综合评分: {total} / 100 (等级: {grade})",
            f"关键问题: {len(critical_issues)} 项",
            f"警告: {len(warnings)} 项",
            f"建议: {len(recommendations)} 项",
        ]

        if not critical_issues and not warnings:
            summary_lines.append("数据质量良好，可直接用于分析。")

        return {
            "status": "success",
            "summary": "\n".join(summary_lines),
            "critical_issues": critical_issues,
            "warnings": warnings,
            "recommendations": recommendations,
            "score": score,
        }
    except Exception as e:
        logger.exception("governance_summary failed")
        return {"status": "error", "error_message": str(e)}


# ---------------------------------------------------------------------------
# Data Standard Registry tools (v14.5)
# ---------------------------------------------------------------------------

def list_data_standards() -> str:
    """列出所有已注册的数据标准（如 GB/T 21010 地类编码、DLTB 地类图斑字段规范）。

    Returns:
        JSON格式的标准列表，含ID、名称、版本、字段数、代码表数。
    """
    import json
    try:
        from ..standard_registry import StandardRegistry
        standards = StandardRegistry.list_standards()
        if not standards:
            return json.dumps({"status": "ok", "message": "暂无已注册的数据标准", "standards": []},
                              ensure_ascii=False)
        return json.dumps({"status": "ok", "count": len(standards), "standards": standards},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def validate_against_standard(file_path: str, standard_id: str) -> str:
    """按预置数据标准一键校验数据文件。检查字段缺失、值域超限、类型不匹配等。

    Args:
        file_path: 待校验数据文件路径（Shapefile/GeoJSON/GPKG/FGDB等）。
        standard_id: 标准ID（如 "dltb_2023" 或 "gb_t_21010_2017"），可通过 list_data_standards 查看。

    Returns:
        JSON格式的校验报告：缺失字段、非法值、类型错误等。
    """
    import json
    try:
        from ..gis_processors import check_field_standards
        result = check_field_standards(file_path, standard_id)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def validate_field_formulas(file_path: str, standard_id: str = "", formulas: str = "") -> str:
    """验证数据字段间的计算关系是否正确（如 TBDLMJ = TBMJ - KCMJ）。

    Args:
        file_path: 数据文件路径。
        standard_id: 标准ID（自动加载标准内置公式），可选。
        formulas: JSON公式列表，如 '[{"expr":"TBDLMJ = TBMJ - KCMJ","tolerance":0.01}]'。留空则使用标准内置公式。

    Returns:
        JSON格式的公式校验结果。
    """
    try:
        from ..gis_processors import _resolve_path

        formula_list = []
        if formulas:
            formula_list = json.loads(formulas)
        elif standard_id:
            from ..standard_registry import StandardRegistry
            std = StandardRegistry.get(standard_id)
            if std and std.formulas:
                formula_list = std.formulas
        if not formula_list:
            return json.dumps({"status": "error", "message": "请提供公式或标准ID（含内置公式）"},
                              ensure_ascii=False)

        gdf = gpd.read_file(_resolve_path(file_path))
        results = []
        for f in formula_list:
            expr = f.get("expr", "")
            tol = f.get("tolerance", 0.01)
            desc = f.get("description", expr)
            if "=" not in expr:
                results.append({"expr": expr, "status": "error", "message": "公式格式错误，需包含 '='"})
                continue
            lhs, rhs = expr.split("=", 1)
            lhs = lhs.strip()
            rhs = rhs.strip()
            # Check required fields exist
            import re
            fields_in_expr = re.findall(r'[A-Za-z_]\w*', rhs)
            missing = [fn for fn in [lhs] + fields_in_expr if fn not in gdf.columns]
            if missing:
                results.append({"expr": expr, "status": "skip", "missing_fields": missing})
                continue
            try:
                expected = gdf.eval(rhs)
                actual = gdf[lhs]
                diff = (actual - expected).abs()
                violations = int((diff > tol).sum())
                results.append({
                    "expr": expr, "description": desc, "tolerance": tol,
                    "status": "pass" if violations == 0 else "fail",
                    "violations": violations, "total_rows": len(gdf),
                    "max_diff": round(float(diff.max()), 4) if violations > 0 else 0,
                })
            except Exception as calc_err:
                results.append({"expr": expr, "status": "error", "message": str(calc_err)[:200]})

        all_pass = all(r.get("status") == "pass" for r in results if r.get("status") != "skip")
        return json.dumps({"status": "ok", "all_pass": all_pass, "results": results},
                          ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def generate_gap_matrix(file_path: str, standard_id: str) -> str:
    """生成数据字段与标准字段的差距矩阵：缺失/多余/类型不匹配/完整性评分。

    Args:
        file_path: 数据文件路径。
        standard_id: 标准ID（如 "dltb_2023"）。

    Returns:
        JSON格式的差距矩阵，含逐字段对比和汇总统计。
    """
    try:
        from ..gis_processors import _resolve_path
        from ..standard_registry import StandardRegistry

        std = StandardRegistry.get(standard_id)
        if not std:
            return json.dumps({"status": "error", "message": f"未找到标准: {standard_id}"},
                              ensure_ascii=False)

        gdf = gpd.read_file(_resolve_path(file_path))
        data_cols = set(gdf.columns) - {"geometry"}
        std_fields = {f.name for f in std.fields}

        TYPE_MAP = {
            "string": ["object", "str", "string"],
            "numeric": ["float64", "float32", "int64", "int32", "Float64", "Int64"],
            "integer": ["int64", "int32", "Int64"],
            "date": ["datetime64"],
        }

        matrix = []
        mandatory_total = 0
        mandatory_present = 0

        for fspec in std.fields:
            entry = {
                "field": fspec.name, "required": fspec.required,
                "expected_type": fspec.type, "description": fspec.description,
            }
            if fspec.required == "M":
                mandatory_total += 1
            if fspec.name in data_cols:
                entry["status"] = "present"
                actual_type = str(gdf[fspec.name].dtype)
                entry["actual_type"] = actual_type
                if fspec.type in TYPE_MAP:
                    entry["type_match"] = any(t in actual_type for t in TYPE_MAP[fspec.type])
                else:
                    entry["type_match"] = True
                non_null = gdf[fspec.name].notna().sum()
                total = len(gdf)
                entry["completeness"] = round(non_null / total * 100, 1) if total else 0
                if fspec.required == "M":
                    mandatory_present += 1
            else:
                entry["status"] = "missing"
                entry["type_match"] = None
                entry["completeness"] = 0
            matrix.append(entry)

        # Extra fields (in data but not in standard)
        extra_cols = data_cols - std_fields
        for col in sorted(extra_cols):
            matrix.append({
                "field": col, "status": "extra", "required": "-",
                "expected_type": "-", "actual_type": str(gdf[col].dtype),
                "type_match": None, "completeness": 100.0,
            })

        present = sum(1 for m in matrix if m["status"] == "present")
        missing = sum(1 for m in matrix if m["status"] == "missing")
        extra = sum(1 for m in matrix if m["status"] == "extra")
        gap_score = round(present / len(std.fields) * 100, 1) if std.fields else 0

        summary = {
            "total_standard_fields": len(std.fields),
            "present": present, "missing": missing, "extra": extra,
            "mandatory_coverage": f"{mandatory_present}/{mandatory_total} ({round(mandatory_present/mandatory_total*100,1) if mandatory_total else 100}%)",
            "overall_gap_score": gap_score,
        }
        return json.dumps({"status": "ok", "standard": standard_id, "matrix": matrix, "summary": summary},
                          ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def generate_governance_plan(file_path: str, standard_id: str) -> str:
    """根据数据探查结果和目标标准，自动生成治理方案（探查→差距分析→治理步骤）。

    Args:
        file_path: 数据文件路径。
        standard_id: 目标标准ID（如 "dltb_2023"）。

    Returns:
        JSON格式的治理方案，含问题诊断和推荐治理步骤。
    """
    try:
        from ..gis_processors import check_field_standards, _resolve_path
        from ..utils import _load_spatial_data

        # 1. Profile data
        gdf = _load_spatial_data(file_path)
        profile = {
            "row_count": len(gdf),
            "columns": [c for c in gdf.columns if c != "geometry"],
            "crs": str(gdf.crs) if gdf.crs else None,
            "null_summary": {c: int(gdf[c].isna().sum()) for c in gdf.columns if c != "geometry"},
        }

        # 2. Gap analysis
        gap_result = json.loads(generate_gap_matrix(file_path, standard_id))
        if gap_result.get("status") == "error":
            return json.dumps(gap_result, ensure_ascii=False)

        # 3. Standards check
        std_result = check_field_standards(file_path, standard_id)

        # 4. Generate governance steps
        steps = []
        priority = 1

        # Missing mandatory fields → add_missing_fields
        missing_m = std_result.get("missing_mandatory", [])
        if missing_m:
            steps.append({
                "priority": priority, "tool": "add_missing_fields",
                "action": f"补齐 {len(missing_m)} 个缺失必填字段",
                "params": {"standard_id": standard_id},
                "fields": missing_m,
            })
            priority += 1

        # Type mismatches → cast_field_type
        type_issues = std_result.get("type_mismatches", [])
        for ti in type_issues:
            steps.append({
                "priority": priority, "tool": "cast_field_type",
                "action": f"字段 {ti['field']} 类型转换: {ti['actual']} → {ti['expected']}",
                "params": {"field": ti["field"], "target_type": ti["expected"]},
            })
            priority += 1

        # Invalid values → map_field_codes
        invalid = std_result.get("invalid_values", [])
        for iv in invalid:
            steps.append({
                "priority": priority, "tool": "map_field_codes",
                "action": f"字段 {iv['field']} 有 {iv['count']} 个非法值需映射",
                "params": {"field": iv["field"]},
                "sample_issues": iv.get("sample", [])[:3],
            })
            priority += 1

        # Mandatory nulls → fill_null_values
        m_nulls = std_result.get("mandatory_nulls", [])
        for mn in m_nulls:
            steps.append({
                "priority": priority, "tool": "fill_null_values",
                "action": f"必填字段 {mn['field']} 有 {mn['null_count']} 个空值需填充",
                "params": {"field": mn["field"], "strategy": "mode"},
            })
            priority += 1

        # CRS check
        if not gdf.crs or "4490" not in str(gdf.crs):
            steps.append({
                "priority": priority, "tool": "standardize_crs",
                "action": f"坐标系从 {gdf.crs or '未定义'} 统一为 EPSG:4490 (CGCS2000)",
                "params": {"target_crs": "EPSG:4490"},
            })
            priority += 1

        # Length violations
        for lv in std_result.get("length_violations", []):
            steps.append({
                "priority": priority, "tool": "clip_outliers",
                "action": f"字段 {lv['field']} 有 {lv['violation_count']} 个值超长 (限{lv['max_length']}字符)",
                "params": {"field": lv["field"]},
            })
            priority += 1

        gap_summary = gap_result.get("summary", {})
        return json.dumps({
            "status": "ok",
            "standard": standard_id,
            "data_profile": profile,
            "gap_summary": gap_summary,
            "compliance_rate": std_result.get("compliance_rate", 0),
            "governance_steps": steps,
            "step_count": len(steps),
            "estimated_actions": f"需执行 {len(steps)} 步治理操作",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    check_gaps,
    check_completeness,
    check_attribute_range,
    check_duplicates,
    check_crs_consistency,
    governance_score,
    governance_summary,
    list_data_standards,
    validate_against_standard,
    validate_field_formulas,
    generate_gap_matrix,
    generate_governance_plan,
]


class GovernanceToolset(BaseToolset):
    """数据治理专项审计工具集 — 间隙/完整性/属性/重复/CRS/评分"""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
