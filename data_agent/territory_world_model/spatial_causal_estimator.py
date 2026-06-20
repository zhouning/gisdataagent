from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .utils import safe_float


SPATIAL_CAUSAL_ESTIMATOR_SCHEMA = "territory_world_model.spatial_causal_estimator.v1"


@dataclass
class SpatialCausalEstimatorAdapter:
    """Transparent spatial treatment-effect estimator for local TWM calibration.

    The adapter uses mixed spatial units as fixed effects and treated-control
    neighbor pairs as a spatial matching signal. It is deliberately conservative:
    when spatial support is absent or treatment is concentrated by cluster, the
    adapter returns review instead of upgrading a planning claim.
    """

    name: str = "spatial_fixed_effect_neighbor_adapter"
    version: str = "v1"

    def estimate(
        self,
        records: list[dict[str, Any]],
        *,
        thresholds: dict[str, Any],
        neighbor_edges: list[tuple[int, int, float]] | None = None,
        observational_effect: float | None = None,
        observational_standard_error: float | None = None,
    ) -> dict[str, Any]:
        if not thresholds.get("enable_spatial_estimator", True):
            return self._not_applicable("spatial estimator disabled by thresholds")

        spatial_rows = [row for row in records if row.get("spatial")]
        if not spatial_rows:
            return self._not_applicable("no spatial coordinates, cluster ids or neighbor links supplied")

        edges = list(neighbor_edges or [])
        clusters = self._clusters(records)
        cluster_effects = self._cluster_fixed_effects(clusters)
        neighbor_effects = self._neighbor_pair_effects(records, edges)
        cluster_support = len(cluster_effects)
        neighbor_support = len(neighbor_effects)

        components: list[dict[str, Any]] = []
        if cluster_effects:
            components.append(
                {
                    "component": "spatial_unit_fixed_effect",
                    "effect": _weighted_mean(
                        [item["effect"] for item in cluster_effects],
                        [item["weight"] for item in cluster_effects],
                    ),
                    "standard_error": _standard_error([item["effect"] for item in cluster_effects]),
                    "support_count": cluster_support,
                    "weight": sum(item["weight"] for item in cluster_effects),
                }
            )
        if neighbor_effects:
            components.append(
                {
                    "component": "treated_control_neighbor_match",
                    "effect": _weighted_mean(
                        [item["effect"] for item in neighbor_effects],
                        [item["weight"] for item in neighbor_effects],
                    ),
                    "standard_error": _standard_error([item["effect"] for item in neighbor_effects]),
                    "support_count": neighbor_support,
                    "weight": sum(item["weight"] for item in neighbor_effects),
                }
            )

        effect_values = [item["effect"] for item in cluster_effects] + [item["effect"] for item in neighbor_effects]
        if components:
            component_weights = [max(1.0, min(float(item["weight"]), float(item["support_count"]) * 2.0)) for item in components]
            effect = _weighted_mean([float(item["effect"]) for item in components], component_weights)
            standard_error = _standard_error(effect_values)
        else:
            effect = 0.0
            standard_error = 1.0

        min_units = int(thresholds.get("min_spatial_units", 3) or 3)
        min_pairs = int(thresholds.get("min_spatial_unit_pairs", 3) or 3)
        min_edges = int(thresholds.get("min_cross_treatment_edges", 3) or 3)
        max_se = float(thresholds.get("max_spatial_estimator_standard_error", thresholds.get("max_standard_error", 0.25)) or 0.25)
        max_cluster_gap = float(thresholds.get("max_spatial_cluster_treatment_gap", 0.45) or 0.45)
        max_effect_gap = float(thresholds.get("max_spatial_effect_gap", 0.25) or 0.25)

        cluster_balance = self._cluster_balance(clusters, records)
        uncertainty = self._uncertainty_diagnostics(cluster_effects, effect, thresholds)
        effect_gap = abs(effect - float(observational_effect)) if observational_effect is not None else 0.0
        support_passed = cluster_support >= min_units or neighbor_support >= min_edges
        reasons: list[str] = []
        if not support_passed:
            reasons.append("insufficient_balanced_spatial_units")
        if cluster_support and cluster_support < min_pairs:
            reasons.append("insufficient_mixed_spatial_unit_pairs")
        if cluster_balance["max_abs_treatment_share_gap"] > max_cluster_gap:
            reasons.append("spatial_treatment_concentration")
        if standard_error > max_se:
            reasons.append("spatial_standard_error")
        if effect_gap > max_effect_gap:
            reasons.append("spatial_observational_effect_gap")
        if uncertainty["spatial_block_bootstrap"]["status"] == "review":
            reasons.append("spatial_bootstrap_uncertainty")
        if uncertainty["geographic_holdout"]["status"] == "review":
            reasons.append("geographic_holdout_instability")

        status = "pass" if not reasons else "review"
        return {
            "schema": SPATIAL_CAUSAL_ESTIMATOR_SCHEMA,
            "adapter": {"name": self.name, "version": self.version},
            "status": status,
            "effect": round(effect, 6),
            "standard_error": round(standard_error, 6),
            "observational_effect": round(float(observational_effect), 6) if observational_effect is not None else None,
            "observational_standard_error": round(float(observational_standard_error), 6) if observational_standard_error is not None else None,
            "effect_gap_from_observational": round(effect_gap, 6),
            "identification": "observational_spatial_fixed_effects_plus_neighbor_matching",
            "claim": "spatial_observational_calibration_only",
            "support": {
                "spatial_record_count": len(spatial_rows),
                "spatial_unit_count": len(clusters),
                "mixed_spatial_unit_count": cluster_support,
                "cross_treatment_neighbor_edge_count": neighbor_support,
                "treated_count": sum(1 for row in records if row.get("treatment") == 1),
                "control_count": sum(1 for row in records if row.get("treatment") == 0),
            },
            "components": [
                {
                    "component": item["component"],
                    "effect": round(float(item["effect"]), 6),
                    "standard_error": round(float(item["standard_error"]), 6),
                    "support_count": int(item["support_count"]),
                }
                for item in components
            ],
            "diagnostics": {
                "cluster_balance": cluster_balance,
                "cluster_effects": cluster_effects,
                "neighbor_pair_effects": neighbor_effects[:50],
            },
            "uncertainty": uncertainty,
            "thresholds": {
                "min_spatial_units": min_units,
                "min_spatial_unit_pairs": min_pairs,
                "min_cross_treatment_edges": min_edges,
                "max_spatial_estimator_standard_error": max_se,
                "max_spatial_cluster_treatment_gap": max_cluster_gap,
                "max_spatial_effect_gap": max_effect_gap,
                "spatial_bootstrap_samples": int(thresholds.get("spatial_bootstrap_samples", 64) or 64),
                "max_spatial_bootstrap_interval_width": float(thresholds.get("max_spatial_bootstrap_interval_width", 0.35) or 0.35),
                "max_spatial_holdout_delta": float(thresholds.get("max_spatial_holdout_delta", 0.2) or 0.2),
            },
            "review_reasons": reasons,
        }

    def _not_applicable(self, note: str) -> dict[str, Any]:
        return {
            "schema": SPATIAL_CAUSAL_ESTIMATOR_SCHEMA,
            "adapter": {"name": self.name, "version": self.version},
            "status": "not_applicable",
            "effect": 0.0,
            "standard_error": 1.0,
            "identification": "not_applicable",
            "claim": "spatial_observational_calibration_only",
            "support": {
                "spatial_record_count": 0,
                "spatial_unit_count": 0,
                "mixed_spatial_unit_count": 0,
                "cross_treatment_neighbor_edge_count": 0,
                "treated_count": 0,
                "control_count": 0,
            },
            "components": [],
            "diagnostics": {},
            "uncertainty": {
                "spatial_block_bootstrap": {"status": "not_applicable", "note": note},
                "geographic_holdout": {"status": "not_applicable", "note": note},
            },
            "review_reasons": [],
            "note": note,
        }

    def _clusters(self, records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        clusters: dict[str, list[dict[str, Any]]] = {}
        for row in records:
            spatial = dict(row.get("spatial") or {})
            cluster = spatial.get("cluster")
            if cluster is not None:
                clusters.setdefault(str(cluster), []).append(row)
        return clusters

    def _cluster_fixed_effects(self, clusters: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        effects: list[dict[str, Any]] = []
        for cluster, rows in sorted(clusters.items()):
            treated = [row for row in rows if row.get("treatment") == 1]
            control = [row for row in rows if row.get("treatment") == 0]
            if not treated or not control:
                continue
            treated_weight = sum(float(row.get("evidence_weight") or 1.0) for row in treated)
            control_weight = sum(float(row.get("evidence_weight") or 1.0) for row in control)
            effect = _weighted_mean([float(row["outcome"]) for row in treated], [float(row.get("evidence_weight") or 1.0) for row in treated]) - _weighted_mean(
                [float(row["outcome"]) for row in control],
                [float(row.get("evidence_weight") or 1.0) for row in control],
            )
            effects.append(
                {
                    "spatial_unit": cluster,
                    "effect": round(effect, 6),
                    "treated_count": len(treated),
                    "control_count": len(control),
                    "weight": round(max(1.0, min(treated_weight, control_weight)), 6),
                }
            )
        return effects

    def _neighbor_pair_effects(self, records: list[dict[str, Any]], edges: list[tuple[int, int, float]]) -> list[dict[str, Any]]:
        effects: list[dict[str, Any]] = []
        for left, right, edge_weight in edges:
            if left >= len(records) or right >= len(records):
                continue
            left_row = records[left]
            right_row = records[right]
            left_t = int(left_row.get("treatment") or 0)
            right_t = int(right_row.get("treatment") or 0)
            if left_t == right_t:
                continue
            treated = left_row if left_t == 1 else right_row
            control = right_row if left_t == 1 else left_row
            effect = float(treated["outcome"]) - float(control["outcome"])
            evidence_weight = min(float(treated.get("evidence_weight") or 1.0), float(control.get("evidence_weight") or 1.0))
            effects.append(
                {
                    "treated_unit_id": str(treated.get("unit_id") or ""),
                    "control_unit_id": str(control.get("unit_id") or ""),
                    "effect": round(effect, 6),
                    "weight": round(max(0.0, float(edge_weight)) * max(0.0, evidence_weight), 6),
                }
            )
        return effects

    def _cluster_balance(self, clusters: dict[str, list[dict[str, Any]]], records: list[dict[str, Any]]) -> dict[str, Any]:
        if not clusters:
            return {"status": "not_applicable", "max_abs_treatment_share_gap": 0.0, "diagnostics": []}
        global_share = _mean([float(row.get("treatment") or 0.0) for row in records])
        diagnostics: list[dict[str, Any]] = []
        max_gap = 0.0
        for cluster, rows in sorted(clusters.items()):
            share = _mean([float(row.get("treatment") or 0.0) for row in rows])
            gap = share - global_share
            max_gap = max(max_gap, abs(gap))
            diagnostics.append(
                {
                    "spatial_unit": cluster,
                    "record_count": len(rows),
                    "treatment_share": round(share, 6),
                    "global_treatment_share_gap": round(gap, 6),
                }
            )
        return {
            "status": "pass",
            "max_abs_treatment_share_gap": round(max_gap, 6),
            "diagnostics": diagnostics,
        }

    def _uncertainty_diagnostics(
        self,
        cluster_effects: list[dict[str, Any]],
        full_effect: float,
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "spatial_block_bootstrap": self._spatial_block_bootstrap(cluster_effects, thresholds),
            "geographic_holdout": self._geographic_holdout(cluster_effects, full_effect, thresholds),
        }

    def _spatial_block_bootstrap(self, cluster_effects: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
        min_units = int(thresholds.get("min_spatial_bootstrap_units", thresholds.get("min_spatial_units", 3)) or 3)
        if len(cluster_effects) < min_units:
            return {
                "status": "not_applicable",
                "spatial_unit_count": len(cluster_effects),
                "min_spatial_bootstrap_units": min_units,
                "note": "insufficient mixed spatial units for block bootstrap",
            }

        samples = max(8, min(512, int(thresholds.get("spatial_bootstrap_samples", 64) or 64)))
        effects = [float(item["effect"]) for item in cluster_effects]
        weights = [float(item.get("weight") or 1.0) for item in cluster_effects]
        estimates: list[float] = []
        for rep in range(samples):
            values = []
            sample_weights = []
            for pos in range(len(cluster_effects)):
                idx = ((rep + 1) * 17 + (pos + 3) * 31 + rep * pos) % len(cluster_effects)
                values.append(effects[idx])
                sample_weights.append(weights[idx])
            estimates.append(_weighted_mean(values, sample_weights))

        estimates = sorted(estimates)
        low_idx = max(0, min(len(estimates) - 1, int(0.025 * (len(estimates) - 1))))
        high_idx = max(0, min(len(estimates) - 1, int(0.975 * (len(estimates) - 1))))
        low = estimates[low_idx]
        high = estimates[high_idx]
        interval_width = high - low
        center_sign = _sign(_weighted_mean(effects, weights))
        if center_sign == 0:
            sign_stability = 0.0
        else:
            sign_stability = sum(1 for value in estimates if _sign(value) == center_sign) / len(estimates)
        max_width = float(thresholds.get("max_spatial_bootstrap_interval_width", 0.35) or 0.35)
        min_sign_stability = float(thresholds.get("min_spatial_bootstrap_sign_stability", 0.8) or 0.8)
        status = "pass"
        if interval_width > max_width or sign_stability < min_sign_stability:
            status = "review"
        return {
            "status": status,
            "method": "deterministic_spatial_unit_block_bootstrap",
            "sample_count": samples,
            "spatial_unit_count": len(cluster_effects),
            "mean_effect": round(_mean(estimates), 6),
            "interval_95": [round(low, 6), round(high, 6)],
            "interval_width": round(interval_width, 6),
            "sign_stability": round(sign_stability, 6),
            "thresholds": {
                "max_spatial_bootstrap_interval_width": max_width,
                "min_spatial_bootstrap_sign_stability": min_sign_stability,
            },
        }

    def _geographic_holdout(self, cluster_effects: list[dict[str, Any]], full_effect: float, thresholds: dict[str, Any]) -> dict[str, Any]:
        min_units = int(thresholds.get("min_spatial_holdout_units", thresholds.get("min_spatial_units", 3)) or 3)
        if len(cluster_effects) < min_units:
            return {
                "status": "not_applicable",
                "spatial_unit_count": len(cluster_effects),
                "min_spatial_holdout_units": min_units,
                "note": "insufficient mixed spatial units for geographic holdout",
            }

        effects = [float(item["effect"]) for item in cluster_effects]
        weights = [float(item.get("weight") or 1.0) for item in cluster_effects]
        diagnostics = []
        for idx, item in enumerate(cluster_effects):
            remaining_effects = effects[:idx] + effects[idx + 1 :]
            remaining_weights = weights[:idx] + weights[idx + 1 :]
            holdout_effect = _weighted_mean(remaining_effects, remaining_weights)
            diagnostics.append(
                {
                    "held_out_spatial_unit": str(item.get("spatial_unit") or idx),
                    "effect_without_unit": round(holdout_effect, 6),
                    "delta_from_full_effect": round(holdout_effect - full_effect, 6),
                    "same_sign_as_full": _sign(holdout_effect) == _sign(full_effect) if _sign(full_effect) != 0 else False,
                }
            )

        max_delta = max(abs(float(item["delta_from_full_effect"])) for item in diagnostics)
        sign_agreement = sum(1 for item in diagnostics if item["same_sign_as_full"]) / len(diagnostics)
        max_delta_threshold = float(thresholds.get("max_spatial_holdout_delta", 0.2) or 0.2)
        min_sign_agreement = float(thresholds.get("min_spatial_holdout_sign_agreement", 0.8) or 0.8)
        status = "pass"
        if max_delta > max_delta_threshold or sign_agreement < min_sign_agreement:
            status = "review"
        return {
            "status": status,
            "method": "leave_one_spatial_unit_out",
            "spatial_unit_count": len(cluster_effects),
            "max_abs_delta_from_full_effect": round(max_delta, 6),
            "sign_agreement": round(sign_agreement, 6),
            "thresholds": {
                "max_spatial_holdout_delta": max_delta_threshold,
                "min_spatial_holdout_sign_agreement": min_sign_agreement,
            },
            "diagnostics": diagnostics,
        }


def estimate_spatial_treatment_effect(
    records: list[dict[str, Any]],
    *,
    thresholds: dict[str, Any],
    neighbor_edges: list[tuple[int, int, float]] | None = None,
    observational_effect: float | None = None,
    observational_standard_error: float | None = None,
) -> dict[str, Any]:
    return SpatialCausalEstimatorAdapter().estimate(
        records,
        thresholds=thresholds,
        neighbor_edges=neighbor_edges,
        observational_effect=observational_effect,
        observational_standard_error=observational_standard_error,
    )


def build_neighbor_edges(records: list[dict[str, Any]], thresholds: dict[str, Any]) -> list[tuple[int, int, float]]:
    index_by_id = {str(row.get("unit_id") or idx): idx for idx, row in enumerate(records)}
    edges: dict[tuple[int, int], float] = {}
    for idx, row in enumerate(records):
        spatial = dict(row.get("spatial") or {})
        for neighbor_id in spatial.get("neighbors") or []:
            other = index_by_id.get(str(neighbor_id))
            if other is None or other == idx:
                continue
            pair = tuple(sorted((idx, other)))
            edges[pair] = 1.0

    distance_threshold = safe_float(thresholds.get("spatial_neighbor_distance"), None)
    coordinate_rows = [
        (idx, dict(row.get("spatial") or {}))
        for idx, row in enumerate(records)
        if "x" in dict(row.get("spatial") or {}) and "y" in dict(row.get("spatial") or {})
    ]
    if distance_threshold is not None and distance_threshold > 0 and len(coordinate_rows) > 1:
        for pos, (idx, left) in enumerate(coordinate_rows):
            for other, right in coordinate_rows[pos + 1 :]:
                distance = math.sqrt((float(left["x"]) - float(right["x"])) ** 2 + (float(left["y"]) - float(right["y"])) ** 2)
                if distance <= float(distance_threshold):
                    pair = tuple(sorted((idx, other)))
                    edges[pair] = 1.0 / max(distance, 1e-9)
    return [(left, right, weight) for (left, right), weight in sorted(edges.items())]


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    if not values:
        return 0.0
    if not weights or len(weights) != len(values):
        return _mean(values)
    total_weight = sum(max(0.0, weight) for weight in weights)
    if total_weight <= 0:
        return _mean(values)
    return sum(value * max(0.0, weight) for value, weight in zip(values, weights)) / total_weight


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((item - mean) ** 2 for item in values) / (len(values) - 1)


def _standard_error(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0 if not values else 0.0
    return math.sqrt(_variance(values)) / math.sqrt(len(values))
