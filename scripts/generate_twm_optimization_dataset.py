#!/usr/bin/env python3
"""Generate multi-objective optimization fixtures for TWM datasets.

This script turns an existing TWM data package into a decision-comparison
dataset: objectives, candidate scenarios, action space, constraint masks,
scenario metrics, constraint violations, and a Pareto summary.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_multi_admin_eval")
DEFAULT_PROJECT_CRS = "EPSG:32648"
GENERATED_DATE = "2026-06-16"


OBJECTIVES = [
    {
        "objective_id": "pbf_overlap_m2",
        "objective_name_zh": "永久基本农田占用最小化",
        "category": "hard_constraint",
        "direction": "min",
        "unit": "m2",
        "weight": 1.0,
        "hard_constraint": True,
        "description_zh": "候选方案与永久基本农田保护范围的正面积叠置，应优先为 0。",
    },
    {
        "objective_id": "eco_overlap_m2",
        "objective_name_zh": "生态保护红线触碰最小化",
        "category": "hard_constraint",
        "direction": "min",
        "unit": "m2",
        "weight": 1.0,
        "hard_constraint": True,
        "description_zh": "候选方案与生态保护红线的正面积叠置，应优先为 0。",
    },
    {
        "objective_id": "planning_conflict_m2",
        "objective_name_zh": "用途管制冲突最小化",
        "category": "planning_consistency",
        "direction": "min",
        "unit": "m2",
        "weight": 0.8,
        "hard_constraint": False,
        "description_zh": "候选方案与规划分区或用途管制规则不一致的面积。",
    },
    {
        "objective_id": "farmland_loss_m2",
        "objective_name_zh": "耕地损失最小化",
        "category": "resource_protection",
        "direction": "min",
        "unit": "m2",
        "weight": 0.9,
        "hard_constraint": False,
        "description_zh": "候选方案或推演变化造成的耕地面积减少。",
    },
    {
        "objective_id": "farmland_gain_m2",
        "objective_name_zh": "耕地补充最大化",
        "category": "resource_protection",
        "direction": "max",
        "unit": "m2",
        "weight": 0.55,
        "hard_constraint": False,
        "description_zh": "候选方案或推演变化带来的耕地补充面积。",
    },
    {
        "objective_id": "development_area_m2",
        "objective_name_zh": "建设承载能力最大化",
        "category": "development",
        "direction": "max",
        "unit": "m2",
        "weight": 0.45,
        "hard_constraint": False,
        "description_zh": "在合法可行空间内可承载的项目或建设调整面积。",
    },
    {
        "objective_id": "compactness_score",
        "objective_name_zh": "空间紧凑性最大化",
        "category": "spatial_form",
        "direction": "max",
        "unit": "score",
        "weight": 0.5,
        "hard_constraint": False,
        "description_zh": "基于 4*pi*area/perimeter^2 的面积加权紧凑度近似指标。",
    },
    {
        "objective_id": "adjustment_cost_proxy",
        "objective_name_zh": "调整成本最小化",
        "category": "cost",
        "direction": "min",
        "unit": "proxy",
        "weight": 0.55,
        "hard_constraint": False,
        "description_zh": "用调整面积、硬约束触碰和规划冲突构造的工程测试成本代理指标。",
    },
    {
        "objective_id": "admin_fairness_cv",
        "objective_name_zh": "行政区负担均衡",
        "category": "fairness",
        "direction": "min",
        "unit": "cv",
        "weight": 0.35,
        "hard_constraint": False,
        "description_zh": "方案面积在行政单元间分布的变异系数，越低代表越均衡。",
    },
    {
        "objective_id": "robustness_score",
        "objective_name_zh": "方案稳健性最大化",
        "category": "uncertainty",
        "direction": "max",
        "unit": "score",
        "weight": 0.45,
        "hard_constraint": False,
        "description_zh": "基于硬约束风险、复核负荷和 WorldModel episode 稳定性的稳健性近似指标。",
    },
    {
        "objective_id": "review_load_count",
        "objective_name_zh": "人工复核负荷最小化",
        "category": "governance",
        "direction": "min",
        "unit": "count",
        "weight": 0.35,
        "hard_constraint": False,
        "description_zh": "候选方案触发需人工复核的规则命中数量。",
    },
    {
        "objective_id": "slope_improvement_pct",
        "objective_name_zh": "坡度适宜性改善最大化",
        "category": "dynamic_projection",
        "direction": "max",
        "unit": "pct",
        "weight": 0.3,
        "hard_constraint": False,
        "description_zh": "来自 WorldModel/MPC 摘要的坡度改善信号；负坡度变化按改善处理。",
    },
    {
        "objective_id": "contiguity_gain",
        "objective_name_zh": "空间连片度提升最大化",
        "category": "dynamic_projection",
        "direction": "max",
        "unit": "score",
        "weight": 0.3,
        "hard_constraint": False,
        "description_zh": "来自 WorldModel/MPC 摘要的连片度变化信号。",
    },
]

FARMLAND_CODES = {"011", "012", "013", "0101", "111", "112", "113"}
FOREST_CODES = {"031", "032", "033", "0301", "0311"}
HARD_CONSTRAINT_OBJECTIVES = {"pbf_overlap_m2", "eco_overlap_m2"}
HARD_CONSTRAINT_TOLERANCE_M2 = 1.0

OPTIMIZATION_FIELD_ALIASES = {
    "objective_id": {"alias_zh": "目标编号", "description_zh": "多目标优化指标的稳定编号。"},
    "objective_name_zh": {"alias_zh": "目标中文名称", "description_zh": "多目标优化指标的中文显示名。"},
    "category": {"alias_zh": "目标类别", "description_zh": "目标所属类别，例如硬约束、资源保护、成本或治理。"},
    "direction": {"alias_zh": "优化方向", "description_zh": "min 表示越小越优，max 表示越大越优。"},
    "unit": {"alias_zh": "计量单位", "description_zh": "指标值的计量单位。"},
    "weight": {"alias_zh": "目标权重", "description_zh": "工程测试中的归一化加权评分权重。"},
    "hard_constraint": {"alias_zh": "是否硬约束", "description_zh": "true 表示该目标属于法定硬约束过滤条件。"},
    "description_zh": {"alias_zh": "中文说明", "description_zh": "目标、方案或字段的中文解释。"},
    "action_id": {"alias_zh": "动作编号", "description_zh": "候选优化动作的稳定编号。"},
    "action_type": {"alias_zh": "动作类型", "description_zh": "候选动作类型，例如项目范围或调整图斑。"},
    "action_area_m2": {"alias_zh": "动作面积", "description_zh": "候选动作范围面积，单位平方米。"},
    "pbf_overlap_m2": {"alias_zh": "永久基本农田叠置面积", "description_zh": "方案或动作与永久基本农田的正面积叠置。"},
    "eco_overlap_m2": {"alias_zh": "生态红线叠置面积", "description_zh": "方案或动作与生态保护红线的正面积叠置。"},
    "planning_conflict_m2": {"alias_zh": "规划冲突面积", "description_zh": "方案或动作与用途管制规则不一致的面积。"},
    "urban_inside_m2": {"alias_zh": "城镇边界内面积", "description_zh": "动作范围落入城镇开发边界内的面积。"},
    "urban_outside_m2": {"alias_zh": "城镇边界外面积", "description_zh": "动作范围落在城镇开发边界外的面积。"},
    "hard_constraint_violation_m2": {"alias_zh": "硬约束触碰面积", "description_zh": "永久基本农田和生态红线触碰面积合计。"},
    "review_hit_count": {"alias_zh": "复核命中数量", "description_zh": "候选动作触发需人工复核规则的次数。"},
    "compactness_score": {"alias_zh": "空间紧凑性得分", "description_zh": "基于面积和周长的紧凑度近似指标。"},
    "feasibility_class": {"alias_zh": "动作可行性类别", "description_zh": "候选动作的硬约束和复核风险分类。"},
    "constraint_id": {"alias_zh": "约束编号", "description_zh": "约束掩码或约束违规项编号。"},
    "constraint_name_zh": {"alias_zh": "约束中文名称", "description_zh": "约束条件的中文显示名。"},
    "optimization_role": {"alias_zh": "优化作用", "description_zh": "约束掩码在优化中的作用，例如硬约束、偏好或统计单元。"},
    "legal_strength": {"alias_zh": "约束强度", "description_zh": "约束的法定或工程强度，例如 hard、soft、aggregation。"},
    "source_layer": {"alias_zh": "来源图层", "description_zh": "约束掩码来源图层。"},
    "scenario_id": {"alias_zh": "方案编号", "description_zh": "候选方案或情景的稳定编号。"},
    "scenario_name_zh": {"alias_zh": "方案中文名称", "description_zh": "候选方案的中文显示名。"},
    "scenario_type": {"alias_zh": "方案类型", "description_zh": "方案类型，例如基线、动态推演、项目组合或压力测试。"},
    "source": {"alias_zh": "方案来源", "description_zh": "方案由现状、动作空间或 WorldModel 输出派生。"},
    "project_count": {"alias_zh": "项目数量", "description_zh": "方案包含的候选项目数量。"},
    "change_count": {"alias_zh": "变化图斑数量", "description_zh": "方案关联的年度变化图斑数量。"},
    "status": {"alias_zh": "数据状态", "description_zh": "数据对象状态，例如 engineering_fixture。"},
    "optimization_scope": {"alias_zh": "优化比较范围", "description_zh": "legal_feasible_space 表示进入合法可行空间比选；stress_test_only 表示仅用于压力测试。"},
    "hard_constraint_status": {"alias_zh": "硬约束状态", "description_zh": "方案通过或被法定硬约束阻断的状态。"},
    "requires_legal_review": {"alias_zh": "需法定复核", "description_zh": "true 表示方案触发硬约束法定复核。"},
    "excluded_from_recommendation": {"alias_zh": "排除推荐", "description_zh": "true 表示该方案不能进入可推荐方案空间。"},
    "feasibility_reason_zh": {"alias_zh": "可行性原因", "description_zh": "方案硬约束可行性分层的中文解释。"},
    "selection_order": {"alias_zh": "选择序号", "description_zh": "项目在方案组合中的选择顺序。"},
    "inclusion_weight": {"alias_zh": "纳入权重", "description_zh": "项目被纳入方案组合的权重。"},
    "metric_value": {"alias_zh": "指标值", "description_zh": "某方案在某优化目标上的原始指标值。"},
    "metric_source": {"alias_zh": "指标来源", "description_zh": "指标由现状、动作空间、规则结果或 WorldModel 输出计算。"},
    "normalized_score": {"alias_zh": "归一化得分", "description_zh": "按目标方向归一化后的 0-1 得分。"},
    "weighted_score": {"alias_zh": "加权得分", "description_zh": "归一化得分乘以目标权重后的得分。"},
    "severity": {"alias_zh": "严重程度", "description_zh": "约束违规严重程度。"},
    "violation_value": {"alias_zh": "违规值", "description_zh": "约束违规面积、数量或其他计量值。"},
    "requires_review": {"alias_zh": "需要复核", "description_zh": "true 表示该违规项需要人工或法定复核。"},
}


def _read_gdf(data_dir: Path, filename: str, project_crs: str) -> gpd.GeoDataFrame:
    path = data_dir / filename
    if not path.exists():
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=project_crs)
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"{path} has no CRS")
    return gdf.to_crs(project_crs)


def _read_table(data_dir: Path, name: str) -> pd.DataFrame:
    path = data_dir / "tables" / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_relation(data_dir: Path, name: str) -> pd.DataFrame:
    path = data_dir / "relations" / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return number
    except Exception:
        return default


def _metric_map_from_relation(df: pd.DataFrame) -> dict[str, float]:
    if df.empty or "project_id" not in df.columns or "overlap_area_m2" not in df.columns:
        return {}
    grouped = pd.to_numeric(df["overlap_area_m2"], errors="coerce").fillna(0.0).groupby(df["project_id"]).sum()
    return {str(k): float(v) for k, v in grouped.to_dict().items()}


def _rule_metric_maps(rule_eval: pd.DataFrame) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    metrics: dict[str, dict[str, float]] = {}
    hit_counts: dict[str, int] = {}
    if rule_eval.empty or "project_id" not in rule_eval.columns:
        return metrics, hit_counts
    for _, row in rule_eval.iterrows():
        pid = str(row.get("project_id", ""))
        rule_id = str(row.get("rule_id", ""))
        value = _safe_float(row.get("metric_value"))
        if "FARM" in rule_id:
            metrics.setdefault("pbf_overlap_m2", {})[pid] = value
        elif "ECO" in rule_id:
            metrics.setdefault("eco_overlap_m2", {})[pid] = value
        elif "PLAN" in rule_id:
            metrics.setdefault("planning_conflict_m2", {})[pid] = value
        elif "URBAN" in rule_id:
            metrics.setdefault("urban_boundary_conflict_m2", {})[pid] = value
        if str(row.get("finding_status", "")) == "hit_requires_review":
            hit_counts[pid] = hit_counts.get(pid, 0) + 1
    return metrics, hit_counts


def _compactness(gdf: gpd.GeoDataFrame) -> float:
    if gdf.empty:
        return 1.0
    projected = gdf.copy()
    areas = projected.geometry.area.astype(float)
    perimeters = projected.geometry.length.astype(float)
    scores = []
    weights = []
    for area, perimeter in zip(areas, perimeters):
        if area <= 0 or perimeter <= 0:
            continue
        scores.append(max(0.0, min(1.0, (4.0 * math.pi * area) / (perimeter * perimeter))))
        weights.append(area)
    if not scores:
        return 0.0
    return round(float(np.average(scores, weights=weights)), 6)


def _overlay_area(left: gpd.GeoDataFrame, right: gpd.GeoDataFrame) -> float:
    if left.empty or right.empty:
        return 0.0
    right_union = unary_union(list(right.geometry))
    total = 0.0
    for geom in left.geometry:
        inter = geom.intersection(right_union)
        if not inter.is_empty:
            total += float(inter.area)
    return round(total, 3)


def _code_is_farmland(value: Any) -> bool:
    code = str(value or "").strip()
    return code in FARMLAND_CODES or code.startswith("01")


def _build_project_action_space(data_dir: Path, project_crs: str) -> gpd.GeoDataFrame:
    projects = _read_gdf(data_dir, "synthetic_projects.geojson", project_crs)
    if projects.empty:
        return projects
    rule_eval = _read_table(data_dir, "rule_evaluation")
    rule_metrics, hit_counts = _rule_metric_maps(rule_eval)
    pbf_rel = _metric_map_from_relation(_read_relation(data_dir, "project_pbf_rel"))
    eco_rel = _metric_map_from_relation(_read_relation(data_dir, "project_eco_rel"))
    planning_rel = _metric_map_from_relation(_read_relation(data_dir, "project_planning_rel"))
    urban_rel = _metric_map_from_relation(_read_relation(data_dir, "project_urban_boundary_rel"))

    rows = []
    for idx, row in projects.reset_index(drop=True).iterrows():
        pid = str(row.get("project_id") or row.get("XMDM") or f"PROJECT-{idx:05d}")
        area = _safe_float(row.get("planned_area_m2"), _safe_float(row.get("YDMJ"), float(row.geometry.area)))
        pbf_overlap = rule_metrics.get("pbf_overlap_m2", {}).get(pid, pbf_rel.get(pid, 0.0))
        eco_overlap = rule_metrics.get("eco_overlap_m2", {}).get(pid, eco_rel.get(pid, 0.0))
        planning_conflict = rule_metrics.get("planning_conflict_m2", {}).get(pid, planning_rel.get(pid, 0.0))
        urban_inside = urban_rel.get(pid, 0.0)
        urban_outside = max(area - urban_inside, 0.0)
        hard_violation = pbf_overlap + eco_overlap
        review_count = hit_counts.get(pid, 0)
        if hard_violation > max(1.0, area * 0.01):
            feasibility = "blocked_by_hard_constraint"
        elif hard_violation > 0 or review_count > 0:
            feasibility = "requires_review"
        else:
            feasibility = "candidate_feasible"
        attrs = row.drop(labels="geometry").to_dict()
        attrs.update(
            {
                "action_id": f"ACT-{idx + 1:05d}",
                "project_id": pid,
                "action_type": "project_footprint",
                "action_area_m2": round(area, 3),
                "pbf_overlap_m2": round(float(pbf_overlap), 3),
                "eco_overlap_m2": round(float(eco_overlap), 3),
                "planning_conflict_m2": round(float(planning_conflict), 3),
                "urban_inside_m2": round(float(urban_inside), 3),
                "urban_outside_m2": round(float(urban_outside), 3),
                "hard_constraint_violation_m2": round(float(hard_violation), 3),
                "review_hit_count": int(review_count),
                "compactness_score": _compactness(gpd.GeoDataFrame([row], geometry="geometry", crs=projects.crs)),
                "feasibility_class": feasibility,
            }
        )
        rows.append({**attrs, "geometry": row.geometry})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=projects.crs)


def _build_constraint_masks(data_dir: Path, project_crs: str) -> gpd.GeoDataFrame:
    specs = [
        ("synthetic_pbf.geojson", "MASK-PBF", "永久基本农田硬约束掩码", "hard_no_go", "pbf_overlap_m2", "hard"),
        ("synthetic_eco_redline.geojson", "MASK-ECO", "生态保护红线硬约束掩码", "hard_no_go", "eco_overlap_m2", "hard"),
        ("synthetic_urban_boundary.geojson", "MASK-URBAN", "城镇开发边界偏好掩码", "development_preferred", "urban_outside_m2", "soft"),
        ("admin_units.geojson", "MASK-ADMIN", "行政区公平性统计单元", "aggregation_unit", "admin_fairness_cv", "aggregation"),
    ]
    rows = []
    for filename, cid, name, role, objective_id, strength in specs:
        gdf = _read_gdf(data_dir, filename, project_crs)
        if gdf.empty:
            continue
        geom = unary_union(list(gdf.geometry))
        rows.append(
            {
                "constraint_id": cid,
                "constraint_name_zh": name,
                "optimization_role": role,
                "objective_id": objective_id,
                "legal_strength": strength,
                "source_layer": filename,
                "area_m2": round(float(geom.area), 3),
                "synthetic": bool(gdf["synthetic"].astype(bool).all()) if "synthetic" in gdf.columns else False,
                "not_for_production": True,
                "geometry": geom,
            }
        )
    planning = _read_gdf(data_dir, "synthetic_planning_zones.geojson", project_crs)
    if not planning.empty:
        group_col = "GHFQMC" if "GHFQMC" in planning.columns else "plan_zone_type"
        for value, group in planning.groupby(group_col, dropna=False):
            geom = unary_union(list(group.geometry))
            rows.append(
                {
                    "constraint_id": f"MASK-PLAN-{len(rows) + 1:03d}",
                    "constraint_name_zh": f"规划分区掩码-{value}",
                    "optimization_role": "planning_compatibility",
                    "objective_id": "planning_conflict_m2",
                    "legal_strength": "soft",
                    "source_layer": "synthetic_planning_zones.geojson",
                    "area_m2": round(float(geom.area), 3),
                    "synthetic": bool(group["synthetic"].astype(bool).all()) if "synthetic" in group.columns else False,
                    "not_for_production": True,
                    "geometry": geom,
                }
            )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=project_crs)


def _world_model_metrics(data_dir: Path, changes: gpd.GeoDataFrame, pbf: gpd.GeoDataFrame, eco: gpd.GeoDataFrame) -> dict[str, float]:
    path = data_dir / "world_model_summary.json"
    summary: dict[str, Any] = {}
    if path.exists():
        summary = json.loads(path.read_text(encoding="utf-8"))
    aggregate = summary.get("aggregate", {})
    results = summary.get("results", [])
    rewards = [_safe_float(row.get("total_reward")) for row in results if row.get("total_reward") is not None]
    reward_mean = float(np.mean(rewards)) if rewards else 0.0
    reward_std = float(np.std(rewards)) if rewards else 0.0

    farmland_loss = 0.0
    farmland_gain = 0.0
    if not changes.empty:
        for _, row in changes.iterrows():
            from_code = row.get("from_dlbm") or row.get("ORIG_DLBM") or row.get("JQDLDM")
            to_code = row.get("to_dlbm") or row.get("OPT_DLBM") or row.get("GHDLDM")
            area = _safe_float(row.get("geom_area_m2"), float(row.geometry.area))
            if _code_is_farmland(from_code) and not _code_is_farmland(to_code):
                farmland_loss += area
            if not _code_is_farmland(from_code) and _code_is_farmland(to_code):
                farmland_gain += area
    pbf_overlap = _overlay_area(changes, pbf)
    eco_overlap = _overlay_area(changes, eco)
    change_area = float(changes.geometry.area.sum()) if not changes.empty else 0.0
    robustness = 1.0
    if reward_mean:
        robustness = 1.0 / (1.0 + abs(reward_std / reward_mean))
    if change_area:
        robustness /= 1.0 + ((pbf_overlap + eco_overlap) / max(change_area, 1.0))
    return {
        "pbf_overlap_m2": round(pbf_overlap, 3),
        "eco_overlap_m2": round(eco_overlap, 3),
        "planning_conflict_m2": 0.0,
        "farmland_loss_m2": round(float(farmland_loss), 3),
        "farmland_gain_m2": round(float(farmland_gain), 3),
        "development_area_m2": 0.0,
        "compactness_score": _compactness(changes),
        "adjustment_cost_proxy": round(change_area + 2.0 * (pbf_overlap + eco_overlap), 3),
        "admin_fairness_cv": 0.0,
        "robustness_score": round(float(robustness), 6),
        "review_load_count": 0.0,
        "slope_improvement_pct": round(abs(_safe_float(aggregate.get("slope_pct_mean"))), 6),
        "contiguity_gain": round(_safe_float(aggregate.get("cont_mean")), 6),
    }


def _scenario_memberships(action_space: gpd.GeoDataFrame, max_projects: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    scenarios = [
        {
            "scenario_id": "SCN-BASELINE-CURRENT",
            "scenario_name_zh": "现状基线",
            "scenario_type": "baseline",
            "source": "parcel_current",
            "description_zh": "不引入新增项目或优化动作，用于作为多目标比选基准。",
        },
        {
            "scenario_id": "SCN-WM-V21-REFERENCE",
            "scenario_name_zh": "WorldModel v2.1 参考推演",
            "scenario_type": "dynamic_projection",
            "source": "world_model_summary + synthetic_annual_change",
            "description_zh": "使用已有 WorldModel/MPC 输出和年度变化图斑形成的参考推演方案。",
        },
    ]
    memberships = []
    if action_space.empty:
        return pd.DataFrame(scenarios), pd.DataFrame(memberships)

    actions = action_space.copy()
    actions["risk_rank"] = actions["feasibility_class"].map(
        {"candidate_feasible": 0, "requires_review": 1, "blocked_by_hard_constraint": 2}
    ).fillna(1)
    low_risk = actions.sort_values(["risk_rank", "hard_constraint_violation_m2", "planning_conflict_m2", "action_area_m2"]).head(max_projects)
    balanced = actions[actions["feasibility_class"] != "blocked_by_hard_constraint"].sort_values(
        ["review_hit_count", "planning_conflict_m2", "action_area_m2"],
        ascending=[True, True, False],
    ).head(max_projects)
    if balanced.empty:
        balanced = low_risk
    development = actions.sort_values("action_area_m2", ascending=False).head(max_projects)
    ecological = actions[
        (actions["eco_overlap_m2"] <= 1.0)
        & (actions["pbf_overlap_m2"] <= actions["action_area_m2"].clip(lower=1.0) * 0.05)
    ].sort_values(["eco_overlap_m2", "pbf_overlap_m2", "planning_conflict_m2"]).head(max_projects)
    if ecological.empty:
        ecological = low_risk
    review_focus = actions[actions["review_hit_count"] > 0].sort_values(
        ["review_hit_count", "hard_constraint_violation_m2"],
        ascending=[False, False],
    ).head(max_projects)
    if review_focus.empty:
        review_focus = actions.sort_values("hard_constraint_violation_m2", ascending=False).head(max_projects)

    scenario_sets = [
        (
            "SCN-LOW-RISK",
            "低风险优先方案",
            "project_bundle",
            "action_space",
            "优先选择硬约束触碰少、规划冲突低、复核负荷低的项目组合。",
            low_risk,
        ),
        (
            "SCN-BALANCED",
            "均衡治理方案",
            "project_bundle",
            "action_space",
            "在风险、建设承载和空间形态之间保持均衡的项目组合。",
            balanced,
        ),
        (
            "SCN-DEVELOPMENT-PRIORITY",
            "建设承载优先方案",
            "project_bundle",
            "action_space",
            "优先纳入面积较大的项目，用于检验建设承载与约束风险之间的权衡。",
            development,
        ),
        (
            "SCN-ECOLOGICAL-PRIORITY",
            "生态约束优先方案",
            "project_bundle",
            "action_space",
            "优先避让生态红线和永久基本农田的项目组合。",
            ecological,
        ),
        (
            "SCN-REVIEW-FOCUS",
            "复核压力测试方案",
            "stress_test",
            "action_space",
            "集中纳入高风险项目，用于测试规则命中、证据链和人工复核负荷。",
            review_focus,
        ),
    ]
    for sid, name, stype, source, desc, frame in scenario_sets:
        scenarios.append(
            {
                "scenario_id": sid,
                "scenario_name_zh": name,
                "scenario_type": stype,
                "source": source,
                "description_zh": desc,
            }
        )
        for order, (_, row) in enumerate(frame.iterrows(), start=1):
            memberships.append(
                {
                    "scenario_id": sid,
                    "project_id": row["project_id"],
                    "action_id": row["action_id"],
                    "selection_order": order,
                    "inclusion_weight": 1.0,
                    "action_area_m2": row["action_area_m2"],
                    "feasibility_class": row["feasibility_class"],
                    "synthetic": True,
                    "not_for_production": True,
                }
            )
    return pd.DataFrame(scenarios), pd.DataFrame(memberships)


def _scenario_metric_values(
    scenarios: pd.DataFrame,
    memberships: pd.DataFrame,
    action_space: gpd.GeoDataFrame,
    wm_metrics: dict[str, float],
) -> pd.DataFrame:
    action_by_project = action_space.set_index("project_id") if not action_space.empty else pd.DataFrame()
    metric_rows = []
    for _, scenario in scenarios.iterrows():
        sid = scenario["scenario_id"]
        if sid == "SCN-WM-V21-REFERENCE":
            values = wm_metrics.copy()
        else:
            members = memberships[memberships["scenario_id"] == sid] if not memberships.empty else pd.DataFrame()
            selected = action_by_project.loc[members["project_id"].tolist()] if not members.empty and not action_by_project.empty else pd.DataFrame()
            if selected.empty:
                values = {obj["objective_id"]: 0.0 for obj in OBJECTIVES}
                values["compactness_score"] = 1.0
                values["robustness_score"] = 1.0
            else:
                area = pd.to_numeric(selected["action_area_m2"], errors="coerce").fillna(0.0)
                hard = pd.to_numeric(selected["hard_constraint_violation_m2"], errors="coerce").fillna(0.0)
                planning = pd.to_numeric(selected["planning_conflict_m2"], errors="coerce").fillna(0.0)
                review = pd.to_numeric(selected["review_hit_count"], errors="coerce").fillna(0.0)
                admin_area = area.groupby(selected.get("SZXZQDM", selected.get("admin9", pd.Series(["unknown"] * len(selected), index=selected.index))).astype(str)).sum()
                fairness = float(admin_area.std(ddof=0) / admin_area.mean()) if len(admin_area) > 1 and admin_area.mean() else 0.0
                zygdmj = pd.to_numeric(selected.get("ZYGDMJ", pd.Series([0.0] * len(selected), index=selected.index)), errors="coerce").fillna(0.0)
                values = {
                    "pbf_overlap_m2": float(pd.to_numeric(selected["pbf_overlap_m2"], errors="coerce").fillna(0.0).sum()),
                    "eco_overlap_m2": float(pd.to_numeric(selected["eco_overlap_m2"], errors="coerce").fillna(0.0).sum()),
                    "planning_conflict_m2": float(planning.sum()),
                    "farmland_loss_m2": float(zygdmj.sum()),
                    "farmland_gain_m2": 0.0,
                    "development_area_m2": float(area.sum()),
                    "compactness_score": float(np.average(selected["compactness_score"], weights=area)) if area.sum() else 0.0,
                    "adjustment_cost_proxy": float(area.sum() + 2.0 * hard.sum() + 0.5 * planning.sum()),
                    "admin_fairness_cv": fairness,
                    "robustness_score": float(1.0 / (1.0 + hard.sum() / max(area.sum(), 1.0) + review.sum() / 20.0)),
                    "review_load_count": float(review.sum()),
                    "slope_improvement_pct": 0.0,
                    "contiguity_gain": 0.0,
                }
        for obj in OBJECTIVES:
            oid = obj["objective_id"]
            metric_rows.append(
                {
                    "scenario_id": sid,
                    "objective_id": oid,
                    "metric_value": round(float(values.get(oid, 0.0)), 6),
                    "unit": obj["unit"],
                    "direction": obj["direction"],
                    "weight": obj["weight"],
                    "hard_constraint": obj["hard_constraint"],
                    "metric_source": scenario["source"],
                    "synthetic": True,
                    "not_for_production": True,
                }
            )
    metrics = pd.DataFrame(metric_rows)
    metrics["normalized_score"] = 0.0
    for oid, group in metrics.groupby("objective_id"):
        direction = group["direction"].iloc[0]
        values = pd.to_numeric(group["metric_value"], errors="coerce").fillna(0.0)
        min_value = float(values.min())
        max_value = float(values.max())
        if abs(max_value - min_value) < 1e-12:
            scores = pd.Series([1.0] * len(group), index=group.index)
        elif direction == "max":
            scores = (values - min_value) / (max_value - min_value)
        else:
            scores = (max_value - values) / (max_value - min_value)
        metrics.loc[group.index, "normalized_score"] = scores.clip(0.0, 1.0).round(6)
    metrics["weighted_score"] = (metrics["normalized_score"] * metrics["weight"]).round(6)
    return metrics


def _constraint_violations(metrics: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("pbf_overlap_m2", "CONSTRAINT-PBF", "永久基本农田保护", "critical", "m2"),
        ("eco_overlap_m2", "CONSTRAINT-ECO", "生态保护红线", "critical", "m2"),
        ("planning_conflict_m2", "CONSTRAINT-PLANNING", "用途管制分区", "major", "m2"),
        ("review_load_count", "CONSTRAINT-REVIEW", "人工复核负荷", "minor", "count"),
    ]
    rows = []
    for objective_id, constraint_id, name, severity, unit in specs:
        subset = metrics[metrics["objective_id"] == objective_id]
        for _, row in subset.iterrows():
            value = _safe_float(row["metric_value"])
            if value <= 0:
                continue
            rows.append(
                {
                    "scenario_id": row["scenario_id"],
                    "constraint_id": constraint_id,
                    "constraint_name_zh": name,
                    "objective_id": objective_id,
                    "severity": severity,
                    "violation_value": round(value, 6),
                    "unit": unit,
                    "requires_review": severity in {"critical", "major"},
                    "synthetic": True,
                    "not_for_production": True,
                }
            )
    return pd.DataFrame(rows)


def _scenario_feasibility(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty:
        return pd.DataFrame()
    hard = metrics[metrics["objective_id"].isin(HARD_CONSTRAINT_OBJECTIVES)].copy()
    if hard.empty:
        return pd.DataFrame()
    pivot = hard.pivot_table(
        index="scenario_id",
        columns="objective_id",
        values="metric_value",
        aggfunc="sum",
    ).fillna(0.0)
    rows = []
    for sid, row in pivot.iterrows():
        pbf = _safe_float(row.get("pbf_overlap_m2"))
        eco = _safe_float(row.get("eco_overlap_m2"))
        hard_total = pbf + eco
        if hard_total <= HARD_CONSTRAINT_TOLERANCE_M2:
            status = "legal_feasible"
            scope = "legal_feasible_space"
            excluded = False
            reason = "硬约束触碰面积低于工程容差，可进入合法可行空间比选。"
        else:
            status = "blocked_by_hard_constraint"
            scope = "stress_test_only"
            excluded = True
            reason = "触碰永久基本农田或生态保护红线，不能进入合法可推荐方案空间。"
        rows.append(
            {
                "scenario_id": sid,
                "hard_constraint_violation_m2": round(float(hard_total), 6),
                "pbf_overlap_m2": round(float(pbf), 6),
                "eco_overlap_m2": round(float(eco), 6),
                "hard_constraint_status": status,
                "optimization_scope": scope,
                "requires_legal_review": bool(hard_total > HARD_CONSTRAINT_TOLERANCE_M2),
                "excluded_from_recommendation": excluded,
                "feasibility_reason_zh": reason,
            }
        )
    return pd.DataFrame(rows)


def _pareto_summary(metrics: pd.DataFrame, scenarios: pd.DataFrame, objective_catalog: pd.DataFrame) -> dict[str, Any]:
    pivot = metrics.pivot_table(index="scenario_id", columns="objective_id", values="normalized_score", aggfunc="first").fillna(0.0)
    weights = objective_catalog.set_index("objective_id")["weight"].astype(float).to_dict()
    weighted_scores = {}
    for sid, row in pivot.iterrows():
        total_weight = sum(weights.get(col, 0.0) for col in pivot.columns)
        weighted_scores[sid] = round(
            sum(float(row[col]) * weights.get(col, 0.0) for col in pivot.columns) / max(total_weight, 1e-9),
            6,
        )
    scenario_meta = scenarios.set_index("scenario_id").to_dict("index")
    legal_feasible_ids = [
        sid
        for sid in pivot.index
        if scenario_meta.get(sid, {}).get("optimization_scope") == "legal_feasible_space"
    ]
    blocked_ids = [
        sid
        for sid in pivot.index
        if scenario_meta.get(sid, {}).get("optimization_scope") == "stress_test_only"
    ]
    comparison_ids = legal_feasible_ids or list(pivot.index)

    def _dominance_for(ids: list[str]) -> tuple[list[str], dict[str, list[str]]]:
        non_dominated_ids = []
        dominance_map = {}
        scoped = pivot.loc[ids] if ids else pivot.iloc[0:0]
        for sid, row in scoped.iterrows():
            dominated_by = []
            for other_id, other in scoped.iterrows():
                if sid == other_id:
                    continue
                if bool((other >= row).all()) and bool((other > row).any()):
                    dominated_by.append(other_id)
            dominance_map[sid] = dominated_by
            if not dominated_by:
                non_dominated_ids.append(sid)
        return non_dominated_ids, dominance_map

    non_dominated, dominance = _dominance_for(comparison_ids)
    all_non_dominated, all_dominance = _dominance_for(list(pivot.index))
    ranked = sorted(
        ((sid, weighted_scores[sid]) for sid in comparison_ids),
        key=lambda item: item[1],
        reverse=True,
    )
    all_ranked = sorted(weighted_scores.items(), key=lambda item: item[1], reverse=True)
    scenario_names = scenarios.set_index("scenario_id")["scenario_name_zh"].to_dict()
    def _scenario_payload(sid: str, score: float | None = None) -> dict[str, Any]:
        meta = scenario_meta.get(sid, {})
        payload: dict[str, Any] = {
            "scenario_id": sid,
            "scenario_name_zh": scenario_names.get(sid, sid),
            "hard_constraint_status": meta.get("hard_constraint_status"),
            "optimization_scope": meta.get("optimization_scope"),
            "hard_constraint_violation_m2": meta.get("hard_constraint_violation_m2"),
        }
        if score is not None:
            payload["weighted_score"] = score
        return payload

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "hard_constraint_filter_then_normalized_weighted_score_and_non_dominated_sorting",
        "not_for_production": True,
        "hard_constraint_tolerance_m2": HARD_CONSTRAINT_TOLERANCE_M2,
        "hard_constraint_policy_zh": (
            "永久基本农田和生态保护红线作为法定硬约束先过滤；超过工程容差的方案仅保留为压力测试"
            "或复核样本，不进入合法可推荐空间的 Pareto 排序。"
        ),
        "objective_count": int(len(objective_catalog)),
        "scenario_count": int(len(scenarios)),
        "legal_feasible_scenario_count": int(len(legal_feasible_ids)),
        "blocked_scenario_count": int(len(blocked_ids)),
        "comparison_scope": "legal_feasible_space" if legal_feasible_ids else "all_scenarios_no_legal_feasible_found",
        "non_dominated_scenarios": [
            _scenario_payload(sid, weighted_scores[sid])
            for sid in non_dominated
        ],
        "ranked_scenarios": [
            {"rank": i + 1, **_scenario_payload(sid, score)}
            for i, (sid, score) in enumerate(ranked)
        ],
        "blocked_scenarios": [_scenario_payload(sid, weighted_scores[sid]) for sid in blocked_ids],
        "all_scenario_ranked": [
            {"rank": i + 1, **_scenario_payload(sid, score)}
            for i, (sid, score) in enumerate(all_ranked)
        ],
        "all_scenario_non_dominated": [_scenario_payload(sid, weighted_scores[sid]) for sid in all_non_dominated],
        "dominance": dominance,
        "all_scenario_dominance": all_dominance,
        "interpretation_zh": (
            "该 Pareto 摘要用于 TWM 工程测试。主排序只比较通过硬约束过滤的合法可行空间，"
            "被硬约束阻断的方案只用于压力测试、证据链和人工复核能力验证；所有结果均不是生产级"
            "行政决策或审批结论。"
        ),
    }


def _update_manifest(data_dir: Path, optimization_dir: Path, summary: dict[str, Any]) -> None:
    path = data_dir / "dataset_manifest.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["optimization_dataset"] = {
        "path": str(optimization_dir),
        "objective_catalog": str(optimization_dir / "objective_catalog.csv"),
        "scenario_candidates": str(optimization_dir / "scenario_candidates.csv"),
        "scenario_feasibility": str(optimization_dir / "scenario_feasibility.csv"),
        "scenario_metrics": str(optimization_dir / "scenario_metrics.csv"),
        "constraint_masks": str(optimization_dir / "constraint_masks.geojson"),
        "action_space": str(optimization_dir / "action_space.geojson"),
        "pareto_summary": str(optimization_dir / "pareto_summary.json"),
        "objective_count": summary["objective_count"],
        "scenario_count": summary["scenario_count"],
        "legal_feasible_scenario_count": summary.get("legal_feasible_scenario_count"),
        "blocked_scenario_count": summary.get("blocked_scenario_count"),
        "not_for_production": True,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _update_evidence_index(data_dir: Path) -> None:
    path = data_dir / "tables" / "multimodal_evidence_index.csv"
    if not path.exists():
        return
    df = pd.read_csv(path)
    remove_types = {
        "optimization_scenario_set",
        "optimization_pareto_summary",
        "world_model_optimization_summary",
    }
    if "evidence_type" in df.columns:
        df = df[~df["evidence_type"].astype(str).isin(remove_types)].copy()
    rows = [
        {
            "evidence_id": "EVD-OPT-000001",
            "evidence_type": "optimization_scenario_set",
            "evidence_uri": "optimization/scenario_candidates.csv",
            "linked_object_id": "TWM-OPTIMIZATION-DATASET",
            "linked_object_type": "optimization_dataset",
            "observed_date": GENERATED_DATE,
            "confidence": 0.82,
            "synthetic": True,
            "not_for_production": True,
        },
        {
            "evidence_id": "EVD-OPT-000002",
            "evidence_type": "optimization_pareto_summary",
            "evidence_uri": "optimization/pareto_summary.json",
            "linked_object_id": "TWM-PARETO-SUMMARY",
            "linked_object_type": "optimization_summary",
            "observed_date": GENERATED_DATE,
            "confidence": 0.82,
            "synthetic": True,
            "not_for_production": True,
        },
    ]
    if (data_dir / "world_model_summary.json").exists():
        rows.append(
            {
                "evidence_id": "EVD-OPT-000003",
                "evidence_type": "world_model_optimization_summary",
                "evidence_uri": "world_model_summary.json",
                "linked_object_id": "WORLD-MODEL-V21-SUMMARY",
                "linked_object_type": "model_output",
                "observed_date": GENERATED_DATE,
                "confidence": 0.86,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    df.to_csv(path, index=False)


def _update_data_dictionary(data_dir: Path) -> None:
    path = data_dir / "data_dictionary.zh.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = payload.setdefault("fields", {})
    for field, meta in OPTIMIZATION_FIELD_ALIASES.items():
        fields.setdefault(field, meta)
    layers = payload.setdefault("layers", {})
    layers.setdefault(
        "optimization",
        {
            "alias_zh": "多目标优化方案比选数据",
            "description_zh": "面向 TWM 动态推演、多目标优化、硬约束过滤和方案比选的工程测试数据目录。",
            "business_role_zh": "动态推演与多目标方案比选",
        },
    )
    payload.setdefault("tables", {}).update(
        {
            "optimization/objective_catalog.csv": {
                "alias_zh": "优化目标目录",
                "description_zh": "定义 TWM 多目标优化使用的硬约束、软约束、收益、成本、公平性和稳健性指标。",
            },
            "optimization/scenario_candidates.csv": {
                "alias_zh": "候选方案清单",
                "description_zh": "记录现状基线、WorldModel 参考推演、项目组合和压力测试方案。",
            },
            "optimization/scenario_feasibility.csv": {
                "alias_zh": "方案硬约束可行性",
                "description_zh": "记录方案是否进入合法可行空间，或仅作为压力测试和复核样本保留。",
            },
            "optimization/scenario_project_membership.csv": {
                "alias_zh": "方案项目组成",
                "description_zh": "记录每个项目组合方案纳入的候选项目和选择顺序。",
            },
            "optimization/scenario_metrics.csv": {
                "alias_zh": "方案多目标指标",
                "description_zh": "记录每个方案在各优化目标上的原始值、归一化得分和加权得分。",
            },
            "optimization/scenario_constraint_violations.csv": {
                "alias_zh": "方案约束违规清单",
                "description_zh": "记录方案触发的硬约束、用途管制和复核负荷问题。",
            },
            "optimization/pareto_summary.json": {
                "alias_zh": "Pareto 比选摘要",
                "description_zh": "硬约束过滤后的 Pareto 非支配集合、加权排序和被阻断方案列表。",
            },
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_readme(optimization_dir: Path) -> None:
    text = """# TWM Optimization Dataset

This directory is an engineering fixture for TWM dynamic projection and
multi-objective scenario comparison.

It is not a production decision output. It organizes the existing test package
into objective definitions, candidate actions, scenario bundles, metrics,
constraint violations, and a Pareto-style summary so the TWM optimization layer
can be developed against a stable contract.

Key files:

- `objective_catalog.csv`
- `action_space.geojson`
- `constraint_masks.geojson`
- `scenario_candidates.csv`
- `scenario_feasibility.csv`
- `scenario_project_membership.csv`
- `scenario_metrics.csv`
- `scenario_constraint_violations.csv`
- `pareto_summary.json`
"""
    (optimization_dir / "README.md").write_text(text, encoding="utf-8")


def build_optimization_dataset(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = Path(args.data_dir)
    optimization_dir = data_dir / "optimization"
    optimization_dir.mkdir(parents=True, exist_ok=True)

    action_space = _build_project_action_space(data_dir, args.project_crs)
    constraint_masks = _build_constraint_masks(data_dir, args.project_crs)
    changes = _read_gdf(data_dir, "synthetic_annual_change.geojson", args.project_crs)
    pbf = _read_gdf(data_dir, "synthetic_pbf.geojson", args.project_crs)
    eco = _read_gdf(data_dir, "synthetic_eco_redline.geojson", args.project_crs)
    wm_metrics = _world_model_metrics(data_dir, changes, pbf, eco)

    scenarios, memberships = _scenario_memberships(action_space, args.max_projects)
    scenarios["project_count"] = scenarios["scenario_id"].map(
        memberships.groupby("scenario_id")["project_id"].nunique().to_dict() if not memberships.empty else {}
    ).fillna(0).astype(int)
    scenarios["change_count"] = scenarios["scenario_id"].map(
        {"SCN-WM-V21-REFERENCE": int(len(changes))}
    ).fillna(0).astype(int)
    scenarios["status"] = "engineering_fixture"
    scenarios["synthetic"] = True
    scenarios["not_for_production"] = True

    objective_catalog = pd.DataFrame(OBJECTIVES)
    metrics = _scenario_metric_values(scenarios, memberships, action_space, wm_metrics)
    violations = _constraint_violations(metrics)
    feasibility = _scenario_feasibility(metrics)
    if not feasibility.empty:
        scenarios = scenarios.merge(feasibility, on="scenario_id", how="left")
    default_text = "硬约束触碰面积低于工程容差，可进入合法可行空间比选。"
    scenarios["hard_constraint_violation_m2"] = pd.to_numeric(
        scenarios.get("hard_constraint_violation_m2", 0.0),
        errors="coerce",
    ).fillna(0.0)
    scenarios["hard_constraint_status"] = scenarios.get(
        "hard_constraint_status",
        pd.Series(["legal_feasible"] * len(scenarios), index=scenarios.index),
    ).fillna("legal_feasible")
    scenarios["optimization_scope"] = scenarios.get(
        "optimization_scope",
        pd.Series(["legal_feasible_space"] * len(scenarios), index=scenarios.index),
    ).fillna("legal_feasible_space")
    scenarios["requires_legal_review"] = scenarios.get(
        "requires_legal_review",
        pd.Series([False] * len(scenarios), index=scenarios.index),
    ).fillna(False).astype(bool)
    scenarios["excluded_from_recommendation"] = scenarios.get(
        "excluded_from_recommendation",
        pd.Series([False] * len(scenarios), index=scenarios.index),
    ).fillna(False).astype(bool)
    scenarios["feasibility_reason_zh"] = scenarios.get(
        "feasibility_reason_zh",
        pd.Series([default_text] * len(scenarios), index=scenarios.index),
    ).fillna(default_text)
    pareto = _pareto_summary(metrics, scenarios, objective_catalog)

    objective_catalog.to_csv(optimization_dir / "objective_catalog.csv", index=False)
    scenarios.to_csv(optimization_dir / "scenario_candidates.csv", index=False)
    memberships.to_csv(optimization_dir / "scenario_project_membership.csv", index=False)
    metrics.to_csv(optimization_dir / "scenario_metrics.csv", index=False)
    violations.to_csv(optimization_dir / "scenario_constraint_violations.csv", index=False)
    feasibility.to_csv(optimization_dir / "scenario_feasibility.csv", index=False)
    if not action_space.empty:
        action_space.to_file(optimization_dir / "action_space.geojson", driver="GeoJSON")
    if not constraint_masks.empty:
        constraint_masks.to_file(optimization_dir / "constraint_masks.geojson", driver="GeoJSON")
    (optimization_dir / "pareto_summary.json").write_text(
        json.dumps(pareto, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _write_readme(optimization_dir)
    _update_manifest(data_dir, optimization_dir, pareto)
    _update_evidence_index(data_dir)
    _update_data_dictionary(data_dir)

    return {
        "status": "success",
        "data_dir": str(data_dir),
        "optimization_dir": str(optimization_dir),
        "objectives": int(len(objective_catalog)),
        "scenarios": int(len(scenarios)),
        "memberships": int(len(memberships)),
        "metrics": int(len(metrics)),
        "violations": int(len(violations)),
        "actions": int(len(action_space)),
        "constraint_masks": int(len(constraint_masks)),
        "non_dominated": pareto["non_dominated_scenarios"],
        "top_ranked": pareto["ranked_scenarios"][:3],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--project-crs", default=DEFAULT_PROJECT_CRS)
    parser.add_argument("--max-projects", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    result = build_optimization_dataset(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
