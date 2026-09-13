from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable

from .models import (
    StateBuildResult,
    TerritoryWorldModelAction,
    TerritoryWorldModelForecast,
    TwmCounterfactualRollout,
    TwmRolloutStep,
    TwmScenarioMetric,
    TwmScenarioPlan,
    TwmStateObject,
    TwmStateRelation,
    TwmStateVersion,
    jsonable,
    now_utc_iso,
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _stable_state_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(jsonable(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coerce_state_bundle(state_bundle: StateBuildResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(state_bundle, StateBuildResult):
        return {
            "project": state_bundle.project,
            "state_version": state_bundle.state_version,
            "objects": list(state_bundle.objects),
            "relations": list(state_bundle.relations),
            "object_counts_by_role": dict(state_bundle.object_counts_by_role),
            "relation_counts_by_type": dict(state_bundle.relation_counts_by_type),
            "hierarchy_tokens": dict(state_bundle.hierarchy_tokens),
            "quality_summary": dict(state_bundle.quality_summary),
            "warnings": list(state_bundle.warnings),
        }
    return dict(state_bundle)


def _action_signature(action: TerritoryWorldModelAction) -> dict[str, Any]:
    return {
        "action_type": action.action_type,
        "target_role": action.target_role,
        "target_objects": jsonable(action.target_objects),
        "spatial_scope": jsonable(action.spatial_scope),
        "magnitude": _float(action.magnitude, 1.0),
        "scenario": action.scenario,
        "description": action.description,
        "legal_intent": action.legal_intent,
        "execution_mask": jsonable(action.execution_mask),
        "parameters": jsonable(action.parameters),
        "treatment": action.treatment,
    }


def _action_mask_summary(action: TerritoryWorldModelAction) -> dict[str, Any]:
    mask = dict(action.execution_mask or {})
    hard_blocks = list(mask.get("hard_blocks") or mask.get("blocked_rules") or [])
    required_reviews = list(mask.get("required_reviews") or mask.get("review_required") or [])
    allowed = mask.get("allowed", mask.get("is_allowed", True))
    if isinstance(allowed, str):
        allowed = allowed.strip().lower() not in {"0", "false", "no", "n", "blocked", "deny", "denied"}
    mask_confidence = _clamp(_float(mask.get("confidence"), 1.0))
    target_count = len(action.target_objects or [])
    scope_level = str((action.spatial_scope or {}).get("level") or (action.spatial_scope or {}).get("admin_level") or "")
    return {
        "allowed": bool(allowed),
        "hard_blocks": hard_blocks,
        "required_reviews": required_reviews,
        "confidence": round(mask_confidence, 4),
        "target_object_count": target_count,
        "scope_level": scope_level,
        "legal_intent": action.legal_intent,
    }


def _state_counts(bundle: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    object_counts = dict(bundle.get("object_counts_by_role") or {})
    relation_counts = dict(bundle.get("relation_counts_by_type") or {})
    if not object_counts and bundle.get("objects"):
        for obj in bundle.get("objects") or []:
            if isinstance(obj, TwmStateObject):
                key = obj.canonical_role or obj.source_role or obj.object_type or "feature"
            else:
                key = str(getattr(obj, "canonical_role", "") or getattr(obj, "source_role", "") or getattr(obj, "object_type", "") or "feature")
            object_counts[key] = object_counts.get(key, 0) + 1
    if not relation_counts and bundle.get("relations"):
        for rel in bundle.get("relations") or []:
            if isinstance(rel, TwmStateRelation):
                key = rel.relation_type or rel.predicate or "relation"
            else:
                key = str(getattr(rel, "relation_type", "") or getattr(rel, "predicate", "") or "relation")
            relation_counts[key] = relation_counts.get(key, 0) + 1
    return object_counts, relation_counts


class TerritoryWorldModelPlanner:
    """Deterministic planning facade for TWM consumers.

    The planner is intentionally action-conditioned and multi-head. It does not
    define the world model itself; it consumes state bundles and emits a
    structured forecast with future latent state, constraint probability,
    utility delta, uncertainty and calibration metadata.
    """

    def __init__(self, *, default_evidence_threshold: float = 0.55):
        self.default_evidence_threshold = default_evidence_threshold

    def forecast(
        self,
        state_bundle: StateBuildResult | dict[str, Any],
        action: TerritoryWorldModelAction,
        *,
        scenario: str | None = None,
        rule_hits: Iterable[Any] | None = None,
        evidence_coverage: float | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        scenario_context: dict[str, Any] | None = None,
    ) -> TerritoryWorldModelForecast:
        bundle = _coerce_state_bundle(state_bundle)
        state_version: TwmStateVersion = bundle.get("state_version") or TwmStateVersion()
        object_counts, relation_counts = _state_counts(bundle)
        quality_summary = dict(bundle.get("quality_summary") or {})
        warnings = list(bundle.get("warnings") or [])
        action_sig = _action_signature(action)
        mask_summary = _action_mask_summary(action)
        scenario_name = str(scenario or action.scenario or "baseline").strip() or "baseline"
        spatial_projection = self._spatial_projection_for_action(action, scenario_context or {})

        rule_hits_list = list(rule_hits or [])
        severity_counts: dict[str, int] = {}
        for item in rule_hits_list:
            severity = str(getattr(item, "severity", "") or (item.get("severity") if isinstance(item, dict) else "medium"))
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

        blocking_count = severity_counts.get("blocking", 0)
        critical_count = severity_counts.get("critical", 0)
        high_count = severity_counts.get("high", 0)
        medium_count = severity_counts.get("medium", 0)
        low_count = severity_counts.get("low", 0)
        info_count = severity_counts.get("info", 0)

        qa_disabled_count = int(quality_summary.get("qa_disabled_object_count") or 0)
        not_for_production_count = int(quality_summary.get("not_for_production_object_count") or 0)
        total_objects = max(1, int(quality_summary.get("object_count") or len(bundle.get("objects") or [])))
        evidence_ratio = evidence_coverage
        if evidence_ratio is None:
            evidence_ratio = quality_summary.get("evidence_coverage")
        if evidence_ratio is None:
            evidence_ratio = 0.0
        evidence_ratio = _clamp(_float(evidence_ratio, 0.0))

        action_magnitude = max(0.0, _float(action.magnitude, 1.0))
        target_role = action.target_role or "project"
        target_pressure = object_counts.get(target_role, 0) / total_objects
        risk_pressure = _clamp(
            0.12
            + 0.16 * high_count
            + 0.22 * critical_count
            + 0.08 * medium_count
            + 0.08 * blocking_count
            + 0.04 * low_count
        )
        risk_pressure = _clamp(risk_pressure + min(0.18, target_pressure))
        risk_pressure = _clamp(risk_pressure + min(0.15, qa_disabled_count / total_objects))
        risk_pressure = _clamp(risk_pressure + min(0.12, not_for_production_count / total_objects))
        risk_pressure = _clamp(risk_pressure + max(0.0, 0.25 - evidence_ratio))
        if not mask_summary["allowed"]:
            risk_pressure = _clamp(risk_pressure + 0.25)
        if mask_summary["hard_blocks"]:
            risk_pressure = _clamp(risk_pressure + min(0.3, 0.12 * len(mask_summary["hard_blocks"])))
        if mask_summary["required_reviews"]:
            risk_pressure = _clamp(risk_pressure + min(0.12, 0.04 * len(mask_summary["required_reviews"])))
        if spatial_projection:
            constraint_recheck = dict(spatial_projection.get("constraint_recheck") or {})
            explicit_risk = _float(action.parameters.get("constraint_violation_probability"), risk_pressure)
            risk_pressure = _clamp(max(explicit_risk, 0.0 if constraint_recheck.get("passed", True) else 1.0))

        scenario_bias = self._scenario_bias(scenario_name, action)
        treatment_effect = self._treatment_effect(action, scenario_context or {})
        causal_adjustment = self._causal_adjustment(scenario_context or {})
        utility_delta = self._utility_delta(
            action=action,
            scenario_name=scenario_name,
            quality_summary=quality_summary,
            risk_pressure=risk_pressure,
            scenario_bias=scenario_bias,
            treatment_effect=treatment_effect,
            mask_summary=mask_summary,
            utility_scale_adjustment=causal_adjustment["utility_scale_adjustment"],
            scenario_scale_adjustment=causal_adjustment["scenario_scale_adjustment"],
        )
        if spatial_projection and "planning_utility_delta" in action.parameters:
            total_utility = _float(action.parameters.get("planning_utility_delta"), utility_delta)
            completion = _clamp(_float(spatial_projection.get("completion_ratio"), 1.0))
            previous_completion = _clamp(_float(spatial_projection.get("previous_completion_ratio"), 0.0))
            utility_delta = total_utility * max(0.0, completion - previous_completion)

        epistemic = _clamp(0.14 + abs(action_magnitude - 1.0) * 0.22 + max(0.0, 0.18 - evidence_ratio))
        aleatoric = _clamp(0.12 + risk_pressure * 0.32 + qa_disabled_count / (total_objects * 5.0))
        calibration_gap = _clamp(abs((scenario_context or {}).get("calibration_gap", 0.0)) + max(0.0, 0.22 - evidence_ratio))
        confidence = _clamp(1.0 - max(epistemic, aleatoric, calibration_gap))
        if spatial_projection:
            rollout_step = max(0, int(_float((scenario_context or {}).get("rollout_step"), 0.0)))
            confidence = _clamp(_float(mask_summary.get("confidence"), confidence) - rollout_step * 0.02)

        projected_object_counts = self._project_counts(object_counts, action)
        projected_relation_counts = self._project_relations(relation_counts, action)

        evidence_required = ["source_feature", "rule_clause", "spatial_calc", "semantic_mapping"]
        missing_evidence = []
        if evidence_ratio < self.default_evidence_threshold:
            missing_evidence.append("evidence_coverage")
        if not_for_production_count:
            missing_evidence.append("not_for_production")
        if qa_disabled_count:
            missing_evidence.append("qa_use_for_rules")
        if not mask_summary["allowed"]:
            missing_evidence.append("action_mask_allowed")
        if mask_summary["hard_blocks"]:
            missing_evidence.append("action_mask_hard_blocks")
        if action.parameters.get("spatial_trajectory") and not spatial_projection:
            missing_evidence.append("spatial_state_projection")
        if spatial_projection and not (spatial_projection.get("constraint_recheck") or {}).get("passed", True):
            missing_evidence.append("spatial_hard_constraint_recheck")
        evidence_gate_passed = not missing_evidence and blocking_count == 0 and confidence >= 0.35

        current_rollout_state = dict(bundle.get("rollout_state") or {})
        projected_rollout_state = dict(spatial_projection or {})
        if projected_rollout_state and not projected_rollout_state.get("state_sha256"):
            projected_rollout_state["state_sha256"] = _stable_state_hash(projected_rollout_state)
        state_writeback = {
            "applied": bool(projected_rollout_state),
            "from_state_sha256": current_rollout_state.get("state_sha256") or state_version.id,
            "to_state_sha256": projected_rollout_state.get("state_sha256") or current_rollout_state.get("state_sha256") or state_version.id,
            "geometry_changed": bool(projected_rollout_state) and current_rollout_state.get("geometry_sha256") != projected_rollout_state.get("geometry_sha256"),
            "constraint_recomputed": bool(projected_rollout_state.get("constraint_recheck")),
            "source": projected_rollout_state.get("transition_source") or "planner_count_projection",
        }

        future_latent_state = {
            "schema": "territory_world_model.latent_state.v1",
            "state_version_id": state_version.id,
            "project_id": state_version.project_id,
            "action_signature": action_sig,
            "scenario": scenario_name,
            "current": {
                "object_counts_by_role": object_counts,
                "relation_counts_by_type": relation_counts,
                "quality_summary": quality_summary,
                "rollout_state": current_rollout_state,
            },
            "projected": {
                "object_counts_by_role": projected_object_counts,
                "relation_counts_by_type": projected_relation_counts,
                "projected_risk_pressure": round(risk_pressure, 4),
                "projected_utility_delta": round(utility_delta, 4),
                "action_mask": mask_summary,
                "causal_adjustment": causal_adjustment,
                "spatial_state": projected_rollout_state,
                "state_writeback": state_writeback,
            },
            "hierarchy_tokens": dict(bundle.get("hierarchy_tokens") or {}),
            "warnings": warnings,
        }

        uncertainty = {
            "aleatoric": round(aleatoric, 4),
            "epistemic": round(epistemic, 4),
            "calibration_gap": round(calibration_gap, 4),
            "confidence": round(confidence, 4),
            "evidence_ratio": round(evidence_ratio, 4),
        }
        calibration = {
            "scenario_bias": round(scenario_bias, 4),
            "treatment_effect": round(treatment_effect, 4),
            "risk_pressure": round(risk_pressure, 4),
            "calibrated_utility_delta": round(utility_delta + treatment_effect, 4),
            "utility_scale_adjustment": round(causal_adjustment["utility_scale_adjustment"], 4),
            "scenario_scale_adjustment": round(causal_adjustment["scenario_scale_adjustment"], 4),
            "causal_calibration": causal_adjustment.get("source", {}),
            "transition_source": projected_rollout_state.get("transition_source") or "deterministic_action_conditioned_planner",
            "support": {
                "blocking_hits": blocking_count,
                "critical_hits": critical_count,
                "high_hits": high_count,
                "medium_hits": medium_count,
                "info_hits": info_count,
            },
        }
        evidence_gate = {
            "passed": evidence_gate_passed,
            "status": "pass" if evidence_gate_passed else "review",
            "required": evidence_required,
            "missing": missing_evidence,
            "evidence_threshold": self.default_evidence_threshold,
            "coverage": round(evidence_ratio, 4),
            "action_mask": mask_summary,
        }

        return TerritoryWorldModelForecast(
            action=action,
            future_latent_state=future_latent_state,
            constraint_violation_probability=round(risk_pressure, 4),
            planning_utility_delta=round(utility_delta, 4),
            uncertainty=uncertainty,
            calibration=calibration,
            evidence_gate=evidence_gate,
            created_at=now_utc_iso(),
        )

    def plan(
        self,
        state_bundle: StateBuildResult | dict[str, Any],
        action: TerritoryWorldModelAction,
        *,
        scenario: str | None = None,
        rule_hits: Iterable[Any] | None = None,
        evidence_coverage: float | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        scenario_context: dict[str, Any] | None = None,
    ) -> TwmScenarioPlan:
        forecast = self.forecast(
            state_bundle,
            action,
            scenario=scenario,
            rule_hits=rule_hits,
            evidence_coverage=evidence_coverage,
            model_name=model_name,
            model_version=model_version,
            scenario_context=scenario_context,
        )
        metrics = [
            TwmScenarioMetric(
                scenario_id="",
                metric_code="planning_utility_delta",
                metric_name="planning utility delta",
                value=forecast.planning_utility_delta,
                unit="score",
                benchmark_value=0.0,
                direction="higher_better",
                explanation="Heuristic utility lift conditioned on action, scenario and evidence.",
            ),
            TwmScenarioMetric(
                scenario_id="",
                metric_code="constraint_violation_probability",
                metric_name="constraint violation probability",
                value=forecast.constraint_violation_probability,
                unit="probability",
                benchmark_value=0.2,
                direction="lower_better",
                explanation="Projected hard-constraint pressure after the proposed action.",
            ),
            TwmScenarioMetric(
                scenario_id="",
                metric_code="uncertainty",
                metric_name="forecast uncertainty",
                value=forecast.uncertainty.get("confidence", 0.0),
                unit="confidence",
                benchmark_value=0.5,
                direction="higher_better",
                explanation="Evidence-gated confidence score for the forecast.",
            ),
        ]
        summary = {
            "scenario": scenario or action.scenario or "baseline",
            "action_signature": _action_signature(action),
            "risk_pressure": forecast.constraint_violation_probability,
            "utility_delta": forecast.planning_utility_delta,
            "uncertainty": forecast.uncertainty,
            "evidence_gate": forecast.evidence_gate,
        }
        return TwmScenarioPlan(
            state_version_id=(state_bundle.state_version.id if isinstance(state_bundle, StateBuildResult) else str((state_bundle.get("state_version") or {}).id if hasattr(state_bundle.get("state_version"), "id") else (state_bundle.get("state_version_id") or ""))),
            action=action,
            forecast=forecast,
            candidate_metrics=metrics,
            summary=summary,
        )

    def beam_search(
        self,
        state_bundle: StateBuildResult | dict[str, Any],
        actions: Iterable[TerritoryWorldModelAction],
        *,
        scenario: str | None = None,
        evidence_coverage: float | None = None,
        rule_hits: Iterable[Any] | None = None,
        limit: int = 5,
        scenario_context: dict[str, Any] | None = None,
    ) -> list[TwmScenarioPlan]:
        plans = [
            self.plan(
                state_bundle,
                action,
                scenario=scenario,
                rule_hits=rule_hits,
                evidence_coverage=evidence_coverage,
                scenario_context=scenario_context,
            )
            for action in list(actions)
        ]
        plans.sort(
            key=lambda item: (
                item.forecast.planning_utility_delta - item.forecast.constraint_violation_probability,
                item.forecast.uncertainty.get("confidence", 0.0),
            ),
            reverse=True,
        )
        return plans[: max(1, int(limit))]

    def counterfactual_rollout(
        self,
        state_bundle: StateBuildResult | dict[str, Any],
        *,
        baseline_action: TerritoryWorldModelAction,
        intervention_actions: Iterable[TerritoryWorldModelAction],
        scenario: str | None = None,
        horizon: int = 3,
        evidence_coverage: float | None = None,
        rule_hits: Iterable[Any] | None = None,
        scenario_context: dict[str, Any] | None = None,
    ) -> TwmCounterfactualRollout:
        bundle = _coerce_state_bundle(state_bundle)
        state_version: TwmStateVersion = bundle.get("state_version") or TwmStateVersion()
        scenario_name = str(scenario or baseline_action.scenario or "baseline").strip() or "baseline"
        horizon = max(1, int(horizon))
        interventions = list(intervention_actions)
        if not interventions:
            interventions = [baseline_action]

        baseline_steps = self._rollout_arm(
            bundle,
            arm="baseline",
            actions=[baseline_action],
            scenario=scenario_name,
            horizon=horizon,
            evidence_coverage=evidence_coverage,
            rule_hits=rule_hits,
            scenario_context=scenario_context or {},
        )
        intervention_steps = self._rollout_arm(
            bundle,
            arm="intervention",
            actions=interventions,
            scenario=scenario_name,
            horizon=horizon,
            evidence_coverage=evidence_coverage,
            rule_hits=rule_hits,
            scenario_context=scenario_context or {},
        )
        deltas = self._rollout_deltas(baseline_steps, intervention_steps)
        evidence_gate = self._rollout_evidence_gate(baseline_steps, intervention_steps)
        calibration_summary = self._rollout_calibration_summary(baseline_steps, intervention_steps)
        summary = {
            "schema": "territory_world_model.counterfactual_rollout.v1",
            "state_version_id": state_version.id,
            "scenario": scenario_name,
            "horizon": horizon,
            "baseline_final": baseline_steps[-1].metrics if baseline_steps else {},
            "intervention_final": intervention_steps[-1].metrics if intervention_steps else {},
            "planning_lift": deltas.get("final", {}).get("utility_delta_lift", 0.0),
            "risk_delta": deltas.get("final", {}).get("constraint_probability_delta", 0.0),
            "claim_status": "claim_supported" if evidence_gate.get("passed") and deltas.get("final", {}).get("utility_delta_lift", 0.0) > 0 else "review_required",
        }
        return TwmCounterfactualRollout(
            state_version_id=state_version.id,
            scenario=scenario_name,
            horizon=horizon,
            baseline_action=baseline_action,
            intervention_actions=interventions,
            baseline_steps=baseline_steps,
            intervention_steps=intervention_steps,
            deltas=deltas,
            evidence_gate=evidence_gate,
            calibration_summary=calibration_summary,
            summary=summary,
        )

    def _rollout_arm(
        self,
        state_bundle: dict[str, Any],
        *,
        arm: str,
        actions: list[TerritoryWorldModelAction],
        scenario: str,
        horizon: int,
        evidence_coverage: float | None,
        rule_hits: Iterable[Any] | None,
        scenario_context: dict[str, Any],
    ) -> list[TwmRolloutStep]:
        steps: list[TwmRolloutStep] = []
        current_bundle = dict(state_bundle)
        for idx in range(horizon):
            action = actions[min(idx, len(actions) - 1)]
            step_context = dict(scenario_context)
            step_context["rollout_step"] = idx
            if idx:
                step_context["calibration_gap"] = _float(step_context.get("calibration_gap"), 0.0) + idx * 0.015
            forecast = self.forecast(
                current_bundle,
                action,
                scenario=scenario,
                rule_hits=rule_hits,
                evidence_coverage=evidence_coverage,
                scenario_context=step_context,
            )
            metrics = {
                "constraint_violation_probability": forecast.constraint_violation_probability,
                "planning_utility_delta": forecast.planning_utility_delta,
                "confidence": forecast.uncertainty.get("confidence", 0.0),
                "calibration_gap": forecast.uncertainty.get("calibration_gap", 0.0),
                "evidence_gate_status": forecast.evidence_gate.get("status", "review"),
            }
            steps.append(
                TwmRolloutStep(
                    step_index=idx,
                    arm=arm,
                    action=action,
                    forecast=forecast,
                    metrics=metrics,
                )
            )
            projected = forecast.future_latent_state.get("projected") or {}
            current_bundle["object_counts_by_role"] = dict(projected.get("object_counts_by_role") or {})
            current_bundle["relation_counts_by_type"] = dict(projected.get("relation_counts_by_type") or {})
            projected_spatial_state = dict(projected.get("spatial_state") or {})
            if projected_spatial_state:
                current_bundle["rollout_state"] = projected_spatial_state
                current_bundle["hierarchy_tokens"] = dict(current_bundle.get("hierarchy_tokens") or {}) | {
                    "rollout_state": projected_spatial_state,
                }
                current_bundle["quality_summary"] = dict(current_bundle.get("quality_summary") or {}) | {
                    "rollout_step": idx + 1,
                    "rollout_state_sha256": projected_spatial_state.get("state_sha256"),
                    "spatial_constraint_recheck_passed": (projected_spatial_state.get("constraint_recheck") or {}).get("passed"),
                }
        return steps

    def _spatial_projection_for_action(
        self,
        action: TerritoryWorldModelAction,
        scenario_context: dict[str, Any],
    ) -> dict[str, Any]:
        trajectory = action.parameters.get("spatial_trajectory")
        if not isinstance(trajectory, list) or not trajectory:
            return {}
        step = max(0, int(_float(scenario_context.get("rollout_step"), 0.0)))
        selected = trajectory[min(step, len(trajectory) - 1)]
        if not isinstance(selected, dict):
            return {}
        projection = dict(selected)
        previous = trajectory[step - 1] if step > 0 and step - 1 < len(trajectory) else {}
        projection["previous_completion_ratio"] = _float(
            previous.get("completion_ratio") if isinstance(previous, dict) else 0.0,
            0.0,
        )
        projection.setdefault("transition_source", action.parameters.get("transition_source") or "optimization_bundle_spatial_state")
        return projection

    def _rollout_deltas(
        self,
        baseline_steps: list[TwmRolloutStep],
        intervention_steps: list[TwmRolloutStep],
    ) -> dict[str, Any]:
        pairs = zip(baseline_steps, intervention_steps)
        by_step = []
        for base, inter in pairs:
            by_step.append(
                {
                    "step_index": base.step_index,
                    "utility_delta_lift": round(
                        _float(inter.metrics.get("planning_utility_delta")) - _float(base.metrics.get("planning_utility_delta")),
                        4,
                    ),
                    "constraint_probability_delta": round(
                        _float(inter.metrics.get("constraint_violation_probability")) - _float(base.metrics.get("constraint_violation_probability")),
                        4,
                    ),
                    "confidence_delta": round(
                        _float(inter.metrics.get("confidence")) - _float(base.metrics.get("confidence")),
                        4,
                    ),
                }
            )
        final = by_step[-1] if by_step else {
            "utility_delta_lift": 0.0,
            "constraint_probability_delta": 0.0,
            "confidence_delta": 0.0,
        }
        return {
            "by_step": by_step,
            "final": final,
            "cumulative": {
                "utility_delta_lift": round(sum(item["utility_delta_lift"] for item in by_step), 4),
                "constraint_probability_delta": round(sum(item["constraint_probability_delta"] for item in by_step), 4),
                "confidence_delta": round(sum(item["confidence_delta"] for item in by_step), 4),
            },
        }

    def _rollout_evidence_gate(
        self,
        baseline_steps: list[TwmRolloutStep],
        intervention_steps: list[TwmRolloutStep],
    ) -> dict[str, Any]:
        gates = [step.forecast.evidence_gate for step in baseline_steps + intervention_steps]
        missing: list[str] = []
        for gate in gates:
            for item in gate.get("missing") or []:
                if item not in missing:
                    missing.append(item)
        passed = bool(gates) and all(bool(gate.get("passed")) for gate in gates)
        min_coverage = min((_float(gate.get("coverage"), 0.0) for gate in gates), default=0.0)
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "missing": missing,
            "min_coverage": round(min_coverage, 4),
            "step_count": len(gates),
        }

    def _rollout_calibration_summary(
        self,
        baseline_steps: list[TwmRolloutStep],
        intervention_steps: list[TwmRolloutStep],
    ) -> dict[str, Any]:
        all_steps = baseline_steps + intervention_steps
        gaps = [_float(step.metrics.get("calibration_gap"), 0.0) for step in all_steps]
        treatment_effects = [_float(step.forecast.calibration.get("treatment_effect"), 0.0) for step in all_steps]
        return {
            "max_calibration_gap": round(max(gaps, default=0.0), 4),
            "mean_treatment_effect": round(sum(treatment_effects) / max(1, len(treatment_effects)), 4),
            "calibration_required": any(gap > 0.2 for gap in gaps),
            "support": {
                "baseline_steps": len(baseline_steps),
                "intervention_steps": len(intervention_steps),
            },
        }

    def _scenario_bias(self, scenario: str, action: TerritoryWorldModelAction) -> float:
        s = scenario.lower()
        a = action.action_type.lower()
        bias = 0.0
        if "baseline" in s:
            bias += 0.0
        elif any(key in s for key in ("restoration", "ecology")):
            bias += 0.08
        elif any(key in s for key in ("agricultural", "farm")):
            bias += 0.06
        elif any(key in s for key in ("urban", "construction")):
            bias += 0.04
        if any(key in a for key in ("mitigate", "protect", "reduce", "constrain")):
            bias += 0.12
        if any(key in a for key in ("expand", "relocate", "convert")):
            bias -= 0.08
        return max(-0.2, min(0.2, bias))

    def _treatment_effect(self, action: TerritoryWorldModelAction, scenario_context: dict[str, Any]) -> float:
        treatment_effect = _float(action.parameters.get("treatment_effect"), 0.0)
        treatment_effect += _float(scenario_context.get("observed_treatment_effect"), 0.0)
        if action.treatment:
            treatment_effect += 0.03
        return max(-0.25, min(0.25, treatment_effect))

    def _causal_adjustment(self, scenario_context: dict[str, Any]) -> dict[str, Any]:
        raw = dict(scenario_context.get("causal_calibration") or scenario_context.get("causal_calibration_report") or {})
        calibration = dict(raw.get("calibration") or raw)
        utility_scale = max(0.1, min(5.0, _float(calibration.get("utility_scale_adjustment"), 1.0)))
        scenario_scale = max(0.5, min(1.5, _float(calibration.get("scenario_scale_adjustment"), 1.0)))
        status = str(raw.get("status") or (raw.get("evidence_gate") or {}).get("status") or calibration.get("status") or "")
        if status and status != "pass":
            utility_scale = 1.0
            scenario_scale = 1.0
        return {
            "utility_scale_adjustment": utility_scale,
            "scenario_scale_adjustment": scenario_scale,
            "source": {
                "status": status or "not_provided",
                "schema": raw.get("schema", ""),
                "identification_strength": raw.get("identification_strength") or ("observational" if raw else ""),
                "identification_note": raw.get("identification_note", ""),
                "estimate": raw.get("estimate", {}),
            },
        }

    def _utility_delta(
        self,
        *,
        action: TerritoryWorldModelAction,
        scenario_name: str,
        quality_summary: dict[str, Any],
        risk_pressure: float,
        scenario_bias: float,
        treatment_effect: float,
        mask_summary: dict[str, Any],
        utility_scale_adjustment: float = 1.0,
        scenario_scale_adjustment: float = 1.0,
    ) -> float:
        action_type = action.action_type.lower()
        magnitude = max(0.0, _float(action.magnitude, 1.0))
        base = 0.0
        if any(key in action_type for key in ("protect", "mitigate", "restore", "reclaim", "constrain")):
            base += 0.35
        elif any(key in action_type for key in ("expand", "add", "convert")):
            base += 0.18
        elif any(key in action_type for key in ("inspect", "review", "audit")):
            base += 0.05
        else:
            base += 0.1
        base *= magnitude
        quality_bonus = 0.0
        evidence_coverage = _float(quality_summary.get("evidence_coverage"), 0.0)
        quality_bonus += min(0.12, evidence_coverage * 0.08)
        quality_bonus += 0.04 if not quality_summary.get("qa_disabled_object_count") else -0.04
        utility = base + quality_bonus + (scenario_bias * scenario_scale_adjustment) + treatment_effect - risk_pressure * 0.45
        if not mask_summary.get("allowed", True):
            utility -= 0.35
        if mask_summary.get("hard_blocks"):
            utility -= min(0.3, 0.1 * len(mask_summary.get("hard_blocks") or []))
        if mask_summary.get("required_reviews"):
            utility -= min(0.08, 0.025 * len(mask_summary.get("required_reviews") or []))
        if action.legal_intent and any(key in action.legal_intent.lower() for key in ("protect", "farmland", "ecology", "compliance")):
            utility += 0.04
        if "baseline" in scenario_name.lower():
            utility += 0.02
        return utility * utility_scale_adjustment

    def _project_counts(self, counts: dict[str, int], action: TerritoryWorldModelAction) -> dict[str, int]:
        projected = dict(counts)
        action_type = action.action_type.lower()
        magnitude = max(0.0, _float(action.magnitude, 1.0))
        role = action.target_role or "project"
        if any(key in action_type for key in ("expand", "convert", "add")):
            projected[role] = projected.get(role, 0) + max(1, int(round(magnitude)))
        elif any(key in action_type for key in ("remove", "mitigate", "constrain", "protect")):
            projected[role] = max(0, projected.get(role, 0) - max(1, int(round(magnitude * 0.5))))
        else:
            projected[role] = projected.get(role, 0)
        return projected

    def _project_relations(self, counts: dict[str, int], action: TerritoryWorldModelAction) -> dict[str, int]:
        projected = dict(counts)
        action_type = action.action_type.lower()
        delta = max(1, int(round(max(0.0, _float(action.magnitude, 1.0)))))
        if "plan" in action_type or "opt" in action_type:
            projected["project_overlaps_planning_zone"] = projected.get("project_overlaps_planning_zone", 0) + delta
        if any(key in action_type for key in ("protect", "mitigate", "constrain")):
            projected["project_overlaps_permanent_basic_farmland"] = max(0, projected.get("project_overlaps_permanent_basic_farmland", 0) - delta)
            projected["project_overlaps_ecological_redline"] = max(0, projected.get("project_overlaps_ecological_redline", 0) - delta)
        return projected
