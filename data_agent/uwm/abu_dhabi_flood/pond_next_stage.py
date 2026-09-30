"""Select a first survey wave and reuse raw evidence without granting admission.

The MILP reduces desk/field review workload on a frozen spatial candidate set.
It has no storage, hydraulic capacity or construction cost constraints and must
never be described as a pond design optimizer or a flood-coverage certificate.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from .pond_planning import SCHEMA as SCREEN_SCHEMA, canonical, load_snapshot

SCHEMA = "gwm.abu_dhabi_flood.pond_next_stage.v1"


def audit_inlet_elevation_fields(evidence: list[dict]) -> dict:
    """Compare numeric fields without inferring units or applying a datum shift."""
    from statistics import median
    rows = []
    for item in evidence:
        props = item["raw_properties"]
        if props.get("asset_role") != "inlet":
            continue
        values = {}
        for name in ["COVER_LEVEL", "INVERT_LEVEL", "GroundElev", "WellBottomElev"]:
            value = props.get(name)
            values[name] = float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None
        cover, invert, ground, bottom = (values[k] for k in ["COVER_LEVEL", "INVERT_LEVEL", "GroundElev", "WellBottomElev"])
        rows.append({"source_key": item["source_key"], **values,
                     "raw_cover_minus_ground_numeric": None if cover is None or ground is None else cover - ground,
                     "raw_cover_minus_invert_numeric": None if cover is None or invert is None else cover - invert,
                     "processed_ground_minus_bottom_numeric": None if ground is None or bottom is None else ground - bottom,
                     "original_pair_both_zero": cover == 0 and invert == 0,
                     "processed_elevation_source": props.get("ElevSource"),
                     "units_and_vertical_datum": "unconfirmed", "automatic_offset_applied": False})
    deltas = [r["raw_cover_minus_ground_numeric"] for r in rows
              if r["raw_cover_minus_ground_numeric"] is not None and not r["original_pair_both_zero"]]
    return {"records": rows, "inlet_count": len(rows),
            "nonzero_pair_delta_summary": {"count": len(deltas), "minimum": min(deltas) if deltas else None,
                "median": median(deltas) if deltas else None, "maximum": max(deltas) if deltas else None},
            "interpretation": "numeric_comparison_only_different_units_datums_epochs_or_surface_meanings_possible",
            "next_action": "recover_benchmarks_and_dictionary_then_survey_coincident_control_points_before_transforming",
            "automatic_offset_applied": False, "engineering_admitted": False}


def select_survey_wave(result: dict, *, review_existing_ponds: bool = True) -> dict:
    """Lexicographic MILP: site count, crossed utility records, distance lower bound.

    Assign exactly one survey connection per hotspot. This is an initial review
    wave; all other alternatives stay in the source screening for escalation.
    """
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp

    if result.get("schema") != SCREEN_SCHEMA or result.get("engineering_admitted") is not False:
        raise ValueError("pond_next_stage_spatial_screen_required")
    if type(review_existing_ponds) is not bool:
        raise ValueError("pond_next_stage_review_policy_invalid")
    candidates = sorted(result["candidates"], key=lambda x: x["candidate_id"])
    links = sorted(result["connections"], key=lambda x: x["connection_id"])
    hotspots = sorted(f["properties"]["source_key"] for f in result["geojson"]["hotspots"]["features"])
    ids = [c["candidate_id"] for c in candidates]
    if not 1 <= len(candidates) <= 200 or not 1 <= len(links) <= 2000 or not hotspots:
        raise ValueError("pond_next_stage_empty_or_oversized_input")
    if len(set(ids)) != len(ids) or len(set(hotspots)) != len(hotspots) or len({l["connection_id"] for l in links}) != len(links):
        raise ValueError("pond_next_stage_duplicate_id")
    if any(l["candidate_id"] not in ids or l["hotspot_id"] not in hotspots for l in links):
        raise ValueError("pond_next_stage_connection_reference_invalid")
    if len({(l["candidate_id"], l["hotspot_id"]) for l in links}) != len(links):
        raise ValueError("pond_next_stage_duplicate_pair")
    for link in links:
        distance, crossings = link["distance_lower_bound_m"], link["utility_intersections"]
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance) or not 0 <= distance <= 5000:
            raise ValueError("pond_next_stage_distance_invalid")
        if type(crossings) is not int or not 0 <= crossings <= 10000000:
            raise ValueError("pond_next_stage_utility_count_invalid")
    missing = [h for h in hotspots if not any(l["hotspot_id"] == h for l in links)]
    if missing:
        raise ValueError("pond_next_stage_hotspots_without_alternatives:" + ",".join(missing))
    n, m = len(candidates), len(links)
    rows, lower, upper = [], [], []
    for h in hotspots:
        row = np.zeros(n + m)
        for j, link in enumerate(links):
            if link["hotspot_id"] == h:
                row[n + j] = 1
        rows.append(row); lower.append(1); upper.append(1)
    for j, link in enumerate(links):
        row = np.zeros(n + m); row[n + j] = 1; row[ids.index(link["candidate_id"])] = -1
        rows.append(row); lower.append(-np.inf); upper.append(0)
    mandatory = [c["candidate_id"] for c in candidates if review_existing_ponds and c["kind"] == "existing_pond_asset"]
    bound_lower = np.zeros(n + m)
    for cid in mandatory:
        bound_lower[ids.index(cid)] = 1
    objectives = [
        ("distinct_review_sites", np.r_[np.ones(n), np.zeros(m)]),
        ("assigned_connection_utility_record_intersections", np.r_[np.zeros(n), [l["utility_intersections"] for l in links]]),
        ("assigned_connection_distance_lower_bound_cm", np.r_[np.zeros(n), [round(l["distance_lower_bound_m"] * 100) for l in links]]),
    ]
    receipts = []
    for name, objective in objectives:
        solved = milp(objective, integrality=np.ones(n + m), bounds=Bounds(bound_lower, np.ones(n + m)),
                      constraints=LinearConstraint(np.asarray(rows), lower, upper),
                      options={"time_limit": 30, "mip_rel_gap": 0})
        if not solved.success or solved.x is None or solved.status != 0:
            raise ValueError(f"pond_survey_milp_not_optimal:{name}:{solved.status}")
        solution = np.rint(solved.x).astype(int)
        if np.max(np.abs(solved.x - solution)) > 1e-5:
            raise ValueError("pond_survey_milp_nonintegral_solution")
        value = int(round(float(objective @ solution)))
        receipts.append({"objective": name, "optimum": value, "mip_gap": float(solved.mip_gap)})
        rows.append(objective); lower.append(value); upper.append(value)
    chosen = [c for i, c in enumerate(candidates) if solution[i]]
    assigned = [l for j, l in enumerate(links) if solution[n + j]]
    chosen_ids = {c["candidate_id"] for c in chosen}
    if len(assigned) != len(hotspots) or {l["hotspot_id"] for l in assigned} != set(hotspots) or any(l["candidate_id"] not in chosen_ids for l in assigned):
        raise ValueError("pond_survey_milp_postcondition_failed")
    return {"catchment_fid": result["catchment_fid"], "catchment_label": result["catchment"]["label"],
            "screening_id": result["screening_id"], "selected_candidates": chosen, "assigned_connections": assigned,
            "deferred_candidate_ids": [cid for cid in ids if cid not in chosen_ids],
            "mandatory_existing_pond_ids": mandatory, "solver": "scipy.optimize.milp/HiGHS", "objectives": receipts,
            "selection_meaning": "first_survey_wave_one_spatial_alternative_per_hotspot",
            "optimality_scope": "frozen_nearest_candidate_graph_and_stated_review_policy_only",
            "hydraulic_coverage_proven": False, "engineering_cost_optimized": False}


def _task(scope: str, key: str, code: str, title: str, role: str, acceptance: str, *, conditional: bool = False) -> dict:
    return {"task_id": hashlib.sha256(canonical([scope, key, code])).hexdigest()[:20],
            "scope": scope, "scope_id": key, "requirement": code, "title": title,
            "suggested_owner_role": role, "assigned_owner": "", "status": "conditional_pending" if conditional else "pending",
            "acceptance_evidence": acceptance, "value": None, "unit": None, "vertical_datum": None,
            "evidence_file": None, "evidence_sha256": None, "reviewer": None, "reviewed_at": None}


def build_next_stage_package(results: list[dict], *, root: Path | None = None, review_existing_ponds: bool = True) -> dict:
    if not results or len({r["snapshot_id"] for r in results}) != 1:
        raise ValueError("pond_next_stage_one_snapshot_required")
    if len({r["catchment_fid"] for r in results}) != len(results):
        raise ValueError("pond_next_stage_duplicate_pilot")
    results = sorted(results, key=lambda r: int(r["catchment_fid"]))
    snapshot_id = results[0]["snapshot_id"]
    manifest, layers = load_snapshot(snapshot_id, root=root, layer_names={"stormwater", "parcels", "ponds"})
    waves = [select_survey_wave(r, review_existing_ponds=review_existing_ponds) for r in results]
    records = {f["properties"]["source_key"]: f for name in layers for f in layers[name]["features"]}
    source_evidence, survey_features, tasks = [], [], []
    for code, title, role, evidence in [
        ("datum_units_dictionary", "恢复原始高程基准、字段单位和加工规则", "数据提供方与测量负责人", "原始元数据、字段字典、DEM精度及竖向转换证据；禁止以展示Z值替代测量"),
        ("cost_catalogue", "建立分项工程量及单价目录", "造价与运维负责人", "价格日期和币种；挖运、防护、占地、穿越、泵管租赁、能耗、维护及恢复成本"),
        ("acceptance_criteria", "签认保护与不转移风险标准", "DMT业务与水力负责人", "按保护对象签认水深/历时、最大水位、排空时间、下游增淹及模型质量阈值"),
    ]:
        tasks.append(_task("study", snapshot_id, code, title, role, evidence))
    source_keys = set()
    for result, wave in zip(results, waves, strict=True):
        fid = wave["catchment_fid"]
        for code, title, evidence in [
            ("domain_and_baseline", "核定试点计算域与现状模型", "批准模型输入与校准资料；上下游影响范围；禁止直接以GIS的2公里背景作模型边界"),
            ("event_and_initial_state", "统一降雨、尾水与初始状态", "事件时间轴、时区、设计雨型、潮位基准和泵/塘初态；跨试点复用需明确覆盖关系"),
            ("observations", "取得积水与退水验证观测", "至少一组可对齐事件的时间、水深/范围及退水观测，区分率定与独立验证"),
            ("exchange_and_mesh", "核验一二维交换与局部网格", "入口/井/塘对应2D单元；交换流量方程；路缘/墙/涵洞；禁止双计降雨和交换水量"),
        ]:
            tasks.append(_task("pilot", fid, code, title, "模型与数据负责人", evidence))
        for candidate in wave["selected_candidates"]:
            cid = candidate["candidate_id"]; source_keys.add(cid)
            for code, title, role, evidence in [
                ("permission", "核验土地和资产可用范围", "土地与资产管理负责人", "批准可挖多边形/现状塘使用权、退界、期限、未来开发及维护通行"),
                ("storage_survey", "测定塘形与有效库容", "测量与水工负责人", "塘底、岸顶、入口、最高安全水位、初始水位和泥沙；水位—面积—库容曲线及基准"),
                ("geotechnics", "核验地下水与地勘条件", "岩土与环境负责人", "地下水、土质、边坡稳定及污染；无试验时不计入渗收益"),
                ("overflow_and_recovery", "核定溢流、排空和连续暴雨恢复", "水力与运维负责人", "安全溢流路径及受纳许可；排空能力、下一场雨间隔和失电/堵塞方案"),
            ]:
                tasks.append(_task("candidate", cid, code, title, role, evidence))
        features_by_link = {f["properties"]["connection_id"]: f for f in result["geojson"]["connections"]["features"]}
        hotspot_features = {f["properties"]["source_key"]: f for f in result["geojson"]["hotspots"]["features"]}
        for link in wave["assigned_connections"]:
            lid = link["connection_id"]
            for code, title, evidence, conditional in [
                ("route_survey_and_permission", "复核线路纵断面、障碍与穿越许可", "实地路线与纵断面、道路/地下管线净距、跨权属与穿路许可；直线仅作勘测参考", False),
                ("capture_and_connection", "核实入口捕获与真实水力连接", "入口断面和堵塞、管渠断面/糙率、控制高程和连接拓扑；最近雨水口不等于接入口", False),
                ("pump_if_needed", "泵送方案时补泵管性能及就绪条件", "Q-H/效率曲线、静扬程和全管路损失、供电/燃料、备用和雨前可用性；经核验不用泵后才标不适用", True),
            ]:
                tasks.append(_task("connection", lid, code, title, "测量/管线/机电负责人", evidence, conditional=conditional))
            inlet_key = link.get("nearest_inlet_source_key")
            if inlet_key:
                source_keys.add(inlet_key)
            point_sources = [("hotspot_reference", hotspot_features[link["hotspot_id"]]["geometry"])]
            if lid in features_by_link:
                coords = features_by_link[lid]["geometry"]["coordinates"]
                point_sources.append(("candidate_nearest_edge_reference", {"type": "Point", "coordinates": coords[-1]}))
            if inlet_key in records:
                point_sources.append(("nearest_inlet_reference_not_confirmed_connection", records[inlet_key]["geometry"]))
            for role, geometry in point_sources:
                survey_features.append({"type": "Feature", "geometry": geometry, "properties": {
                    "catchment_fid": fid, "connection_id": lid, "candidate_id": link["candidate_id"],
                    "role": role, "elevation_m": None, "vertical_datum": None,
                    "status": "reference_location_requires_field_confirmation"}})
    for key in sorted(source_keys):
        if key not in records:
            raise ValueError("pond_next_stage_source_evidence_missing:" + key)
        props = records[key]["properties"]
        source_evidence.append({"source_key": key, "raw_properties": props,
            "value_use": "prefill_only_pending_units_datum_quality_and_asset_mapping",
            "engineering_admitted": False, "confirmed_values": {}})
    payload = {"schema": SCHEMA, "snapshot_id": snapshot_id,
               "input_screening_sha256": {r["screening_id"]: hashlib.sha256(canonical(r)).hexdigest() for r in results},
               "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "policy": {"review_existing_ponds": review_existing_ponds, "alternatives_per_hotspot_in_first_wave": 1},
               "survey_waves": waves, "source_evidence": source_evidence, "tasks": tasks,
               "inlet_elevation_field_audit": audit_inlet_elevation_fields(source_evidence),
               "survey_reference_locations": {"type": "FeatureCollection", "features": survey_features},
               "level_definitions": manifest["level_definitions"],
               "stage_status": {"survey_preparation": "ready", "conditional_hydraulic_experiments": "requires_explicit_parameter_scenarios_and_solver_binding",
                                "verified_pilot_hydraulics": "blocked_pending_evidence", "construction_cost_optimization": "blocked_pending_hydraulics_prices_permissions"},
               "engineering_admitted": False, "hydraulic_simulation_executed": False,
               "engineering_cost_optimization_executed": False,
               "limitations": ["one_reference_alternative_is_not_flood_capacity_or_redundancy", "unit_site_count_and_record_crossings_are_workload_proxies_not_costs",
                    "optimal_only_within_frozen_spatial_candidates", "missing_or_failed_permissions_trigger_reselection_from_retained_alternatives",
                    "field_work_requires_access_and_asset_owner_coordination", "source_values_and_source_geometry_are_not_survey_acceptance"]}
    payload["package_id"] = "pond-next-" + hashlib.sha256(canonical(payload)).hexdigest()[:20]
    return payload
