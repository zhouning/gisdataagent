"""
GovernanceToolset — 12 governance audit + standard tools (v14.5) + grid anonymize (v15.8).

Provides comprehensive data quality audit capabilities:
- Gap detection, completeness, attribute range, duplicates, CRS consistency
- Composite governance scoring (0-100, 6 dimensions)
- Data Standard Registry integration (list/validate/formulas/gap matrix)
- Governance plan generation
- Grid-based spatial data anonymization (declassification)
"""

import json
import logging

import geopandas as gpd
import numpy as np
from shapely.geometry import box, mapping

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..utils import _load_spatial_data
from ..gis_processors import _resolve_path
from ..i18n import t as translate

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
        return {"status": "error", "error_message": translate(
            "governance.operation_failed", error=e)}


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
        return {"status": "error", "error_message": translate(
            "governance.operation_failed", error=e)}


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
                                   "error": translate(
                                       "governance.field_not_found", field=col)}
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
                                       "total": col_total, "error": translate(
                                           "governance.numeric_conversion_failed")}
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
        return {"status": "error", "error_message": translate(
            "governance.operation_failed", error=e)}


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
        return {"status": "error", "error_message": translate(
            "governance.operation_failed", error=e)}


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
                "recommendation": translate("governance.crs_missing"),
            }

        current_epsg = current_crs.to_epsg()
        is_compliant = current_epsg == expected_epsg

        # Also accept CGCS2000 family
        is_cgcs2000_family = current_epsg in _CGCS2000_EPSGS if current_epsg else False

        if is_compliant:
            recommendation = translate("governance.crs_compliant")
        elif is_cgcs2000_family:
            recommendation = translate(
                "governance.crs_family",
                current=current_epsg,
                expected=expected_epsg,
            )
        else:
            recommendation = translate(
                "governance.crs_noncompliant",
                current=current_epsg,
                expected=expected_epsg,
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
        return {"status": "error", "error_message": translate(
            "governance.operation_failed", error=e)}


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
            {"name": translate("governance.dimension_topology"), "value": topo_score},
            {"name": translate("governance.dimension_gaps"), "value": gap_score},
            {"name": translate("governance.dimension_completeness"), "value": comp_score},
            {"name": translate("governance.dimension_attributes"), "value": attr_score},
            {"name": translate("governance.dimension_duplicates"), "value": dup_score},
            {"name": translate("governance.dimension_crs"), "value": crs_score},
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
        return {"status": "error", "error_message": translate(
            "governance.operation_failed", error=e)}


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
                critical_issues.append(translate(
                    "governance.self_intersections",
                    count=errors["self_intersections"]["count"],
                ))
            if "overlaps" in errors:
                critical_issues.append(translate(
                    "governance.overlaps",
                    count=errors["overlaps"]["count"],
                ))
            if "multi_part" in errors:
                warnings.append(translate(
                    "governance.multipart",
                    count=errors["multi_part"]["count"],
                ))

        # Gap issues
        gaps = audit_results.get("gaps", {})
        if gaps.get("status") == "fail":
            critical_issues.append(translate(
                "governance.gap_summary",
                count=gaps.get("gap_count", 0),
                area=gaps.get("total_gap_area", 0),
            ))
            recommendations.append(translate("governance.fill_gaps"))

        # Completeness issues
        comp = audit_results.get("completeness", {})
        if comp.get("status") in ("warn", "fail"):
            low_fields = [
                f for f, pct in comp.get("fields", {}).items() if pct < 80
            ]
            if low_fields:
                msg = translate(
                    "governance.low_completeness",
                    fields=", ".join(low_fields[:5]),
                )
                if comp.get("status") == "fail":
                    critical_issues.append(msg)
                else:
                    warnings.append(msg)
            recommendations.append(translate("governance.fix_incomplete"))

        geom_comp = comp.get("geometry_completeness", 100)
        if geom_comp < 100:
            warnings.append(translate(
                "governance.geometry_completeness", percent=geom_comp))
            recommendations.append(translate("governance.fix_empty_geometry"))

        # Attribute range issues
        attr = audit_results.get("attribute_range", {})
        if attr.get("status") in ("warn", "fail"):
            for col, info in attr.get("violations", {}).items():
                warnings.append(translate(
                    "governance.range_violations",
                    field=col,
                    count=info.get("count", 0),
                ))
            recommendations.append(translate("governance.fix_ranges"))

        # Duplicate issues
        dups = audit_results.get("duplicates", {})
        if dups.get("status") == "fail":
            geom_dups = dups.get("geometry_duplicates", 0)
            attr_dups = dups.get("attribute_duplicates", 0)
            if geom_dups:
                warnings.append(translate(
                    "governance.geometry_duplicates", count=geom_dups))
            if attr_dups:
                warnings.append(translate(
                    "governance.attribute_duplicates", count=attr_dups))
            recommendations.append(translate("governance.remove_duplicates"))

        # CRS issues
        crs = audit_results.get("crs", {})
        if crs.get("status") == "fail":
            rec = crs.get("recommendation", "")
            if rec:
                critical_issues.append(rec)
            recommendations.append(translate(
                "governance.reproject",
                epsg=crs.get("expected_epsg", 4490),
            ))

        # Build summary text
        summary_lines = [
            translate("governance.report_title", path=file_path),
            translate("governance.report_score", score=total, grade=grade),
            translate("governance.report_critical", count=len(critical_issues)),
            translate("governance.report_warnings", count=len(warnings)),
            translate("governance.report_recommendations", count=len(recommendations)),
        ]

        if not critical_issues and not warnings:
            summary_lines.append(translate("governance.quality_good"))

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
        return {"status": "error", "error_message": translate(
            "governance.operation_failed", error=e)}


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
            return json.dumps({
                "status": "ok",
                "message": translate("governance.no_standards"),
                "standards": [],
            },
                              ensure_ascii=False)
        return json.dumps({"status": "ok", "count": len(standards), "standards": standards},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


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
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


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
            return json.dumps({
                "status": "error",
                "message": translate("governance.formula_required"),
            },
                              ensure_ascii=False)

        gdf = gpd.read_file(_resolve_path(file_path))
        results = []
        for f in formula_list:
            expr = f.get("expr", "")
            tol = f.get("tolerance", 0.01)
            desc = f.get("description", expr)
            if "=" not in expr:
                results.append({
                    "expr": expr,
                    "status": "error",
                    "message": translate("governance.formula_invalid"),
                })
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
                results.append({
                    "expr": expr,
                    "status": "error",
                    "message": translate(
                        "governance.formula_calc_failed", error=str(calc_err)[:200]),
                })

        all_pass = all(r.get("status") == "pass" for r in results if r.get("status") != "skip")
        return json.dumps({"status": "ok", "all_pass": all_pass, "results": results},
                          ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


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
            return json.dumps({"status": "error", "message": translate(
                                  "governance.standard_not_found",
                                  standard_id=standard_id,
                              )},
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
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


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
                "action": translate(
                    "governance.plan_add_fields", count=len(missing_m)),
                "params": {"standard_id": standard_id},
                "fields": missing_m,
            })
            priority += 1

        # Type mismatches → cast_field_type
        type_issues = std_result.get("type_mismatches", [])
        for ti in type_issues:
            steps.append({
                "priority": priority, "tool": "cast_field_type",
                "action": translate(
                    "governance.plan_cast_field",
                    field=ti["field"],
                    actual=ti["actual"],
                    expected=ti["expected"],
                ),
                "params": {"field": ti["field"], "target_type": ti["expected"]},
            })
            priority += 1

        # Invalid values → map_field_codes
        invalid = std_result.get("invalid_values", [])
        for iv in invalid:
            steps.append({
                "priority": priority, "tool": "map_field_codes",
                "action": translate(
                    "governance.plan_map_values",
                    field=iv["field"],
                    count=iv["count"],
                ),
                "params": {"field": iv["field"]},
                "sample_issues": iv.get("sample", [])[:3],
            })
            priority += 1

        # Mandatory nulls → fill_null_values
        m_nulls = std_result.get("mandatory_nulls", [])
        for mn in m_nulls:
            steps.append({
                "priority": priority, "tool": "fill_null_values",
                "action": translate(
                    "governance.plan_fill_nulls",
                    field=mn["field"],
                    count=mn["null_count"],
                ),
                "params": {"field": mn["field"], "strategy": "mode"},
            })
            priority += 1

        # CRS check
        if not gdf.crs or "4490" not in str(gdf.crs):
            steps.append({
                "priority": priority, "tool": "standardize_crs",
                "action": translate(
                    "governance.plan_standardize_crs",
                    source=gdf.crs or translate("governance.undefined"),
                ),
                "params": {"target_crs": "EPSG:4490"},
            })
            priority += 1

        # Length violations
        for lv in std_result.get("length_violations", []):
            steps.append({
                "priority": priority, "tool": "clip_outliers",
                "action": translate(
                    "governance.plan_length_violations",
                    field=lv["field"],
                    count=lv["violation_count"],
                    max_length=lv["max_length"],
                ),
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
            "estimated_actions": translate(
                "governance.plan_actions", count=len(steps)),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

def check_logic_consistency(file_path: str, rules: str = "") -> str:
    """[数据治理] 逻辑一致性检查 — 校验字段间逻辑关系（如面积=长×宽±容差）。

    Args:
        file_path: 待检查的空间数据文件路径
        rules: JSON 格式的逻辑规则列表，如 '[{"expr":"TBMJ=CD*KD","tolerance":0.01}]'。
               为空时自动从标准注册表加载 formulas。
    """
    try:
        import geopandas as gpd
        gdf = gpd.read_file(file_path)
        violations = []

        if rules:
            rule_list = json.loads(rules)
        else:
            rule_list = []

        for rule in rule_list:
            expr = rule.get("expr", "")
            tol = rule.get("tolerance", 0.01)
            if "=" not in expr:
                continue
            left, right = expr.split("=", 1)
            left = left.strip()
            right = right.strip()
            try:
                left_vals = gdf.eval(left)
                right_vals = gdf.eval(right)
                diff = (left_vals - right_vals).abs()
                bad_mask = diff > tol
                bad_count = int(bad_mask.sum())
                if bad_count > 0:
                    violations.append({
                        "rule": expr,
                        "tolerance": tol,
                        "violation_count": bad_count,
                        "max_diff": float(diff.max()),
                    })
            except Exception as e:
                violations.append({"rule": expr, "error": str(e)})

        result = {
            "status": "pass" if not violations else "fail",
            "total_records": len(gdf),
            "rules_checked": len(rule_list),
            "violations": violations,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


def check_temporal_validity(file_path: str, date_field: str, valid_range: str = "") -> str:
    """[数据治理] 时效性检查 — 检查数据时间戳是否在有效期内。

    Args:
        file_path: 待检查的空间数据文件路径
        date_field: 日期字段名
        valid_range: 有效期范围，格式 'YYYY-MM-DD,YYYY-MM-DD'（起止日期）。为空则检查是否为空值。
    """
    try:
        import geopandas as gpd
        import pandas as pd
        gdf = gpd.read_file(file_path)

        if date_field not in gdf.columns:
            return json.dumps({"status": "error", "message": translate(
                                  "governance.field_not_found", field=date_field)},
                              ensure_ascii=False)

        dates = pd.to_datetime(gdf[date_field], errors="coerce")
        null_count = int(dates.isna().sum())
        total = len(gdf)

        expired_count = 0
        future_count = 0
        if valid_range:
            parts = valid_range.split(",")
            if len(parts) == 2:
                start = pd.Timestamp(parts[0].strip())
                end = pd.Timestamp(parts[1].strip())
                valid_dates = dates.dropna()
                expired_count = int((valid_dates < start).sum())
                future_count = int((valid_dates > end).sum())

        result = {
            "status": "pass" if (expired_count == 0 and future_count == 0 and null_count == 0) else "warn" if null_count > 0 else "fail",
            "total_records": total,
            "date_field": date_field,
            "null_dates": null_count,
            "expired_count": expired_count,
            "future_count": future_count,
            "valid_range": valid_range or "N/A",
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


def check_naming_convention(file_path: str, standard_id: str = "gb_t_24356") -> str:
    """[数据治理] 命名规范检查 — 检查图层名/字段名是否符合标准命名规则。

    Args:
        file_path: 待检查的空间数据文件路径
        standard_id: 标准ID，用于获取标准字段名列表
    """
    try:
        import geopandas as gpd
        gdf = gpd.read_file(file_path)
        actual_fields = list(gdf.columns)

        from ..standard_registry import StandardRegistry
        std = StandardRegistry.get(standard_id)

        issues = []
        # Check for non-ASCII field names (common issue in Chinese GIS data)
        import re
        for f in actual_fields:
            if f == "geometry":
                continue
            if not re.match(r'^[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*$', f):
                issues.append({
                    "field": f,
                    "issue": translate("governance.name_invalid_chars"),
                })
            if len(f) > 30:
                issues.append({
                    "field": f,
                    "issue": translate("governance.name_too_long"),
                })

        # Check against standard field names if available
        standard_fields = []
        if std:
            standard_fields = [fs.name for fs in std.fields]
            for sf in standard_fields:
                # Case-insensitive match
                matched = any(af.upper() == sf.upper() for af in actual_fields)
                if not matched and any(af.upper().startswith(sf[:3].upper()) for af in actual_fields):
                    issues.append({
                        "field": sf,
                        "issue": translate(
                            "governance.name_nonstandard", standard_name=sf),
                    })

        result = {
            "status": "pass" if not issues else "warn",
            "total_fields": len(actual_fields),
            "standard_id": standard_id,
            "standard_fields_count": len(standard_fields),
            "naming_issues": issues,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


def classify_defects(file_path: str, standard_id: str = "gb_t_24356") -> str:
    """[数据治理] 缺陷分类统计 — 对数据执行全面检查，按缺陷分类法归类所有问题，输出分类统计和质量评分。

    Args:
        file_path: 待检查的空间数据文件路径
        standard_id: 质检标准ID
    """
    try:
        import geopandas as gpd
        gdf = gpd.read_file(file_path)
        found_defects = []

        # --- Format checks ---
        if gdf.crs is None:
            found_defects.append("MIS-004")  # 坐标系信息缺失
        elif gdf.crs.to_epsg() and gdf.crs.to_epsg() != 4490:
            found_defects.append("FMT-001")  # 坐标系定义错误

        # --- Completeness checks ---
        from ..standard_registry import StandardRegistry
        std = StandardRegistry.get(standard_id)
        if std:
            mandatory = std.get_mandatory_fields()
            for mf in mandatory:
                if mf not in gdf.columns:
                    found_defects.append("MIS-001")  # 必填属性缺失
                    break
                elif gdf[mf].isna().any():
                    found_defects.append("MIS-001")
                    break

        # --- Topology checks ---
        if hasattr(gdf, "geometry") and gdf.geometry is not None:
            invalid_count = int((~gdf.geometry.is_valid).sum())
            if invalid_count > 0:
                found_defects.append("TOP-005")  # 无效几何

            empty_count = int(gdf.geometry.is_empty.sum())
            if empty_count > 0:
                found_defects.append("TOP-005")

            # Check duplicates
            if len(gdf) > 1:
                from shapely import equals_exact
                dup_count = 0
                geoms = gdf.geometry.values
                seen = set()
                for i, g in enumerate(geoms):
                    wkb = g.wkb if hasattr(g, "wkb") else str(g)
                    if wkb in seen:
                        dup_count += 1
                    seen.add(wkb)
                if dup_count > 0:
                    found_defects.append("TOP-006")  # 重复要素

        # --- Naming checks ---
        import re
        for col in gdf.columns:
            if col == "geometry":
                continue
            if not re.match(r'^[A-Za-z_\u4e00-\u9fff]', col):
                found_defects.append("NRM-001")
                break

        # Deduplicate
        found_defects = list(dict.fromkeys(found_defects))

        # Compute quality score
        from ..standard_registry import DefectTaxonomy
        score_result = DefectTaxonomy.compute_quality_score(found_defects, total_items=len(gdf))

        # Build detailed defect list
        defect_details = []
        for code in found_defects:
            dt = DefectTaxonomy.get_by_code(code)
            if dt:
                defect_details.append({
                    "code": dt.code,
                    "name": dt.name,
                    "category": dt.category,
                    "severity": dt.severity,
                    "auto_fixable": dt.auto_fixable,
                })

        result = {
            "status": score_result["grade"],
            "total_records": len(gdf),
            "defect_count": len(found_defects),
            "quality_score": score_result["score"],
            "quality_grade": score_result["grade"],
            "severity_counts": score_result["severity_counts"],
            "category_counts": score_result["category_counts"],
            "defects": defect_details,
            "auto_fixable_count": sum(1 for d in defect_details if d.get("auto_fixable")),
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Grid Anonymize — spatial declassification via regular grid aggregation
# ---------------------------------------------------------------------------

_SENSITIVE_FIELD_BLACKLIST = frozenset({
    "bsm", "qsdwdm", "qsdwmc", "zldwdm", "zldwmc",
    "cbf", "cbfmc", "syqr", "syqrmc",
    "qlr", "qlrmc", "zjhm", "zjh",
    "bdcdyh", "zl", "dzwtzb",
})

_LEVEL_GRID_SIZE = {
    "L1": 25.0,
    "L2": 100.0,
    "L3": 250.0,
    "L4": 1000.0,
}

_METRIC_CRS_LOOKUP = {
    4490: 4523,
    4610: 4523,
    4326: 32649,
}


def grid_anonymize(
    file_path: str,
    grid_size_m: float = 100.0,
    level: str = "L2",
    keep_attrs: str = "dlmc,tbmj",
    agg_strategy: str = "mode",
    random_offset: bool = True,
) -> str:
    """[脱密工具] 格网化脱密：将矢量图斑转为规则格网，剥离敏感字段，实现空间数据脱密。

    将原始地类图斑（如 cq_dltb）按指定尺寸的规则方格网进行空间聚合，
    自动剥离权属/标识等涉密字段，仅保留白名单属性的聚合值。
    输出可安全用于跨部门共享或对外展示。

    脱密等级参考：
    - L1 (25m): 内部精细分析，定位精度~13m，仍属内部级
    - L2 (100m): 跨部门协作，定位精度~50m，可内部共享
    - L3 (250m): 对外展示，定位精度~125m，可公开发布
    - L4 (1000m): 科普可视化，仅主导地类

    Args:
        file_path: 输入空间数据文件路径（Shapefile/GeoJSON/GPKG 等）。
        grid_size_m: 格网边长（米），默认 100。若指定 level 则以 level 对应尺寸为准。
        level: 脱密等级 L1/L2/L3/L4，覆盖 grid_size_m。
        keep_attrs: 保留的属性字段（逗号分隔），敏感字段即使列入也会被强制剥离。
        agg_strategy: 聚合策略 mode（众数）/ area_weighted（面积加权）/ topk（前3类占比）。
        random_offset: 是否对格网原点施加随机偏移（防止通过已知格网重建原图斑边界）。

    Returns:
        JSON 格式结果：输出文件路径、格网数、脱密等级、被剥离的敏感字段列表。
    """
    from ..gis_processors import _resolve_path, _generate_output_path
    from ..utils import _load_spatial_data

    try:
        resolved = _resolve_path(file_path)
        gdf = _load_spatial_data(resolved)

        if gdf.empty:
            return json.dumps({
                "status": "error",
                "message": translate("governance.input_empty"),
            }, ensure_ascii=False)

        actual_grid_size = _LEVEL_GRID_SIZE.get(level, grid_size_m)

        # --- 1. Project to metric CRS ---
        src_epsg = gdf.crs.to_epsg() if gdf.crs else None
        target_epsg = _METRIC_CRS_LOOKUP.get(src_epsg, 4523)
        gdf_proj = gdf.to_crs(epsg=target_epsg)

        # --- 2. Determine keep fields (whitelist minus blacklist) ---
        requested_attrs = [a.strip().lower() for a in keep_attrs.split(",") if a.strip()]
        available_cols = [c for c in gdf_proj.columns if c != "geometry"]
        col_lower_map = {c.lower(): c for c in available_cols}

        stripped_sensitive = []
        final_attrs = []
        for attr in requested_attrs:
            if attr in _SENSITIVE_FIELD_BLACKLIST:
                stripped_sensitive.append(attr)
            elif attr in col_lower_map:
                final_attrs.append(col_lower_map[attr])

        # Also detect and report any sensitive fields present in source
        for col in available_cols:
            if col.lower() in _SENSITIVE_FIELD_BLACKLIST and col.lower() not in stripped_sensitive:
                stripped_sensitive.append(col.lower())

        # --- 3. Generate regular grid ---
        minx, miny, maxx, maxy = gdf_proj.total_bounds
        if random_offset:
            rng = np.random.default_rng(42)
            offset_x = rng.uniform(-actual_grid_size / 2, actual_grid_size / 2)
            offset_y = rng.uniform(-actual_grid_size / 2, actual_grid_size / 2)
            minx += offset_x
            miny += offset_y

        cols_count = int(np.ceil((maxx - minx) / actual_grid_size))
        rows_count = int(np.ceil((maxy - miny) / actual_grid_size))

        if cols_count * rows_count > 500_000:
            return json.dumps({
                "status": "error",
                "message": translate(
                    "governance.too_many_grids",
                    count=cols_count * rows_count,
                ),
            }, ensure_ascii=False)

        grid_cells = []
        grid_ids = []
        for row_i in range(rows_count):
            for col_i in range(cols_count):
                x0 = minx + col_i * actual_grid_size
                y0 = miny + row_i * actual_grid_size
                cell = box(x0, y0, x0 + actual_grid_size, y0 + actual_grid_size)
                grid_cells.append(cell)
                col_letter = ""
                ci = col_i
                while True:
                    col_letter = chr(65 + ci % 26) + col_letter
                    ci = ci // 26 - 1
                    if ci < 0:
                        break
                grid_ids.append(f"{col_letter}-{row_i + 1}")

        grid_gdf = gpd.GeoDataFrame(
            {"_ANON_GID": grid_ids},
            geometry=grid_cells,
            crs=f"EPSG:{target_epsg}",
        )

        # --- 4. Spatial join + aggregation ---
        joined = gpd.overlay(gdf_proj, grid_gdf, how="intersection")
        joined["_cell_area"] = joined.geometry.area

        agg_results = []
        for grid_id, group in joined.groupby("_ANON_GID"):
            row_data = {"GRID_ID": grid_id}

            for attr in final_attrs:
                if attr not in group.columns:
                    continue
                if agg_strategy == "mode":
                    mode_val = group[attr].mode()
                    row_data[attr] = mode_val.iloc[0] if not mode_val.empty else None
                elif agg_strategy == "area_weighted":
                    if group[attr].dtype in ("float64", "int64", "float32", "int32"):
                        total_area = group["_cell_area"].sum()
                        if total_area > 0:
                            row_data[attr] = round(
                                (group[attr] * group["_cell_area"]).sum() / total_area, 4
                            )
                        else:
                            row_data[attr] = None
                    else:
                        mode_val = group[attr].mode()
                        row_data[attr] = mode_val.iloc[0] if not mode_val.empty else None
                elif agg_strategy == "topk":
                    area_by_val = group.groupby(attr)["_cell_area"].sum().sort_values(ascending=False)
                    total = area_by_val.sum()
                    top3 = area_by_val.head(3)
                    row_data[attr] = "|".join(
                        f"{v}:{round(a / total * 100, 1)}%" for v, a in top3.items()
                    )

            row_data["Shape_Area"] = round(group["_cell_area"].sum(), 2)
            agg_results.append(row_data)

        if not agg_results:
            return json.dumps({
                "status": "error",
                "message": translate("governance.grid_result_empty"),
            }, ensure_ascii=False)

        # --- 5. Build output GeoDataFrame ---
        result_df = gpd.GeoDataFrame(agg_results)
        grid_lookup = grid_gdf.set_index("_ANON_GID")["geometry"]
        result_df = gpd.GeoDataFrame(
            result_df,
            geometry=result_df["GRID_ID"].map(grid_lookup),
            crs=f"EPSG:{target_epsg}",
        )

        # --- 6. Write output ---
        out_path = _generate_output_path(f"grid_anon_{level}_{int(actual_grid_size)}m", "shp")
        result_df.to_file(out_path, encoding="utf-8")

        output = {
            "status": "ok",
            "output_file": out_path,
            "grid_count": len(result_df),
            "grid_size_m": actual_grid_size,
            "level": level,
            "crs": f"EPSG:{target_epsg}",
            "kept_attrs": final_attrs,
            "stripped_sensitive_fields": sorted(stripped_sensitive),
            "agg_strategy": agg_strategy,
            "random_offset_applied": random_offset,
            "note": translate(
                "governance.anonymize_note",
                level=level,
                precision=f"{actual_grid_size / 2:.0f}",
                access=translate(
                    "governance.access_public"
                    if actual_grid_size >= 250
                    else "governance.access_internal"
                ),
            ),
        }
        return json.dumps(output, ensure_ascii=False, default=str)

    except Exception as e:
        logger.exception("grid_anonymize failed")
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


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
    check_logic_consistency,
    check_temporal_validity,
    check_naming_convention,
    classify_defects,
]


def classify_data_sensitivity(file_path: str) -> str:
    """扫描数据文件中的敏感信息（手机号/身份证/银行卡/邮箱/地址），自动分级。

    Args:
        file_path: 数据文件路径。

    Returns:
        JSON格式的分类结果：敏感等级、各字段 PII 检测结果。
    """
    try:
        from ..data_classification import classify_asset
        result = classify_asset(file_path)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


def recommend_data_model(file_path: str, standard_id: str = "") -> str:
    """根据数据探查结果和目标标准，LLM 自动推荐治理路径和目标数据模型。

    Args:
        file_path: 数据文件路径。
        standard_id: 目标标准ID（如 "dltb_2023"），可选。

    Returns:
        JSON格式的推荐方案：差距分析 + 治理路径 + 目标模型建议。
    """
    try:
        from ..gis_processors import check_field_standards, _resolve_path
        from ..utils import _load_spatial_data

        gdf = _load_spatial_data(file_path)
        current_cols = [c for c in gdf.columns if c != "geometry"]
        col_types = {c: str(gdf[c].dtype) for c in current_cols}

        recommendation = {
            "status": "ok",
            "current_model": {
                "columns": current_cols,
                "column_count": len(current_cols),
                "column_types": col_types,
                "row_count": len(gdf),
                "crs": str(gdf.crs) if gdf.crs else None,
                "geometry_type": list(gdf.geometry.geom_type.unique()) if not gdf.empty else [],
            },
        }

        # If standard provided, compute gap and recommend transformation steps
        if standard_id:
            gap_result = json.loads(generate_gap_matrix(file_path, standard_id))
            if gap_result.get("status") == "ok":
                summary = gap_result.get("summary", {})
                missing = [m["field"] for m in gap_result.get("matrix", []) if m.get("status") == "missing"]
                extra = [m["field"] for m in gap_result.get("matrix", []) if m.get("status") == "extra"]
                type_mismatches = [m["field"] for m in gap_result.get("matrix", [])
                                   if m.get("type_match") is False]

                transforms = []
                if missing:
                    transforms.append({
                        "step": "add_missing_fields",
                        "description": translate(
                            "governance.recommend_add_fields", count=len(missing)),
                        "tool": "add_missing_fields",
                        "fields": missing[:10],
                    })
                if type_mismatches:
                    transforms.append({
                        "step": "cast_field_types",
                        "description": translate(
                            "governance.recommend_cast_fields",
                            count=len(type_mismatches),
                        ),
                        "tool": "cast_field_type",
                        "fields": type_mismatches[:10],
                    })
                if extra:
                    transforms.append({
                        "step": "review_extra_fields",
                        "description": translate(
                            "governance.recommend_review_fields",
                            count=len(extra),
                        ),
                        "fields": extra[:10],
                    })

                recommendation["target_standard"] = standard_id
                recommendation["gap_summary"] = summary
                recommendation["recommended_transforms"] = transforms
                recommendation["estimated_effort"] = (
                    translate("governance.effort_low") if len(transforms) <= 1 else
                    translate("governance.effort_medium") if len(transforms) <= 3 else
                    translate("governance.effort_high")
                )

        return json.dumps(recommendation, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


def grid_anonymize_pg(
    source_table: str,
    output_table: str,
    level: str = "L3",
    grid_size_m: float = 0.0,
    keep_attrs: str = "dlmc,tbmj",
    agg_strategy: str = "mode",
    k_anonymity: int = 5,
    dp_epsilon: float = 0.0,
    dp_numeric_fields: str = "",
    random_offset: bool = True,
    dry_run: bool = False,
) -> str:
    """[脱密工具-DB版] PostGIS 直连格网脱密：对数据库大表做格网化脱密处理。

    适用于行数在 10 万~百万级的 PostGIS 表（如 cq_dltb 101,657 图斑）。
    使用原生 ST_SquareGrid 实现，不经 GeoPandas，避免 OOM。
    输出新 PG 表，自动建空间索引并注册到数据血缘。

    Args:
        source_table: 源表名 (如 "cq_dltb")
        output_table: 输出表名 (如 "cq_dltb_grid_L3_public")
        level: 脱密等级 L1(25m)/L2(100m)/L3(250m)/L4(1000m)
        grid_size_m: 手动指定格网尺寸（米），>0 则覆盖 level
        keep_attrs: 保留字段（逗号分隔），敏感字段即使列入也会被强制剥离
        agg_strategy: mode（众数）/ area_weighted（面积加权）/ topk（类型列表）
        k_anonymity: k-匿名阈值，覆盖源图斑数 < k 的格网会被剔除（默认 5）
        dp_epsilon: 差分隐私预算，>0 时对 dp_numeric_fields 加拉普拉斯噪声
        dp_numeric_fields: 需要加 DP 噪声的数值字段（逗号分隔）
        random_offset: 是否施加格网原点随机偏移
        dry_run: True 仅返回执行计划，不实际写入

    Returns:
        JSON 结果: 输出表/行数/k-匿名过滤数/剥离字段/血缘ID/合规验证入口
    """
    try:
        from ..grid_anonymize import grid_anonymize_pg as _impl
        result = _impl(
            source_table=source_table,
            output_table=output_table,
            level=level,
            grid_size_m=grid_size_m if grid_size_m > 0 else None,
            keep_attrs=[a.strip() for a in keep_attrs.split(",") if a.strip()],
            agg_strategy=agg_strategy,
            k_anonymity=k_anonymity,
            dp_epsilon=dp_epsilon if dp_epsilon > 0 else None,
            dp_numeric_fields=[a.strip() for a in dp_numeric_fields.split(",") if a.strip()],
            random_offset=random_offset,
            dry_run=dry_run,
        )
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("grid_anonymize_pg wrapper failed")
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


def verify_anonymization(
    source_table: str,
    output_table: str,
    sample_size: int = 100,
) -> str:
    """[验证工具] 对脱密输出做逆向攻击测试，计算再识别风险评分。

    5 项测试: 敏感字段泄露 / 几何反推攻击 / k-匿名违规 / l-多样性 / 综合评分。

    Args:
        source_table: 源表名
        output_table: 脱密输出表名
        sample_size: 几何重建攻击的抽样格网数（默认 100）

    Returns:
        JSON: 各维度风险评分 (0-100, 越低越好) + 综合再识别风险 + 判决
    """
    try:
        from ..grid_anonymize import verify_anonymization as _impl
        result = _impl(
            source_table=source_table,
            output_table=output_table,
            sample_size=sample_size,
        )
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("verify_anonymization wrapper failed")
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


def poi_grid_aggregate_pg(
    source_table: str,
    output_table: str,
    category_column: str,
    level: str = "L3",
    grid_size_m: float = 0.0,
    k_anonymity: int = 5,
    top_k_categories: int = 5,
    geom_column: str = "",
    dry_run: bool = False,
) -> str:
    """[脱密工具-POI版] 对点数据（高德 POI/百度 AOI 等）做格网聚合，丢弃所有个体记录。

    与图斑版不同: POI 每点含商户名/电话/精确地址/亚米级坐标等严重 PII,
    不能保留任何个体记录。本工具只输出每格网内: POI 总数 + Top K 类别计数。

    Args:
        source_table: POI 源表 (如 "cq_amap_poi_2024")
        output_table: 输出表 (如 "cq_amap_poi_2024_grid_L3_public")
        category_column: 分类字段名（可含中文，如 "类型"）
        level: L1/L2/L3/L4
        grid_size_m: 手动指定，>0 覆盖 level
        k_anonymity: 格网 POI 数 < k 则剔除
        top_k_categories: 每格网保留 Top K 类别
        geom_column: 几何列名（空则自动检测）
        dry_run: True 仅返回计划

    Returns:
        JSON: 输出表 / 行数 / 源POI数 / 保留POI数 / 血缘ID
    """
    try:
        from ..grid_anonymize import poi_grid_aggregate_pg as _impl
        result = _impl(
            source_table=source_table,
            output_table=output_table,
            category_column=category_column,
            level=level,
            grid_size_m=grid_size_m if grid_size_m > 0 else None,
            k_anonymity=k_anonymity,
            top_k_categories=top_k_categories,
            geom_column=geom_column if geom_column else None,
            dry_run=dry_run,
        )
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("poi_grid_aggregate_pg wrapper failed")
        return json.dumps({"status": "error", "message": translate(
                              "governance.operation_failed", error=e)}, ensure_ascii=False)


_ALL_FUNCS_FINAL = _ALL_FUNCS + [
    classify_data_sensitivity,
    recommend_data_model,
    grid_anonymize,
    grid_anonymize_pg,
    poi_grid_aggregate_pg,
    verify_anonymization,
]


class GovernanceToolset(BaseToolset):
    """数据治理专项审计工具集 — 间隙/完整性/属性/重复/CRS/评分/标准/分类"""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS_FINAL]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
