"""Real-data multi-stage intervention planner over the full-admin UWM graph."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import numpy as np

from data_agent.i18n import t
from data_agent.uwm.offline_world_model_policy import (
    FEATURE_NAMES,
    TARGET_NAMES,
    _degree_by_unit,
    _features_for_action,
    _fit_ridge_multi_output,
    _holdout_indices,
    _mae_by_target,
    _node_features_by_unit,
    _reward_residual_std_by_action_type,
    _target_units,
    _training_row,
)

from .run_store import MultiStageRunStore


SCHEMA = "uwm.multistage_intervention_run.v1"
OVERVIEW_SCHEMA = "uwm.multistage_intervention_overview.v1"
DEFAULT_ACTION_TYPES = (
    "increase_green_infrastructure",
    "traffic_emission_control",
    "add_community_service",
)
DEFAULT_FOCUS_UNIT = "沙坪坝区|土湾街道|975"

FEATURE_DEFINITIONS = [
    {"name": "bias", "label": "常数偏置", "group": "模型基准", "meaning": "所有样本固定为1，承担截距作用"},
    {"name": "action_increase_green_infrastructure", "label": "动作：增绿降温", "group": "动作编码", "meaning": "动作类型独热编码"},
    {"name": "action_traffic_emission_control", "label": "动作：交通减排", "group": "动作编码", "meaning": "动作类型独热编码"},
    {"name": "action_add_community_service", "label": "动作：补充公共服务", "group": "动作编码", "meaning": "动作类型独热编码"},
    {"name": "action_other", "label": "动作：其他", "group": "动作编码", "meaning": "为扩展动作类型保留的兜底编码"},
    {"name": "intensity", "label": "动作强度", "group": "动作强度", "meaning": "当前候选目录统一为1.0"},
    {"name": "target_heat_risk", "label": "目标单元热风险", "group": "目标状态", "meaning": "目标空间单元当前热风险"},
    {"name": "target_air_pollution_exposure", "label": "目标单元污染暴露", "group": "目标状态", "meaning": "目标空间单元当前空气污染暴露"},
    {"name": "target_service_gap", "label": "公共服务缺口", "group": "目标状态", "meaning": "1减当前服务可达性"},
    {"name": "target_equity", "label": "公平性", "group": "目标状态", "meaning": "目标空间单元当前公平性"},
    {"name": "target_livability_gap", "label": "宜居性缺口", "group": "目标状态", "meaning": "1减当前宜居性"},
    {"name": "target_degree_norm", "label": "空间连接度", "group": "空间与交通上下文", "meaning": "目标节点在空间图中的归一化连接度"},
    {"name": "target_travel_time_min_norm", "label": "出行时间", "group": "空间与交通上下文", "meaning": "归一化最近必要服务出行时间"},
    {"name": "target_road_segment_count_norm", "label": "道路段数量", "group": "空间与交通上下文", "meaning": "归一化道路段数量"},
    {"name": "target_road_length_km_norm", "label": "道路总长度", "group": "空间与交通上下文", "meaning": "归一化道路长度"},
    {"name": "target_mean_road_speed_kmh_norm", "label": "平均道路速度", "group": "空间与交通上下文", "meaning": "归一化平均道路速度"},
    {"name": "target_capacity_norm", "label": "设施容量", "group": "空间与交通上下文", "meaning": "归一化服务设施容量代理"},
    {"name": "target_essential_norm", "label": "必要设施数量", "group": "空间与交通上下文", "meaning": "归一化必要设施代理"},
    {"name": "target_travel_time_inverse_norm", "label": "可达性倒数", "group": "空间与交通上下文", "meaning": "归一化出行时间倒数"},
    {"name": "mask_heat_risk", "label": "热风险触发标记", "group": "候选生成依据", "meaning": "是否因热风险阈值进入候选目录"},
    {"name": "mask_air_pollution", "label": "污染触发标记", "group": "候选生成依据", "meaning": "是否因污染暴露阈值进入候选目录"},
    {"name": "mask_service_gap", "label": "服务短板触发标记", "group": "候选生成依据", "meaning": "是否因服务可达性阈值进入候选目录"},
    {"name": "step_index_norm", "label": "规划步骤", "group": "时序上下文", "meaning": "当前动作位于多阶段规划的第几步"},
]

TARGET_DEFINITIONS = [
    {"name": "reward", "label": "综合回报", "meaning": "用于规划器比较候选未来的综合价值"},
    {"name": "heat_risk_delta", "label": "热风险变化", "meaning": "动作后热风险的预测变化"},
    {"name": "air_pollution_exposure_delta", "label": "污染暴露变化", "meaning": "动作后空气污染暴露的预测变化"},
    {"name": "service_accessibility_delta", "label": "服务可达性变化", "meaning": "动作后公共服务可达性的预测变化"},
    {"name": "equity_delta", "label": "公平性变化", "meaning": "动作后公平性的预测变化"},
    {"name": "livability_delta", "label": "宜居性变化", "meaning": "动作后综合宜居性的预测变化"},
]


_FEATURE_I18N_KEYS = {
    item["name"]: f"uwm_service.feature.{item['name']}"
    for item in FEATURE_DEFINITIONS
}
_TARGET_I18N_KEYS = {
    item["name"]: f"uwm_service.target.{item['name']}"
    for item in TARGET_DEFINITIONS
}
_GROUP_I18N_KEYS = {
    "模型基准": "uwm_service.group.baseline",
    "动作编码": "uwm_service.group.action_encoding",
    "动作强度": "uwm_service.group.action_intensity",
    "目标状态": "uwm_service.group.target_state",
    "空间与交通上下文": "uwm_service.group.spatial_context",
    "候选生成依据": "uwm_service.group.candidate_basis",
    "时序上下文": "uwm_service.group.temporal_context",
}


class MultiStageInterventionPlannerService:
    def __init__(self, *, root: Path | None = None, run_root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[3]
        self.data_root = self.root / "data/uwm_public_proxy/chongqing_central"
        configured_run_root = os.environ.get("UWM_MULTISTAGE_RUN_ROOT", "").strip()
        self.run_store = MultiStageRunStore(
            run_root
            or (Path(configured_run_root).expanduser() if configured_run_root else self.root / "outputs/uwm_multistage_intervention/runs")
        )

    def overview(self) -> dict[str, Any]:
        replay, inventory, benchmark, graph, _ = self._assets()
        graph_stats = (replay.get("graph_mdp_state") or {}).get("graph_statistics") or {}
        transitions = (replay.get("trajectory_dataset") or {}).get("transitions") or []
        inventory_summary = inventory.get("summary") or {}
        source_panel_summary = replay.get("source_admin_livability_panel_summary") or {}
        source_graph_summary = replay.get("source_admin_spatial_graph_summary") or {}
        similarity_summary = replay.get("source_geographic_similarity_kernel_summary") or {}
        return {
            "schema": OVERVIEW_SCHEMA,
            "scenario_id": "compound-livability-multistage-intervention",
            "title": t("uwm_service.overview.title"),
            "world_model_necessity": {
                "functionally_required": True,
                "reason": t("uwm_service.overview.world_model_reason"),
                "not_required_brand": t("uwm_service.overview.not_required_brand"),
            },
            "data_foundation": {
                "graph_node_count": int(graph_stats.get("node_count") or 0),
                "graph_edge_count": int(graph_stats.get("edge_count") or 0),
                "available_action_count": int(graph_stats.get("available_action_count") or 0),
                "transition_count": len(transitions),
                "action_type_counts": inventory_summary.get("action_type_counts") or {},
                "geometry_feature_count": len(graph.get("nodes") or []),
                "snapshot_created_at": inventory.get("created_at"),
                "state_feature_count": len(((replay.get("graph_mdp_state") or {}).get("nodes") or [{}])[0].get("features") or {}),
                "joined_admin_count": int(source_panel_summary.get("joined_admin_count") or 0),
                "service_matched_admin_count": int(source_panel_summary.get("service_matched_admin_count") or 0),
                "isolated_node_count": int(source_graph_summary.get("isolated_node_count") or 0),
                "boundary_edge_count": int(source_graph_summary.get("edge_count") or 0),
                "similarity_edge_count": int(similarity_summary.get("similarity_edge_count") or 0),
                "data_layers": self._data_layer_overview(replay, inventory, graph, transitions),
                "evidence_note": t("uwm_service.overview.evidence_note"),
            },
            "action_catalog": self._action_catalog_overview(inventory),
            "simulator_specification": self._simulator_specification(),
            "default_request": {
                "horizon": 2,
                "beam_width": 8,
                "gamma": 0.9,
                "uncertainty_penalty": 0.5,
                "action_types": list(DEFAULT_ACTION_TYPES),
                "county": "",
                "focus_unit": DEFAULT_FOCUS_UNIT,
                "neighborhood_hops": 1,
            },
            "validated_benchmark": {
                "supported_claim": benchmark.get("supported_claim"),
                "policy_improvement_gate": benchmark.get("policy_improvement_gate") or {},
                "dynamics_holdout_metrics": benchmark.get("dynamics_holdout_metrics") or {},
                "claim_boundary": benchmark.get("claim_boundary") or {},
            },
            "claim_boundary": self._claim_boundary(),
        }

    def resolve_focus_area(self, *, county: str = "", township: str = "") -> dict[str, Any]:
        """Resolve model-extracted place names against authoritative graph nodes."""

        _, _, _, graph, _ = self._assets()
        normalized_county = str(county or "").strip()
        normalized_township = str(township or "").strip()
        nodes = graph.get("nodes") or []
        if normalized_township:
            matches = [
                node
                for node in nodes
                if str(node.get("township") or "") == normalized_township
                and (
                    not normalized_county
                    or str(node.get("county") or "") == normalized_county
                )
            ]
            if len(matches) == 1:
                node = matches[0]
                return {
                    "status": "resolved",
                    "focus_unit": str(node.get("unit_id") or ""),
                    "display_name": f"{node.get('county')} · {node.get('township')}",
                    "county_filter": "",
                    "used_default": False,
                    "warning": "",
                }
            warning = t(
                "uwm_service.focus.warning.unknown_area",
                area=f"{normalized_county}{normalized_township}",
            )
            return self._default_focus_resolution(warning)
        if normalized_county:
            county_nodes = [
                node for node in nodes if str(node.get("county") or "") == normalized_county
            ]
            if county_nodes:
                return {
                    "status": "resolved_county",
                    "focus_unit": "",
                    "display_name": normalized_county,
                    "county_filter": normalized_county,
                    "used_default": False,
                    "warning": t("uwm_service.focus.warning.county_scope"),
                }
            return self._default_focus_resolution(
                t("uwm_service.focus.warning.unknown_county", county=normalized_county)
            )
        return self._default_focus_resolution(t("uwm_service.focus.warning.default_area"))

    def _default_focus_resolution(self, warning: str) -> dict[str, Any]:
        parts = DEFAULT_FOCUS_UNIT.split("|")
        return {
            "status": "defaulted",
            "focus_unit": DEFAULT_FOCUS_UNIT,
            "display_name": " · ".join(parts[:2]),
            "county_filter": "",
            "used_default": True,
            "warning": warning,
        }

    def _data_layer_overview(
        self,
        replay: dict[str, Any],
        inventory: dict[str, Any],
        graph: dict[str, Any],
        transitions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        panel = replay.get("source_admin_livability_panel_summary") or {}
        admin_graph = replay.get("source_admin_spatial_graph_summary") or {}
        similarity = replay.get("source_geographic_similarity_kernel_summary") or {}
        return [
            {
                "layer": t("uwm_service.layer.geometry.label"),
                "coverage": t("uwm_service.layer.geometry.coverage", count=len(graph.get("nodes") or [])),
                "content": t("uwm_service.layer.geometry.content"),
                "status": t("uwm_service.status.complete") if len(graph.get("nodes") or []) == 1017 else t("uwm_service.status.review"),
            },
            {
                "layer": t("uwm_service.layer.livability.label"),
                "coverage": t("uwm_service.layer.livability.coverage", count=int(panel.get("joined_admin_count") or 0)),
                "content": t("uwm_service.layer.livability.content"),
                "status": t("uwm_service.status.complete") if int(panel.get("service_missing_admin_count") or 0) == 0 else t("uwm_service.status.missing"),
            },
            {
                "layer": t("uwm_service.layer.relations.label"),
                "coverage": t("uwm_service.layer.relations.coverage", boundary=int(admin_graph.get("edge_count") or 0), similarity=int(similarity.get("similarity_edge_count") or 0)),
                "content": t("uwm_service.layer.relations.content"),
                "status": t("uwm_service.status.available"),
            },
            {
                "layer": t("uwm_service.layer.catalog.label"),
                "coverage": t("uwm_service.layer.catalog.coverage", actions=int((inventory.get("summary") or {}).get("available_action_count") or 0)),
                "content": t("uwm_service.layer.catalog.content"),
                "status": t("uwm_service.status.scenario"),
            },
            {
                "layer": t("uwm_service.layer.training.label"),
                "coverage": t("uwm_service.layer.training.coverage", count=len(transitions)),
                "content": t("uwm_service.layer.training.content"),
                "status": t("uwm_service.status.replay"),
            },
        ]

    def _action_catalog_overview(self, inventory: dict[str, Any]) -> dict[str, Any]:
        summary = inventory.get("summary") or {}
        definitions = inventory.get("action_type_definitions") or {}
        counts = summary.get("action_type_counts") or {}
        thresholds = summary.get("thresholds") or {}
        label_by_type = {
            action_type: t(f"uwm_service.action.{action_type}")
            for action_type in DEFAULT_ACTION_TYPES
        }
        trigger_by_type = {
            "increase_green_infrastructure": t("uwm_service.trigger.heat", threshold=thresholds.get("heat_risk", 0.7)),
            "traffic_emission_control": t("uwm_service.trigger.pollution", threshold=thresholds.get("air_pollution_exposure", 0.6)),
            "add_community_service": t("uwm_service.trigger.service", threshold=thresholds.get("service_accessibility", 0.5)),
        }
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for action in inventory.get("actions") or []:
            grouped[str(action.get("action_type") or "")].append(action)
        rows = []
        for action_type in DEFAULT_ACTION_TYPES:
            examples = sorted(
                grouped.get(action_type) or [],
                key=lambda action: (-self._traditional_need_score(action), str(action.get("action_id") or "")),
            )[:3]
            definition = definitions.get(action_type) or {}
            rows.append(
                {
                    "action_type": action_type,
                    "label": label_by_type[action_type],
                    "instance_count": int(counts.get(action_type) or 0),
                    "trigger": trigger_by_type[action_type],
                    "expected_effect": definition.get("expected_primary_effect"),
                    "examples": [
                        {
                            "target": f"{action.get('target_county')} · {action.get('target_township')}",
                            "intensity": action.get("intensity"),
                            "current_state": action.get("target_features") or {},
                        }
                        for action in examples
                    ],
                }
            )
        return {
            "template_count": len(DEFAULT_ACTION_TYPES),
            "instance_count": int(summary.get("available_action_count") or 0),
            "instance_definition": t(
                "uwm_service.catalog.instance_definition",
                count=int(summary.get("available_action_count") or 0),
            ),
            "intensity_definition": t("uwm_service.catalog.intensity_definition"),
            "historical_project_log": False,
            "rows": rows,
        }

    def _simulator_specification(self) -> dict[str, Any]:
        group_counts: dict[str, int] = defaultdict(int)
        for feature in FEATURE_DEFINITIONS:
            group_counts[str(feature["group"])] += 1
        return {
            "model_class": t("uwm_service.simulator.model_class"),
            "input_dimension": len(FEATURE_NAMES),
            "output_dimension": len(TARGET_NAMES),
            "coefficient_count": len(FEATURE_NAMES) * len(TARGET_NAMES),
            "coefficient_matrix_shape": [len(FEATURE_NAMES), len(TARGET_NAMES)],
            "extra_intercept_count": 0,
            "parameter_explanation": t("uwm_service.simulator.parameter_explanation"),
            "input_groups": [
                {
                    "group": t(_GROUP_I18N_KEYS.get(group, "")) if _GROUP_I18N_KEYS.get(group) else group,
                    "dimension": count,
                }
                for group, count in group_counts.items()
            ],
            "input_features": [
                {
                    **feature,
                    "label": t(_FEATURE_I18N_KEYS[feature["name"]] + ".label"),
                    "meaning": t(_FEATURE_I18N_KEYS[feature["name"]] + ".meaning"),
                    "group": t(_GROUP_I18N_KEYS.get(feature["group"], "")) if _GROUP_I18N_KEYS.get(feature["group"]) else feature["group"],
                }
                for feature in FEATURE_DEFINITIONS
            ],
            "output_targets": [
                {
                    **target,
                    "label": t(_TARGET_I18N_KEYS[target["name"]] + ".label"),
                    "meaning": t(_TARGET_I18N_KEYS[target["name"]] + ".meaning"),
                }
                for target in TARGET_DEFINITIONS
            ],
            "formula": "ŷ = x(1×23) · W(23×6)",
            "training_method": t("uwm_service.simulator.training_method"),
            "scope_note": t("uwm_service.simulator.scope_note"),
        }

    def actions(
        self,
        *,
        county: str = "",
        action_types: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        _, inventory, _, _, _ = self._assets()
        selected_types = set(action_types or DEFAULT_ACTION_TYPES)
        rows = [
            action
            for action in inventory.get("actions") or []
            if str(action.get("action_type")) in selected_types
            and (not county or str(action.get("target_county")) == county)
        ]
        rows.sort(
            key=lambda action: (
                -self._traditional_need_score(action),
                str(action.get("action_id") or ""),
            )
        )
        return {
            "schema": "uwm.multistage_intervention_actions.v1",
            "total": len(rows),
            "returned": min(max(1, limit), len(rows)),
            "county": county,
            "action_types": sorted(selected_types),
            "actions": rows[: max(1, min(limit, 500))],
        }

    def inspect_state(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        """Inspect the current planning state without training or future rollout."""

        payload = request or {}
        replay, inventory, _, graph, admin_geojson = self._assets()
        graph_state = replay.get("graph_mdp_state") or {}
        focus_unit = str(
            payload.get("focus_unit")
            if payload.get("focus_unit") is not None
            else DEFAULT_FOCUS_UNIT
        )
        county = str(payload.get("county") or "").strip()
        neighborhood_hops = int(payload.get("neighborhood_hops") or 1)
        action_types = [
            str(value)
            for value in (payload.get("action_types") or DEFAULT_ACTION_TYPES)
            if str(value) in DEFAULT_ACTION_TYPES
        ]
        allowed_units = self._focus_units(
            graph, focus_unit=focus_unit, neighborhood_hops=neighborhood_hops
        )
        if not focus_unit and county:
            allowed_units = {
                str(node.get("unit_id"))
                for node in graph.get("nodes") or []
                if str(node.get("county") or "") == county
            }
        candidate_actions = self._candidate_actions(
            graph_state.get("available_actions") or [],
            inventory,
            county=county,
            action_types=action_types,
            allowed_units=allowed_units,
        )
        node_features = _node_features_by_unit(graph_state)
        rows = []
        for unit_id in sorted(allowed_units or set(node_features)):
            features = node_features.get(unit_id) or {}
            parts = unit_id.split("|")
            rows.append(
                {
                    "unit_id": unit_id,
                    "display_name": " · ".join(parts[:2]) if len(parts) >= 2 else unit_id,
                    "county": parts[0] if parts else "",
                    "township": parts[1] if len(parts) >= 2 else "",
                    "heat_risk": round(float(features.get("heat_risk") or 0.0), 6),
                    "air_pollution_exposure": round(float(features.get("air_pollution_exposure") or 0.0), 6),
                    "service_accessibility": round(float(features.get("service_accessibility") or 0.0), 6),
                    "equity": round(float(features.get("equity") or 0.0), 6),
                    "livability": round(float(features.get("livability") or 0.0), 6),
                    "candidate_action_count": sum(
                        1
                        for action in candidate_actions
                        if unit_id in _target_units(action)
                    ),
                }
            )
        rows.sort(
            key=lambda row: (
                float(row["livability"]),
                -float(row["heat_risk"]),
                str(row["display_name"]),
            )
        )
        overview = self.overview()
        return {
            "schema": "uwm.multistage_intervention_state_inspection.v1",
            "scenario": {
                "display_name": (
                    t("uwm_service.state.scenario.county", county=county)
                    if county and not focus_unit
                    else t(
                        "uwm_service.state.scenario.focus",
                        area=" · ".join(focus_unit.split("|")[:2]),
                        hops=neighborhood_hops,
                    )
                ),
                "focus_unit": focus_unit,
                "county": county,
                "neighborhood_hops": neighborhood_hops,
            },
            "state_snapshot": {
                "unit_count": len(rows),
                "units": rows,
                "state_dimension_count": 5,
                "state_dimensions": [
                    t("uwm_service.dimension.heat_risk"),
                    t("uwm_service.dimension.air_pollution_exposure"),
                    t("uwm_service.dimension.service_accessibility"),
                    t("uwm_service.dimension.equity"),
                    t("uwm_service.dimension.livability"),
                ],
            },
            "candidate_action_summary": self._candidate_summary(candidate_actions),
            "action_catalog": overview["action_catalog"],
            "simulator_specification": overview["simulator_specification"],
            "data_foundation": overview["data_foundation"],
            "execution_status": {
                "simulator_trained": False,
                "future_rollout_executed": False,
                "planner_executed": False,
                "message": t("uwm_service.state.execution_not_run"),
            },
            "map_update": self._state_inspection_map(
                admin_geojson=admin_geojson,
                rows=rows,
                candidate_actions=candidate_actions,
            ),
            "claim_boundary": self._claim_boundary(),
        }

    def _state_inspection_map(
        self,
        *,
        admin_geojson: dict[str, Any],
        rows: list[dict[str, Any]],
        candidate_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row_by_name = {
            (str(row.get("county") or ""), str(row.get("township") or "")): row
            for row in rows
        }
        features = []
        for feature in admin_geojson.get("features") or []:
            properties = feature.get("properties") or {}
            key = (str(properties.get("county") or ""), str(properties.get("township") or ""))
            row = row_by_name.get(key)
            if not row:
                continue
            enriched = deepcopy(feature)
            enriched["properties"] = {
                "显示名称": row["display_name"],
                "热风险": row["heat_risk"],
                "空气污染暴露": row["air_pollution_exposure"],
                "服务可达性": row["service_accessibility"],
                "公平性": row["equity"],
                "宜居性": row["livability"],
                "候选动作数": row["candidate_action_count"],
                "地图角色": t("uwm_service.map.role.state_input"),
            }
            features.append(enriched)
        return {
            "schema": "map_update.v1",
            "summary": {"title": t("uwm_service.map.state_title")},
            "layers": [
                self._geojson_layer(
                    t("uwm_service.map.state_layer"),
                    features,
                    "#0ea5e9",
                    0.32,
                )
            ],
            "metadata": {
                "fit_bounds": True,
                "view_mode": "uwm_state_inspection_before_rollout",
                "future_rollout_executed": False,
                "candidate_action_count": len(candidate_actions),
                "narrative": t("uwm_service.map.state_narrative"),
            },
        }

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        total_started = perf_counter()
        config = self._validate_request(request)
        asset_started = perf_counter()
        replay, inventory, benchmark, graph, admin_geojson = self._assets()
        asset_load_ms = self._elapsed_ms(asset_started)
        graph_state = replay.get("graph_mdp_state") or {}
        allowed_units = self._focus_units(
            graph,
            focus_unit=config["focus_unit"],
            neighborhood_hops=config["neighborhood_hops"],
        )
        if not config["focus_unit"] and config["county"]:
            allowed_units = {
                str(node.get("unit_id"))
                for node in graph.get("nodes") or []
                if str(node.get("county") or "") == config["county"]
            }
        candidate_actions = self._candidate_actions(
            graph_state.get("available_actions") or [],
            inventory,
            county=config["county"],
            action_types=config["action_types"],
            allowed_units=allowed_units,
        )
        if len(candidate_actions) < config["horizon"]:
            raise ValueError(t("uwm_service.error.insufficient_actions"))

        training_started = perf_counter()
        trained = self._train_dynamics(replay, config)
        training_ms = self._elapsed_ms(training_started)
        node_features = _node_features_by_unit(graph_state)
        degree_by_unit = _degree_by_unit(graph_state)
        kernel_started = perf_counter()
        spillover = self._build_full_admin_spillover(graph, node_features)
        kernel_build_ms = self._elapsed_ms(kernel_started)
        planning_started = perf_counter()
        search = self._beam_search(
            actions=candidate_actions,
            initial_state=node_features,
            degree_by_unit=degree_by_unit,
            trained=trained,
            spillover=spillover,
            config=config,
        )
        selected = search[0]
        search_summary = self._search_summary(
            candidate_count=len(candidate_actions),
            horizon=config["horizon"],
            beam_width=config["beam_width"],
        )
        baselines = self._baselines(
            actions=candidate_actions,
            selected=selected,
            initial_state=node_features,
            degree_by_unit=degree_by_unit,
            trained=trained,
            spillover=spillover,
            config=config,
            benchmark=benchmark,
        )
        dependency = self._state_dependency_diagnostic(
            actions=candidate_actions,
            selected=selected,
            initial_state=node_features,
            degree_by_unit=degree_by_unit,
            trained=trained,
            spillover=spillover,
            config=config,
        )
        planning_ms = self._elapsed_ms(planning_started)
        run_id = f"uwm_multistage_{uuid4().hex[:20]}"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        map_bundle = self._map_payload(
            admin_geojson=admin_geojson,
            selected=selected,
            dependency=dependency,
            run_id=run_id,
            allowed_units=allowed_units,
            initial_state=node_features,
            candidate_actions=candidate_actions,
        )
        total_ms = self._elapsed_ms(total_started)
        run = {
            "schema": SCHEMA,
            "run_id": run_id,
            "created_at": now,
            "scenario_id": "compound-livability-multistage-intervention",
            "request": config,
            "training_summary": trained["summary"],
            "runtime_profile": {
                "asset_load_ms": asset_load_ms,
                "dynamics_training_ms": training_ms,
                "spatial_kernel_build_ms": kernel_build_ms,
                "planning_and_comparison_ms": planning_ms,
                "total_ms": total_ms,
                "execution_device": "local_cpu",
                "gpu_required": False,
            },
            "training_transparency": {
                "training_required": True,
                "trained_component": "simulator_action_conditioned_transition_model",
                "not_trained_components": [
                    "renderer_reads_spatial_state",
                    "kernel_is_computed_from_graph_and_state",
                    "planner_performs_search_over_the_trained_simulator",
                ],
                "current_model_class": "linear_ridge_action_conditioned_dynamics",
                "feature_count": len(FEATURE_NAMES),
                "target_count": len(TARGET_NAMES),
                "coefficient_count": len(FEATURE_NAMES) * len(TARGET_NAMES),
                "training_row_count": trained["summary"]["train_count"],
                "holdout_row_count": trained["summary"]["holdout_count"],
                "why_seconds_not_hours": (
                    t("uwm_service.training.why_seconds")
                ),
                "production_recommendation": t("uwm_service.training.production_recommendation"),
                "deep_neural_world_model_claim": False,
            },
            "nl_scenario_parse": config.get("nl_scenario_parse") or {},
            "world_model_architecture": {
                "renderer": t("uwm_service.architecture.renderer"),
                "simulator": t("uwm_service.architecture.simulator"),
                "planner": t("uwm_service.architecture.planner"),
                "kernel": t("uwm_service.architecture.kernel"),
            },
            "candidate_action_summary": self._candidate_summary(candidate_actions),
            "planning_scope": {
                "focus_unit": config["focus_unit"],
                "neighborhood_hops": config["neighborhood_hops"],
                "allowed_unit_count": len(allowed_units) if allowed_units else 1017,
                "scope_mode": (
                    "county"
                    if config["county"] and not config["focus_unit"]
                    else ("graph_neighborhood" if allowed_units else "full_admin_graph")
                ),
            },
            "selected_sequence": selected,
            "sequence_ranking": search,
            "planner_search_summary": search_summary,
            "state_dependency_diagnostic": dependency,
            "decision_story": self._decision_story(selected, dependency, search_summary),
            "baselines": baselines,
            "map_update": map_bundle["full"],
            "map_scenes": map_bundle["scenes"],
            "claim_boundary": self._claim_boundary(),
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        }
        run["audit"] = {
            "asset_paths": self._asset_paths(),
            "feature_names": FEATURE_NAMES,
            "target_names": TARGET_NAMES,
            "request_digest": self._stable_digest(config),
            "state_update_verified": dependency["state_update_changes_second_step_ranking"],
        }
        self.run_store.save(run)
        return run

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.run_store.load(run_id)

    def get_map(self, run_id: str) -> dict[str, Any]:
        return self.get_run(run_id).get("map_update") or {}

    def _validate_request(self, request: dict[str, Any]) -> dict[str, Any]:
        horizon = int(request.get("horizon") or 2)
        beam_width = int(request.get("beam_width") or 8)
        gamma = float(request.get("gamma") if request.get("gamma") is not None else 0.9)
        uncertainty_penalty = float(
            request.get("uncertainty_penalty")
            if request.get("uncertainty_penalty") is not None
            else 0.5
        )
        action_types = request.get("action_types") or list(DEFAULT_ACTION_TYPES)
        if not isinstance(action_types, list):
            raise ValueError("action_types must be a list")
        action_types = [str(value) for value in action_types if str(value) in DEFAULT_ACTION_TYPES]
        if horizon < 2 or horizon > 3:
            raise ValueError("horizon must be 2 or 3")
        if beam_width < 2 or beam_width > 30:
            raise ValueError("beam_width must be between 2 and 30")
        if not 0.0 < gamma <= 1.0:
            raise ValueError("gamma must be in (0, 1]")
        if uncertainty_penalty < 0.0 or uncertainty_penalty > 5.0:
            raise ValueError("uncertainty_penalty must be between 0 and 5")
        if not action_types:
            raise ValueError("at least one supported action type is required")
        return {
            "horizon": horizon,
            "beam_width": beam_width,
            "gamma": gamma,
            "uncertainty_penalty": uncertainty_penalty,
            "holdout_stride": 7,
            "ridge": 0.001,
            "action_types": action_types,
            "county": str(request.get("county") or "").strip(),
            "focus_unit": str(
                request.get("focus_unit")
                if request.get("focus_unit") is not None
                else DEFAULT_FOCUS_UNIT
            ).strip(),
            "neighborhood_hops": int(request.get("neighborhood_hops") or 1),
            "nl_scenario_parse": request.get("nl_scenario_parse") or {},
        }

    def _train_dynamics(self, replay: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        graph_state = replay.get("graph_mdp_state") or {}
        transitions = (replay.get("trajectory_dataset") or {}).get("transitions") or []
        node_features = _node_features_by_unit(graph_state)
        degree_by_unit = _degree_by_unit(graph_state)
        node_count = max(1, len(node_features))
        rows = [
            _training_row(
                transition,
                node_features=node_features,
                degree_by_unit=degree_by_unit,
                node_count=node_count,
            )
            for transition in transitions
        ]
        matrix = np.array([row["features"] for row in rows], dtype=float)
        targets = np.array([row["targets"] for row in rows], dtype=float)
        holdout_indices = _holdout_indices(len(rows), config["holdout_stride"])
        holdout_set = set(holdout_indices)
        train_indices = [index for index in range(len(rows)) if index not in holdout_set]
        coefficients = _fit_ridge_multi_output(
            matrix[train_indices], targets[train_indices], config["ridge"]
        )
        train_predictions = matrix[train_indices] @ coefficients
        holdout_predictions = matrix[holdout_indices] @ coefficients
        residuals = targets[train_indices, 0] - train_predictions[:, 0]
        residual_std = _reward_residual_std_by_action_type(
            [rows[index] for index in train_indices], residuals
        )
        holdout_mae = _mae_by_target(targets[holdout_indices], holdout_predictions)
        return {
            "coefficients": coefficients,
            "residual_std": residual_std,
            "global_residual_std": float(np.std(residuals)) if residuals.size else 0.0,
            "summary": {
                "model_class": "linear_ridge_action_conditioned_dynamics",
                "transition_count": len(rows),
                "train_count": len(train_indices),
                "holdout_count": len(holdout_indices),
                "holdout_mae_by_target": {
                    key: round(float(value), 9) for key, value in holdout_mae.items()
                },
                "retrained_for_run": True,
            },
        }

    def _beam_search(
        self,
        *,
        actions: list[dict[str, Any]],
        initial_state: dict[str, dict[str, float]],
        degree_by_unit: dict[str, int],
        trained: dict[str, Any],
        spillover: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        beams = [{"actions": [], "steps": [], "state": deepcopy(initial_state), "score": 0.0, "reward": 0.0}]
        for step_index in range(config["horizon"]):
            expanded: list[dict[str, Any]] = []
            for beam in beams:
                used = {str(action.get("action_id")) for action in beam["actions"]}
                for action in actions:
                    if str(action.get("action_id")) in used:
                        continue
                    step, next_state = self._imagine_step(
                        action=action,
                        state=beam["state"],
                        degree_by_unit=degree_by_unit,
                        trained=trained,
                        spillover=spillover,
                        config=config,
                        step_index=step_index,
                        apply_state_update=True,
                    )
                    discount = config["gamma"] ** step_index
                    expanded.append(
                        {
                            "actions": [*beam["actions"], deepcopy(action)],
                            "steps": [*beam["steps"], step],
                            "state": next_state,
                            "score": beam["score"] + discount * step["conservative_reward"],
                            "reward": beam["reward"] + discount * step["predicted_reward"],
                        }
                    )
            expanded.sort(key=lambda row: (row["score"], row["reward"]), reverse=True)
            beams = expanded[: config["beam_width"]]
        return [self._public_sequence(beam) for beam in beams]

    def _imagine_step(
        self,
        *,
        action: dict[str, Any],
        state: dict[str, dict[str, float]],
        degree_by_unit: dict[str, int],
        trained: dict[str, Any],
        spillover: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
        step_index: int,
        apply_state_update: bool,
    ) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
        features = np.array(
            _features_for_action(
                action,
                node_features=state,
                degree_by_unit=degree_by_unit,
                node_count=max(1, len(state)),
                step_index=float(step_index),
            ),
            dtype=float,
        )
        prediction = features @ trained["coefficients"]
        action_type = str(action.get("action_type") or "unknown")
        uncertainty = float(
            trained["residual_std"].get(action_type, trained["global_residual_std"])
        )
        predicted_dynamics = {
            name: round(float(value), 9)
            for name, value in zip(TARGET_NAMES[1:], prediction[1:])
        }
        next_state, propagation = self._apply_spatial_dynamics(
            state=state,
            action=action,
            predicted_dynamics=predicted_dynamics,
            spillover=spillover,
            enabled=apply_state_update,
        )
        conservative = float(prediction[0]) - config["uncertainty_penalty"] * uncertainty
        return (
            {
                "step_index": step_index,
                "action": deepcopy(action),
                "predicted_reward": round(float(prediction[0]), 9),
                "reward_uncertainty": round(uncertainty, 9),
                "conservative_reward": round(conservative, 9),
                "predicted_dynamics": predicted_dynamics,
                "propagation": propagation,
                "post_state_features": {
                    unit_id: next_state.get(unit_id) or {}
                    for unit_id in propagation["affected_unit_ids"]
                },
            },
            next_state,
        )

    def _apply_spatial_dynamics(
        self,
        *,
        state: dict[str, dict[str, float]],
        action: dict[str, Any],
        predicted_dynamics: dict[str, float],
        spillover: dict[str, list[dict[str, Any]]],
        enabled: bool,
    ) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
        propagated_edges: list[dict[str, Any]] = []
        affected: set[str] = set()
        if not enabled:
            return state, {"enabled": False, "affected_unit_ids": [], "edges": []}
        next_state = dict(state)
        for source in _target_units(action):
            if source in next_state:
                next_state[source] = dict(next_state[source])
            self._apply_delta(next_state, source, predicted_dynamics, 1.0)
            affected.add(source)
            for edge in spillover.get(source) or []:
                target = str(edge.get("target_unit_id") or "")
                factor = float(edge.get("spillover_factor") or 0.0)
                if not target or factor <= 0.0:
                    continue
                if target in next_state and target not in affected:
                    next_state[target] = dict(next_state[target])
                self._apply_delta(next_state, target, predicted_dynamics, factor)
                affected.add(target)
                propagated_edges.append(edge)
        return next_state, {
            "enabled": True,
            "kernel": "full_admin_shared_boundary_state_conditioned_v1",
            "affected_unit_count": len(affected),
            "neighbor_affected_unit_count": max(0, len(affected) - len(_target_units(action))),
            "affected_unit_ids": sorted(affected),
            "edges": propagated_edges,
        }

    def _apply_delta(
        self,
        state: dict[str, dict[str, float]],
        unit_id: str,
        dynamics: dict[str, float],
        factor: float,
    ) -> None:
        row = state.get(unit_id)
        if row is None:
            return
        for feature, delta_name in (
            ("heat_risk", "heat_risk_delta"),
            ("air_pollution_exposure", "air_pollution_exposure_delta"),
            ("service_accessibility", "service_accessibility_delta"),
            ("equity", "equity_delta"),
            ("livability", "livability_delta"),
        ):
            row[feature] = self._clamp(float(row.get(feature) or 0.0) + factor * float(dynamics.get(delta_name) or 0.0))
        row["service_gap"] = self._clamp(1.0 - float(row.get("service_accessibility") or 0.0))

    def _baselines(
        self,
        *,
        actions: list[dict[str, Any]],
        selected: dict[str, Any],
        initial_state: dict[str, dict[str, float]],
        degree_by_unit: dict[str, int],
        trained: dict[str, Any],
        spillover: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
        benchmark: dict[str, Any],
    ) -> dict[str, Any]:
        traditional_actions = sorted(actions, key=self._traditional_need_score, reverse=True)[: config["horizon"]]
        traditional = self._evaluate_fixed_sequence(
            traditional_actions, initial_state, degree_by_unit, trained, spillover, config, False
        )
        no_state_actions = self._rank_actions(
            actions, initial_state, degree_by_unit, trained, spillover, config, step_index=0, excluded=set()
        )[: config["horizon"]]
        no_state = self._evaluate_fixed_sequence(
            [row["action"] for row in no_state_actions],
            initial_state,
            degree_by_unit,
            trained,
            spillover,
            config,
            False,
        )
        one_step = self._evaluate_fixed_sequence(
            [no_state_actions[0]["action"]], initial_state, degree_by_unit, trained, spillover, config, True
        )
        selected_score = float(selected.get("discounted_conservative_return") or 0.0)
        policy_gate = benchmark.get("policy_improvement_gate") or {}
        return {
            "traditional_static_top_indicators": traditional,
            "one_step_world_model_greedy": one_step,
            "multi_step_without_state_update": no_state,
            "validated_action_ablation_benchmark": {
                "baseline_rows": policy_gate.get("baseline_rows") or [],
                "dynamics_reward_gate": policy_gate.get("dynamics_reward_gate") or {},
                "policy_variant_metrics": benchmark.get("policy_variant_metrics") or {},
                "scope": "full_admin_graph_prevalidated",
                "same_scene_normalized_metrics": True,
            },
            "advantages": {
                "over_traditional_static": round(selected_score - float(traditional.get("discounted_conservative_return") or 0.0), 9),
                "over_one_step_greedy": round(selected_score - float(one_step.get("discounted_conservative_return") or 0.0), 9),
                "over_multi_step_without_state_update": round(selected_score - float(no_state.get("discounted_conservative_return") or 0.0), 9),
            },
        }

    def _evaluate_fixed_sequence(
        self,
        actions: list[dict[str, Any]],
        initial_state: dict[str, dict[str, float]],
        degree_by_unit: dict[str, int],
        trained: dict[str, Any],
        spillover: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
        update_state: bool,
    ) -> dict[str, Any]:
        state = deepcopy(initial_state)
        beam = {"actions": [], "steps": [], "state": state, "score": 0.0, "reward": 0.0}
        for step_index, action in enumerate(actions):
            step, next_state = self._imagine_step(
                action=action,
                state=state,
                degree_by_unit=degree_by_unit,
                trained=trained,
                spillover=spillover,
                config=config,
                step_index=step_index,
                apply_state_update=update_state,
            )
            discount = config["gamma"] ** step_index
            beam["actions"].append(deepcopy(action))
            beam["steps"].append(step)
            beam["score"] += discount * step["conservative_reward"]
            beam["reward"] += discount * step["predicted_reward"]
            state = next_state if update_state else state
        return self._public_sequence(beam)

    def _state_dependency_diagnostic(
        self,
        *,
        actions: list[dict[str, Any]],
        selected: dict[str, Any],
        initial_state: dict[str, dict[str, float]],
        degree_by_unit: dict[str, int],
        trained: dict[str, Any],
        spillover: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        sequence = selected.get("action_sequence") or []
        if len(sequence) < 2:
            return {"state_update_changes_second_step_ranking": False, "reason": "sequence_too_short"}
        first = sequence[0]
        second = sequence[1]
        _, state_after_first = self._imagine_step(
            action=first,
            state=initial_state,
            degree_by_unit=degree_by_unit,
            trained=trained,
            spillover=spillover,
            config=config,
            step_index=0,
            apply_state_update=True,
        )
        excluded = {str(first.get("action_id"))}
        before = self._rank_actions(
            actions, initial_state, degree_by_unit, trained, spillover, config, step_index=1, excluded=excluded
        )
        after = self._rank_actions(
            actions, state_after_first, degree_by_unit, trained, spillover, config, step_index=1, excluded=excluded
        )
        before_rank = {str(row["action"].get("action_id")): index + 1 for index, row in enumerate(before)}
        after_rank = {str(row["action"].get("action_id")): index + 1 for index, row in enumerate(after)}
        second_id = str(second.get("action_id"))
        changed_count = sum(
            1 for action_id, rank in before_rank.items() if after_rank.get(action_id) != rank
        )
        before_row = next((row for row in before if str(row["action"].get("action_id")) == second_id), {})
        after_row = next((row for row in after if str(row["action"].get("action_id")) == second_id), {})
        before_top = str((before[0]["action"] if before else {}).get("action_id") or "")
        after_top = str((after[0]["action"] if after else {}).get("action_id") or "")
        return {
            "first_action_id": first.get("action_id"),
            "selected_second_action_id": second_id,
            "top_second_action_without_state_update": before_top,
            "top_second_action_after_state_update": after_top,
            "selected_second_rank_without_state_update": before_rank.get(second_id),
            "selected_second_rank_after_state_update": after_rank.get(second_id),
            "selected_second_score_without_state_update": before_row.get("conservative_reward"),
            "selected_second_score_after_state_update": after_row.get("conservative_reward"),
            "changed_action_rank_count": changed_count,
            "state_update_changes_second_step_ranking": changed_count > 0,
            "state_update_changes_top_second_action": before_top != after_top,
            "ranking_before_state_update": self._ranking_preview(before),
            "ranking_after_state_update": self._ranking_preview(after),
            "ranking_changes": self._ranking_changes(before, after),
            "explanation": t("uwm_service.decision.ranking_explanation"),
        }

    def _ranking_preview(self, ranking: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "rank": index + 1,
                "action_id": row["action"].get("action_id"),
                "action_type": row["action"].get("action_type"),
                "target_unit_id": str((row["action"].get("target_units") or [""])[0]),
                "conservative_reward": row.get("conservative_reward"),
                "predicted_reward": row.get("predicted_reward"),
            }
            for index, row in enumerate(ranking[:limit])
        ]

    def _ranking_changes(
        self,
        before: list[dict[str, Any]],
        after: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        before_rows = {
            str(row["action"].get("action_id")): (index + 1, row)
            for index, row in enumerate(before)
        }
        after_rows = {
            str(row["action"].get("action_id")): (index + 1, row)
            for index, row in enumerate(after)
        }
        changes = []
        for action_id, (before_rank, before_row) in before_rows.items():
            after_rank, after_row = after_rows.get(action_id, (before_rank, before_row))
            if before_rank == after_rank:
                continue
            action = after_row["action"]
            changes.append(
                {
                    "action_id": action_id,
                    "action_type": action.get("action_type"),
                    "target_unit_id": str((action.get("target_units") or [""])[0]),
                    "rank_before": before_rank,
                    "rank_after": after_rank,
                    "rank_delta": before_rank - after_rank,
                    "score_before": before_row.get("conservative_reward"),
                    "score_after": after_row.get("conservative_reward"),
                }
            )
        changes.sort(key=lambda row: (-abs(int(row["rank_delta"])), int(row["rank_after"])))
        return changes

    def _rank_actions(
        self,
        actions: list[dict[str, Any]],
        state: dict[str, dict[str, float]],
        degree_by_unit: dict[str, int],
        trained: dict[str, Any],
        spillover: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
        *,
        step_index: int,
        excluded: set[str],
    ) -> list[dict[str, Any]]:
        ranking = []
        for action in actions:
            if str(action.get("action_id")) in excluded:
                continue
            step, _ = self._imagine_step(
                action=action,
                state=state,
                degree_by_unit=degree_by_unit,
                trained=trained,
                spillover=spillover,
                config=config,
                step_index=step_index,
                apply_state_update=False,
            )
            ranking.append({"action": action, **step})
        ranking.sort(key=lambda row: (row["conservative_reward"], row["predicted_reward"]), reverse=True)
        return ranking

    def _build_full_admin_spillover(
        self,
        graph: dict[str, Any],
        node_features: dict[str, dict[str, float]],
    ) -> dict[str, list[dict[str, Any]]]:
        edges = graph.get("edges") or []
        nodes = {str(node.get("unit_id")): node for node in graph.get("nodes") or []}
        boundary_totals: dict[str, float] = defaultdict(float)
        for edge in edges:
            length = float(edge.get("shared_boundary_length_degrees") or 0.0)
            boundary_totals[str(edge.get("source"))] += length
            boundary_totals[str(edge.get("target"))] += length
        neighbors: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            length = float(edge.get("shared_boundary_length_degrees") or 0.0)
            for source, target in ((str(edge.get("source")), str(edge.get("target"))), (str(edge.get("target")), str(edge.get("source")))):
                if not source or not target or length <= 0.0:
                    continue
                source_features = node_features.get(source) or {}
                target_features = node_features.get(target) or {}
                boundary_share = length / max(boundary_totals.get(source, 0.0), length)
                target_need = 1.0 - float(target_features.get("livability") or 0.0)
                source_exposure = max(
                    float(source_features.get("heat_risk") or 0.0),
                    float(source_features.get("air_pollution_exposure") or 0.0),
                )
                target_exposure = max(
                    float(target_features.get("heat_risk") or 0.0),
                    float(target_features.get("air_pollution_exposure") or 0.0),
                )
                degree = max(1.0, float((nodes.get(source) or {}).get("degree") or 1.0))
                factor = (
                    0.35
                    * boundary_share
                    * (1.0 + 0.5 * target_need)
                    * (1.0 + 0.25 * min(source_exposure, target_exposure))
                    / math.sqrt(degree)
                )
                neighbors[source].append(
                    {
                        "source_unit_id": source,
                        "target_unit_id": target,
                        "spillover_factor": round(factor, 9),
                        "shared_boundary_length_degrees": round(length, 12),
                        "boundary_share": round(boundary_share, 9),
                        "target_livability_need": round(target_need, 9),
                        "exposure_alignment": round(min(source_exposure, target_exposure), 9),
                    }
                )
        return dict(neighbors)

    def _candidate_actions(
        self,
        actions: list[dict[str, Any]],
        inventory: dict[str, Any],
        *,
        county: str,
        action_types: list[str],
        allowed_units: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        inventory_by_id = {
            str(action.get("action_id")): action for action in inventory.get("actions") or []
        }
        selected = []
        for action in actions:
            action_type = str(action.get("action_type") or "")
            if action_type not in action_types:
                continue
            enriched = deepcopy(action)
            enriched.update(
                {
                    key: value
                    for key, value in (inventory_by_id.get(str(action.get("action_id"))) or {}).items()
                    if key not in enriched
                }
            )
            if county and str(enriched.get("target_county") or "") != county:
                continue
            target_unit = str((enriched.get("target_units") or [""])[0])
            if allowed_units and target_unit not in allowed_units:
                continue
            selected.append(enriched)
        return selected

    def _focus_units(
        self,
        graph: dict[str, Any],
        *,
        focus_unit: str,
        neighborhood_hops: int,
    ) -> set[str] | None:
        if not focus_unit:
            return None
        if neighborhood_hops < 0 or neighborhood_hops > 3:
            raise ValueError("neighborhood_hops must be between 0 and 3")
        known_units = {
            str(node.get("unit_id"))
            for node in graph.get("nodes") or []
            if node.get("unit_id") is not None
        }
        if focus_unit not in known_units:
            raise ValueError(f"unknown focus_unit: {focus_unit}")
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in graph.get("edges") or []:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source and target:
                adjacency[source].add(target)
                adjacency[target].add(source)
        selected = {focus_unit}
        frontier = {focus_unit}
        for _ in range(neighborhood_hops):
            frontier = {
                neighbor
                for unit_id in frontier
                for neighbor in adjacency.get(unit_id, set())
                if neighbor not in selected
            }
            selected.update(frontier)
        return selected

    def _candidate_summary(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        counties: set[str] = set()
        for action in actions:
            counts[str(action.get("action_type") or "unknown")] += 1
            if action.get("target_county"):
                counties.add(str(action.get("target_county")))
        return {
            "candidate_action_count": len(actions),
            "action_type_counts": dict(sorted(counts.items())),
            "county_count": len(counties),
            "counties": sorted(counties),
        }

    def _traditional_need_score(self, action: dict[str, Any]) -> float:
        features = action.get("target_features") or {}
        action_type = str(action.get("action_type") or "")
        if action_type == "increase_green_infrastructure":
            return float(features.get("heat_risk") or 0.0)
        if action_type == "traffic_emission_control":
            return float(features.get("air_pollution_exposure") or 0.0)
        if action_type == "add_community_service":
            return 1.0 - float(features.get("service_accessibility") or 0.0)
        return 0.0

    def _public_sequence(self, beam: dict[str, Any]) -> dict[str, Any]:
        return {
            "action_count": len(beam["actions"]),
            "action_sequence": beam["actions"],
            "imagined_steps": beam["steps"],
            "discounted_predicted_return": round(float(beam["reward"]), 9),
            "discounted_conservative_return": round(float(beam["score"]), 9),
        }

    def _map_payload(
        self,
        *,
        admin_geojson: dict[str, Any],
        selected: dict[str, Any],
        dependency: dict[str, Any],
        run_id: str,
        allowed_units: set[str] | None,
        initial_state: dict[str, dict[str, float]],
        candidate_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        features_by_name = {
            (str((feature.get("properties") or {}).get("county")), str((feature.get("properties") or {}).get("township"))): feature
            for feature in admin_geojson.get("features") or []
        }
        layers = []
        colors = ["#dc2626", "#7c3aed", "#0891b2"]
        for index, step in enumerate(selected.get("imagined_steps") or []):
            action = step.get("action") or {}
            target = self._feature_for_action(features_by_name, action)
            if target:
                layers.append(
                    self._geojson_layer(
                        t(
                            "uwm_service.map.action_target",
                            step=index + 1,
                            action=self._action_label(action.get("action_type")),
                        ),
                        [self._enrich_feature(target, action, step, role="target", step_index=index + 1)],
                        colors[index % len(colors)],
                        0.48,
                    )
                )
            neighbor_features = []
            for edge in (step.get("propagation") or {}).get("edges") or []:
                unit_id = str(edge.get("target_unit_id") or "")
                parts = unit_id.split("|")
                feature = features_by_name.get((parts[0], parts[1])) if len(parts) >= 2 else None
                if feature:
                    neighbor_features.append(
                        self._enrich_feature(feature, action, step, role="propagated_neighbor", step_index=index + 1, edge=edge)
                    )
            if neighbor_features:
                layers.append(
                    self._geojson_layer(
                        t("uwm_service.map.action_propagation", step=index + 1),
                        neighbor_features,
                        colors[index % len(colors)],
                        0.16,
                    )
                )
        full_update = {
            "schema": "map_update.v1",
            "summary": {"title": t("uwm_service.map.plan_title"), "run_id": run_id},
            "layers": layers,
            "metadata": {
                "run_id": run_id,
                "fit_bounds": True,
                "state_dependency_diagnostic": dependency,
                "claim_boundary": self._claim_boundary(),
            },
        }
        scope_features = []
        for unit_id in sorted(allowed_units or set()):
            parts = unit_id.split("|")
            feature = features_by_name.get((parts[0], parts[1])) if len(parts) >= 2 else None
            if not feature:
                continue
            enriched = deepcopy(feature)
            state = initial_state.get(unit_id) or {}
            enriched["properties"] = {
                **(enriched.get("properties") or {}),
                "显示名称": f"{parts[0]} · {parts[1]}",
                "heat_risk": state.get("heat_risk"),
                "air_pollution_exposure": state.get("air_pollution_exposure"),
                "service_gap": state.get("service_gap"),
                "livability": state.get("livability"),
                "uwm_role": "t0_scope",
                "uwm_role_label": t("uwm_service.map.role.t0_scope"),
            }
            scope_features.append(enriched)
        steps = selected.get("imagined_steps") or []
        first_step = steps[0] if steps else {}
        second_step = steps[1] if len(steps) > 1 else {}
        first_target = self._feature_for_action(features_by_name, first_step.get("action") or {})
        second_target = self._feature_for_action(features_by_name, second_step.get("action") or {})
        alternative_action = next(
            (
                action
                for action in candidate_actions
                if str(action.get("action_id"))
                == str(dependency.get("top_second_action_without_state_update") or "")
            ),
            {},
        )
        alternative_target = self._feature_for_action(features_by_name, alternative_action)
        t0_layers = [self._geojson_layer(t("uwm_service.map.t0_scope"), scope_features, "#475569", 0.12)]
        if first_target:
            t0_layers.append(
                self._geojson_layer(
                    t("uwm_service.map.t0_first_target"),
                    [self._enrich_feature(first_target, first_step.get("action") or {}, first_step, role="t0_first_target", step_index=0)],
                    "#dc2626",
                    0.42,
                )
            )
        t1_layers = [layer for layer in layers if "a1" in str(layer.get("name"))]
        branch_layers = []
        if alternative_target:
            alternative_layer = self._geojson_layer(
                t("uwm_service.map.branch_without_update"),
                [self._enrich_feature(alternative_target, alternative_action, {}, role="baseline_second_action", step_index=2)],
                "#f59e0b",
                0.42,
            )
            alternative_layer["style"]["dashArray"] = "8 5"
            branch_layers.append(alternative_layer)
        if second_target:
            branch_layers.append(
                self._geojson_layer(
                    t("uwm_service.map.branch_with_update"),
                    [self._enrich_feature(second_target, second_step.get("action") or {}, second_step, role="uwm_second_action", step_index=2)],
                    "#7c3aed",
                    0.55,
                )
            )
        return {
            "full": full_update,
            "scenes": {
                "t0": self._scene_update(run_id, t("uwm_service.map.scene.t0.title"), t0_layers, t("uwm_service.map.scene.t0.narrative")),
                "t1": self._scene_update(run_id, t("uwm_service.map.scene.t1.title"), t1_layers, t("uwm_service.map.scene.t1.narrative")),
                "branch": self._scene_update(run_id, t("uwm_service.map.scene.branch.title"), branch_layers, t("uwm_service.map.scene.branch.narrative")),
                "t2": self._scene_update(run_id, t("uwm_service.map.scene.t2.title"), layers, t("uwm_service.map.scene.t2.narrative")),
            },
        }

    def _scene_update(
        self,
        run_id: str,
        title: str,
        layers: list[dict[str, Any]],
        narrative: str,
    ) -> dict[str, Any]:
        return {
            "schema": "map_update.v1",
            "summary": {"title": title, "run_id": run_id},
            "layers": layers,
            "metadata": {
                "run_id": run_id,
                "fit_bounds": True,
                "narrative": narrative,
            },
        }

    def _search_summary(self, *, candidate_count: int, horizon: int, beam_width: int) -> dict[str, Any]:
        beam_count = 1
        evaluated_action_count = 0
        completed_sequence_count = 0
        for step_index in range(horizon):
            available_per_beam = max(0, candidate_count - step_index)
            expanded = beam_count * available_per_beam
            evaluated_action_count += expanded
            completed_sequence_count = expanded
            beam_count = min(beam_width, expanded)
        return {
            "candidate_action_count": candidate_count,
            "horizon": horizon,
            "beam_width": beam_width,
            "evaluated_imagined_action_count": evaluated_action_count,
            "completed_sequence_count": completed_sequence_count,
            "retained_sequence_count": beam_count,
            "state_recomputed_after_each_action": True,
        }

    def _decision_story(
        self,
        selected: dict[str, Any],
        dependency: dict[str, Any],
        search_summary: dict[str, Any],
    ) -> dict[str, Any]:
        actions = selected.get("action_sequence") or []
        first = actions[0] if actions else {}
        second = actions[1] if len(actions) > 1 else {}
        return {
            "headline": t("uwm_service.decision.headline"),
            "first_action": {
                "label": self._action_label(first.get("action_type")),
                "target_unit_id": str((first.get("target_units") or [""])[0]),
            },
            "old_second_action": {
                "action_id": dependency.get("top_second_action_without_state_update"),
                "message": t("uwm_service.decision.old_message"),
            },
            "new_second_action": {
                "label": self._action_label(second.get("action_type")),
                "target_unit_id": str((second.get("target_units") or [""])[0]),
                "message": t("uwm_service.decision.new_message"),
            },
            "proof_points": [
                t("uwm_service.decision.proof_affected", count=((selected.get("imagined_steps") or [{}])[0].get("propagation") or {}).get("affected_unit_count", 0)),
                t("uwm_service.decision.proof_ranks", count=dependency.get("changed_action_rank_count", 0)),
                t("uwm_service.decision.proof_second", before=dependency.get("selected_second_rank_without_state_update"), after=dependency.get("selected_second_rank_after_state_update")),
                t("uwm_service.decision.proof_evaluated", count=search_summary.get("evaluated_imagined_action_count", 0)),
            ],
        }

    def _feature_for_action(
        self,
        features_by_name: dict[tuple[str, str], dict[str, Any]],
        action: dict[str, Any],
    ) -> dict[str, Any] | None:
        county = str(action.get("target_county") or "")
        township = str(action.get("target_township") or "")
        if not county or not township:
            parts = str((_target_units(action) or [""])[0]).split("|")
            if len(parts) >= 2:
                county, township = parts[0], parts[1]
        return features_by_name.get((county, township))

    def _enrich_feature(
        self,
        feature: dict[str, Any],
        action: dict[str, Any],
        step: dict[str, Any],
        *,
        role: str,
        step_index: int,
        edge: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = deepcopy(feature)
        properties = result.get("properties") or {}
        county = str(properties.get("county") or "")
        township = str(properties.get("township") or "")
        result["properties"] = {
            "区县": county,
            "街道乡镇": township,
            "显示名称": f"{county} · {township}",
            "地图角色": (
                t({
                    "target": "uwm_service.map.role.target",
                    "propagated_neighbor": "uwm_service.map.role.propagated_neighbor",
                    "t0_first_target": "uwm_service.map.role.t0_first_target",
                    "baseline_second_action": "uwm_service.map.role.baseline_second_action",
                    "uwm_second_action": "uwm_service.map.role.uwm_second_action",
                }[role])
                if role in {
                    "target",
                    "propagated_neighbor",
                    "t0_first_target",
                    "baseline_second_action",
                    "uwm_second_action",
                }
                else role
            ),
            "规划步骤": step_index,
            "干预类型": self._action_label(action.get("action_type")),
            "传播权重": (edge or {}).get("spillover_factor"),
        }
        return result

    def _geojson_layer(
        self,
        name: str,
        features: list[dict[str, Any]],
        color: str,
        fill_opacity: float,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "type": "geojson",
            "geojsonData": {"type": "FeatureCollection", "features": features},
            "style": {
                "color": color,
                "weight": 3,
                "opacity": 0.95,
                "fillColor": color,
                "fillOpacity": fill_opacity,
            },
        }

    def _action_label(self, action_type: Any) -> str:
        key = str(action_type or "unknown")
        value = t(f"uwm_service.action.{key}")
        return t("uwm_service.action.unknown") if value == f"uwm_service.action.{key}" else value

    def _claim_boundary(self) -> dict[str, Any]:
        return {
            "max_claim_level": "bounded_same_scene_algorithmic_support",
            "allowed_claim": t("uwm_service.claim.allowed"),
            "prohibited_claims": [
                t("uwm_service.claim.prohibited.causal"),
                t("uwm_service.claim.prohibited.permission"),
                t("uwm_service.claim.prohibited.generalization"),
                t("uwm_service.claim.prohibited.percentage"),
            ],
            "transition_evidence": t("uwm_service.claim.transition_evidence"),
        }

    def _asset_paths(self) -> dict[str, str]:
        return {
            "planner_replay": "data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json",
            "action_inventory": "data/uwm_public_proxy/chongqing_central/full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json",
            "policy_benchmark": "data/uwm_public_proxy/chongqing_central/core_world_model_policy_improvement_benchmark_2026_07_09/uwm_core_world_model_policy_improvement_benchmark.json",
            "admin_graph": "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
            "admin_geometry": "data/uwm_public_proxy/chongqing_central/admin_units/chongqing_township_admin_units.geojson",
        }

    def _stable_digest(self, payload: dict[str, Any]) -> str:
        import hashlib

        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _elapsed_ms(self, started: float) -> float:
        return round((perf_counter() - started) * 1000.0, 3)

    def _clamp(self, value: float) -> float:
        return min(1.0, max(0.0, value))

    @lru_cache(maxsize=1)
    def _assets(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        paths = self._asset_paths()
        return tuple(
            json.loads((self.root / path).read_text(encoding="utf-8"))
            for path in paths.values()
        )  # type: ignore[return-value]
