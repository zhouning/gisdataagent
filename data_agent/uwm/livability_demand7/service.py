"""Evidence-bounded demand-7 livability target and intervention planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Demand7ProductInvalid(RuntimeError):
    pass


PROFILE_WEIGHTS = {
    "balanced": {
        "heat_risk": 0.20,
        "air_pollution_exposure": 0.20,
        "service_accessibility": 0.25,
        "equity": 0.15,
        "livability": 0.20,
    },
    "community_service": {
        "heat_risk": 0.05,
        "air_pollution_exposure": 0.05,
        "service_accessibility": 0.55,
        "equity": 0.20,
        "livability": 0.15,
    },
    "environmental_comfort": {
        "heat_risk": 0.40,
        "air_pollution_exposure": 0.35,
        "service_accessibility": 0.05,
        "equity": 0.05,
        "livability": 0.15,
    },
    "equitable_livability": {
        "heat_risk": 0.10,
        "air_pollution_exposure": 0.10,
        "service_accessibility": 0.20,
        "equity": 0.30,
        "livability": 0.30,
    },
}

ACTION_LABELS = {
    "increase_green_infrastructure": "增加绿色基础设施",
    "traffic_emission_control": "实施交通排放控制",
    "add_community_service": "新增社区服务设施",
}

NEGATIVE_INDICATORS = {"heat_risk", "air_pollution_exposure"}
PLANNING_INDICATORS = tuple(next(iter(PROFILE_WEIGHTS.values())).keys())


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Demand7ProductInvalid(f"invalid_product:{path}:{error}") from error
    if not isinstance(payload, dict):
        raise Demand7ProductInvalid(f"invalid_product_object:{path}")
    return payload


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise Demand7ProductInvalid("empty_benchmark_population")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    ratio = position - lower
    return ordered[lower] * (1 - ratio) + ordered[upper] * ratio


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _coordinate_pairs(value: Any):
    if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        yield float(value[0]), float(value[1])
    elif isinstance(value, list):
        for item in value:
            yield from _coordinate_pairs(item)


class Demand7Service:
    def __init__(self, panel_path: Path, planner_path: Path, geometry_path: Path):
        self.panel_path = panel_path
        self.planner_path = planner_path
        self.geometry_path = geometry_path
        self.panel = _load_json(panel_path)
        self.planner = _load_json(planner_path)
        self.geometry = _load_json(geometry_path)
        self._build_indexes()

    def _build_indexes(self) -> None:
        graph = self.planner.get("graph_mdp_state")
        trajectory = self.planner.get("trajectory_dataset")
        if not isinstance(graph, dict) or not isinstance(trajectory, dict):
            raise Demand7ProductInvalid("planner_graph_or_trajectory_missing")
        nodes = graph.get("nodes")
        actions = graph.get("available_actions")
        edges = graph.get("edges")
        transitions = trajectory.get("transitions")
        features = self.geometry.get("features")
        if not all(isinstance(value, list) for value in (nodes, actions, edges, transitions, features)):
            raise Demand7ProductInvalid("planner_or_geometry_arrays_missing")

        self.nodes = {str(node["unit_id"]): node for node in nodes if node.get("unit_id")}
        self.actions_by_unit: dict[str, list[dict[str, Any]]] = {}
        for action in actions:
            for unit_id in action.get("target_units") or []:
                self.actions_by_unit.setdefault(str(unit_id), []).append(action)
        self.transitions_by_action: dict[str, dict[str, Any]] = {}
        for transition in transitions:
            action = transition.get("action") or {}
            action_id = str(action.get("action_id") or "")
            step_index = (transition.get("transition") or {}).get("step_index")
            if action_id and step_index == 0 and action_id not in self.transitions_by_action:
                self.transitions_by_action[action_id] = transition

        self.geometry_by_place: dict[str, dict[str, Any]] = {}
        for feature in features:
            properties = feature.get("properties") or {}
            place = f"{properties.get('county', '')}|{properties.get('township', '')}"
            self.geometry_by_place[place] = feature

        self.edge_count = len(edges)
        self.action_count = len(actions)
        self.transition_count = len(transitions)
        if (len(self.nodes), self.edge_count, self.action_count, self.transition_count) != (1017, 7932, 1137, 6817):
            raise Demand7ProductInvalid("unexpected_full_admin_product_counts")

        values = {indicator: [] for indicator in PLANNING_INDICATORS}
        for node in self.nodes.values():
            node_features = node.get("features") or {}
            for indicator in PLANNING_INDICATORS:
                values[indicator].append(float(node_features[indicator]))
        self.peer_targets = {
            indicator: round(_percentile(indicator_values, 0.25 if indicator in NEGATIVE_INDICATORS else 0.75), 6)
            for indicator, indicator_values in values.items()
        }
        self.profile_targets = {profile: dict(self.peer_targets) for profile in PROFILE_WEIGHTS}
        self.profile_targets["community_service"]["service_accessibility"] = round(
            _percentile(values["service_accessibility"], 0.90), 6
        )
        self.profile_targets["equitable_livability"]["equity"] = round(_percentile(values["equity"], 0.90), 6)
        self.profile_targets["equitable_livability"]["livability"] = round(
            _percentile(values["livability"], 0.90), 6
        )

    @staticmethod
    def _split_unit(unit_id: str) -> tuple[str, str]:
        parts = unit_id.split("|")
        return (parts[0], parts[1]) if len(parts) >= 2 else ("", "")

    def _geometry_for_unit(self, unit_id: str) -> dict[str, Any] | None:
        county, township = self._split_unit(unit_id)
        feature = self.geometry_by_place.get(f"{county}|{township}")
        if not feature:
            return None
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied.setdefault("properties", {})["unit_id"] = unit_id
        return copied

    @staticmethod
    def _map_view(feature: dict[str, Any] | None) -> dict[str, Any]:
        pairs = list(_coordinate_pairs((feature or {}).get("geometry", {}).get("coordinates")))
        if not pairs:
            return {}
        longitudes = [pair[0] for pair in pairs]
        latitudes = [pair[1] for pair in pairs]
        return {
            "center": [(min(latitudes) + max(latitudes)) / 2, (min(longitudes) + max(longitudes)) / 2],
            "zoom": 10,
        }

    def _unit_summary(self, unit_id: str) -> dict[str, Any]:
        node = self.nodes[unit_id]
        county, township = self._split_unit(unit_id)
        features = node.get("features") or {}
        return {
            "unit_id": unit_id,
            "county": county,
            "township": township,
            "current_state": {indicator: round(float(features[indicator]), 6) for indicator in PLANNING_INDICATORS},
            "livability_need_score": round(1.0 - float(features["livability"]), 6),
            "available_action_count": len(self.actions_by_unit.get(unit_id, [])),
        }

    def overview(self) -> dict[str, Any]:
        return {
            "schema": "uwm.livability.demand7.overview.v1",
            "ready": True,
            "requirement": "宜居性与社区需求的目标差距诊断、动作条件推演与干预优先级",
            "counts": {
                "state_nodes": len(self.nodes),
                "spatial_edges": self.edge_count,
                "available_actions": self.action_count,
                "stored_replay_transitions": self.transition_count,
            },
            "target_profiles": [
                {"id": profile_id, "weights": weights} for profile_id, weights in PROFILE_WEIGHTS.items()
            ],
            "target_definition": {
                "method": "observed_peer_quantile_benchmark",
                "targets": self.peer_targets,
                "profile_targets": self.profile_targets,
                "meaning": "平衡目标使用风险P25/正向P75；社区服务和公平宜居目标对相应正向指标使用P90。全部来自同源观测代理分布，不是政策承诺值。",
            },
            "horizon_evidence": {
                "simulator_step": {"status": "available", "claim_level": "bounded_support"},
                "24_month": {"status": "blocked", "reason": "calendar_horizon_calibration_missing"},
                "five_year": {"status": "blocked", "reason": "calendar_horizon_calibration_missing"},
            },
            "claim_boundary": {
                "model_step_is_calendar_forecast": False,
                "observed_policy_outcome": False,
                "community_voice_available": False,
                "max_claim_level": "bounded_action_conditioned_spatial_scenario",
            },
            "sources": [str(self.panel_path), str(self.planner_path), str(self.geometry_path)],
        }

    def list_units(self, search: str = "", county: str = "", limit: int = 100) -> dict[str, Any]:
        normalized_search = search.strip().lower()
        rows = []
        for unit_id in self.nodes:
            row = self._unit_summary(unit_id)
            if county and row["county"] != county:
                continue
            if normalized_search and normalized_search not in unit_id.lower():
                continue
            rows.append(row)
        rows.sort(key=lambda row: (-row["livability_need_score"], row["unit_id"]))
        return {
            "schema": "uwm.livability.demand7.units.v1",
            "total": len(rows),
            "units": rows[: max(1, min(int(limit), 500))],
        }

    def unit_detail(self, unit_id: str) -> dict[str, Any]:
        if unit_id not in self.nodes:
            raise ValueError("unit_not_found")
        summary = self._unit_summary(unit_id)
        current = summary["current_state"]
        summary.update(
            {
                "schema": "uwm.livability.demand7.unit.v1",
                "peer_target": self.peer_targets,
                "target_gap": self._gaps(current),
                "available_actions": [
                    {
                        "action_id": action["action_id"],
                        "action_type": action["action_type"],
                        "label": ACTION_LABELS.get(action["action_type"], action["action_type"]),
                        "mask_reason": action.get("mask_reason"),
                        "identification_status": action.get("identification_status"),
                    }
                    for action in self.actions_by_unit.get(unit_id, [])
                ],
                "geometry_available": self._geometry_for_unit(unit_id) is not None,
                "limitations": [
                    "community_voice_input_missing",
                    "observed_intervention_outcome_missing",
                    "calendar_horizon_calibration_missing",
                ],
            }
        )
        return summary

    def _gaps(self, state: dict[str, float], targets: dict[str, float] | None = None) -> dict[str, float]:
        target_values = targets or self.peer_targets
        gaps = {}
        for indicator, target in target_values.items():
            value = float(state[indicator])
            gap = value - target if indicator in NEGATIVE_INDICATORS else target - value
            gaps[indicator] = round(max(0.0, gap), 6)
        return gaps

    @staticmethod
    def _weighted_gap(gaps: dict[str, float], weights: dict[str, float]) -> float:
        return sum(float(gaps[indicator]) * weight for indicator, weight in weights.items())

    def _blocked_plan(self, unit_id: str, profile: str, horizon: str) -> dict[str, Any]:
        return {
            "schema": "uwm.livability.demand7.plan.v1",
            "status": "blocked",
            "unit_id": unit_id,
            "target_profile": profile,
            "horizon": horizon,
            "reason": "calendar_horizon_calibration_missing",
            "required_evidence": [
                "customer_aligned_longitudinal_livability_panel",
                "calendar_time_action_exposure_history",
                "24_month_and_five_year_holdout_validation",
                "observed_intervention_outcome_panel",
            ],
            "claim_boundary": "模型步不等于24个月或5年，系统拒绝生成无校准的日历预测。",
        }

    def plan(self, unit_id: str, target_profile: str, horizon: str) -> dict[str, Any]:
        if unit_id not in self.nodes:
            raise ValueError("unit_not_found")
        if target_profile not in PROFILE_WEIGHTS:
            raise ValueError("target_profile_not_supported")
        if horizon in {"24_month", "five_year"}:
            return self._blocked_plan(unit_id, target_profile, horizon)
        if horizon != "simulator_step":
            raise ValueError("horizon_not_supported")

        current = self._unit_summary(unit_id)["current_state"]
        weights = PROFILE_WEIGHTS[target_profile]
        targets = self.profile_targets[target_profile]
        baseline_gaps = self._gaps(current, targets)
        baseline_weighted_gap = self._weighted_gap(baseline_gaps, weights)
        candidates = []
        for action in self.actions_by_unit.get(unit_id, []):
            transition = self.transitions_by_action.get(str(action.get("action_id")))
            if not transition:
                continue
            delta_rows = (transition.get("next_state_delta_summary") or {}).get("top_changed_units") or []
            target_delta = next((row for row in delta_rows if row.get("unit_id") == unit_id), None)
            if not target_delta:
                continue
            projected = {}
            deltas = {}
            for indicator in PLANNING_INDICATORS:
                delta = float(target_delta.get(f"{indicator}_delta", 0.0))
                deltas[indicator] = round(delta, 9)
                projected[indicator] = round(_clamp(float(current[indicator]) + delta), 6)
            projected_gaps = self._gaps(projected, targets)
            projected_weighted_gap = self._weighted_gap(projected_gaps, weights)
            spillover = [row for row in delta_rows if row.get("unit_id") != unit_id]
            candidates.append(
                {
                    "action_id": action["action_id"],
                    "action_type": action["action_type"],
                    "action_label": ACTION_LABELS.get(action["action_type"], action["action_type"]),
                    "mask_reason": action.get("mask_reason"),
                    "target_unit_delta": deltas,
                    "projected_state": projected,
                    "projected_target_gap": projected_gaps,
                    "weighted_gap_closure": round(baseline_weighted_gap - projected_weighted_gap, 9),
                    "replay_reward": round(float(transition.get("reward", 0.0)), 9),
                    "affected_unit_count": int((transition.get("next_state_delta_summary") or {}).get("changed_units", 0)),
                    "spillover_preview": spillover,
                    "evidence_grade": (transition.get("transition") or {}).get("evidence_grade"),
                    "simulator_trace_steps": (transition.get("transition") or {}).get("simulator_trace_steps") or [],
                    "policy_outcome_claim_allowed": bool(action.get("policy_outcome_claim_allowed")),
                }
            )
        if not candidates:
            raise ValueError("no_replay_backed_action_available")
        candidates.sort(key=lambda item: (-item["weighted_gap_closure"], -item["replay_reward"], item["action_id"]))
        recommended = candidates[0]
        affected_ids = [unit_id] + [str(row["unit_id"]) for row in recommended["spillover_preview"]]
        selected_feature = self._geometry_for_unit(unit_id)
        affected_features = [feature for affected_id in affected_ids[1:] if (feature := self._geometry_for_unit(affected_id))]
        service_target = float(targets["service_accessibility"])
        target_county, _ = self._split_unit(unit_id)
        underserved_features = []
        for candidate_id, candidate_node in self.nodes.items():
            candidate_county, _ = self._split_unit(candidate_id)
            if candidate_county != target_county:
                continue
            accessibility = float((candidate_node.get("features") or {}).get("service_accessibility", 0.0))
            if accessibility >= service_target:
                continue
            feature = self._geometry_for_unit(candidate_id)
            if feature:
                feature["properties"].update(
                    {
                        "service_accessibility": round(accessibility, 6),
                        "service_target": round(service_target, 6),
                        "service_gap_to_target": round(service_target - accessibility, 6),
                    }
                )
                underserved_features.append(feature)
        map_view = self._map_view(selected_feature)
        return {
            "schema": "uwm.livability.demand7.plan.v1",
            "status": "completed",
            "unit_id": unit_id,
            "target_profile": target_profile,
            "horizon": horizon,
            "current_state": current,
            "peer_target": targets,
            "baseline_target_gap": baseline_gaps,
            "recommended_action": recommended,
            "alternatives": candidates[1:],
            "map_payload": {
                "schema": "map_update.v1",
                "summary": {"title": "需求7 UWM宜居性干预规划"},
                **map_view,
                "layers": [
                    {"name": "需求7目标行政单元", "type": "geojson", "geojsonData": {"type": "FeatureCollection", "features": [selected_feature] if selected_feature else []}},
                    {"name": "需求7空间溢出预览", "type": "geojson", "geojsonData": {"type": "FeatureCollection", "features": affected_features}},
                    {"name": "需求7服务不足行政单元", "type": "choropleth", "value_column": "service_gap_to_target", "color_scheme": "Reds", "geojsonData": {"type": "FeatureCollection", "features": underserved_features}},
                ],
                "metadata": {
                    "unit_id": unit_id,
                    "action_id": recommended["action_id"],
                    "evidence_grade": recommended["evidence_grade"],
                    "underserved_unit_count": len(underserved_features),
                    "underserved_map_scope": f"{target_county}_complete_units_below_profile_service_target",
                },
            },
            "evidence": {
                "transition_source": "stored_step_0_simulator_replay",
                "geometry_source": "real_1017_township_admin_units",
                "model_step_is_calendar_forecast": False,
                "not_observed_policy_outcome": True,
                "community_voice_status": "missing",
                "claim_level": "bounded_support",
            },
        }
