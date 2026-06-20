from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable

from .models import (
    StateBuildResult,
    TerritoryWorldModelAction,
    TerritoryWorldModelForecast,
    TwmActionMaskReport,
    TwmAuditReport,
    TwmBeamPlanReport,
    TwmCausalCalibrationReport,
    TwmCounterfactualRollout,
    TwmDynamicsBackendReport,
    TwmDynamicsEvaluationReport,
    TwmDynamicsFitReport,
    TwmDynamicsReadinessReport,
    TwmDynamicsTrainingDataset,
    TwmDynamicsTrainingExample,
    TwmEvidenceItem,
    TwmGeoFMGateReport,
    TwmGeoFMGateVariant,
    TwmLayerBinding,
    TwmPolicyRule,
    TwmProject,
    TwmRelationSpec,
    TwmReviewTask,
    TwmRuleEvaluationResult,
    TwmRuleHit,
    TwmRuleSet,
    TwmScenario,
    TwmScenarioMetric,
    TwmScenarioPlan,
    TwmStateContractReport,
    TwmStateObject,
    TwmStateRelation,
    TwmStateVersion,
    TwmTrainDynamicsReport,
    TwmTrainingObjectiveReport,
    TwmValidationReport,
    TwmValidationStage,
    TwmWorldModelCapability,
    TwmWorldModelProfile,
    jsonable,
    now_utc_iso,
)
from .causal_calibration import estimate_observational_treatment_effect
from .neural_dynamics import (
    HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA,
    NEURAL_DYNAMICS_SCHEMA,
    SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA,
    train_hierarchical_graph_dynamics,
    train_neural_multi_head_dynamics,
    train_spatiotemporal_transformer_dynamics,
)
from .planner import TerritoryWorldModelPlanner
from .repository import TwmRepository, get_twm_repository
from .rule_evaluator import RuleEvaluator, evaluate_rules
from .state_builder import StateBuilder, build_state_from_bundle
from .utils import read_csv, safe_float, safe_int, truthy


_INSTANCE_LOCK = threading.Lock()
_INSTANCE: "TerritoryWorldModelService | None" = None


def _json(data: Any) -> str:
    return json.dumps(jsonable(data), ensure_ascii=False, default=str)


class TerritoryWorldModelService:
    """Facade for TWM project lifecycle, state build, rules, and planning."""

    def __init__(self, repository: TwmRepository | None = None):
        self.repository = repository or get_twm_repository()
        self.state_builder = StateBuilder()
        self.rule_evaluator = RuleEvaluator(repository=self.repository)
        self.planner = TerritoryWorldModelPlanner()

    def status(self) -> dict[str, Any]:
        repo_status = self.repository.status()
        return {
            "status": "ready",
            "version": "0.1.0",
            "repository": repo_status,
            "planner": {
                "multi_head": True,
                "action_conditioned": True,
                "evidence_gated": True,
            },
            "capabilities": {
                "projects": True,
                "state_build": True,
                "rules": True,
                "evidence": True,
                "reviews": True,
                "planning": True,
                "geofm_ablation_gate": True,
                "causal_calibration": True,
                "action_mask": True,
                "dynamics_readiness": True,
                "dynamics_evaluation": True,
                "dynamics_fit": True,
                "dynamics_backend": True,
                "train_dynamics": True,
                "training_objective": True,
                "beam_plan": True,
                "state_contract": True,
            },
            "updated_at": now_utc_iso(),
        }

    # ------------------------------------------------------------------
    # Project / binding lifecycle
    # ------------------------------------------------------------------

    def create_project(self, payload: dict[str, Any], username: str = "") -> dict[str, Any]:
        project = TwmProject(
            name=str(payload.get("name") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            region_code=str(payload.get("region_code") or payload.get("admin_code") or "").strip(),
            business_scenario=str(payload.get("business_scenario") or "planning_supervision").strip() or "planning_supervision",
            owner_username=str(payload.get("owner_username") or username or "").strip(),
            status=str(payload.get("status") or "draft").strip() or "draft",
            metadata=dict(payload.get("metadata") or {}),
        )
        saved = self.repository.save_project(project)
        return saved.to_dict()

    def list_projects(self, owner_username: str | None = None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.repository.list_projects(owner_username=owner_username)]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        project = self.repository.get_project(project_id)
        return project.to_dict() if project else None

    def bind_layer(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        binding = TwmLayerBinding(
            project_id=project_id,
            role=str(payload.get("role") or payload.get("semantic_domain") or "").strip(),
            canonical_role=str(payload.get("canonical_role") or payload.get("standard_role") or payload.get("role") or "").strip(),
            object_type=str(payload.get("object_type") or "feature").strip() or "feature",
            layer_alias=str(payload.get("layer_alias") or payload.get("role_alias_zh") or payload.get("alias_zh") or "").strip(),
            source_path=str(payload.get("source_path") or payload.get("path") or "").strip(),
            semantic_product_path=str(payload.get("semantic_product_path") or "").strip(),
            asset_id=payload.get("asset_id"),
            time_label=str(payload.get("time_label") or "").strip(),
            valid_from=payload.get("valid_from"),
            valid_to=payload.get("valid_to"),
            field_mapping=dict(payload.get("field_mapping") or payload.get("twm_binding") or {}),
            quality_snapshot=dict(payload.get("quality_snapshot") or {}),
            metadata=dict(payload.get("metadata") or {}),
            synthetic=bool(payload.get("synthetic", False)),
            not_for_production=bool(payload.get("not_for_production", False)),
        )
        saved = self.repository.save_layer_binding(binding)
        return saved.to_dict()

    def list_layer_bindings(self, project_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.repository.list_layer_bindings(project_id)]

    # ------------------------------------------------------------------
    # State build
    # ------------------------------------------------------------------

    def build_state(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self.repository.get_project(project_id)
        if project is None:
            raise LookupError(f"project not found: {project_id}")
        bindings = self.repository.list_layer_bindings(project_id)
        bundle_dir = payload.get("bundle_dir") or payload.get("semantic_bundle_dir")
        if bundle_dir:
            result = self.state_builder.build_from_bundle(
                bundle_dir,
                project=project,
                label=payload.get("label"),
                state_time=payload.get("state_time"),
                rule_set_id=payload.get("rule_set_id"),
                include_auxiliary_tables=bool(payload.get("include_auxiliary_tables", True)),
            )
        else:
            if not bindings:
                raise ValueError(f"project {project_id} has no layer bindings")
            result = self.state_builder.build_from_bindings(
                project,
                bindings,
                bundle_root=payload.get("bundle_root"),
                bundle_manifest=payload.get("bundle_manifest"),
                bundle_contract=payload.get("bundle_contract"),
                bundle_state_input=payload.get("bundle_state_input"),
                bundle_warnings=list(payload.get("bundle_warnings") or []),
                label=payload.get("label"),
                state_time=payload.get("state_time"),
                rule_set_id=payload.get("rule_set_id"),
                include_auxiliary_tables=bool(payload.get("include_auxiliary_tables", True)),
            )

        self.repository.save_state_bundle(result)
        return result.to_dict()

    def get_state(self, state_version_id: str) -> dict[str, Any] | None:
        bundle = self.repository.get_state_bundle(state_version_id)
        if bundle is None:
            return None
        return {
            "state_version": bundle["state_version"].to_dict(),
            "objects": [item.to_dict() for item in bundle["objects"]],
            "relations": [item.to_dict() for item in bundle["relations"]],
            "hits": [item.to_dict() for item in bundle["hits"]],
            "evidence_items": [item.to_dict() for item in bundle["evidence_items"]],
            "review_tasks": [item.to_dict() for item in bundle["review_tasks"]],
        }

    def state_contract_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        state_bundle = self.repository.get_state_bundle(state_version_id)
        if state is None or state_bundle is None:
            raise LookupError(f"state not found: {state_version_id}")
        objects = list(state_bundle.get("objects") or [])
        relations = list(state_bundle.get("relations") or [])
        rule_hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        token_contract = self._state_contract_hierarchy(state, objects, relations)
        feature_channels = self._state_contract_feature_channels(state, objects, relations)
        constraint_channels = self._state_contract_constraint_channels(rule_hits, evidence_items, review_tasks)
        temporal_support = self._state_contract_temporal_support(state, payload)
        geofm_policy = self._state_contract_geofm_policy(state, payload)
        claim_boundary = self._state_contract_claim_boundary(
            token_contract=token_contract,
            constraint_channels=constraint_channels,
            temporal_support=temporal_support,
            geofm_policy=geofm_policy,
        )
        report = TwmStateContractReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=claim_boundary["status"],
            hierarchy=token_contract,
            feature_channels=feature_channels,
            constraint_channels=constraint_channels,
            temporal_support=temporal_support,
            geofm_policy=geofm_policy,
            downstream_consumers=[
                "action_conditioned_forecast",
                "dynamics_training_examples",
                "dynamics_readiness_report",
                "dynamics_candidate_fit",
                "beam_plan",
                "counterfactual_rollout",
            ],
            claim_boundary=claim_boundary,
            recommendations=self._state_contract_recommendations(
                token_contract=token_contract,
                constraint_channels=constraint_channels,
                temporal_support=temporal_support,
                geofm_policy=geofm_policy,
            ),
        )
        return report.to_dict()

    def dynamics_backend_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        state_contract = self.state_contract_report(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
        backend = self._dynamics_backend_descriptor(payload)
        input_contract = self._dynamics_backend_input_contract(state_contract, backend)
        output_contract = self._dynamics_backend_output_contract(payload)
        adapter_contract = self._dynamics_backend_adapter_contract(payload)
        gate_results = self._dynamics_backend_gate_results(
            backend=backend,
            state_contract=state_contract,
            readiness=readiness,
            input_contract=input_contract,
            output_contract=output_contract,
            adapter_contract=adapter_contract,
            payload=payload,
        )
        evidence_gate = self._dynamics_backend_evidence_gate(gate_results, backend, readiness)
        claim_boundary = self._dynamics_backend_claim_boundary(gate_results, backend, evidence_gate)
        report = TwmDynamicsBackendReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=claim_boundary.get("status", "review"),
            backend=backend,
            input_contract=input_contract,
            output_contract=output_contract,
            adapter_contract=adapter_contract,
            gate_results=gate_results,
            evidence_gate=evidence_gate,
            claim_boundary=claim_boundary,
            recommendations=self._dynamics_backend_recommendations(gate_results, evidence_gate, backend),
        )
        return report.to_dict()

    def training_objective_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        backend_payload = payload.get("dynamics_backend_report")
        backend_report = dict(backend_payload) if isinstance(backend_payload, dict) else self.dynamics_backend_report(state_version_id, {"dataset": dataset, **payload})
        predictions = self._training_objective_predictions(dataset, payload, backend_report)
        metrics, head_metrics, eval_inventory = self._dynamics_evaluation_metrics(dataset, predictions)
        objective_contract = self._training_objective_contract(dataset, backend_report)
        loss_components = self._training_objective_loss_components(dataset, predictions, metrics)
        ranking_diagnostics = self._training_objective_ranking_diagnostics(dataset, predictions, metrics)
        calibration_diagnostics = self._training_objective_calibration_diagnostics(dataset, predictions)
        evidence_gate = self._training_objective_evidence_gate(backend_report, objective_contract, loss_components)
        report = TwmTrainingObjectiveReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=evidence_gate.get("status", "review"),
            objective_contract=objective_contract,
            loss_components=loss_components,
            ranking_diagnostics=ranking_diagnostics,
            calibration_diagnostics=calibration_diagnostics,
            evidence_gate=evidence_gate,
            sample_inventory=eval_inventory,
            recommendations=self._training_objective_recommendations(loss_components, evidence_gate, backend_report),
        )
        return report.to_dict()

    def train_dynamics_candidate(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
        trainer = self._train_dynamics_trainer_descriptor(payload)
        seed_objective = self.training_objective_report(state_version_id, {"dataset": dataset, **payload})
        if readiness.get("status") != "pass" or seed_objective.get("evidence_gate", {}).get("status") == "blocked":
            evidence_gate = self._train_dynamics_evidence_gate(
                readiness=readiness,
                backend_report={},
                objective_report=seed_objective,
                trainer=trainer,
            )
            report = TwmTrainDynamicsReport(
                state_version_id=state_version_id,
                project_id=state.project_id,
                status=evidence_gate.get("status", "blocked"),
                trainer=trainer,
                objective=seed_objective,
                learned_parameters={},
                predictions={},
                candidate_report={},
                backend_report={},
                evidence_gate=evidence_gate,
                recommendations=self._train_dynamics_recommendations(evidence_gate, trainer),
            )
            return report.to_dict()

        if self._use_spatiotemporal_transformer_dynamics_trainer(trainer):
            train_result = train_spatiotemporal_transformer_dynamics(dataset, trainer, seed_objective, payload)
            learned_parameters = dict(train_result.get("learned_parameters") or {})
            predictions = dict(train_result.get("predictions") or {})
            candidate_report = self._neural_dynamics_candidate_report(trainer, learned_parameters, predictions, dict(train_result.get("diagnostics") or {}))
        elif self._use_hierarchical_graph_dynamics_trainer(trainer):
            train_result = train_hierarchical_graph_dynamics(dataset, trainer, seed_objective, payload)
            learned_parameters = dict(train_result.get("learned_parameters") or {})
            predictions = dict(train_result.get("predictions") or {})
            candidate_report = self._neural_dynamics_candidate_report(trainer, learned_parameters, predictions, dict(train_result.get("diagnostics") or {}))
        elif self._use_neural_dynamics_trainer(trainer):
            train_result = train_neural_multi_head_dynamics(dataset, trainer, seed_objective, payload)
            learned_parameters = dict(train_result.get("learned_parameters") or {})
            predictions = dict(train_result.get("predictions") or {})
            candidate_report = self._neural_dynamics_candidate_report(trainer, learned_parameters, predictions, dict(train_result.get("diagnostics") or {}))
        else:
            learned_parameters = self._train_dynamics_parameters(dataset, seed_objective, trainer)
            predictions = self._predict_with_baseline_dynamics(dataset, learned_parameters)
            candidate_report = self._train_dynamics_candidate_report(trainer, learned_parameters, predictions)
        backend_payload = {
            "dataset": dataset,
            "backend": {
                "backend_id": trainer["trainer_id"],
                "backend_type": "trainable_candidate_scaffold",
                "model_name": trainer["model_name"],
                "model_version": trainer["model_version"],
                "model_family": trainer["model_family"],
                "trainable": True,
                "action_conditioned": True,
                "uses_geofm": trainer.get("uses_geofm", False),
                "uses_causal_calibration": trainer.get("uses_causal_calibration", False),
            },
            "candidate_report": candidate_report,
            "thresholds": payload.get("thresholds") or {},
            "geofm_gate_report": payload.get("geofm_gate_report") or {},
            "causal_calibration_report": payload.get("causal_calibration_report") or {},
        }
        backend_report = self.dynamics_backend_report(state_version_id, backend_payload)
        objective_report = self.training_objective_report(
            state_version_id,
            {
                "dataset": dataset,
                "dynamics_backend_report": backend_report,
                "predictions": predictions,
            },
        )
        evidence_gate = self._train_dynamics_evidence_gate(
            readiness=readiness,
            backend_report=backend_report,
            objective_report=objective_report,
            trainer=trainer,
        )
        report = TwmTrainDynamicsReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=evidence_gate.get("status", "review"),
            trainer=trainer,
            objective=objective_report,
            learned_parameters=learned_parameters,
            predictions=predictions,
            candidate_report=candidate_report,
            backend_report=backend_report,
            evidence_gate=evidence_gate,
            recommendations=self._train_dynamics_recommendations(evidence_gate, trainer),
        )
        return report.to_dict()

    # ------------------------------------------------------------------
    # Rules / reviews / evidence
    # ------------------------------------------------------------------

    def ensure_default_rules(self) -> dict[str, Any]:
        rule_set = TwmRuleSet(
            name="TWM Default Rule Set",
            version_label="default-demo",
            status="active",
            created_by="system",
        )
        saved_rule_set = self.repository.save_rule_set(rule_set)
        rules = self.rule_evaluator._default_rules()
        self.repository.ensure_default_rule_set(saved_rule_set, rules)
        return {
            "rule_set": saved_rule_set.to_dict(),
            "rules": [item.to_dict() for item in self.repository.list_policy_rules(saved_rule_set.id, enabled=True)],
        }

    def evaluate_rules(
        self,
        state_version_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        if state_bundle is None:
            raise LookupError(f"state not found: {state_version_id}")
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        state_result = StateBuildResult(
            project=self.repository.get_project(state.project_id) or TwmProject(id=state.project_id),
            state_version=state,
            objects=state_bundle["objects"],
            relations=state_bundle["relations"],
            object_counts_by_role={},
            relation_counts_by_type={},
            hierarchy_tokens={},
            quality_summary=state.quality_summary,
            warnings=[],
            relation_specs=[],
        )
        rule_set = self.repository.get_rule_set(payload.get("rule_set_id")) if payload and payload.get("rule_set_id") else None
        rules = self.repository.list_policy_rules(rule_set.id, enabled=True) if rule_set else None
        result = self.rule_evaluator.evaluate_state(
            state_result,
            rule_set=rule_set,
            rules=rules,
            include_default_rules=payload is None or payload.get("include_default_rules", True),
            model_output=payload.get("model_output") if payload else None,
            scenario_context=payload.get("scenario_context") if payload else None,
        )
        return result.to_dict()

    def get_rule_hits(self, state_version_id: str, *, severity: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.repository.list_rule_hits(state_version_id=state_version_id, severity=severity, status=status)]

    def get_rule_hit(self, hit_id: str) -> dict[str, Any] | None:
        hit = self.repository.get_rule_hit(hit_id)
        if hit is None:
            return None
        evidence = self.repository.list_evidence_items(rule_hit_id=hit.id)
        review_tasks = self.repository.list_review_tasks(rule_hit_id=hit.id)
        return {
            "hit": hit.to_dict(),
            "evidence_items": [item.to_dict() for item in evidence],
            "review_tasks": [item.to_dict() for item in review_tasks],
        }

    def review_hit(self, hit_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        hit, task = self.repository.review_rule_hit(
            hit_id,
            decision=str(payload.get("decision") or payload.get("review_result") or ""),
            comment=str(payload.get("comment") or payload.get("note") or ""),
            assignee=payload.get("assignee"),
            status=payload.get("status"),
        )
        if hit is None or task is None:
            raise LookupError(f"rule hit not found: {hit_id}")
        return {
            "hit": hit.to_dict(),
            "review_task": task.to_dict(),
        }

    def generate_audit_report(self, state_version_id: str) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        confirmed = sum(1 for task in review_tasks if task.status == "confirmed")
        dismissed = sum(1 for task in review_tasks if task.status == "dismissed")
        mitigation = sum(1 for hit in hits if hit.hit_status == "mitigated")
        evidence_gate_passed = all(item.checksum for item in evidence_items)
        severity_distribution: dict[str, int] = {}
        for hit in hits:
            severity_distribution[hit.severity] = severity_distribution.get(hit.severity, 0) + 1
        report = TwmAuditReport(
            project_id=state.project_id,
            state_version_id=state_version_id,
            rule_hit_count=len(hits),
            confirmed_count=confirmed,
            dismissed_count=dismissed,
            mitigation_count=mitigation,
            evidence_gate_passed=evidence_gate_passed,
            evidence_gate_summary={
                "evidence_item_count": len(evidence_items),
                "all_have_checksum": evidence_gate_passed,
            },
            source_summary=state.source_manifest,
            rule_summary={
                "severity_distribution": severity_distribution,
            },
            state_summary=state.summary,
        )
        return report.to_dict()

    # ------------------------------------------------------------------
    # Scenario planning
    # ------------------------------------------------------------------

    def create_scenario(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenario = TwmScenario(
            project_id=str(payload.get("project_id") or ""),
            base_state_version_id=str(payload.get("base_state_version_id") or ""),
            name=str(payload.get("name") or "").strip(),
            scenario_type=str(payload.get("scenario_type") or "baseline").strip() or "baseline",
            input_changes=dict(payload.get("input_changes") or {}),
            source_model=payload.get("source_model"),
            status=str(payload.get("status") or "draft").strip() or "draft",
        )
        saved = self.repository.save_scenario(scenario)
        metrics = payload.get("metrics") or []
        if metrics:
            saved_metrics = []
            for metric in metrics:
                item = TwmScenarioMetric(
                    scenario_id=saved.id,
                    metric_code=str(metric.get("metric_code") or metric.get("code") or ""),
                    metric_name=str(metric.get("metric_name") or metric.get("name") or ""),
                    value=float(metric.get("value") or 0.0),
                    unit=str(metric.get("unit") or ""),
                    benchmark_value=metric.get("benchmark_value"),
                    direction=str(metric.get("direction") or "lower_better"),
                    explanation=str(metric.get("explanation") or ""),
                )
                saved_metrics.append(self.repository.save_scenario_metric(item))
            return {
                "scenario": saved.to_dict(),
                "metrics": [item.to_dict() for item in saved_metrics],
            }
        return {"scenario": saved.to_dict(), "metrics": []}

    def compare_scenario(self, scenario_id: str) -> dict[str, Any]:
        scenario = self.repository.get_scenario(scenario_id)
        if scenario is None:
            raise LookupError(f"scenario not found: {scenario_id}")
        metrics = self.repository.list_scenario_metrics(scenario_id)
        delta = {item.metric_code: item.value - (item.benchmark_value or 0.0) for item in metrics}
        return {
            "scenario": scenario.to_dict(),
            "metrics": [item.to_dict() for item in metrics],
            "delta": delta,
            "summary": {
                "metric_count": len(metrics),
                "utility_delta": sum(delta.values()),
            },
        }

    def get_status(self) -> dict[str, Any]:
        return self.status()

    def forecast(self, state_version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        execution_mask = dict(payload.get("execution_mask") or {})
        if not execution_mask and bool(payload.get("auto_action_mask")):
            mask_report = self.action_mask_report(state_version_id, payload)
            execution_mask = dict(mask_report.get("execution_mask") or {})
        action = TerritoryWorldModelAction(
            action_type=str(payload.get("action_type") or "inspect"),
            target_role=str(payload.get("target_role") or "project"),
            target_objects=[str(item) for item in payload.get("target_objects") or []],
            spatial_scope=dict(payload.get("spatial_scope") or {}),
            magnitude=float(payload.get("magnitude") or 1.0),
            scenario=str(payload.get("scenario") or "baseline"),
            description=str(payload.get("description") or ""),
            legal_intent=str(payload.get("legal_intent") or ""),
            execution_mask=execution_mask,
            parameters=dict(payload.get("parameters") or {}),
            treatment=str(payload.get("treatment") or ""),
        )
        scenario_context = dict(payload.get("scenario_context") or {})
        scenario_context = self._scenario_context_with_causal_calibration(state_version_id, payload, scenario_context)
        plan = self.planner.plan(
            {
                "state_version": state,
                "objects": state_bundle["objects"],
                "relations": state_bundle["relations"],
                "quality_summary": state.quality_summary,
                "warnings": [],
                "hierarchy_tokens": state.summary,
            },
            action,
            scenario=payload.get("scenario"),
            rule_hits=self.repository.list_rule_hits(state_version_id=state_version_id),
            evidence_coverage=payload.get("evidence_coverage"),
            model_name=payload.get("model_name"),
            model_version=payload.get("model_version"),
            scenario_context=scenario_context,
        )
        result = plan.to_dict()
        return self._forecast_with_dynamics_candidate(result, payload)

    def action_mask_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        action = self._action_from_payload(payload)
        objects = list(state_bundle.get("objects") or [])
        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        target_summary = self._action_target_summary(action, objects)
        related_hits = self._action_related_rule_hits(action, target_summary, hits)
        blocking_severities = self._blocking_severities_for_action(action)
        blocking_hits = [
            self._mask_hit_payload(hit)
            for hit in related_hits
            if hit.severity in blocking_severities and hit.hit_status not in {"reviewed_dismissed", "mitigated"}
        ]
        high_review_hits = [
            hit
            for hit in related_hits
            if hit.severity in {"high", "critical", "blocking"} and hit.hit_status not in {"reviewed_dismissed", "mitigated"}
        ]
        review_by_hit = {task.rule_hit_id: task for task in review_tasks}
        required_reviews = []
        for hit in high_review_hits:
            task = review_by_hit.get(hit.id)
            if task is None or task.status == "pending":
                required_reviews.append(
                    {
                        "rule_hit_id": hit.id,
                        "rule_id": hit.rule_id,
                        "severity": hit.severity,
                        "review_task_id": task.id if task else hit.review_task_id,
                        "status": task.status if task else "missing",
                    }
                )
        missing: list[str] = []
        if target_summary["requested_target_count"] and target_summary["matched_target_count"] == 0:
            missing.append("target_objects")
        evidence_by_hit = {item.rule_hit_id for item in evidence_items if item.checksum}
        missing_evidence_hits = [hit.id for hit in related_hits if hit.id not in evidence_by_hit and hit.severity in {"high", "critical", "blocking"}]
        if missing_evidence_hits:
            missing.append("high_severity_evidence")
        hard_blocks = [item["rule_id"] for item in blocking_hits]
        allowed = not hard_blocks and not missing_evidence_hits and target_summary["target_scope_valid"]
        confidence = self._action_mask_confidence(
            target_summary=target_summary,
            blocking_hits=blocking_hits,
            required_reviews=required_reviews,
            missing_evidence_hits=missing_evidence_hits,
        )
        execution_mask = {
            "allowed": allowed,
            "hard_blocks": hard_blocks,
            "required_reviews": [item["rule_id"] for item in required_reviews],
            "confidence": confidence,
            "target_object_count": target_summary["matched_target_count"],
            "related_rule_hit_count": len(related_hits),
            "missing_evidence_hit_count": len(missing_evidence_hits),
        }
        evidence_gate = {
            "passed": allowed and not required_reviews,
            "status": "pass" if allowed and not required_reviews else "review",
            "missing": missing + (["required_reviews"] if required_reviews else []) + (["hard_blocks"] if hard_blocks else []),
            "evidence_item_count": len(evidence_items),
            "related_rule_hit_count": len(related_hits),
        }
        recommendations = []
        if hard_blocks:
            recommendations.append("remove blocked target objects or mitigate critical rule hits before planning")
        if required_reviews:
            recommendations.append("complete required review tasks before upgrading this action claim")
        if missing_evidence_hits:
            recommendations.append("attach checksum evidence for high-severity related rule hits")
        if not target_summary["target_scope_valid"]:
            recommendations.append("provide target objects or a spatial scope matching the requested target role")
        report = TwmActionMaskReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            action=action,
            allowed=allowed,
            execution_mask=execution_mask,
            target_summary=target_summary,
            blocking_hits=blocking_hits,
            required_reviews=required_reviews,
            evidence_gate=evidence_gate,
            recommendations=recommendations,
        )
        return report.to_dict()

    def counterfactual_rollout(self, state_version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        baseline_payload = dict(payload.get("baseline_action") or {})
        baseline_action = self._action_from_payload(
            {
                "action_type": baseline_payload.get("action_type") or "inspect",
                "target_role": baseline_payload.get("target_role") or payload.get("target_role") or "project",
                "magnitude": baseline_payload.get("magnitude") or 1.0,
                "scenario": baseline_payload.get("scenario") or payload.get("scenario") or "baseline",
                "description": baseline_payload.get("description") or "baseline reference action",
                "parameters": baseline_payload.get("parameters") or {},
                "treatment": baseline_payload.get("treatment") or "",
            }
        )
        raw_interventions = payload.get("intervention_actions") or payload.get("actions") or []
        if isinstance(raw_interventions, dict):
            raw_interventions = [raw_interventions]
        intervention_actions = [
            self._action_from_payload(
                {
                    "scenario": payload.get("scenario") or baseline_action.scenario,
                    **dict(item),
                }
            )
            for item in raw_interventions
            if isinstance(item, dict)
        ]
        if not intervention_actions:
            intervention_actions = [
                self._action_from_payload(
                    {
                        "action_type": payload.get("action_type") or "protect",
                        "target_role": payload.get("target_role") or "project",
                        "magnitude": payload.get("magnitude") or 1.0,
                        "scenario": payload.get("scenario") or baseline_action.scenario,
                        "description": payload.get("description") or "intervention action",
                        "parameters": dict(payload.get("parameters") or {}),
                        "treatment": payload.get("treatment") or "",
                    }
                )
            ]
        scenario_context = dict(payload.get("scenario_context") or {})
        scenario_context = self._scenario_context_with_causal_calibration(state_version_id, payload, scenario_context)
        rollout = self.planner.counterfactual_rollout(
            {
                "state_version": state,
                "objects": state_bundle["objects"],
                "relations": state_bundle["relations"],
                "quality_summary": state.quality_summary,
                "warnings": [],
                "hierarchy_tokens": state.summary,
            },
            baseline_action=baseline_action,
            intervention_actions=intervention_actions,
            scenario=payload.get("scenario") or baseline_action.scenario,
            horizon=int(payload.get("horizon") or 3),
            rule_hits=self.repository.list_rule_hits(state_version_id=state_version_id),
            evidence_coverage=payload.get("evidence_coverage"),
            scenario_context=scenario_context,
        )
        result = rollout.to_dict()
        return self._counterfactual_with_dynamics_candidate(result, payload)

    def beam_plan(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        raw_actions = payload.get("actions") or payload.get("candidate_actions") or []
        if isinstance(raw_actions, dict):
            raw_actions = [raw_actions]
        if not raw_actions:
            raw_actions = [
                {"action_type": "inspect", "target_role": payload.get("target_role") or "project", "magnitude": 1.0},
                {"action_type": "protect", "target_role": payload.get("target_role") or "project", "magnitude": 1.2, "treatment": "causal_calibrated"},
                {"action_type": "expand", "target_role": payload.get("target_role") or "project", "magnitude": 1.3},
            ]
        candidates = []
        for idx, raw_action in enumerate(raw_actions):
            if not isinstance(raw_action, dict):
                continue
            action_payload = dict(payload)
            action_payload.update(dict(raw_action))
            action_payload["scenario"] = raw_action.get("scenario") or payload.get("scenario") or "beam_plan"
            action_payload.setdefault("evidence_coverage", payload.get("evidence_coverage"))
            if payload.get("auto_action_mask") and "auto_action_mask" not in action_payload:
                action_payload["auto_action_mask"] = True
            if payload.get("dynamics_candidate_report") and "dynamics_prediction_id" not in action_payload:
                action_payload["dynamics_prediction_id"] = str(raw_action.get("prediction_id") or f"candidate:{idx}")
            forecast_plan = self.forecast(state_version_id, action_payload)
            candidate = self._beam_candidate_from_forecast(idx, action_payload, forecast_plan)
            candidates.append(candidate)
        candidates.sort(key=lambda item: (item["rank_score"], item["confidence"]), reverse=True)
        limit = max(1, int(payload.get("limit") or payload.get("beam_width") or len(candidates) or 1))
        ranking = []
        for rank, candidate in enumerate(candidates[:limit], start=1):
            candidate["rank"] = rank
            ranking.append(
                {
                    "rank": rank,
                    "candidate_id": candidate["candidate_id"],
                    "action_type": candidate["action"].get("action_type"),
                    "rank_score": candidate["rank_score"],
                    "utility": candidate["utility"],
                    "risk": candidate["risk"],
                    "confidence": candidate["confidence"],
                    "evidence_gate_status": candidate["evidence_gate"].get("status"),
                    "claim_status": candidate["claim_status"],
                }
            )
        selected = candidates[0] if candidates else {}
        evidence_gate = self._beam_evidence_gate(candidates)
        status = "pass" if evidence_gate.get("passed") else "review"
        if not candidates:
            status = "blocked"
        report = TwmBeamPlanReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            scenario=str(payload.get("scenario") or "beam_plan"),
            status=status,
            candidates=candidates,
            ranking=ranking,
            selected=selected,
            evidence_gate=evidence_gate,
            recommendations=self._beam_plan_recommendations(candidates, evidence_gate),
        )
        return report.to_dict()

    def validation_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")

        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        forecast_payload = {
            "action_type": payload.get("action_type") or "inspect",
            "target_role": payload.get("target_role") or "project",
            "magnitude": payload.get("magnitude") or 1.0,
            "scenario": payload.get("scenario") or "validation_baseline",
            "evidence_coverage": payload.get("evidence_coverage"),
            "treatment": payload.get("treatment") or "",
            "parameters": dict(payload.get("parameters") or {}),
            "scenario_context": dict(payload.get("scenario_context") or {}),
        }
        self._copy_dynamics_candidate_payload(payload, forecast_payload)
        forecast = self.forecast(state_version_id, forecast_payload)
        rollout_payload = {
            "scenario": payload.get("scenario") or "validation_counterfactual",
            "horizon": int(payload.get("horizon") or 3),
            "evidence_coverage": payload.get("evidence_coverage"),
            "baseline_action": payload.get("baseline_action") or {
                "action_type": "inspect",
                "target_role": forecast_payload["target_role"],
                "magnitude": 1.0,
            },
            "intervention_actions": payload.get("intervention_actions") or [
                {
                    "action_type": payload.get("intervention_action_type") or "protect",
                    "target_role": forecast_payload["target_role"],
                    "magnitude": payload.get("intervention_magnitude") or 1.0,
                    "treatment": payload.get("treatment") or "",
                    "parameters": dict(payload.get("parameters") or {}),
                }
            ],
            "scenario_context": dict(payload.get("scenario_context") or {}),
        }
        self._copy_dynamics_candidate_payload(payload, rollout_payload)
        rollout = self.counterfactual_rollout(state_version_id, rollout_payload)
        audit = self.generate_audit_report(state_version_id)

        stages = [
            self._validation_state_stage(state, state_bundle),
            self._validation_future_stage(forecast),
            self._validation_constraint_stage(hits, forecast),
            self._validation_counterfactual_stage(rollout),
            self._validation_planning_stage(rollout),
            self._validation_deployability_stage(audit, evidence_items, review_tasks),
        ]
        blocking_gaps = [gap for stage in stages if stage.status in {"blocked", "review"} for gap in stage.gaps]
        overall_status = "pass" if all(stage.status == "pass" for stage in stages) else "review"
        if any(stage.status == "blocked" for stage in stages):
            overall_status = "blocked"
        report = TwmValidationReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            overall_status=overall_status,
            stages=stages,
            summary={
                "stage_count": len(stages),
                "passed_stage_count": sum(1 for stage in stages if stage.status == "pass"),
                "review_stage_count": sum(1 for stage in stages if stage.status == "review"),
                "blocked_stage_count": sum(1 for stage in stages if stage.status == "blocked"),
                "blocking_gaps": blocking_gaps,
                "validation_ladder": [
                    "state_build",
                    "future_state_prediction",
                    "constraint_prediction",
                    "counterfactual_rollout",
                    "planning_lift",
                    "gis_deployability",
                ],
            },
        )
        return report.to_dict()

    def world_model_profile(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        validation = self.validation_report(state_version_id, payload)
        audit = self.generate_audit_report(state_version_id)
        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        stage_status = {stage.get("stage_code"): stage.get("status") for stage in validation.get("stages", [])}
        quality_summary = dict(state.quality_summary or {})

        rendering_status = "pass" if state.object_count and state.relation_count else "review"
        simulation_status = "pass" if stage_status.get("future_state_prediction") == "pass" and stage_status.get("counterfactual_rollout") in {"pass", "review"} else "review"
        planning_status = "pass" if stage_status.get("planning_lift") == "pass" else "review"
        closed_loop_status = "pass" if stage_status.get("gis_deployability") == "pass" else "review"
        evidence_status = "pass" if audit.get("evidence_gate_passed") else "review"

        capabilities = [
            TwmWorldModelCapability(
                axis="rendering",
                status=rendering_status,
                interpretation=(
                    "TWM does not render photorealistic visual worlds; it renders GIS-operational world state "
                    "as hierarchical objects, relations, rule overlays and audit-ready map/table artifacts."
                ),
                core_algorithm={
                    "role_in_taxonomy": "renderer",
                    "algorithm_family": "structured GIS state renderer",
                    "core_algorithm": "MMFE semantic bundle -> hierarchical object-relation state construction -> rule/evidence overlay composition",
                    "current_implementation": [
                        "StateBuilder semantic ingestion",
                        "hierarchy token summarization",
                        "rule overlay assembly",
                        "audit-ready map/table state packaging",
                    ],
                    "note": "In Fei-Fei Li's sense this renderer emits structured territorial observations rather than RGB pixels.",
                },
                implemented_components=[
                    "state objects",
                    "state relations",
                    "hierarchy tokens",
                    "rule overlays",
                    "audit report inputs",
                ],
                evidence={
                    "object_count": state.object_count,
                    "relation_count": state.relation_count,
                    "object_counts_by_role": (state.summary or {}).get("object_counts_by_role", {}),
                    "relation_counts_by_type": (state.summary or {}).get("relation_counts_by_type", {}),
                },
                gaps=[
                    "photorealistic 3D/4D rendering is outside current TWM scope",
                    "cartographic front-end rendering is a consumer layer, not the world model core",
                ],
            ),
            TwmWorldModelCapability(
                axis="simulation",
                status=simulation_status,
                interpretation=(
                    "TWM simulation means action-conditioned rollout over territorial state, constraint state, "
                    "utility state and uncertainty, not only next-frame image prediction."
                ),
                core_algorithm={
                    "role_in_taxonomy": "simulator",
                    "algorithm_family": "action-conditioned territorial dynamics",
                    "core_algorithm": "multi-head forecast + counterfactual rollout over future_latent_state / constraint / utility / uncertainty, backed by deterministic scaffold, trainable MLP candidate, hierarchical graph-temporal candidate, or lightweight spatiotemporal transformer candidate",
                    "current_implementation": [
                        "deterministic forecast scaffold",
                        "counterfactual rollout",
                        "torch_multi_head_mlp candidate",
                        "torch_hierarchical_graph candidate with relation + temporal message mixing",
                        "torch_spatiotemporal_transformer candidate with fixed semantic token attention",
                    ],
                    "note": "The current trainable simulator includes small candidate backends, not yet the final production-scale territorial graph transformer.",
                },
                implemented_components=[
                    "future latent state forecast",
                    "constraint violation probability",
                    "counterfactual rollout",
                    "uncertainty and calibration metadata",
                ],
                evidence={
                    "future_state_stage": stage_status.get("future_state_prediction"),
                    "counterfactual_stage": stage_status.get("counterfactual_rollout"),
                    "quality_summary": quality_summary,
                },
                gaps=[
                    "only a small local neural trainable candidate is implemented; the final graph/transformer hierarchical dynamics backbone is still missing",
                    "temporal holdout validation is still required for simulation claims",
                ],
            ),
            TwmWorldModelCapability(
                axis="planning",
                status=planning_status,
                interpretation=(
                    "TWM planning is a consumer-facing capability: forecast and rollout outputs are consumed by "
                    "beam search, latent MPC or constrained rollout. The planner is not the world model itself."
                ),
                core_algorithm={
                    "role_in_taxonomy": "planner",
                    "algorithm_family": "constrained action ranking and rollout consumption",
                    "core_algorithm": "evidence-gated constrained beam search over candidate actions using planning_utility_delta - constraint_risk + confidence ranking, with action-mask filtering and optional dynamics candidate consumption",
                    "current_implementation": [
                        "beam-plan candidate ranking",
                        "action-mask gating",
                        "counterfactual baseline/intervention comparison",
                        "validation-ladder planning lift check",
                    ],
                    "note": "Latent MPC is still a target consumer architecture; the currently implemented planner core is constrained beam planning plus rollout comparison.",
                },
                implemented_components=[
                    "planning utility delta",
                    "baseline/intervention delta",
                    "beam-search planning facade",
                    "validation ladder planning lift stage",
                ],
                evidence={
                    "planning_lift_stage": stage_status.get("planning_lift"),
                    "rule_hit_count": len(hits),
                },
                gaps=[
                    "candidate ranking loss is not yet trained",
                    "hard action-mask search over target object sets is not yet implemented",
                ],
            ),
            TwmWorldModelCapability(
                axis="closed_loop",
                status=closed_loop_status,
                interpretation=(
                    "Following the renderer-simulator-planner loop, TWM closes the loop through GIS evidence, "
                    "rule review and audit reports rather than direct autonomous execution."
                ),
                implemented_components=[
                    "rule evaluation",
                    "evidence checksums",
                    "review tasks",
                    "audit report",
                    "validation report",
                ],
                evidence={
                    "gis_deployability_stage": stage_status.get("gis_deployability"),
                    "evidence_item_count": len(evidence_items),
                    "review_task_count": len(review_tasks),
                },
                gaps=[
                    "human review completion is required before administrative deployment",
                    "live GIS front-end feedback is still a downstream integration task",
                ],
            ),
            TwmWorldModelCapability(
                axis="evidence_provenance",
                status=evidence_status,
                interpretation=(
                    "TWM extends the functional taxonomy with a GIS governance axis: every forecast, rollout "
                    "and planning claim must be traceable to source data, rules, evidence and review state."
                ),
                implemented_components=[
                    "source manifest",
                    "evidence items",
                    "checksums",
                    "rule hit explanations",
                    "review tasks",
                ],
                evidence={
                    "evidence_gate_passed": audit.get("evidence_gate_passed"),
                    "evidence_gate_summary": audit.get("evidence_gate_summary", {}),
                },
                gaps=[] if evidence_status == "pass" else ["evidence gate did not pass for all current claims"],
            ),
        ]
        profile = TwmWorldModelProfile(
            state_version_id=state_version_id,
            project_id=state.project_id,
            taxonomy="fei_fei_li_functional_taxonomy_plus_gis_evidence",
            capabilities=capabilities,
            summary={
                "source_article": {
                    "title": "A Functional Taxonomy of World Models",
                    "author": "Fei-Fei Li",
                    "published_at": "2026-06-03",
                    "url": "https://drfeifei.substack.com/p/a-functional-taxonomy-of-world-models",
                    "note": "Article/blog essay, not a peer-reviewed paper.",
                },
                "capability_count": len(capabilities),
                "pass_count": sum(1 for item in capabilities if item.status == "pass"),
                "review_count": sum(1 for item in capabilities if item.status == "review"),
                "core_alignment": [
                    "renderer -> GIS-operational state rendering",
                    "simulator -> action-conditioned territorial rollout",
                    "planner -> constrained planning consumer",
                    "loop -> evidence-gated GIS review and audit loop",
                ],
            },
        )
        return profile.to_dict()

    def dynamics_training_examples(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        scenario = str(payload.get("scenario") or "dynamics_training").strip() or "dynamics_training"
        evidence_coverage = payload.get("evidence_coverage")
        horizon = int(payload.get("horizon") or 2)
        raw_actions = payload.get("actions")
        if not raw_actions:
            raw_actions = [
                {"action_type": "inspect", "target_role": "project", "magnitude": 1.0, "description": "baseline inspection"},
                {"action_type": "protect", "target_role": "project", "magnitude": 1.2, "description": "farmland protection intervention", "treatment": "causal_calibrated"},
                {"action_type": "expand", "target_role": "project", "magnitude": 1.4, "description": "development pressure stress test"},
            ]
        actions = [self._action_from_payload({"scenario": scenario, **dict(item)}) for item in raw_actions if isinstance(item, dict)]
        rule_hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        validation = self.validation_report(
            state_version_id,
            {
                "scenario": scenario,
                "horizon": horizon,
                "evidence_coverage": evidence_coverage,
                "scenario_context": dict(payload.get("scenario_context") or {}),
            },
        )
        source_transition_examples = self._temporal_transition_examples_from_state_snapshots(
            state=state,
            state_bundle=state_bundle,
            scenario=scenario,
            evidence_coverage=evidence_coverage,
            rule_hits=rule_hits,
            validation=validation,
            payload=payload,
        )
        current_state_summary = {
            "object_count": state.object_count,
            "relation_count": state.relation_count,
            "object_counts_by_role": (state.summary or {}).get("object_counts_by_role", {}),
            "relation_counts_by_type": (state.summary or {}).get("relation_counts_by_type", {}),
            "quality_summary": state.quality_summary,
            "hierarchy_tokens": self._state_hierarchy_tokens(state),
        }
        examples: list[TwmDynamicsTrainingExample] = []
        for idx, action in enumerate(actions):
            forecast = self.planner.forecast(
                {
                    "state_version": state,
                    "objects": state_bundle["objects"],
                    "relations": state_bundle["relations"],
                    "quality_summary": state.quality_summary,
                    "warnings": [],
                    "hierarchy_tokens": state.summary,
                },
                action,
                scenario=scenario,
                rule_hits=rule_hits,
                evidence_coverage=evidence_coverage,
                scenario_context=dict(payload.get("scenario_context") or {}),
            )
            action_mask = (forecast.evidence_gate or {}).get("action_mask") or {}
            not_for_training: list[str] = []
            if forecast.evidence_gate.get("status") != "pass":
                not_for_training.append("evidence_gate_not_passed")
            if validation.get("overall_status") != "pass":
                not_for_training.append("validation_report_not_fully_passed")
            if not evidence_items:
                not_for_training.append("no_evidence_items")
            if not action_mask.get("allowed", True):
                not_for_training.append("action_mask_blocks_execution")
            example = TwmDynamicsTrainingExample(
                state_version_id=state_version_id,
                project_id=state.project_id,
                split=str(payload.get("split") or "candidate"),
                sample_type="action_conditioned_forecast",
                current_state_summary=current_state_summary,
                action=action,
                scenario_context={
                    "scenario": scenario,
                    "horizon": horizon,
                    "scenario_context": dict(payload.get("scenario_context") or {}),
                    "temporal_holdout": self._temporal_holdout_policy(payload),
                },
                targets={
                    "future_latent_state": forecast.future_latent_state,
                    "constraint_violation_probability": forecast.constraint_violation_probability,
                    "planning_utility_delta": forecast.planning_utility_delta,
                    "uncertainty": forecast.uncertainty,
                    "calibration": forecast.calibration,
                    "action_mask": action_mask,
                },
                labels={
                    "constraint_label": "violation_likely" if forecast.constraint_violation_probability >= 0.5 else "violation_unlikely",
                    "utility_label": "positive_lift" if forecast.planning_utility_delta > 0 else "non_positive_lift",
                    "ranking_score": round(forecast.planning_utility_delta - forecast.constraint_violation_probability, 4),
                    "evidence_supported": forecast.evidence_gate.get("status") == "pass",
                    "supervision_source": "deterministic_scaffold",
                },
                losses={
                    "transition_loss": "future_latent_state",
                    "constraint_loss": "constraint_violation_probability",
                    "planning_ranking_loss": "ranking_score",
                    "calibration_loss": "calibration.calibrated_utility_delta",
                    "uncertainty_calibration_loss": "uncertainty.confidence",
                    "evidence_consistency_loss": "evidence_gate.status",
                    "action_mask_loss": "targets.action_mask.allowed",
                },
                evidence_gate=forecast.evidence_gate,
                provenance={
                    "state_version_id": state_version_id,
                    "rule_hit_count": len(rule_hits),
                    "evidence_item_count": len(evidence_items),
                    "validation_overall_status": validation.get("overall_status"),
                    "sample_index": idx,
                    "sample_family": "forecast_scaffold",
                    "ground_truth": False,
                },
                not_for_training_reasons=not_for_training,
            )
            examples.append(example)
        examples.extend(source_transition_examples)
        examples.sort(key=lambda item: item.labels.get("ranking_score", 0.0), reverse=True)
        dataset = TwmDynamicsTrainingDataset(
            state_version_id=state_version_id,
            project_id=state.project_id,
            examples=examples,
            summary={
                "example_count": len(examples),
                "forecast_scaffold_example_count": sum(1 for item in examples if item.sample_type == "action_conditioned_forecast"),
                "temporal_transition_example_count": sum(1 for item in examples if item.sample_type == "temporal_state_transition"),
                "usable_example_count": sum(1 for item in examples if not item.not_for_training_reasons),
                "review_example_count": sum(1 for item in examples if item.not_for_training_reasons),
                "temporal_holdout": self._temporal_holdout_policy(payload),
                "top_action": examples[0].action.to_dict() if examples else {},
                "loss_contract": {
                    "transition_loss": "predict observed/synthetic future latent state from hierarchical current state and action",
                    "constraint_loss": "predict future constraint state and violation probability",
                    "planning_ranking_loss": "rank candidate actions by downstream utility minus constraint risk",
                    "calibration_loss": "calibrate utility and scenario scale with causal/treatment evidence",
                    "uncertainty_calibration_loss": "align uncertainty with observed error and evidence coverage",
                    "evidence_consistency_loss": "penalize unsupported claim upgrades",
                    "action_mask_loss": "learn infeasible or review-required action regions",
                },
                "supervision_sources": {
                    "deterministic_scaffold": sum(1 for item in examples if item.labels.get("supervision_source") == "deterministic_scaffold"),
                    "state_snapshots": sum(1 for item in examples if item.labels.get("supervision_source") == "state_snapshots"),
                },
                "schema_notes": [
                    "This is a training-data contract for future trainable dynamics.",
                    "Forecast scaffold targets are generated by deterministic TWM logic and must not be treated as ground truth labels.",
                    "Temporal transition targets from state_snapshots are usable only within their provenance flags; synthetic or not_for_production rows remain review-only.",
                    "Use evidence_gate and validation status to decide whether a sample can supervise a claim.",
                ],
            },
        )
        return dataset.to_dict()

    def dynamics_readiness_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        thresholds = self._dynamics_readiness_thresholds(payload)
        sample_inventory = self._dynamics_sample_inventory(dataset)
        gate_results = self._dynamics_readiness_gates(
            state_version_id=state_version_id,
            dataset=dataset,
            inventory=sample_inventory,
            thresholds=thresholds,
            payload=payload,
        )
        status = self._dynamics_readiness_status(gate_results)
        training_scope = self._dynamics_training_scope(gate_results)
        recommendations = self._dynamics_readiness_recommendations(
            inventory=sample_inventory,
            gate_results=gate_results,
            thresholds=thresholds,
        )
        report = TwmDynamicsReadinessReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=status,
            training_scope=training_scope,
            sample_inventory=sample_inventory,
            thresholds=thresholds,
            gate_results=gate_results,
            target_model_contract=self._dynamics_target_model_contract(dataset, gate_results),
            recommendations=recommendations,
        )
        return report.to_dict()

    def dynamics_evaluation_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
        candidate = self._dynamics_candidate_descriptor(payload)
        predictions = self._dynamics_predictions_for_evaluation(dataset, payload)
        metrics, target_head_metrics, eval_inventory = self._dynamics_evaluation_metrics(dataset, predictions)
        evidence_gate = self._dynamics_evaluation_gate(
            readiness=readiness,
            candidate=candidate,
            metrics=metrics,
            eval_inventory=eval_inventory,
            payload=payload,
        )
        status = "pass" if evidence_gate.get("passed") else "review"
        if evidence_gate.get("blocked"):
            status = "blocked"
        report = TwmDynamicsEvaluationReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=status,
            candidate=candidate,
            evaluation_scope={
                "readiness_status": readiness.get("status"),
                "readiness_training_scope": readiness.get("training_scope"),
                "split": payload.get("split") or "holdout",
                "prediction_source": "payload_predictions" if payload.get("predictions") else "deterministic_scaffold_baseline",
            },
            metrics=metrics,
            target_head_metrics=target_head_metrics,
            evidence_gate=evidence_gate,
            sample_inventory=eval_inventory,
            recommendations=self._dynamics_evaluation_recommendations(evidence_gate, candidate, eval_inventory),
        )
        return report.to_dict()

    def fit_dynamics_candidate(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
        candidate = self._fit_candidate_descriptor(payload)
        if readiness.get("status") != "pass":
            evidence_gate = {
                "passed": False,
                "blocked": True,
                "status": "blocked",
                "missing": ["readiness_pass"],
            }
            report = TwmDynamicsFitReport(
                state_version_id=state_version_id,
                project_id=state.project_id,
                status="blocked",
                candidate=candidate,
                readiness=readiness,
                learned_parameters={},
                predictions={},
                evaluation={},
                evidence_gate=evidence_gate,
                recommendations=[
                    "dynamics candidate fitting is blocked until readiness gate passes",
                    "provide observed temporal holdout examples and reduce scaffold/review-only dependence",
                ],
            )
            return report.to_dict()

        learned_parameters = self._fit_baseline_dynamics_parameters(dataset)
        predictions = self._predict_with_baseline_dynamics(dataset, learned_parameters)
        evaluation_payload = {
            "dataset": dataset,
            "predictions": predictions,
            "candidate": candidate,
            "thresholds": payload.get("thresholds") or {},
            "evaluation_thresholds": payload.get("evaluation_thresholds") or {},
            "geofm_gate_report": payload.get("geofm_gate_report") or {},
            "causal_calibration_report": payload.get("causal_calibration_report") or {},
        }
        evaluation = self.dynamics_evaluation_report(state_version_id, evaluation_payload)
        evidence_gate = {
            "passed": evaluation.get("status") == "pass",
            "blocked": evaluation.get("status") == "blocked",
            "status": evaluation.get("status", "review"),
            "missing": list((evaluation.get("evidence_gate") or {}).get("missing") or []),
        }
        report = TwmDynamicsFitReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=evidence_gate["status"],
            candidate=candidate,
            readiness=readiness,
            learned_parameters=learned_parameters,
            predictions=predictions,
            evaluation=evaluation,
            evidence_gate=evidence_gate,
            recommendations=self._fit_dynamics_recommendations(evidence_gate, learned_parameters),
        )
        return report.to_dict()

    def geofm_ablation_gate(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")

        thresholds = self._geofm_gate_thresholds(payload)
        vector_inventory = self._geofm_vector_inventory(state)
        scenario = str(payload.get("scenario") or "geofm_b0_b1_gate").strip() or "geofm_b0_b1_gate"
        evidence_coverage = payload.get("evidence_coverage")
        if evidence_coverage is None:
            evidence_coverage = (state.quality_summary or {}).get("evidence_coverage")

        baseline_metrics = self._variant_metrics_from_payload(payload.get("baseline_metrics"))
        augmented_metrics = self._variant_metrics_from_payload(payload.get("augmented_metrics") or payload.get("geofm_metrics"))
        if not baseline_metrics or not augmented_metrics:
            inferred = self._infer_geofm_gate_metrics(
                state=state,
                state_bundle=state_bundle,
                scenario=scenario,
                evidence_coverage=evidence_coverage,
                vector_inventory=vector_inventory,
                payload=payload,
            )
            baseline_metrics = baseline_metrics or inferred["baseline_metrics"]
            augmented_metrics = augmented_metrics or inferred["augmented_metrics"]

        baseline_gate = self._variant_evidence_gate(
            uses_geofm=False,
            metrics=baseline_metrics,
            vector_inventory=vector_inventory,
            evidence_coverage=evidence_coverage,
            thresholds=thresholds,
        )
        augmented_gate = self._variant_evidence_gate(
            uses_geofm=True,
            metrics=augmented_metrics,
            vector_inventory=vector_inventory,
            evidence_coverage=evidence_coverage,
            thresholds=thresholds,
        )
        deltas = self._geofm_metric_deltas(baseline_metrics, augmented_metrics)
        gate_status, decision, recommendations = self._geofm_gate_decision(
            deltas=deltas,
            baseline_gate=baseline_gate,
            augmented_gate=augmented_gate,
            thresholds=thresholds,
            vector_inventory=vector_inventory,
            explicit_metrics=bool(payload.get("baseline_metrics") and (payload.get("augmented_metrics") or payload.get("geofm_metrics"))),
        )

        report = TwmGeoFMGateReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            gate_status=gate_status,
            decision=decision,
            baseline=TwmGeoFMGateVariant(
                variant_id="B0",
                label="GIS-only hierarchical state",
                uses_geofm=False,
                metrics=baseline_metrics,
                evidence_gate=baseline_gate,
                provenance={
                    "state_version_id": state_version_id,
                    "source": "payload_or_deterministic_twm",
                    "geofm_used": False,
                },
            ),
            augmented=TwmGeoFMGateVariant(
                variant_id="B1",
                label="GIS state plus gated GeoFM embedding",
                uses_geofm=True,
                metrics=augmented_metrics,
                evidence_gate=augmented_gate,
                provenance={
                    "state_version_id": state_version_id,
                    "source": "payload_or_deterministic_twm",
                    "geofm_used": True,
                    "vector_inventory": vector_inventory,
                },
            ),
            deltas=deltas,
            thresholds=thresholds,
            evidence={
                "vector_inventory": vector_inventory,
                "evidence_coverage": evidence_coverage,
                "rule_hit_count": len(self.repository.list_rule_hits(state_version_id=state_version_id)),
                "note": "GeoFM is retained only when downstream planning lift and evidence gates pass.",
            },
            recommendations=recommendations,
        )
        return report.to_dict()

    def causal_calibration_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")

        treatment_name = str(payload.get("treatment") or payload.get("treatment_name") or "planning_intervention")
        outcome_name = str(payload.get("outcome") or payload.get("outcome_name") or "planning_utility_delta")
        records, record_source = self._causal_records_for_calibration(state_version_id, payload)
        thresholds = self._causal_calibration_thresholds(payload)
        estimate = self._estimate_observational_treatment_effect(records, thresholds=thresholds)
        model_effect = safe_float(payload.get("model_effect"), None)
        if model_effect is None:
            model_effect = self._model_effect_from_rollout(state_version_id, payload)
        calibration = self._causal_calibration_from_estimate(estimate, model_effect)
        evidence_gate = self._causal_evidence_gate(
            records=records,
            estimate=estimate,
            calibration=calibration,
            thresholds=thresholds,
            record_source=record_source,
        )
        recommendations = self._causal_calibration_recommendations(evidence_gate, estimate, calibration, record_source)
        status = "pass" if evidence_gate.get("status") == "pass" else "review"
        if evidence_gate.get("blocked"):
            status = "blocked"

        report = TwmCausalCalibrationReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=status,
            treatment={
                "name": treatment_name,
                "positive_label": payload.get("positive_label", 1),
                "assignment": "observational",
            },
            outcome={
                "name": outcome_name,
                "direction": str(payload.get("outcome_direction") or "higher_better"),
            },
            estimate=estimate,
            calibration=calibration,
            evidence_gate=evidence_gate,
            provenance={
                "state_version_id": state_version_id,
                "record_source": record_source,
                "record_count": len(records),
                "rule_hit_count": len(self.repository.list_rule_hits(state_version_id=state_version_id)),
                "method_note": "primary estimator comes from the local causal calibration backend and remains observational rather than randomized identification",
            },
            recommendations=recommendations,
        )
        return report.to_dict()

    def _scenario_context_with_causal_calibration(
        self,
        state_version_id: str,
        payload: dict[str, Any],
        scenario_context: dict[str, Any],
    ) -> dict[str, Any]:
        if "causal_calibration" in scenario_context or "causal_calibration_report" in scenario_context:
            return scenario_context
        explicit_report = payload.get("causal_calibration_report")
        if isinstance(explicit_report, dict):
            scenario_context["causal_calibration"] = explicit_report
            return scenario_context
        calibration_payload = payload.get("causal_calibration")
        if not isinstance(calibration_payload, dict):
            return scenario_context
        nested_payload = dict(calibration_payload)
        nested_payload.setdefault("scenario", payload.get("scenario"))
        nested_payload.setdefault("evidence_coverage", payload.get("evidence_coverage"))
        nested_payload.pop("causal_calibration", None)
        nested_payload.pop("causal_calibration_report", None)
        report = self.causal_calibration_report(state_version_id, nested_payload)
        scenario_context["causal_calibration"] = report
        return scenario_context

    def _validation_state_stage(self, state: TwmStateVersion, state_bundle: dict[str, Any]) -> TwmValidationStage:
        object_count = int(state.object_count or len(state_bundle.get("objects") or []))
        relation_count = int(state.relation_count or len(state_bundle.get("relations") or []))
        quality_summary = dict(state.quality_summary or {})
        gaps: list[str] = []
        if object_count <= 0:
            gaps.append("state has no objects")
        if relation_count <= 0:
            gaps.append("state has no relations")
        if state.build_status != "ready":
            gaps.append(f"state build_status is {state.build_status}")
        if quality_summary.get("not_for_production_object_count"):
            gaps.append("state contains not_for_production objects")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="state_build",
            stage_name="State Build Integrity",
            status=status,
            claim="Layer inputs have been converted into a computable hierarchical object-relation state.",
            evidence={
                "object_count": object_count,
                "relation_count": relation_count,
                "build_status": state.build_status,
                "quality_summary": quality_summary,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["repair state source bindings or semantic bundle quality flags"],
        )

    def _validation_future_stage(self, forecast_payload: dict[str, Any]) -> TwmValidationStage:
        forecast = forecast_payload.get("forecast") or {}
        latent = forecast.get("future_latent_state") or {}
        projected = latent.get("projected") or {}
        uncertainty = forecast.get("uncertainty") or {}
        gaps: list[str] = []
        if not latent:
            gaps.append("future_latent_state head is missing")
        if not projected.get("object_counts_by_role"):
            gaps.append("projected object counts are missing")
        if float(uncertainty.get("confidence") or 0.0) < 0.35:
            gaps.append("forecast confidence is below evidence gate threshold")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="future_state_prediction",
            stage_name="Future State Prediction",
            status=status,
            claim="TWM produced an action-conditioned future latent state head.",
            evidence={
                "future_latent_schema": latent.get("schema"),
                "projected": projected,
                "uncertainty": uncertainty,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["collect temporal holdout labels and calibrate future-state prediction"],
        )

    def _validation_constraint_stage(self, hits: list[TwmRuleHit], forecast_payload: dict[str, Any]) -> TwmValidationStage:
        forecast = forecast_payload.get("forecast") or {}
        probability = float(forecast.get("constraint_violation_probability") or 0.0)
        severity_distribution: dict[str, int] = {}
        for hit in hits:
            severity_distribution[hit.severity] = severity_distribution.get(hit.severity, 0) + 1
        gaps: list[str] = []
        if not hits:
            gaps.append("no rule evaluation hits are available for constraint validation")
        if probability >= 0.8:
            gaps.append("constraint violation probability is high")
        if severity_distribution.get("blocking") or severity_distribution.get("critical"):
            gaps.append("blocking or critical rule hits remain open")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="constraint_prediction",
            stage_name="Constraint Prediction",
            status=status,
            claim="TWM generated a constraint-risk head tied to current rule evaluation evidence.",
            evidence={
                "rule_hit_count": len(hits),
                "severity_distribution": severity_distribution,
                "constraint_violation_probability": probability,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["resolve high-severity rule hits or recalibrate constraint head"],
        )

    def _validation_counterfactual_stage(self, rollout: dict[str, Any]) -> TwmValidationStage:
        evidence_gate = dict(rollout.get("evidence_gate") or {})
        calibration_summary = dict(rollout.get("calibration_summary") or {})
        gaps: list[str] = []
        if not rollout.get("baseline_steps") or not rollout.get("intervention_steps"):
            gaps.append("baseline or intervention rollout steps are missing")
        if evidence_gate.get("status") != "pass":
            gaps.append("counterfactual rollout evidence gate did not pass")
        if calibration_summary.get("calibration_required"):
            gaps.append("counterfactual calibration gap requires review")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="counterfactual_rollout",
            stage_name="Counterfactual Rollout",
            status=status,
            claim="Baseline and intervention actions were rolled out under the same scenario for counterfactual comparison.",
            evidence={
                "horizon": rollout.get("horizon"),
                "evidence_gate": evidence_gate,
                "calibration_summary": calibration_summary,
                "delta_final": (rollout.get("deltas") or {}).get("final", {}),
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["increase evidence coverage or connect treatment-effect calibration"],
        )

    def _validation_planning_stage(self, rollout: dict[str, Any]) -> TwmValidationStage:
        final = ((rollout.get("deltas") or {}).get("final") or {})
        lift = float(final.get("utility_delta_lift") or 0.0)
        risk_delta = float(final.get("constraint_probability_delta") or 0.0)
        confidence_delta = float(final.get("confidence_delta") or 0.0)
        gaps: list[str] = []
        if lift <= 0:
            gaps.append("intervention does not improve planning utility over baseline")
        if risk_delta > 0:
            gaps.append("intervention increases constraint risk")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="planning_lift",
            stage_name="Planning Lift",
            status=status,
            claim="The intervention arm is compared against baseline on utility, risk and confidence deltas.",
            evidence={
                "utility_delta_lift": lift,
                "constraint_probability_delta": risk_delta,
                "confidence_delta": confidence_delta,
                "claim_status": (rollout.get("summary") or {}).get("claim_status"),
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["run candidate ranking or constrained beam search before claiming planning lift"],
        )

    def _validation_deployability_stage(
        self,
        audit: dict[str, Any],
        evidence_items: list[Any],
        review_tasks: list[Any],
    ) -> TwmValidationStage:
        evidence_gate = dict(audit.get("evidence_gate_summary") or {})
        gaps: list[str] = []
        if not evidence_items:
            gaps.append("no evidence items are attached")
        if not evidence_gate.get("all_have_checksum"):
            gaps.append("not all evidence items have checksum")
        pending_reviews = sum(1 for task in review_tasks if getattr(task, "status", "") == "pending")
        if pending_reviews:
            gaps.append(f"{pending_reviews} review tasks are still pending")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="gis_deployability",
            stage_name="GIS Deployability And Audit",
            status=status,
            claim="Outputs are tied to GIS evidence items, checksums and human review tasks.",
            evidence={
                "audit_report_type": audit.get("report_type"),
                "evidence_item_count": len(evidence_items),
                "evidence_gate_summary": evidence_gate,
                "review_task_count": len(review_tasks),
                "pending_review_count": pending_reviews,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["complete review tasks and checksum missing evidence before deployment"],
        )

    def _action_target_summary(self, action: TerritoryWorldModelAction, objects: list[TwmStateObject]) -> dict[str, Any]:
        requested = [str(item) for item in action.target_objects or [] if str(item)]
        role = action.target_role or ""
        role_objects = [
            obj for obj in objects
            if not role or role in {obj.canonical_role, obj.source_role, obj.object_type}
        ]
        index: dict[str, TwmStateObject] = {}
        for obj in objects:
            for key in (obj.id, obj.object_code, obj.source_feature_id):
                if key:
                    index[str(key)] = obj
        matched = []
        missing = []
        if requested:
            for key in requested:
                obj = index.get(key)
                if obj is None:
                    missing.append(key)
                    continue
                if role and role not in {obj.canonical_role, obj.source_role, obj.object_type}:
                    missing.append(key)
                    continue
                matched.append(obj)
        else:
            matched = role_objects
        return {
            "target_role": role,
            "requested_target_count": len(requested),
            "matched_target_count": len(matched),
            "role_target_count": len(role_objects),
            "missing_target_objects": missing,
            "target_scope_valid": bool(matched) and not missing,
            "matched_object_ids": [obj.id for obj in matched],
            "matched_object_codes": [obj.object_code for obj in matched[:25]],
            "spatial_scope": action.spatial_scope,
        }

    def _action_related_rule_hits(
        self,
        action: TerritoryWorldModelAction,
        target_summary: dict[str, Any],
        hits: list[TwmRuleHit],
    ) -> list[TwmRuleHit]:
        target_ids = set(target_summary.get("matched_object_ids") or [])
        if not target_ids:
            return []
        related = [
            hit for hit in hits
            if hit.subject_object_id in target_ids or (hit.target_object_id and hit.target_object_id in target_ids)
        ]
        if action.action_type.lower() in {"protect", "mitigate", "constrain", "review", "inspect"}:
            return related
        return [hit for hit in related if hit.severity in {"high", "critical", "blocking", "medium"}]

    def _mask_hit_payload(self, hit: TwmRuleHit) -> dict[str, Any]:
        return {
            "rule_hit_id": hit.id,
            "rule_id": hit.rule_id,
            "severity": hit.severity,
            "risk_score": hit.risk_score,
            "hit_status": hit.hit_status,
            "subject_object_id": hit.subject_object_id,
            "target_object_id": hit.target_object_id,
            "explanation": hit.explanation,
        }

    def _blocking_severities_for_action(self, action: TerritoryWorldModelAction) -> set[str]:
        action_type = (action.action_type or "").lower()
        high_risk_terms = ("convert", "expand", "relocate", "develop", "construct", "add")
        if any(term in action_type for term in high_risk_terms):
            return {"blocking", "critical", "high"}
        return {"blocking", "critical"}

    def _forecast_with_dynamics_candidate(self, plan_payload: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        candidate_report = self._candidate_report_from_payload(payload)
        if not candidate_report:
            return plan_payload
        forecast = dict(plan_payload.get("forecast") or {})
        gate = self._dynamics_candidate_forecast_gate(candidate_report, payload)
        base_gate = dict(forecast.get("evidence_gate") or {})
        base_missing = list(base_gate.get("missing") or [])
        for item in gate.get("missing") or []:
            if item not in base_missing:
                base_missing.append(item)
        candidate_summary = {
            "schema": candidate_report.get("schema", ""),
            "status": candidate_report.get("status", ""),
            "candidate": dict(candidate_report.get("candidate") or {}),
            "source": "dynamics_candidate_report",
        }
        if gate.get("passed"):
            prediction = self._select_candidate_prediction(candidate_report, payload)
            if prediction:
                self._apply_candidate_prediction_to_forecast(forecast, prediction, candidate_summary)
                candidate_summary["prediction_applied"] = True
            else:
                gate["passed"] = False
                gate["status"] = "review"
                gate.setdefault("missing", []).append("candidate_prediction")
                candidate_summary["prediction_applied"] = False
        else:
            candidate_summary["prediction_applied"] = False
        base_gate["dynamics_candidate"] = candidate_summary | {
            "gate": gate,
        }
        base_gate["missing"] = base_missing
        base_gate["passed"] = bool(base_gate.get("passed")) and bool(gate.get("passed"))
        base_gate["status"] = "pass" if base_gate.get("passed") else "review"
        forecast["evidence_gate"] = base_gate
        plan_payload["forecast"] = forecast
        summary = dict(plan_payload.get("summary") or {})
        summary["evidence_gate"] = base_gate
        summary["dynamics_candidate"] = candidate_summary
        plan_payload["summary"] = summary
        metrics = list(plan_payload.get("candidate_metrics") or [])
        for metric in metrics:
            if metric.get("metric_code") == "planning_utility_delta":
                metric["value"] = forecast.get("planning_utility_delta", metric.get("value"))
            elif metric.get("metric_code") == "constraint_violation_probability":
                metric["value"] = forecast.get("constraint_violation_probability", metric.get("value"))
            elif metric.get("metric_code") == "uncertainty":
                metric["value"] = (forecast.get("uncertainty") or {}).get("confidence", metric.get("value"))
        plan_payload["candidate_metrics"] = metrics
        return plan_payload

    def _counterfactual_with_dynamics_candidate(self, rollout_payload: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if not self._candidate_report_from_payload(payload):
            return rollout_payload
        for arm_key in ("baseline_steps", "intervention_steps"):
            updated_steps = []
            for step in rollout_payload.get(arm_key) or []:
                if not isinstance(step, dict):
                    updated_steps.append(step)
                    continue
                plan_like = {
                    "forecast": dict(step.get("forecast") or {}),
                    "summary": {"evidence_gate": (step.get("forecast") or {}).get("evidence_gate", {})},
                    "candidate_metrics": [],
                }
                step_payload = dict(payload)
                step_payload["dynamics_prediction_id"] = self._rollout_prediction_id(step)
                adapted = self._forecast_with_dynamics_candidate(plan_like, step_payload)
                forecast = dict(adapted.get("forecast") or {})
                step["forecast"] = forecast
                step["metrics"] = self._rollout_step_metrics_from_forecast(forecast)
                updated_steps.append(step)
            rollout_payload[arm_key] = updated_steps
        rollout_payload["deltas"] = self._rollout_delta_dicts(
            rollout_payload.get("baseline_steps") or [],
            rollout_payload.get("intervention_steps") or [],
        )
        rollout_payload["evidence_gate"] = self._rollout_evidence_gate_dicts(
            rollout_payload.get("baseline_steps") or [],
            rollout_payload.get("intervention_steps") or [],
        )
        rollout_payload["calibration_summary"] = self._rollout_calibration_summary_dicts(
            rollout_payload.get("baseline_steps") or [],
            rollout_payload.get("intervention_steps") or [],
        )
        summary = dict(rollout_payload.get("summary") or {})
        baseline_steps = rollout_payload.get("baseline_steps") or []
        intervention_steps = rollout_payload.get("intervention_steps") or []
        summary["baseline_final"] = (baseline_steps[-1].get("metrics") if baseline_steps else {}) or {}
        summary["intervention_final"] = (intervention_steps[-1].get("metrics") if intervention_steps else {}) or {}
        summary["planning_lift"] = (rollout_payload.get("deltas") or {}).get("final", {}).get("utility_delta_lift", 0.0)
        summary["risk_delta"] = (rollout_payload.get("deltas") or {}).get("final", {}).get("constraint_probability_delta", 0.0)
        gate = dict(rollout_payload.get("evidence_gate") or {})
        summary["claim_status"] = "claim_supported" if gate.get("passed") and summary.get("planning_lift", 0.0) > 0 else "review_required"
        summary["dynamics_candidate_applied"] = any(
            (((step.get("forecast") or {}).get("evidence_gate") or {}).get("dynamics_candidate") or {}).get("prediction_applied")
            for step in baseline_steps + intervention_steps
            if isinstance(step, dict)
        )
        rollout_payload["summary"] = summary
        return rollout_payload

    def _copy_dynamics_candidate_payload(self, source: dict[str, Any], target: dict[str, Any]) -> None:
        for key in (
            "dynamics_candidate_report",
            "dynamics_fit_report",
            "fit_report",
            "dynamics_candidate",
            "dynamics_candidate_prediction",
            "dynamics_prediction_id",
            "dynamics_candidate_required_status",
            "allow_review_dynamics_candidate",
        ):
            if key in source:
                target[key] = source[key]

    def _rollout_prediction_id(self, step: dict[str, Any]) -> str:
        explicit = step.get("prediction_id")
        if explicit:
            return str(explicit)
        arm = str(step.get("arm") or "")
        idx = step.get("step_index")
        return f"{arm}:{idx}" if arm or idx is not None else ""

    def _rollout_step_metrics_from_forecast(self, forecast: dict[str, Any]) -> dict[str, Any]:
        uncertainty = dict(forecast.get("uncertainty") or {})
        evidence_gate = dict(forecast.get("evidence_gate") or {})
        return {
            "constraint_violation_probability": float(safe_float(forecast.get("constraint_violation_probability"), 0.0) or 0.0),
            "planning_utility_delta": float(safe_float(forecast.get("planning_utility_delta"), 0.0) or 0.0),
            "confidence": float(safe_float(uncertainty.get("confidence"), 0.0) or 0.0),
            "calibration_gap": float(safe_float(uncertainty.get("calibration_gap"), 0.0) or 0.0),
            "evidence_gate_status": evidence_gate.get("status", "review"),
        }

    def _rollout_delta_dicts(self, baseline_steps: list[dict[str, Any]], intervention_steps: list[dict[str, Any]]) -> dict[str, Any]:
        by_step = []
        for base, inter in zip(baseline_steps, intervention_steps):
            base_metrics = dict(base.get("metrics") or {})
            inter_metrics = dict(inter.get("metrics") or {})
            by_step.append(
                {
                    "step_index": base.get("step_index", 0),
                    "utility_delta_lift": round(float(safe_float(inter_metrics.get("planning_utility_delta"), 0.0) or 0.0) - float(safe_float(base_metrics.get("planning_utility_delta"), 0.0) or 0.0), 4),
                    "constraint_probability_delta": round(float(safe_float(inter_metrics.get("constraint_violation_probability"), 0.0) or 0.0) - float(safe_float(base_metrics.get("constraint_violation_probability"), 0.0) or 0.0), 4),
                    "confidence_delta": round(float(safe_float(inter_metrics.get("confidence"), 0.0) or 0.0) - float(safe_float(base_metrics.get("confidence"), 0.0) or 0.0), 4),
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

    def _rollout_evidence_gate_dicts(self, baseline_steps: list[dict[str, Any]], intervention_steps: list[dict[str, Any]]) -> dict[str, Any]:
        gates = [((step.get("forecast") or {}).get("evidence_gate") or {}) for step in baseline_steps + intervention_steps if isinstance(step, dict)]
        missing: list[str] = []
        for gate in gates:
            for item in gate.get("missing") or []:
                if item not in missing:
                    missing.append(item)
        passed = bool(gates) and all(bool(gate.get("passed")) for gate in gates)
        coverages = [float(safe_float(gate.get("coverage"), 0.0) or 0.0) for gate in gates]
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "missing": missing,
            "min_coverage": round(min(coverages), 4) if coverages else 0.0,
            "step_count": len(gates),
        }

    def _rollout_calibration_summary_dicts(self, baseline_steps: list[dict[str, Any]], intervention_steps: list[dict[str, Any]]) -> dict[str, Any]:
        all_steps = baseline_steps + intervention_steps
        gaps = [float(safe_float((step.get("metrics") or {}).get("calibration_gap"), 0.0) or 0.0) for step in all_steps]
        treatment_effects = [
            float(safe_float(((step.get("forecast") or {}).get("calibration") or {}).get("treatment_effect"), 0.0) or 0.0)
            for step in all_steps
        ]
        return {
            "max_calibration_gap": round(max(gaps, default=0.0), 4),
            "mean_treatment_effect": round(sum(treatment_effects) / max(1, len(treatment_effects)), 4),
            "calibration_required": any(gap > 0.2 for gap in gaps),
            "support": {
                "baseline_steps": len(baseline_steps),
                "intervention_steps": len(intervention_steps),
            },
        }

    def _beam_candidate_from_forecast(self, idx: int, action_payload: dict[str, Any], forecast_plan: dict[str, Any]) -> dict[str, Any]:
        forecast = dict(forecast_plan.get("forecast") or {})
        evidence_gate = dict(forecast.get("evidence_gate") or {})
        uncertainty = dict(forecast.get("uncertainty") or {})
        utility = float(safe_float(forecast.get("planning_utility_delta"), 0.0) or 0.0)
        risk = float(safe_float(forecast.get("constraint_violation_probability"), 0.0) or 0.0)
        confidence = float(safe_float(uncertainty.get("confidence"), 0.0) or 0.0)
        action_mask = dict(evidence_gate.get("action_mask") or {})
        blocked = (
            evidence_gate.get("status") == "blocked"
            or bool(action_mask.get("hard_blocks"))
            or not action_mask.get("allowed", True)
        )
        rank_score = round(utility - risk + confidence * 0.1, 6)
        if blocked:
            rank_score = round(rank_score - 1.0, 6)
        if evidence_gate.get("status") != "pass":
            rank_score = round(rank_score - 0.15, 6)
        return {
            "candidate_id": str(action_payload.get("candidate_id") or action_payload.get("id") or f"candidate:{idx}"),
            "rank": None,
            "action": {
                "action_type": action_payload.get("action_type") or "inspect",
                "target_role": action_payload.get("target_role") or "project",
                "target_objects": list(action_payload.get("target_objects") or []),
                "magnitude": action_payload.get("magnitude") or 1.0,
                "scenario": action_payload.get("scenario") or "beam_plan",
            },
            "forecast": forecast,
            "utility": round(utility, 6),
            "risk": round(risk, 6),
            "confidence": round(confidence, 6),
            "rank_score": rank_score,
            "evidence_gate": evidence_gate,
            "claim_status": "claim_supported" if evidence_gate.get("status") == "pass" and not blocked else "review_required",
        }

    def _beam_evidence_gate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        missing: list[str] = []
        statuses = []
        for candidate in candidates:
            gate = dict(candidate.get("evidence_gate") or {})
            statuses.append(gate.get("status", "review"))
            for item in gate.get("missing") or []:
                if item not in missing:
                    missing.append(item)
        passed_candidates = sum(1 for candidate in candidates if candidate.get("claim_status") == "claim_supported")
        return {
            "passed": bool(candidates) and passed_candidates > 0,
            "status": "pass" if candidates and passed_candidates > 0 else "review",
            "missing": missing,
            "candidate_count": len(candidates),
            "claim_supported_count": passed_candidates,
            "candidate_statuses": statuses,
        }

    def _beam_plan_recommendations(self, candidates: list[dict[str, Any]], evidence_gate: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []
        if not candidates:
            return ["provide at least one candidate action for beam planning"]
        if evidence_gate.get("status") != "pass":
            recommendations.append("treat beam result as review-only until at least one candidate passes evidence gate")
        if any((((candidate.get("evidence_gate") or {}).get("action_mask") or {}).get("hard_blocks")) for candidate in candidates):
            recommendations.append("remove or mitigate hard-blocked candidate actions before deployment")
        if any((((candidate.get("evidence_gate") or {}).get("dynamics_candidate") or {}).get("gate") or {}).get("status") != "pass" for candidate in candidates if ((candidate.get("evidence_gate") or {}).get("dynamics_candidate"))):
            recommendations.append("do not let review/blocked dynamics candidates drive planning rank")
        recommendations.append("validate selected candidate with counterfactual rollout before operational GIS deployment")
        return recommendations

    def _candidate_report_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        backend_report = payload.get("dynamics_backend_report")
        if isinstance(backend_report, dict):
            adapted = self._candidate_report_from_backend_report(backend_report)
            if adapted:
                return adapted
        for key in ("dynamics_candidate_report", "fit_report", "dynamics_fit_report"):
            report = payload.get(key)
            if isinstance(report, dict):
                return dict(report)
        candidate = payload.get("dynamics_candidate")
        if isinstance(candidate, dict):
            return {
                "schema": "territory_world_model.external_dynamics_candidate.v1",
                "status": candidate.get("status") or "review",
                "candidate": dict(candidate.get("candidate") or candidate.get("metadata") or {}),
                "learned_parameters": dict(candidate.get("learned_parameters") or {}),
                "predictions": dict(candidate.get("predictions") or {}),
                "evaluation": dict(candidate.get("evaluation") or {}),
                "evidence_gate": dict(candidate.get("evidence_gate") or {}),
            }
        return {}

    def _candidate_report_from_backend_report(self, backend_report: dict[str, Any]) -> dict[str, Any]:
        adapter = dict(backend_report.get("adapter_contract") or {})
        candidate = dict(adapter.get("candidate_report") or {})
        if not candidate:
            return {}
        evidence_gate = dict(backend_report.get("evidence_gate") or {})
        report_status = str(backend_report.get("status") or "review")
        candidate["status"] = "pass" if report_status == "pass" and evidence_gate.get("status") == "pass" else report_status
        candidate["evidence_gate"] = evidence_gate
        candidate["schema"] = candidate.get("schema") or "territory_world_model.dynamics_backend_candidate.v1"
        return candidate

    def _dynamics_backend_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        backend = dict(payload.get("backend") or payload.get("dynamics_backend") or {})
        candidate_report = self._raw_backend_candidate_report(payload)
        backend_type = str(backend.get("backend_type") or backend.get("type") or ("external_candidate" if candidate_report else "deterministic_scaffold"))
        return {
            "backend_id": str(backend.get("backend_id") or backend.get("id") or backend.get("model_name") or backend_type),
            "backend_type": backend_type,
            "model_name": str(backend.get("model_name") or (candidate_report.get("candidate") or {}).get("model_name") or backend_type),
            "model_version": str(backend.get("model_version") or (candidate_report.get("candidate") or {}).get("model_version") or "unversioned"),
            "model_family": str(backend.get("model_family") or (candidate_report.get("candidate") or {}).get("model_family") or "action_conditioned_dynamics"),
            "trainable": bool(backend.get("trainable", backend_type not in {"deterministic_scaffold", "hierarchical_baseline"})),
            "action_conditioned": bool(backend.get("action_conditioned", True)),
            "uses_geofm": bool(backend.get("uses_geofm", (candidate_report.get("candidate") or {}).get("uses_geofm", False))),
            "uses_causal_calibration": bool(backend.get("uses_causal_calibration", (candidate_report.get("candidate") or {}).get("uses_causal_calibration", True))),
            "is_scaffold_baseline": backend_type in {"deterministic_scaffold", "hierarchical_baseline"} or bool((candidate_report.get("candidate") or {}).get("is_scaffold_baseline", False)),
            "metadata": dict(backend.get("metadata") or {}),
        }

    def _raw_backend_candidate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("candidate_report", "dynamics_candidate_report", "fit_report", "dynamics_fit_report"):
            value = payload.get(key)
            if isinstance(value, dict):
                return dict(value)
        candidate = payload.get("dynamics_candidate")
        if isinstance(candidate, dict):
            return {
                "schema": "territory_world_model.external_dynamics_candidate.v1",
                "status": candidate.get("status") or "review",
                "candidate": dict(candidate.get("candidate") or candidate.get("metadata") or {}),
                "predictions": dict(candidate.get("predictions") or {}),
                "learned_parameters": dict(candidate.get("learned_parameters") or {}),
                "evaluation": dict(candidate.get("evaluation") or {}),
                "evidence_gate": dict(candidate.get("evidence_gate") or {}),
            }
        return {}

    def _dynamics_backend_input_contract(self, state_contract: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
        hierarchy = dict(state_contract.get("hierarchy") or {})
        claim = dict(state_contract.get("claim_boundary") or {})
        return {
            "schema": "territory_world_model.dynamics_backend_input_contract.v1",
            "required_inputs": ["current_state", "action", "scenario"],
            "state_contract_status": state_contract.get("status", "review"),
            "state_claim_scope": claim.get("claim_scope", ""),
            "hierarchy_required_levels": [item.get("level") for item in hierarchy.get("tokens") or [] if item.get("required")],
            "missing_required_levels": list(hierarchy.get("missing_required_levels") or []),
            "review_required_levels": list(hierarchy.get("review_required_levels") or []),
            "action_conditioned": bool(backend.get("action_conditioned")),
            "flat_vector_allowed": False,
        }

    def _dynamics_backend_output_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_report = self._raw_backend_candidate_report(payload)
        predictions = dict(candidate_report.get("predictions") or payload.get("predictions") or {})
        head_counts = {
            "future_latent_state": 0,
            "constraint_violation_probability": 0,
            "planning_utility_delta": 0,
            "uncertainty": 0,
            "calibration": 0,
            "action_mask": 0,
        }
        for prediction in predictions.values():
            if not isinstance(prediction, dict):
                continue
            for head in head_counts:
                if head in prediction:
                    head_counts[head] += 1
        required_heads = ["future_latent_state", "constraint_violation_probability", "planning_utility_delta", "uncertainty"]
        return {
            "schema": "territory_world_model.dynamics_backend_output_contract.v1",
            "required_heads": required_heads,
            "optional_heads": ["calibration", "action_mask"],
            "prediction_count": len(predictions),
            "head_coverage": head_counts,
            "multi_head_ready": bool(predictions) and all(head_counts[head] > 0 for head in required_heads),
            "must_predict": "p(next_state, constraint_state, utility_state | current_state, action, scenario)",
        }

    def _dynamics_backend_adapter_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_report = self._raw_backend_candidate_report(payload)
        predictions = dict(candidate_report.get("predictions") or payload.get("predictions") or {})
        return {
            "schema": "territory_world_model.dynamics_backend_adapter_contract.v1",
            "adapter": "candidate_report_forecast_adapter",
            "forecast_consumable": bool(candidate_report and predictions),
            "candidate_report": candidate_report,
            "supported_consumers": ["forecast", "counterfactual_rollout", "beam_plan", "validation_report"],
            "prediction_selection": ["dynamics_prediction_id", "example_id", "action_type", "first_prediction"],
        }

    def _dynamics_backend_gate_results(
        self,
        *,
        backend: dict[str, Any],
        state_contract: dict[str, Any],
        readiness: dict[str, Any],
        input_contract: dict[str, Any],
        output_contract: dict[str, Any],
        adapter_contract: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_report = self._raw_backend_candidate_report(payload)
        candidate_gate = self._dynamics_candidate_forecast_gate(candidate_report, payload) if candidate_report else {"passed": False, "status": "review", "missing": ["candidate_report"]}
        gates = {
            "state_contract": {
                "passed": state_contract.get("status") in {"pass", "review"},
                "status": state_contract.get("status", "review"),
                "claim_scope": (state_contract.get("claim_boundary") or {}).get("claim_scope"),
            },
            "readiness": {
                "passed": readiness.get("status") == "pass",
                "status": readiness.get("status", "review"),
                "training_scope": readiness.get("training_scope", ""),
            },
            "action_conditioned": {
                "passed": bool(input_contract.get("action_conditioned")),
                "value": bool(input_contract.get("action_conditioned")),
            },
            "multi_head_output": {
                "passed": bool(output_contract.get("multi_head_ready")),
                "head_coverage": dict(output_contract.get("head_coverage") or {}),
            },
            "forecast_adapter": {
                "passed": bool(adapter_contract.get("forecast_consumable")),
                "adapter": adapter_contract.get("adapter", ""),
            },
            "candidate_gate": candidate_gate,
            "non_scaffold_backend": {
                "passed": not bool(backend.get("is_scaffold_baseline")),
                "is_scaffold_baseline": bool(backend.get("is_scaffold_baseline")),
            },
        }
        if backend.get("uses_geofm"):
            geofm_gate = (readiness.get("gate_results") or {}).get("geofm_gate") or {}
            gates["geofm_gate"] = {
                "passed": geofm_gate.get("status") == "pass" or not geofm_gate.get("required", False),
                "status": geofm_gate.get("status", "review"),
            }
        if backend.get("uses_causal_calibration"):
            causal_gate = (readiness.get("gate_results") or {}).get("causal_calibration") or {}
            gates["causal_calibration"] = {
                "passed": causal_gate.get("status") == "pass" or not causal_gate.get("required", False),
                "status": causal_gate.get("status", "review"),
            }
        required = ["state_contract", "readiness", "action_conditioned", "multi_head_output", "forecast_adapter", "candidate_gate", "non_scaffold_backend"]
        if backend.get("uses_geofm"):
            required.append("geofm_gate")
        if backend.get("uses_causal_calibration"):
            required.append("causal_calibration")
        blocked = [name for name in required if not gates[name].get("passed")]
        gates["summary"] = {
            "blocked_gates": blocked,
            "claim_boundary": "forecast_consumable_backend" if not blocked else "adapter_or_review_only",
            "backend_ready": not blocked,
        }
        return gates

    def _dynamics_backend_evidence_gate(self, gate_results: dict[str, Any], backend: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
        blocked = list((gate_results.get("summary") or {}).get("blocked_gates") or [])
        hard = {"state_contract", "action_conditioned", "multi_head_output", "forecast_adapter", "candidate_gate"}
        status = "pass" if not blocked else "blocked" if any(item in hard for item in blocked) else "review"
        missing = []
        for item in blocked:
            if item not in missing:
                missing.append(item)
        return {
            "passed": not blocked,
            "blocked": status == "blocked",
            "status": status,
            "missing": missing,
            "backend_id": backend.get("backend_id", ""),
            "readiness_status": readiness.get("status", "review"),
        }

    def _dynamics_backend_claim_boundary(self, gate_results: dict[str, Any], backend: dict[str, Any], evidence_gate: dict[str, Any]) -> dict[str, Any]:
        status = "pass" if evidence_gate.get("status") == "pass" else "blocked" if evidence_gate.get("status") == "blocked" else "review"
        return {
            "status": status,
            "claim_scope": "backend_can_drive_forecast_rollout_and_beam" if status == "pass" else "backend_review_only" if status == "review" else "backend_not_consumable",
            "allowed_claims": [
                "backend_contract_checked",
                "candidate_report_adapter_available",
            ]
            + (["forecast_backend_candidate"] if status == "pass" else []),
            "disallowed_claims": [
                "production_ready_world_model",
                "ungated_trainable_dynamics",
            ]
            + (["trainable_backend"] if backend.get("is_scaffold_baseline") else []),
            "blocked_gates": list((gate_results.get("summary") or {}).get("blocked_gates") or []),
        }

    def _dynamics_backend_recommendations(self, gate_results: dict[str, Any], evidence_gate: dict[str, Any], backend: dict[str, Any]) -> list[str]:
        blocked = set((gate_results.get("summary") or {}).get("blocked_gates") or [])
        recommendations: list[str] = []
        if "state_contract" in blocked:
            recommendations.append("fix hierarchical state contract before attaching a dynamics backend")
        if "readiness" in blocked:
            recommendations.append("use backend outputs as review-only until dynamics readiness passes")
        if "action_conditioned" in blocked:
            recommendations.append("backend must condition predictions on current_state, action and scenario")
        if "multi_head_output" in blocked:
            recommendations.append("backend must output future_latent_state, constraint_violation_probability, planning_utility_delta and uncertainty")
        if "forecast_adapter" in blocked or "candidate_gate" in blocked:
            recommendations.append("provide a passed candidate report with forecast-consumable prediction ids")
        if "non_scaffold_backend" in blocked:
            recommendations.append("do not claim trainable dynamics from a deterministic scaffold or transparent baseline alone")
        if backend.get("uses_geofm") and "geofm_gate" in blocked:
            recommendations.append("keep GeoFM features gated until downstream planning lift passes")
        if backend.get("uses_causal_calibration") and "causal_calibration" in blocked:
            recommendations.append("attach a passing causal calibration report before upgrading counterfactual utility claims")
        if not recommendations:
            recommendations.append("backend is forecast-consumable; validate it through counterfactual rollout and beam planning before deployment")
        return recommendations

    def _training_objective_predictions(
        self,
        dataset: dict[str, Any],
        payload: dict[str, Any],
        backend_report: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        explicit_predictions = payload.get("predictions")
        if isinstance(explicit_predictions, dict):
            return {str(key): dict(value) for key, value in explicit_predictions.items() if isinstance(value, dict)}
        candidate_report = self._candidate_report_from_backend_report(backend_report)
        if candidate_report:
            return dict(candidate_report.get("predictions") or {})
        return self._dynamics_predictions_for_evaluation(dataset, payload)

    def _training_objective_contract(self, dataset: dict[str, Any], backend_report: dict[str, Any]) -> dict[str, Any]:
        summary = dict(dataset.get("summary") or {})
        backend = dict(backend_report.get("backend") or {})
        return {
            "schema": "territory_world_model.training_objective_contract.v1",
            "loss_contract": dict(summary.get("loss_contract") or {}),
            "backend_status": backend_report.get("status", "review"),
            "backend_id": backend.get("backend_id") or backend.get("model_name") or "",
            "backend_type": backend.get("backend_type", ""),
            "multi_head_required": [
                "future_latent_state",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty",
                "calibration",
                "action_mask",
            ],
            "training_claim": "review_only" if backend_report.get("status") != "pass" else "objective_contract_ready",
        }

    def _training_objective_loss_components(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        total = len(examples)
        transition_count = 0
        constraint_count = 0
        utility_count = 0
        uncertainty_count = 0
        calibration_count = 0
        evidence_supported_count = 0
        action_mask_count = 0
        for example in examples:
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            labels = dict(example.get("labels") or {})
            pred = dict(predictions.get(example_id) or {})
            if targets.get("future_latent_state") and pred.get("future_latent_state"):
                transition_count += 1
            if "constraint_violation_probability" in targets and "constraint_violation_probability" in pred:
                constraint_count += 1
            if "planning_utility_delta" in targets and "planning_utility_delta" in pred:
                utility_count += 1
            if (targets.get("uncertainty") or {}).get("confidence") is not None and (pred.get("uncertainty") or {}).get("confidence") is not None:
                uncertainty_count += 1
            if targets.get("calibration") and pred.get("calibration"):
                calibration_count += 1
            if labels.get("evidence_supported") is True:
                evidence_supported_count += 1
            if targets.get("action_mask") and pred.get("action_mask"):
                action_mask_count += 1
        transition_loss = float(metrics.get("mean_transition_error") or 0.0)
        constraint_loss = float(metrics.get("mean_constraint_error") or 0.0)
        utility_loss = float(metrics.get("mean_utility_error") or 0.0)
        ranking_loss = round(max(0.0, 1.0 - float(metrics.get("ranking_correlation_proxy") or 0.0)), 6)
        uncertainty_loss = self._training_objective_uncertainty_loss(dataset, predictions)
        calibration_loss = self._training_objective_calibration_loss(dataset, predictions)
        evidence_loss = round(max(0.0, 1.0 - (evidence_supported_count / max(1, total))), 6) if total else None
        action_mask_loss = None
        if action_mask_count:
            accuracy = metrics.get("action_mask_accuracy")
            action_mask_loss = round(max(0.0, 1.0 - float(accuracy or 0.0)), 6) if accuracy is not None else None
        return {
            "transition_loss": {
                "value": round(transition_loss, 6) if transition_count else None,
                "coverage": transition_count,
                "coverage_ratio": round(transition_count / max(1, total), 4) if total else 0.0,
                "weight": 1.0,
            },
            "constraint_loss": {
                "value": round(constraint_loss, 6) if constraint_count else None,
                "coverage": constraint_count,
                "coverage_ratio": round(constraint_count / max(1, total), 4) if total else 0.0,
                "weight": 1.0,
            },
            "planning_ranking_loss": {
                "value": ranking_loss if utility_count else None,
                "coverage": utility_count,
                "coverage_ratio": round(utility_count / max(1, total), 4) if total else 0.0,
                "weight": 1.2,
            },
            "calibration_loss": {
                "value": calibration_loss,
                "coverage": calibration_count,
                "coverage_ratio": round(calibration_count / max(1, total), 4) if total else 0.0,
                "weight": 0.8,
            },
            "uncertainty_calibration_loss": {
                "value": uncertainty_loss,
                "coverage": uncertainty_count,
                "coverage_ratio": round(uncertainty_count / max(1, total), 4) if total else 0.0,
                "weight": 0.8,
            },
            "evidence_consistency_loss": {
                "value": evidence_loss,
                "coverage": total,
                "coverage_ratio": 1.0 if total else 0.0,
                "weight": 0.6,
            },
            "action_mask_loss": {
                "value": action_mask_loss,
                "coverage": action_mask_count,
                "coverage_ratio": round(action_mask_count / max(1, total), 4) if total else 0.0,
                "weight": 0.9,
            },
        }

    def _training_objective_uncertainty_loss(self, dataset: dict[str, Any], predictions: dict[str, dict[str, Any]]) -> float | None:
        diffs: list[float] = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            target_uncertainty = dict(targets.get("uncertainty") or {})
            pred_uncertainty = dict((predictions.get(example_id) or {}).get("uncertainty") or {})
            if "confidence" not in target_uncertainty or "confidence" not in pred_uncertainty:
                continue
            diffs.append(abs(float(safe_float(pred_uncertainty.get("confidence"), 0.0) or 0.0) - float(safe_float(target_uncertainty.get("confidence"), 0.0) or 0.0)))
        return round(self._mean(diffs), 6) if diffs else None

    def _training_objective_calibration_loss(self, dataset: dict[str, Any], predictions: dict[str, dict[str, Any]]) -> float | None:
        diffs: list[float] = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            pred = dict(predictions.get(example_id) or {})
            target_cal = dict(targets.get("calibration") or {})
            pred_cal = dict(pred.get("calibration") or {})
            target_value = safe_float(target_cal.get("calibrated_utility_delta"), None)
            if target_value is None:
                target_value = safe_float(target_cal.get("observed_transition_proxy"), None)
            pred_value = safe_float(pred_cal.get("calibrated_utility_delta"), None)
            if target_value is None or pred_value is None:
                continue
            diffs.append(abs(float(pred_value) - float(target_value)))
        return round(self._mean(diffs), 6) if diffs else None

    def _training_objective_ranking_diagnostics(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        pairs = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            labels = dict(example.get("labels") or {})
            prediction = dict(predictions.get(example_id) or {})
            utility = safe_float(prediction.get("planning_utility_delta"), None)
            rank = safe_float(labels.get("ranking_score"), None)
            if utility is None or rank is None:
                continue
            pairs.append(
                {
                    "example_id": example_id,
                    "predicted_utility": round(float(utility), 6),
                    "target_ranking_score": round(float(rank), 6),
                    "delta": round(float(utility) - float(rank), 6),
                }
            )
        pairs.sort(key=lambda item: abs(item["delta"]), reverse=True)
        return {
            "ranking_correlation_proxy": metrics.get("ranking_correlation_proxy"),
            "pair_count": len(pairs),
            "largest_mismatches": pairs[:5],
            "objective": "maximize planning utility while preserving ranking consistency against target_ranking_score",
        }

    def _training_objective_calibration_diagnostics(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        rows = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            pred = dict(predictions.get(example_id) or {})
            target_cal = dict(targets.get("calibration") or {})
            pred_cal = dict(pred.get("calibration") or {})
            target_value = safe_float(target_cal.get("calibrated_utility_delta"), None)
            if target_value is None:
                target_value = safe_float(target_cal.get("observed_transition_proxy"), None)
            pred_value = safe_float(pred_cal.get("calibrated_utility_delta"), None)
            if target_value is None or pred_value is None:
                continue
            rows.append(abs(float(pred_value) - float(target_value)))
        return {
            "mean_absolute_calibration_gap": round(self._mean(rows), 6) if rows else None,
            "calibration_pair_count": len(rows),
            "objective": "align calibrated utility with observed_transition_proxy or calibrated_utility_delta targets",
        }

    def _training_objective_evidence_gate(
        self,
        backend_report: dict[str, Any],
        objective_contract: dict[str, Any],
        loss_components: dict[str, Any],
    ) -> dict[str, Any]:
        missing = []
        backend_status = str(backend_report.get("status") or "review")
        if backend_status != "pass":
            missing.append("backend_pass")
        for key in ("transition_loss", "constraint_loss", "planning_ranking_loss"):
            component = dict(loss_components.get(key) or {})
            if component.get("value") is None or int(component.get("coverage") or 0) == 0:
                missing.append(key)
        status = "pass" if not missing else "review"
        return {
            "passed": not missing,
            "status": status,
            "missing": missing,
            "backend_status": backend_status,
            "training_claim": objective_contract.get("training_claim", "review_only"),
        }

    def _training_objective_recommendations(
        self,
        loss_components: dict[str, Any],
        evidence_gate: dict[str, Any],
        backend_report: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        if evidence_gate.get("status") != "pass":
            recommendations.append("treat the training objective as review-only until a passed dynamics backend is attached")
        for key, text in (
            ("transition_loss", "increase observed future-state labels for transition supervision"),
            ("constraint_loss", "expand constraint-state labels and high-risk rule coverage"),
            ("planning_ranking_loss", "add candidate ranking labels and counterfactual planning comparisons"),
            ("calibration_loss", "connect calibration targets to causal or observed transition evidence"),
            ("uncertainty_calibration_loss", "record prediction confidence against observed error to calibrate uncertainty"),
        ):
            component = dict(loss_components.get(key) or {})
            if component.get("value") is None or int(component.get("coverage") or 0) == 0:
                recommendations.append(text)
        if backend_report.get("status") == "pass":
            recommendations.append("use this objective report as the loss contract for the first trainable dynamics trainer")
        return recommendations

    def _dynamics_candidate_forecast_gate(self, candidate_report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        required_status = str(payload.get("dynamics_candidate_required_status") or "pass")
        report_status = str(candidate_report.get("status") or "")
        evidence_gate = dict(candidate_report.get("evidence_gate") or {})
        evaluation = dict(candidate_report.get("evaluation") or {})
        evaluation_gate = dict(evaluation.get("evidence_gate") or {})
        missing: list[str] = []
        if required_status == "pass" and report_status != "pass":
            missing.append("dynamics_candidate_pass")
        if evidence_gate and evidence_gate.get("status") not in {"pass", "passed", True}:
            missing.append("dynamics_candidate_evidence_gate")
        if evaluation and evaluation.get("status") != "pass":
            missing.append("dynamics_candidate_evaluation")
        if evaluation_gate and evaluation_gate.get("status") != "pass":
            missing.append("dynamics_candidate_evaluation_gate")
        allow_review = bool(payload.get("allow_review_dynamics_candidate", False))
        passed = not missing or (allow_review and report_status in {"review", "pass"})
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "missing": [] if passed else missing,
            "required_status": required_status,
            "report_status": report_status,
        }

    def _select_candidate_prediction(self, candidate_report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        explicit = payload.get("dynamics_candidate_prediction")
        if isinstance(explicit, dict):
            return dict(explicit)
        predictions = dict(candidate_report.get("predictions") or {})
        if not predictions:
            learned = dict(candidate_report.get("learned_parameters") or {})
            if learned:
                return self._prediction_from_learned_parameters_for_action(learned, payload)
            return {}
        key = str(payload.get("dynamics_prediction_id") or payload.get("example_id") or "")
        if key and isinstance(predictions.get(key), dict):
            return dict(predictions[key])
        if key:
            return {}
        candidate_id = str(payload.get("target_prediction_action_type") or payload.get("action_type") or "")
        for prediction in predictions.values():
            if not isinstance(prediction, dict):
                continue
            action = dict(prediction.get("action") or {})
            if candidate_id and str(action.get("action_type") or "") == candidate_id:
                return dict(prediction)
        first = next((item for item in predictions.values() if isinstance(item, dict)), {})
        return dict(first)

    def _prediction_from_learned_parameters_for_action(self, learned_parameters: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        action_type = str(payload.get("action_type") or "unknown")
        action_parameters = dict(learned_parameters.get("action_parameters") or {})
        params = dict(action_parameters.get(action_type) or learned_parameters.get("global_parameters") or {})
        if not params:
            return {}
        return {
            "future_latent_state": {
                "schema": "territory_world_model.predicted_latent_state.v1",
                "projected": {
                    "projected_risk_pressure": round(float(params.get("constraint_mean") or 0.0), 6),
                    "projected_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
                },
            },
            "constraint_violation_probability": round(float(params.get("constraint_mean") or 0.0), 6),
            "planning_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
            "uncertainty": {
                "confidence": round(float(params.get("confidence_mean") or 0.0), 6),
                "source": "hierarchical_baseline_dynamics_parameters",
            },
            "calibration": {
                "calibrated_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
                "source": "hierarchical_baseline_dynamics_parameters",
            },
        }

    def _apply_candidate_prediction_to_forecast(
        self,
        forecast: dict[str, Any],
        prediction: dict[str, Any],
        candidate_summary: dict[str, Any],
    ) -> None:
        if "future_latent_state" in prediction:
            candidate_latent = dict(prediction.get("future_latent_state") or {})
            base_latent = dict(forecast.get("future_latent_state") or {})
            base_latent["dynamics_candidate_projection"] = candidate_latent
            projected = dict(base_latent.get("projected") or {})
            candidate_projected = dict(candidate_latent.get("projected") or candidate_latent.get("observed_next") or {})
            if "projected_risk_pressure" in candidate_projected:
                projected["projected_risk_pressure"] = candidate_projected["projected_risk_pressure"]
            if "projected_utility_delta" in candidate_projected:
                projected["projected_utility_delta"] = candidate_projected["projected_utility_delta"]
            projected["dynamics_candidate_applied"] = True
            base_latent["projected"] = projected
            forecast["future_latent_state"] = base_latent
        if "constraint_violation_probability" in prediction:
            forecast["constraint_violation_probability"] = round(float(safe_float(prediction.get("constraint_violation_probability"), 0.0) or 0.0), 6)
        if "planning_utility_delta" in prediction:
            forecast["planning_utility_delta"] = round(float(safe_float(prediction.get("planning_utility_delta"), 0.0) or 0.0), 6)
        if "uncertainty" in prediction:
            forecast["uncertainty"] = dict(forecast.get("uncertainty") or {}) | dict(prediction.get("uncertainty") or {})
        if "calibration" in prediction:
            forecast["calibration"] = dict(forecast.get("calibration") or {}) | dict(prediction.get("calibration") or {})
        forecast["calibration"] = dict(forecast.get("calibration") or {}) | {
            "dynamics_backend": candidate_summary,
        }

    def _action_mask_confidence(
        self,
        *,
        target_summary: dict[str, Any],
        blocking_hits: list[dict[str, Any]],
        required_reviews: list[dict[str, Any]],
        missing_evidence_hits: list[str],
    ) -> float:
        confidence = 0.82
        if not target_summary.get("target_scope_valid"):
            confidence -= 0.35
        confidence -= min(0.3, len(blocking_hits) * 0.12)
        confidence -= min(0.2, len(required_reviews) * 0.04)
        confidence -= min(0.18, len(missing_evidence_hits) * 0.04)
        return round(max(0.0, min(1.0, confidence)), 4)

    def _causal_records_for_calibration(self, state_version_id: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        raw_records = payload.get("records") or payload.get("observations") or []
        if isinstance(raw_records, list) and raw_records:
            return [dict(item) for item in raw_records if isinstance(item, dict)], "payload_observations"

        dataset = self.dynamics_training_examples(
            state_version_id,
            {
                "scenario": payload.get("scenario") or "causal_calibration_scaffold",
                "evidence_coverage": payload.get("evidence_coverage"),
                "horizon": payload.get("horizon") or 2,
            },
        )
        records: list[dict[str, Any]] = []
        for idx, example in enumerate(dataset.get("examples") or []):
            if not isinstance(example, dict):
                continue
            labels = dict(example.get("labels") or {})
            action = dict(example.get("action") or {})
            targets = dict(example.get("targets") or {})
            ranking_score = safe_float(labels.get("ranking_score"), 0.0) or 0.0
            treatment = 1 if action.get("treatment") or action.get("action_type") in {"protect", "synthetic_transition", "observed_transition"} else 0
            records.append(
                {
                    "unit_id": example.get("id") or f"example:{idx}",
                    "treatment": treatment,
                    "outcome": ranking_score,
                    "model_effect": safe_float((targets.get("calibration") or {}).get("treatment_effect"), 0.0) or 0.0,
                    "stratum": example.get("sample_type") or "unknown",
                    "synthetic": "synthetic_temporal_transition" in (example.get("not_for_training_reasons") or []),
                    "not_for_production": bool(example.get("not_for_training_reasons")),
                    "source": labels.get("supervision_source") or "dynamics_training_examples",
                }
            )
        return records, "dynamics_training_examples_scaffold"

    def _causal_calibration_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("thresholds") or {})
        return {
            "min_records": int(raw.get("min_records", 8)),
            "min_treated": int(raw.get("min_treated", 3)),
            "min_control": int(raw.get("min_control", 3)),
            "max_standard_error": float(raw.get("max_standard_error", 0.25)),
            "min_overlap_ratio": float(raw.get("min_overlap_ratio", 0.8)),
            "max_abs_standardized_mean_difference": float(raw.get("max_abs_standardized_mean_difference", 0.35)),
            "min_propensity": float(raw.get("min_propensity", 0.05)),
            "max_neighbor_exposure_gap": float(raw.get("max_neighbor_exposure_gap", 0.35)),
            "max_spatial_cluster_treatment_gap": float(raw.get("max_spatial_cluster_treatment_gap", 0.45)),
            "max_spatial_residual_moran": float(raw.get("max_spatial_residual_moran", 0.35)),
            "spatial_neighbor_distance": safe_float(raw.get("spatial_neighbor_distance"), None),
            "min_evidence_coverage": float(raw.get("min_evidence_coverage", 0.55)),
            "allow_synthetic": bool(raw.get("allow_synthetic", False)),
            "allow_not_for_production": bool(raw.get("allow_not_for_production", False)),
            "calibration_factor_bounds": tuple(raw.get("calibration_factor_bounds", [0.1, 5.0])),
        }

    def _estimate_observational_treatment_effect(self, records: list[dict[str, Any]], *, thresholds: dict[str, Any]) -> dict[str, Any]:
        return estimate_observational_treatment_effect(records, thresholds=thresholds)

    def _causal_calibration_from_estimate(self, estimate: dict[str, Any], model_effect: float | None) -> dict[str, Any]:
        observed_effect = float(estimate.get("att") or 0.0)
        if model_effect is None:
            model_effect = estimate.get("mean_model_effect_from_records")
        if model_effect is None:
            model_effect = 0.0
        model_effect = float(model_effect or 0.0)
        if abs(model_effect) < 1e-9:
            factor = 1.0
            calibrated_effect = observed_effect
            status = "review"
        else:
            factor = observed_effect / model_effect
            factor = max(0.1, min(5.0, factor))
            calibrated_effect = model_effect * factor
            status = "pass"
        return {
            "model_effect": round(model_effect, 6),
            "observed_effect": round(observed_effect, 6),
            "calibration_factor": round(factor, 6),
            "calibrated_effect": round(calibrated_effect, 6),
            "utility_scale_adjustment": round(factor, 6),
            "scenario_scale_adjustment": round(1.0 + max(-0.5, min(0.5, observed_effect)), 6),
            "status": status,
        }

    def _causal_evidence_gate(
        self,
        *,
        records: list[dict[str, Any]],
        estimate: dict[str, Any],
        calibration: dict[str, Any],
        thresholds: dict[str, Any],
        record_source: str,
    ) -> dict[str, Any]:
        missing: list[str] = []
        if estimate.get("usable_record_count", 0) < thresholds["min_records"]:
            missing.append("min_records")
        if estimate.get("treated_count", 0) < thresholds["min_treated"]:
            missing.append("min_treated")
        if estimate.get("control_count", 0) < thresholds["min_control"]:
            missing.append("min_control")
        if float(estimate.get("standard_error") or 0.0) > thresholds["max_standard_error"]:
            missing.append("standard_error")
        overlap = dict(estimate.get("overlap") or {})
        if overlap.get("status") != "pass":
            missing.append("overlap")
        balance = dict(estimate.get("balance") or {})
        max_abs_smd = float(balance.get("max_abs_standardized_mean_difference") or 0.0)
        if balance.get("covariate_count", 0) and max_abs_smd > float(thresholds.get("max_abs_standardized_mean_difference") or 0.35):
            missing.append("covariate_balance")
        spatial = dict(estimate.get("spatial") or {})
        if spatial.get("status") == "review":
            missing.append("spatial_interference")
        if calibration.get("status") != "pass":
            missing.append("model_effect")
        synthetic_count = sum(1 for row in records if truthy(row.get("synthetic")))
        nfp_count = sum(1 for row in records if truthy(row.get("not_for_production")))
        if synthetic_count and not thresholds.get("allow_synthetic"):
            missing.append("synthetic_records")
        if nfp_count and not thresholds.get("allow_not_for_production"):
            missing.append("not_for_production_records")
        passed = not missing
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "blocked": False,
            "missing": missing,
            "record_source": record_source,
            "synthetic_record_count": synthetic_count,
            "not_for_production_record_count": nfp_count,
            "thresholds": thresholds,
        }

    def _causal_calibration_recommendations(
        self,
        evidence_gate: dict[str, Any],
        estimate: dict[str, Any],
        calibration: dict[str, Any],
        record_source: str,
    ) -> list[str]:
        recommendations: list[str] = []
        if evidence_gate.get("status") != "pass":
            recommendations.append("collect balanced treated/control observational records before upgrading causal planning claims")
        if "synthetic_records" in (evidence_gate.get("missing") or []):
            recommendations.append("do not use synthetic temporal transitions as causal ground truth without explicit validation")
        if "not_for_production_records" in (evidence_gate.get("missing") or []):
            recommendations.append("replace demo or not_for_production records with production evidence before deployment")
        if calibration.get("status") != "pass":
            recommendations.append("provide a non-zero model_effect or rollout-derived planning lift for calibration")
        if "overlap" in (evidence_gate.get("missing") or []):
            recommendations.append("improve treated/control overlap or provide propensity-aware observational data before using causal scaling")
        if "covariate_balance" in (evidence_gate.get("missing") or []):
            recommendations.append("reduce treated/control covariate imbalance or add better adjustment covariates before upgrading causal claims")
        if "spatial_interference" in (evidence_gate.get("missing") or []):
            recommendations.append("spatial spillover or clustered treatment concentration is too strong; add spatial adjustment or redefine causal units before upgrading claims")
        if record_source.endswith("scaffold"):
            recommendations.append("scaffold-derived calibration is review-only; use payload observations or a causal backend for claims")
        if abs(float(estimate.get("att") or 0.0)) < float(estimate.get("standard_error") or 0.0):
            recommendations.append("estimated treatment effect is not clearly separated from uncertainty")
        return recommendations

    def _model_effect_from_rollout(self, state_version_id: str, payload: dict[str, Any]) -> float | None:
        if not payload.get("baseline_action") and not payload.get("intervention_actions") and not payload.get("action_type"):
            return None
        rollout = self.counterfactual_rollout(
            state_version_id,
            {
                "scenario": payload.get("scenario") or "causal_calibration_rollout",
                "horizon": int(payload.get("horizon") or 2),
                "evidence_coverage": payload.get("evidence_coverage"),
                "baseline_action": payload.get("baseline_action") or {"action_type": "inspect", "target_role": payload.get("target_role") or "project"},
                "intervention_actions": payload.get("intervention_actions")
                or [
                    {
                        "action_type": payload.get("action_type") or "protect",
                        "target_role": payload.get("target_role") or "project",
                        "magnitude": payload.get("magnitude") or 1.0,
                        "treatment": payload.get("treatment") or "causal_calibrated",
                        "parameters": dict(payload.get("parameters") or {}),
                    }
                ],
                "scenario_context": dict(payload.get("scenario_context") or {}),
            },
        )
        return safe_float(((rollout.get("deltas") or {}).get("final") or {}).get("utility_delta_lift"), None)

    def _binary_treatment(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return 1 if value else 0
        if value in (0, 1):
            return int(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "treated", "intervention", "yes", "y"}:
            return 1
        if text in {"0", "false", "control", "baseline", "no", "n"}:
            return 0
        return None

    def _mean(self, values: list[float]) -> float:
        return sum(values) / max(1, len(values))

    def _geofm_gate_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("thresholds") or {})
        return {
            "min_planning_lift_delta": float(raw.get("min_planning_lift_delta", 0.03)),
            "max_constraint_risk_delta": float(raw.get("max_constraint_risk_delta", 0.02)),
            "min_confidence_delta": float(raw.get("min_confidence_delta", -0.02)),
            "min_evidence_coverage": float(raw.get("min_evidence_coverage", 0.55)),
            "require_explicit_downstream_metrics": bool(raw.get("require_explicit_downstream_metrics", True)),
            "allow_not_for_production_vectors": bool(raw.get("allow_not_for_production_vectors", False)),
        }

    def _variant_metrics_from_payload(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        metrics = dict(value)
        normalized = {
            "planning_lift": float(safe_float(metrics.get("planning_lift"), safe_float(metrics.get("planning_utility_delta"), 0.0)) or 0.0),
            "constraint_risk": float(safe_float(metrics.get("constraint_risk"), safe_float(metrics.get("constraint_violation_probability"), 0.0)) or 0.0),
            "confidence": float(safe_float(metrics.get("confidence"), 0.0) or 0.0),
            "calibration_gap": float(safe_float(metrics.get("calibration_gap"), 0.0) or 0.0),
            "ranking_score": float(safe_float(metrics.get("ranking_score"), 0.0) or 0.0),
        }
        for key, item in metrics.items():
            if key not in normalized:
                normalized[key] = item
        if not normalized["ranking_score"]:
            normalized["ranking_score"] = round(normalized["planning_lift"] - normalized["constraint_risk"], 4)
        normalized["source"] = metrics.get("source") or "explicit_downstream_evaluation"
        return normalized

    def _infer_geofm_gate_metrics(
        self,
        *,
        state: TwmStateVersion,
        state_bundle: dict[str, Any],
        scenario: str,
        evidence_coverage: float | None,
        vector_inventory: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        rule_hits = self.repository.list_rule_hits(state_version_id=state.id)
        base_action = self._action_from_payload(
            {
                "action_type": payload.get("action_type") or "protect",
                "target_role": payload.get("target_role") or "project",
                "magnitude": payload.get("magnitude") or 1.0,
                "scenario": scenario,
                "description": "B0 GIS-only ablation baseline",
                "legal_intent": "farmland protection compliance",
                "parameters": dict(payload.get("parameters") or {}),
            }
        )
        geofm_action = self._action_from_payload(
            {
                "action_type": payload.get("action_type") or "protect",
                "target_role": payload.get("target_role") or "project",
                "magnitude": payload.get("magnitude") or 1.0,
                "scenario": scenario,
                "description": "B1 GeoFM-augmented ablation candidate",
                "legal_intent": "farmland protection compliance",
                "parameters": {
                    **dict(payload.get("parameters") or {}),
                    "geofm_embedding_available": bool(vector_inventory.get("available")),
                    "geofm_record_count": vector_inventory.get("record_count", 0),
                },
            }
        )
        base_forecast = self.planner.forecast(
            {
                "state_version": state,
                "objects": state_bundle["objects"],
                "relations": state_bundle["relations"],
                "quality_summary": state.quality_summary,
                "warnings": [],
                "hierarchy_tokens": state.summary,
            },
            base_action,
            scenario=scenario,
            rule_hits=rule_hits,
            evidence_coverage=evidence_coverage,
            scenario_context=dict(payload.get("scenario_context") or {}),
        )
        geofm_context = dict(payload.get("scenario_context") or {})
        # Availability alone gives only a small candidate prior; explicit downstream
        # metrics are still required before the gate can retain GeoFM.
        if vector_inventory.get("available"):
            geofm_context["observed_treatment_effect"] = float(geofm_context.get("observed_treatment_effect") or 0.0) + 0.015
        geofm_forecast = self.planner.forecast(
            {
                "state_version": state,
                "objects": state_bundle["objects"],
                "relations": state_bundle["relations"],
                "quality_summary": state.quality_summary,
                "warnings": [],
                "hierarchy_tokens": state.summary | {"geofm_vector_inventory": vector_inventory},
            },
            geofm_action,
            scenario=scenario,
            rule_hits=rule_hits,
            evidence_coverage=evidence_coverage,
            scenario_context=geofm_context,
        )
        return {
            "baseline_metrics": self._metrics_from_forecast(base_forecast, source="deterministic_b0_forecast"),
            "augmented_metrics": self._metrics_from_forecast(geofm_forecast, source="deterministic_b1_candidate_prior"),
        }

    def _metrics_from_forecast(self, forecast: TerritoryWorldModelForecast, *, source: str) -> dict[str, Any]:
        planning_lift = float(forecast.planning_utility_delta or 0.0)
        constraint_risk = float(forecast.constraint_violation_probability or 0.0)
        confidence = float((forecast.uncertainty or {}).get("confidence") or 0.0)
        return {
            "planning_lift": round(planning_lift, 4),
            "constraint_risk": round(constraint_risk, 4),
            "confidence": round(confidence, 4),
            "calibration_gap": round(float((forecast.uncertainty or {}).get("calibration_gap") or 0.0), 4),
            "ranking_score": round(planning_lift - constraint_risk, 4),
            "source": source,
        }

    def _variant_evidence_gate(
        self,
        *,
        uses_geofm: bool,
        metrics: dict[str, Any],
        vector_inventory: dict[str, Any],
        evidence_coverage: float | None,
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []
        coverage = float(safe_float(evidence_coverage, 0.0) or 0.0)
        if coverage < float(thresholds["min_evidence_coverage"]):
            missing.append("evidence_coverage")
        if uses_geofm and not vector_inventory.get("available"):
            missing.append("geofm_vectors")
        if uses_geofm and vector_inventory.get("not_for_production") and not thresholds.get("allow_not_for_production_vectors"):
            missing.append("geofm_vectors_not_for_production")
        if not metrics:
            missing.append("downstream_metrics")
        passed = not missing
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "missing": missing,
            "coverage": round(coverage, 4),
            "uses_geofm": uses_geofm,
        }

    def _geofm_metric_deltas(self, baseline: dict[str, Any], augmented: dict[str, Any]) -> dict[str, Any]:
        planning_delta = float(augmented.get("planning_lift") or 0.0) - float(baseline.get("planning_lift") or 0.0)
        risk_delta = float(augmented.get("constraint_risk") or 0.0) - float(baseline.get("constraint_risk") or 0.0)
        confidence_delta = float(augmented.get("confidence") or 0.0) - float(baseline.get("confidence") or 0.0)
        ranking_delta = float(augmented.get("ranking_score") or 0.0) - float(baseline.get("ranking_score") or 0.0)
        calibration_gap_delta = float(augmented.get("calibration_gap") or 0.0) - float(baseline.get("calibration_gap") or 0.0)
        return {
            "planning_lift_delta": round(planning_delta, 4),
            "constraint_risk_delta": round(risk_delta, 4),
            "confidence_delta": round(confidence_delta, 4),
            "ranking_score_delta": round(ranking_delta, 4),
            "calibration_gap_delta": round(calibration_gap_delta, 4),
        }

    def _geofm_gate_decision(
        self,
        *,
        deltas: dict[str, Any],
        baseline_gate: dict[str, Any],
        augmented_gate: dict[str, Any],
        thresholds: dict[str, Any],
        vector_inventory: dict[str, Any],
        explicit_metrics: bool,
    ) -> tuple[str, str, list[str]]:
        recommendations: list[str] = []
        if not explicit_metrics and thresholds.get("require_explicit_downstream_metrics"):
            recommendations.append("run explicit B0/B1 downstream planning evaluation before retaining GeoFM")
        if not vector_inventory.get("available"):
            recommendations.append("publish or bind GeoFM/MMFE semantic vector inventory before B1 evaluation")
        if augmented_gate.get("missing"):
            recommendations.append("resolve B1 evidence gaps before using GeoFM in the default dynamics path")

        lift_ok = float(deltas.get("planning_lift_delta") or 0.0) >= float(thresholds["min_planning_lift_delta"])
        risk_ok = float(deltas.get("constraint_risk_delta") or 0.0) <= float(thresholds["max_constraint_risk_delta"])
        confidence_ok = float(deltas.get("confidence_delta") or 0.0) >= float(thresholds["min_confidence_delta"])
        gates_ok = baseline_gate.get("status") == "pass" and augmented_gate.get("status") == "pass"
        explicit_ok = explicit_metrics or not thresholds.get("require_explicit_downstream_metrics")

        if gates_ok and explicit_ok and lift_ok and risk_ok and confidence_ok:
            return "pass", "retain_geofm_for_downstream_planning", recommendations

        if explicit_ok and gates_ok and (not lift_ok or not risk_ok):
            recommendations.append("gate out GeoFM for this task until it improves planning lift without increasing constraint risk")
            return "blocked", "gate_out_geofm", recommendations

        return "review", "review_required", recommendations

    def _geofm_vector_inventory(self, state: TwmStateVersion) -> dict[str, Any]:
        bundle_root = self._state_bundle_root(state)
        if bundle_root is None:
            return {"available": False, "record_count": 0, "path": ""}
        candidates = [
            bundle_root / "twm_mmfe_semantic_vectors.pgvector.json",
            bundle_root.parent / "mmfe_semantic_fusion" / "twm_mmfe_semantic_vectors.pgvector.json",
        ]
        path = next((item for item in candidates if item.exists()), None)
        if path is None:
            return {"available": False, "record_count": 0, "path": ""}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"available": False, "record_count": 0, "path": str(path), "read_error": True}
        records = data.get("records") if isinstance(data, dict) else []
        if not isinstance(records, list):
            records = []
        not_for_production = any(bool((item.get("metadata") or {}).get("not_for_production")) for item in records if isinstance(item, dict))
        synthetic_count = sum(1 for item in records if isinstance(item, dict) and bool((item.get("metadata") or {}).get("synthetic")))
        return {
            "available": bool(records),
            "path": str(path),
            "schema": data.get("schema", "") if isinstance(data, dict) else "",
            "collection": data.get("collection", "") if isinstance(data, dict) else "",
            "embedding_model": data.get("embedding_model", "") if isinstance(data, dict) else "",
            "embedding_required": bool(data.get("embedding_required")) if isinstance(data, dict) else False,
            "record_count": len(records),
            "synthetic_record_count": synthetic_count,
            "not_for_production": not_for_production,
        }

    def _temporal_transition_examples_from_state_snapshots(
        self,
        *,
        state: TwmStateVersion,
        state_bundle: dict[str, Any],
        scenario: str,
        evidence_coverage: float | None,
        rule_hits: Iterable[TwmRuleHit],
        validation: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[TwmDynamicsTrainingExample]:
        bundle_root = self._state_bundle_root(state)
        if bundle_root is None:
            return []
        snapshots_path = self._find_auxiliary_table(bundle_root, "state_snapshots.csv")
        if snapshots_path is None:
            return []
        try:
            rows = read_csv(snapshots_path)
        except Exception:
            return []
        if not rows:
            return []

        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            year = safe_int(row.get("snapshot_year"), -1)
            if year < 0:
                continue
            grouped.setdefault(year, []).append(row)
        years = sorted(grouped)
        if len(years) < 2:
            return []

        examples: list[TwmDynamicsTrainingExample] = []
        holdout_policy = self._temporal_holdout_policy(payload)
        quality_summary = dict(state.quality_summary or {})
        base_context = {
            "scenario": scenario,
            "temporal_holdout": holdout_policy,
            "source_table": str(snapshots_path),
        }
        rule_hits_list = list(rule_hits)
        for idx, (current_year, next_year) in enumerate(zip(years, years[1:])):
            current_rows = grouped[current_year]
            next_rows = grouped[next_year]
            current_latent = self._latent_from_snapshot_rows(current_rows)
            next_latent = self._latent_from_snapshot_rows(next_rows)
            transition_delta = self._snapshot_transition_delta(current_latent, next_latent)
            future_stage = self._dominant_stage(next_rows)
            synthetic = any(truthy(row.get("synthetic")) for row in current_rows + next_rows)
            not_for_production = any(truthy(row.get("not_for_production")) for row in current_rows + next_rows)
            split = self._split_for_transition_year(next_year, holdout_policy)
            action = TerritoryWorldModelAction(
                action_type="observed_transition" if not synthetic else "synthetic_transition",
                target_role="land_space_type",
                magnitude=round(abs(float(transition_delta.get("total_area_delta_m2") or 0.0)), 4),
                scenario=scenario,
                description=f"{current_year}->{next_year} {future_stage} territorial transition",
                legal_intent="temporal_state_supervision",
                execution_mask={
                    "allowed": not not_for_production,
                    "required_reviews": ["synthetic_transition"] if synthetic else [],
                    "hard_blocks": ["not_for_production"] if not_for_production else [],
                    "confidence": 0.35 if synthetic else 0.75,
                },
                parameters={
                    "current_year": current_year,
                    "next_year": next_year,
                    "temporal_stage": future_stage,
                    "synthetic": synthetic,
                    "not_for_production": not_for_production,
                },
                treatment="observational_temporal_calibration",
            )
            forecast = self.planner.forecast(
                {
                    "state_version": state,
                    "objects": state_bundle["objects"],
                    "relations": state_bundle["relations"],
                    "quality_summary": quality_summary,
                    "warnings": [],
                    "hierarchy_tokens": state.summary,
                },
                action,
                scenario=scenario,
                rule_hits=rule_hits_list,
                evidence_coverage=evidence_coverage,
                scenario_context={
                    "observed_treatment_effect": self._transition_treatment_proxy(transition_delta),
                    "calibration_gap": 0.12 if synthetic else 0.04,
                    "temporal_stage": future_stage,
                },
            )
            not_for_training: list[str] = []
            if synthetic:
                not_for_training.append("synthetic_temporal_transition")
            if not_for_production:
                not_for_training.append("not_for_production_transition")
            if validation.get("overall_status") != "pass":
                not_for_training.append("validation_report_not_fully_passed")
            if forecast.evidence_gate.get("status") != "pass":
                not_for_training.append("evidence_gate_not_passed")
            example = TwmDynamicsTrainingExample(
                state_version_id=state.id,
                project_id=state.project_id,
                split=split,
                sample_type="temporal_state_transition",
                current_state_summary={
                    "year": current_year,
                    "latent_state": current_latent,
                    "quality_summary": quality_summary,
                    "hierarchy_tokens": self._state_hierarchy_tokens(state),
                },
                action=action,
                scenario_context=base_context
                | {
                    "current_year": current_year,
                    "next_year": next_year,
                    "temporal_stage": future_stage,
                },
                targets={
                    "future_latent_state": {
                        "schema": "territory_world_model.observed_temporal_latent_state.v1",
                        "state_version_id": state.id,
                        "project_id": state.project_id,
                        "current_year": current_year,
                        "next_year": next_year,
                        "current": current_latent,
                        "observed_next": next_latent,
                        "delta": transition_delta,
                    },
                    "constraint_violation_probability": forecast.constraint_violation_probability,
                    "planning_utility_delta": forecast.planning_utility_delta,
                    "uncertainty": forecast.uncertainty,
                    "calibration": forecast.calibration
                    | {
                        "observed_transition_proxy": self._transition_treatment_proxy(transition_delta),
                    },
                    "action_mask": forecast.evidence_gate.get("action_mask", {}),
                },
                labels={
                    "constraint_label": "review_required" if not_for_production or synthetic else "observed_transition",
                    "utility_label": "positive_lift" if forecast.planning_utility_delta > 0 else "non_positive_lift",
                    "ranking_score": round(forecast.planning_utility_delta - forecast.constraint_violation_probability, 4),
                    "evidence_supported": forecast.evidence_gate.get("status") == "pass",
                    "supervision_source": "state_snapshots",
                    "ground_truth_grade": "synthetic_review" if synthetic or not_for_production else "observed",
                },
                losses={
                    "transition_loss": "targets.future_latent_state.observed_next",
                    "constraint_loss": "targets.constraint_violation_probability",
                    "planning_ranking_loss": "labels.ranking_score",
                    "calibration_loss": "targets.calibration.observed_transition_proxy",
                    "uncertainty_calibration_loss": "targets.uncertainty.confidence",
                    "evidence_consistency_loss": "evidence_gate.status",
                    "action_mask_loss": "targets.action_mask.allowed",
                },
                evidence_gate=forecast.evidence_gate,
                provenance={
                    "state_version_id": state.id,
                    "source_table": str(snapshots_path),
                    "current_year": current_year,
                    "next_year": next_year,
                    "sample_index": idx,
                    "sample_family": "temporal_transition",
                    "ground_truth": not synthetic and not not_for_production,
                    "synthetic": synthetic,
                    "not_for_production": not_for_production,
                },
                not_for_training_reasons=not_for_training,
            )
            examples.append(example)
        return examples

    def _state_bundle_root(self, state: TwmStateVersion) -> Path | None:
        source_manifest = dict(state.source_manifest or {})
        raw = source_manifest.get("bundle_dir")
        if not raw:
            return None
        path = Path(str(raw))
        return path if path.exists() else None

    def _find_auxiliary_table(self, bundle_root: Path, table_name: str) -> Path | None:
        for candidate in (bundle_root / "tables" / table_name, bundle_root.parent / "tables" / table_name):
            if candidate.exists():
                return candidate
        return None

    def _dynamics_readiness_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("thresholds") or {})
        return {
            "min_total_examples": safe_int(raw.get("min_total_examples"), 6) or 6,
            "min_usable_examples": safe_int(raw.get("min_usable_examples"), 4) or 4,
            "min_observed_temporal_examples": safe_int(raw.get("min_observed_temporal_examples"), 2) or 2,
            "min_holdout_examples": safe_int(raw.get("min_holdout_examples"), 1) or 1,
            "max_scaffold_ratio": float(safe_float(raw.get("max_scaffold_ratio"), 0.5) or 0.5),
            "max_review_ratio": float(safe_float(raw.get("max_review_ratio"), 0.35) or 0.35),
            "require_geofm_pass": bool(raw.get("require_geofm_pass", False)),
            "require_causal_pass": bool(raw.get("require_causal_pass", False)),
        }

    def _dynamics_sample_inventory(self, dataset: dict[str, Any]) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        by_type: dict[str, int] = {}
        by_split: dict[str, int] = {}
        by_source: dict[str, int] = {}
        blocked_reason_counts: dict[str, int] = {}
        target_heads = {
            "future_latent_state": 0,
            "constraint_violation_probability": 0,
            "planning_utility_delta": 0,
            "uncertainty": 0,
            "calibration": 0,
            "action_mask": 0,
        }
        usable_count = 0
        review_count = 0
        observed_temporal_count = 0
        synthetic_temporal_count = 0
        scaffold_count = 0
        evidence_supported_count = 0
        action_mask_blocked_count = 0
        ranking_scores: list[float] = []
        for item in examples:
            sample_type = str(item.get("sample_type") or "unknown")
            split = str(item.get("split") or "candidate")
            labels = dict(item.get("labels") or {})
            provenance = dict(item.get("provenance") or {})
            targets = dict(item.get("targets") or {})
            reasons = list(item.get("not_for_training_reasons") or [])
            by_type[sample_type] = by_type.get(sample_type, 0) + 1
            by_split[split] = by_split.get(split, 0) + 1
            source = str(labels.get("supervision_source") or "unknown")
            by_source[source] = by_source.get(source, 0) + 1
            if source == "deterministic_scaffold":
                scaffold_count += 1
            if source == "state_snapshots" and provenance.get("ground_truth"):
                observed_temporal_count += 1
            if source == "state_snapshots" and not provenance.get("ground_truth"):
                synthetic_temporal_count += 1
            if not reasons:
                usable_count += 1
            else:
                review_count += 1
                for reason in reasons:
                    key = str(reason)
                    blocked_reason_counts[key] = blocked_reason_counts.get(key, 0) + 1
            if labels.get("evidence_supported"):
                evidence_supported_count += 1
            action_mask = dict(targets.get("action_mask") or {})
            if not action_mask.get("allowed", True):
                action_mask_blocked_count += 1
            for head in target_heads:
                if head in targets:
                    target_heads[head] += 1
            ranking_scores.append(float(safe_float(labels.get("ranking_score"), 0.0) or 0.0))
        total = len(examples)
        return {
            "example_count": total,
            "usable_example_count": usable_count,
            "review_example_count": review_count,
            "holdout_example_count": by_split.get("holdout", 0),
            "candidate_example_count": by_split.get("candidate", 0),
            "observed_temporal_example_count": observed_temporal_count,
            "synthetic_temporal_example_count": synthetic_temporal_count,
            "forecast_scaffold_example_count": by_type.get("action_conditioned_forecast", 0),
            "scaffold_example_count": scaffold_count,
            "evidence_supported_count": evidence_supported_count,
            "action_mask_blocked_count": action_mask_blocked_count,
            "by_sample_type": by_type,
            "by_split": by_split,
            "by_supervision_source": by_source,
            "blocked_reason_counts": blocked_reason_counts,
            "target_head_coverage": target_heads,
            "scaffold_ratio": round(scaffold_count / max(1, total), 4),
            "review_ratio": round(review_count / max(1, total), 4),
            "ranking_score_range": {
                "min": round(min(ranking_scores), 4) if ranking_scores else 0.0,
                "max": round(max(ranking_scores), 4) if ranking_scores else 0.0,
            },
        }

    def _dynamics_readiness_gates(
        self,
        *,
        state_version_id: str,
        dataset: dict[str, Any],
        inventory: dict[str, Any],
        thresholds: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        summary = dict(dataset.get("summary") or {})
        loss_contract = dict(summary.get("loss_contract") or {})
        gates: dict[str, Any] = {
            "sample_volume": {
                "passed": inventory["example_count"] >= thresholds["min_total_examples"],
                "value": inventory["example_count"],
                "threshold": thresholds["min_total_examples"],
            },
            "usable_volume": {
                "passed": inventory["usable_example_count"] >= thresholds["min_usable_examples"],
                "value": inventory["usable_example_count"],
                "threshold": thresholds["min_usable_examples"],
            },
            "observed_temporal_support": {
                "passed": inventory["observed_temporal_example_count"] >= thresholds["min_observed_temporal_examples"],
                "value": inventory["observed_temporal_example_count"],
                "threshold": thresholds["min_observed_temporal_examples"],
            },
            "holdout_support": {
                "passed": inventory["holdout_example_count"] >= thresholds["min_holdout_examples"],
                "value": inventory["holdout_example_count"],
                "threshold": thresholds["min_holdout_examples"],
            },
            "scaffold_dependence": {
                "passed": inventory["scaffold_ratio"] <= thresholds["max_scaffold_ratio"],
                "value": inventory["scaffold_ratio"],
                "threshold": thresholds["max_scaffold_ratio"],
            },
            "review_pressure": {
                "passed": inventory["review_ratio"] <= thresholds["max_review_ratio"],
                "value": inventory["review_ratio"],
                "threshold": thresholds["max_review_ratio"],
            },
            "multi_head_targets": {
                "passed": all(count == inventory["example_count"] for count in inventory["target_head_coverage"].values()),
                "coverage": inventory["target_head_coverage"],
                "required_heads": [
                    "future_latent_state",
                    "constraint_violation_probability",
                    "planning_utility_delta",
                    "uncertainty",
                    "calibration",
                    "action_mask",
                ],
            },
            "loss_contract": {
                "passed": all(
                    key in loss_contract
                    for key in (
                        "transition_loss",
                        "constraint_loss",
                        "planning_ranking_loss",
                        "calibration_loss",
                        "uncertainty_calibration_loss",
                        "evidence_consistency_loss",
                        "action_mask_loss",
                    )
                ),
                "available_losses": sorted(loss_contract),
            },
        }
        geofm_payload = payload.get("geofm_gate_report")
        geofm_gate = dict(geofm_payload) if isinstance(geofm_payload, dict) else self.geofm_ablation_gate(state_version_id, payload)
        causal_payload = payload.get("causal_calibration_report")
        causal_gate = dict(causal_payload) if isinstance(causal_payload, dict) else self.causal_calibration_report(state_version_id, payload)
        gates["geofm_gate"] = {
            "passed": geofm_gate.get("gate_status") == "pass",
            "required": bool(thresholds["require_geofm_pass"]),
            "status": geofm_gate.get("gate_status", "review"),
            "decision": geofm_gate.get("decision", "review_required"),
        }
        gates["causal_calibration"] = {
            "passed": causal_gate.get("status") == "pass",
            "required": bool(thresholds["require_causal_pass"]),
            "status": causal_gate.get("status", "review"),
            "method": causal_gate.get("method", ""),
        }
        trainable_gates = [
            "sample_volume",
            "usable_volume",
            "observed_temporal_support",
            "holdout_support",
            "scaffold_dependence",
            "review_pressure",
            "multi_head_targets",
            "loss_contract",
        ]
        if thresholds["require_geofm_pass"]:
            trainable_gates.append("geofm_gate")
        if thresholds["require_causal_pass"]:
            trainable_gates.append("causal_calibration")
        blocked = [name for name in trainable_gates if not gates[name].get("passed")]
        review_only = [item.get("id") for item in examples if item.get("not_for_training_reasons")]
        gates["summary"] = {
            "blocked_gates": blocked,
            "review_only_example_ids": [item for item in review_only if item][:25],
            "claim_boundary": "trainable_dynamics_ready" if not blocked else "contract_or_review_only",
        }
        return gates

    def _dynamics_readiness_status(self, gate_results: dict[str, Any]) -> str:
        blocked = list((gate_results.get("summary") or {}).get("blocked_gates") or [])
        if not blocked:
            return "pass"
        hard = {"sample_volume", "usable_volume", "multi_head_targets", "loss_contract"}
        return "blocked" if any(item in hard for item in blocked) else "review"

    def _dynamics_training_scope(self, gate_results: dict[str, Any]) -> str:
        blocked = set((gate_results.get("summary") or {}).get("blocked_gates") or [])
        if not blocked:
            return "trainable_action_conditioned_dynamics"
        if blocked <= {"geofm_gate", "causal_calibration"}:
            return "trainable_core_dynamics_with_review_gated_enhancements"
        if blocked <= {"observed_temporal_support", "holdout_support", "scaffold_dependence", "review_pressure", "geofm_gate", "causal_calibration"}:
            return "limited_experiment_only"
        return "contract_only"

    def _dynamics_target_model_contract(self, dataset: dict[str, Any], gate_results: dict[str, Any]) -> dict[str, Any]:
        summary = dict(dataset.get("summary") or {})
        state_version_id = str(dataset.get("state_version_id") or "")
        state_contract = self.state_contract_report(state_version_id, {}) if state_version_id else {}
        return {
            "schema": "territory_world_model.trainable_dynamics_contract.v1",
            "state_encoder": {
                "required_tokens": ["parcel", "block", "township", "county"],
                "inputs": ["hierarchy_tokens", "explicit_gis_features", "constraint_state", "history_delta"],
                "geofm_policy": "B1 is retained only when geofm_gate.status == pass",
            },
            "state_contract": state_contract,
            "dynamics": {
                "conditioned_on": ["current_state", "action", "scenario", "causal_calibration"],
                "predicts": ["next_state", "constraint_state", "utility_state"],
            },
            "heads": [
                "future_latent_state",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty",
                "action_mask",
            ],
            "loss_contract": dict(summary.get("loss_contract") or {}),
            "claim_gate": dict(gate_results.get("summary") or {}),
        }

    def _dynamics_readiness_recommendations(
        self,
        *,
        inventory: dict[str, Any],
        gate_results: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        blocked = set((gate_results.get("summary") or {}).get("blocked_gates") or [])
        if "sample_volume" in blocked or "usable_volume" in blocked:
            recommendations.append("add more evidence-supported state/action/next-state examples before training neural dynamics")
        if "observed_temporal_support" in blocked:
            recommendations.append("replace synthetic state_snapshots rows with observed temporal transitions or lower the claim scope")
        if "holdout_support" in blocked:
            recommendations.append("reserve at least one temporal or spatial holdout split for future-state validation")
        if "scaffold_dependence" in blocked:
            recommendations.append("do not treat deterministic forecast scaffold samples as ground truth; use them only for contract tests or weak priors")
        if "review_pressure" in blocked:
            recommendations.append("resolve review-only examples, evidence gaps and action-mask blocks before promoting samples into training")
        if "geofm_gate" in blocked:
            recommendations.append("keep GeoFM gated out of the trainable core until B0/B1 downstream planning lift passes")
        if "causal_calibration" in blocked:
            recommendations.append("use balanced treated/control observations or a causal backend before upgrading counterfactual utility claims")
        if not recommendations:
            recommendations.append("start with a small train/holdout dynamics run and report planning lift separately from one-step fit")
        recommendations.append(
            f"current usable/total examples: {inventory['usable_example_count']}/{inventory['example_count']}; "
            f"observed temporal examples: {inventory['observed_temporal_example_count']} "
            f"(threshold {thresholds['min_observed_temporal_examples']})"
        )
        return recommendations

    def _dynamics_candidate_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("candidate") or {})
        name = str(raw.get("model_name") or payload.get("model_name") or "deterministic_scaffold_baseline")
        version = str(raw.get("model_version") or payload.get("model_version") or "current")
        return {
            "model_name": name,
            "model_version": version,
            "model_family": str(raw.get("model_family") or payload.get("model_family") or "twm_dynamics"),
            "uses_geofm": bool(raw.get("uses_geofm", payload.get("uses_geofm", False))),
            "uses_causal_calibration": bool(raw.get("uses_causal_calibration", payload.get("uses_causal_calibration", False))),
            "is_scaffold_baseline": not bool(payload.get("predictions")),
            "metadata": dict(raw.get("metadata") or {}),
        }

    def _fit_candidate_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("candidate") or {})
        return {
            "model_name": str(raw.get("model_name") or payload.get("model_name") or "hierarchical_baseline_dynamics"),
            "model_version": str(raw.get("model_version") or payload.get("model_version") or "fit_scaffold_v1"),
            "model_family": str(raw.get("model_family") or payload.get("model_family") or "action_conditioned_hierarchical_baseline"),
            "uses_geofm": bool(raw.get("uses_geofm", payload.get("uses_geofm", False))),
            "uses_causal_calibration": bool(raw.get("uses_causal_calibration", payload.get("uses_causal_calibration", True))),
            "is_scaffold_baseline": False,
            "metadata": dict(raw.get("metadata") or {}),
        }

    def _train_dynamics_trainer_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("trainer") or payload.get("candidate") or {})
        training_method = str(raw.get("training_method") or payload.get("training_method") or "weighted_multi_head_group_means")
        transformer = training_method in {"torch_spatiotemporal_transformer", "spatiotemporal_transformer_dynamics", "torch_spatiotemporal_transformer_dynamics"}
        neural = training_method in {"torch_multi_head_mlp", "neural_multi_head_mlp"}
        graph = training_method in {"torch_hierarchical_graph", "hierarchical_graph_dynamics", "torch_hierarchical_graph_dynamics"}
        default_name = (
            "spatiotemporal_transformer_dynamics"
            if transformer
            else "hierarchical_graph_token_dynamics"
            if graph
            else "hierarchical_neural_multi_head_dynamics"
            if neural
            else "hierarchical_trainable_dynamics_scaffold"
        )
        default_version = (
            "spatiotemporal_transformer_candidate_v1"
            if transformer
            else "hierarchical_graph_candidate_v1"
            if graph
            else "neural_candidate_v1"
            if neural
            else "trainer_scaffold_v1"
        )
        default_family = (
            "action_conditioned_spatiotemporal_transformer_dynamics"
            if transformer
            else "action_conditioned_hierarchical_graph_dynamics"
            if graph
            else "action_conditioned_hierarchical_neural_dynamics"
            if neural
            else "action_conditioned_hierarchical_trainable_scaffold"
        )
        model_name = str(raw.get("model_name") or payload.get("model_name") or default_name)
        model_version = str(raw.get("model_version") or payload.get("model_version") or default_version)
        return {
            "trainer_id": str(raw.get("trainer_id") or raw.get("id") or f"{model_name}:{model_version}"),
            "model_name": model_name,
            "model_version": model_version,
            "model_family": str(raw.get("model_family") or payload.get("model_family") or default_family),
            "training_method": training_method,
            "uses_geofm": bool(raw.get("uses_geofm", payload.get("uses_geofm", False))),
            "uses_causal_calibration": bool(raw.get("uses_causal_calibration", payload.get("uses_causal_calibration", False))),
            "is_scaffold_trainer": not (neural or graph or transformer),
            "metadata": dict(raw.get("metadata") or {}),
        }

    def _use_neural_dynamics_trainer(self, trainer: dict[str, Any]) -> bool:
        return str(trainer.get("training_method") or "") in {"torch_multi_head_mlp", "neural_multi_head_mlp"}

    def _use_hierarchical_graph_dynamics_trainer(self, trainer: dict[str, Any]) -> bool:
        return str(trainer.get("training_method") or "") in {"torch_hierarchical_graph", "hierarchical_graph_dynamics", "torch_hierarchical_graph_dynamics"}

    def _use_spatiotemporal_transformer_dynamics_trainer(self, trainer: dict[str, Any]) -> bool:
        return str(trainer.get("training_method") or "") in {
            "torch_spatiotemporal_transformer",
            "spatiotemporal_transformer_dynamics",
            "torch_spatiotemporal_transformer_dynamics",
        }

    def _train_dynamics_parameters(self, dataset: dict[str, Any], objective_report: dict[str, Any], trainer: dict[str, Any]) -> dict[str, Any]:
        params = self._fit_baseline_dynamics_parameters(dataset)
        params["schema"] = "territory_world_model.trainable_dynamics_scaffold_parameters.v1"
        params["fit_method"] = trainer.get("training_method", "weighted_multi_head_group_means")
        params["trainer"] = dict(trainer)
        params["objective_contract"] = dict(objective_report.get("objective_contract") or {})
        params["loss_components"] = dict(objective_report.get("loss_components") or {})
        params["limitations"] = [
            "trainer scaffold uses transparent grouped statistics, not a neural dynamics optimizer",
            "replace this scaffold with a trainable model while preserving the same objective/backend contracts",
        ]
        return params

    def _train_dynamics_candidate_report(
        self,
        trainer: dict[str, Any],
        learned_parameters: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema": "territory_world_model.trainable_dynamics_candidate_report.v1",
            "status": "pass" if predictions else "review",
            "candidate": {
                "model_name": trainer.get("model_name", ""),
                "model_version": trainer.get("model_version", ""),
                "model_family": trainer.get("model_family", ""),
                "uses_geofm": bool(trainer.get("uses_geofm")),
                "uses_causal_calibration": bool(trainer.get("uses_causal_calibration")),
                "is_scaffold_baseline": False,
                "is_scaffold_trainer": bool(trainer.get("is_scaffold_trainer", True)),
            },
            "learned_parameters": learned_parameters,
            "predictions": predictions,
            "evaluation": {"status": "pass" if predictions else "review", "evidence_gate": {"status": "pass" if predictions else "review"}},
            "evidence_gate": {"status": "pass" if predictions else "review"},
        }

    def _neural_dynamics_candidate_report(
        self,
        trainer: dict[str, Any],
        learned_parameters: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        training_status = str(learned_parameters.get("training_status") or diagnostics.get("status") or "review")
        status = "pass" if predictions and training_status == "pass" else "blocked" if training_status == "blocked" else "review"
        parameter_schema = learned_parameters.get("schema") or NEURAL_DYNAMICS_SCHEMA
        candidate_schema = (
            "territory_world_model.spatiotemporal_transformer_dynamics_candidate_report.v1"
            if parameter_schema == SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA
            else
            "territory_world_model.hierarchical_graph_dynamics_candidate_report.v1"
            if parameter_schema == HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA
            else "territory_world_model.neural_multi_head_dynamics_candidate_report.v1"
        )
        claim_scope = (
            "spatiotemporal_transformer_trainable_candidate_contract"
            if parameter_schema == SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA
            else "hierarchical_graph_trainable_candidate_contract"
            if parameter_schema == HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA
            else "trainable_neural_candidate_contract"
        )
        evidence_gate = {
            "status": status,
            "passed": status == "pass",
            "missing": [] if status == "pass" else ["neural_training_predictions"] if not predictions else ["neural_training_status"],
            "claim_scope": claim_scope if status == "pass" else "neural_candidate_review_or_blocked",
        }
        return {
            "schema": candidate_schema,
            "status": status,
            "candidate": {
                "model_name": trainer.get("model_name", ""),
                "model_version": trainer.get("model_version", ""),
                "model_family": trainer.get("model_family", ""),
                "uses_geofm": bool(trainer.get("uses_geofm")),
                "uses_causal_calibration": bool(trainer.get("uses_causal_calibration")),
                "is_scaffold_baseline": False,
                "is_scaffold_trainer": False,
                "parameter_schema": parameter_schema,
            },
            "learned_parameters": learned_parameters,
            "predictions": predictions,
            "evaluation": {"status": status, "evidence_gate": evidence_gate, "training_diagnostics": diagnostics},
            "evidence_gate": evidence_gate,
        }

    def _train_dynamics_evidence_gate(
        self,
        *,
        readiness: dict[str, Any],
        backend_report: dict[str, Any],
        objective_report: dict[str, Any],
        trainer: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []
        if readiness.get("status") != "pass":
            missing.append("readiness_pass")
        if backend_report and backend_report.get("status") != "pass":
            missing.append("backend_pass")
        elif not backend_report:
            missing.append("backend_report")
        objective_gate = dict(objective_report.get("evidence_gate") or {})
        if objective_gate.get("status") not in {"pass", "review"}:
            missing.append("objective_contract")
        if trainer.get("is_scaffold_trainer"):
            missing.append("non_scaffold_trainer")
        hard = {"readiness_pass", "backend_report", "objective_contract"}
        status = "pass" if not missing else "blocked" if any(item in hard for item in missing) else "review"
        return {
            "passed": status == "pass",
            "blocked": status == "blocked",
            "status": status,
            "missing": missing,
            "claim_scope": "trainer_candidate_ready" if status == "pass" else "trainer_scaffold_review_only" if status == "review" else "trainer_blocked",
        }

    def _train_dynamics_recommendations(self, evidence_gate: dict[str, Any], trainer: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []
        missing = set(evidence_gate.get("missing") or [])
        if "readiness_pass" in missing:
            recommendations.append("improve observed temporal and usable examples before training a dynamics candidate")
        if "backend_pass" in missing or "backend_report" in missing:
            recommendations.append("ensure trained predictions pass dynamics_backend_report before forecast consumption")
        if "objective_contract" in missing:
            recommendations.append("fix training_objective_report coverage before training")
        if "non_scaffold_trainer" in missing:
            recommendations.append("replace scaffold trainer with a real neural/statistical optimizer before claiming trainable TWM dynamics")
        if not recommendations:
            recommendations.append("validate trained candidate through counterfactual rollout, beam planning and spatial holdout")
        return recommendations

    def _fit_baseline_dynamics_parameters(self, dataset: dict[str, Any]) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict) and not item.get("not_for_training_reasons")]
        by_action: dict[str, dict[str, Any]] = {}
        global_rows: list[dict[str, Any]] = []
        for item in examples:
            action = dict(item.get("action") or {})
            targets = dict(item.get("targets") or {})
            labels = dict(item.get("labels") or {})
            action_type = str(action.get("action_type") or "unknown")
            row = {
                "utility": float(safe_float(targets.get("planning_utility_delta"), 0.0) or 0.0),
                "constraint": float(safe_float(targets.get("constraint_violation_probability"), 0.0) or 0.0),
                "confidence": float(safe_float((targets.get("uncertainty") or {}).get("confidence"), 0.0) or 0.0),
                "ranking_score": float(safe_float(labels.get("ranking_score"), 0.0) or 0.0),
                "area_total": self._target_total_area(targets),
            }
            by_action.setdefault(action_type, {"rows": []})["rows"].append(row)
            global_rows.append(row)
        action_parameters = {}
        for action_type, payload in by_action.items():
            rows = list(payload.get("rows") or [])
            action_parameters[action_type] = self._aggregate_dynamics_rows(rows)
        return {
            "schema": "territory_world_model.hierarchical_baseline_dynamics_parameters.v1",
            "fit_method": "evidence_supported_action_group_means",
            "sample_count": len(global_rows),
            "action_parameters": action_parameters,
            "global_parameters": self._aggregate_dynamics_rows(global_rows),
            "limitations": [
                "baseline parameters are a transparent fit scaffold, not the final neural TWM dynamics",
                "future neural backend must preserve the same multi-head prediction contract and evidence gates",
            ],
        }

    def _aggregate_dynamics_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        area_values = [float(row["area_total"]) for row in rows if row.get("area_total") is not None]
        return {
            "sample_count": len(rows),
            "utility_mean": self._mean([float(row["utility"]) for row in rows]) or 0.0,
            "constraint_mean": self._mean([float(row["constraint"]) for row in rows]) or 0.0,
            "confidence_mean": self._mean([float(row["confidence"]) for row in rows]) or 0.0,
            "ranking_score_mean": self._mean([float(row["ranking_score"]) for row in rows]) or 0.0,
            "area_total_mean": self._mean(area_values),
        }

    def _predict_with_baseline_dynamics(self, dataset: dict[str, Any], learned_parameters: dict[str, Any]) -> dict[str, dict[str, Any]]:
        predictions: dict[str, dict[str, Any]] = {}
        action_parameters = dict(learned_parameters.get("action_parameters") or {})
        global_parameters = dict(learned_parameters.get("global_parameters") or {})
        for item in dataset.get("examples") or []:
            if not isinstance(item, dict):
                continue
            example_id = str(item.get("id") or "")
            if not example_id:
                continue
            action = dict(item.get("action") or {})
            targets = dict(item.get("targets") or {})
            params = dict(action_parameters.get(str(action.get("action_type") or "unknown")) or global_parameters)
            future_latent = self._predict_future_latent_with_params(targets, params)
            predictions[example_id] = {
                "future_latent_state": future_latent,
                "constraint_violation_probability": round(float(params.get("constraint_mean") or 0.0), 6),
                "planning_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
                "uncertainty": {
                    "confidence": round(float(params.get("confidence_mean") or 0.0), 6),
                    "source": "hierarchical_baseline_dynamics_fit",
                },
                "action_mask": dict(targets.get("action_mask") or {}),
            }
        return predictions

    def _predict_future_latent_with_params(self, targets: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        target_latent = dict(targets.get("future_latent_state") or {})
        observed = dict(target_latent.get("observed_next") or target_latent.get("projected") or {})
        if not observed:
            return dict(target_latent)
        prediction = json.loads(json.dumps(observed))
        area_mean = params.get("area_total_mean")
        if area_mean is not None and "total_area_m2" in prediction:
            prediction["total_area_m2"] = round(float(area_mean), 6)
        return {
            "schema": "territory_world_model.predicted_latent_state.v1",
            "observed_next": prediction,
        }

    def _target_total_area(self, targets: dict[str, Any]) -> float | None:
        latent = dict(targets.get("future_latent_state") or {})
        observed = dict(latent.get("observed_next") or latent.get("projected") or {})
        value = safe_float(observed.get("total_area_m2"), None)
        return float(value) if value is not None else None

    def _fit_dynamics_recommendations(self, evidence_gate: dict[str, Any], learned_parameters: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []
        if evidence_gate.get("status") != "pass":
            recommendations.append("do not promote this fitted candidate to production; use it as a transparent baseline for neural dynamics")
        else:
            recommendations.append("candidate passed evaluation gate; compare it against a neural hierarchical dynamics backend on the same holdout")
        if int(learned_parameters.get("sample_count") or 0) < 20:
            recommendations.append("increase observed temporal/action sample count before claiming cross-region generalization")
        recommendations.append("preserve action-conditioned multi-head output contract when replacing this baseline with trainable dynamics")
        return recommendations

    def _dynamics_predictions_for_evaluation(self, dataset: dict[str, Any], payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw_predictions = payload.get("predictions")
        if isinstance(raw_predictions, dict):
            return {str(key): dict(value) for key, value in raw_predictions.items() if isinstance(value, dict)}
        if isinstance(raw_predictions, list):
            result: dict[str, dict[str, Any]] = {}
            for item in raw_predictions:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("example_id") or item.get("id") or "")
                if key:
                    result[key] = dict(item.get("prediction") or item)
            return result
        predictions: dict[str, dict[str, Any]] = {}
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            prediction = dict(example.get("targets") or {})
            if prediction:
                predictions[str(example.get("id") or "")] = prediction
        return predictions

    def _dynamics_evaluation_metrics(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        scored_examples = []
        transition_errors: list[float] = []
        constraint_errors: list[float] = []
        utility_errors: list[float] = []
        uncertainty_confidences: list[float] = []
        ranking_pairs: list[tuple[float, float]] = []
        action_mask_matches = 0
        action_mask_count = 0
        ground_truth_count = 0
        holdout_count = 0
        payload_prediction_count = 0
        for example in examples:
            example_id = str(example.get("id") or "")
            prediction = dict(predictions.get(example_id) or {})
            if not prediction:
                continue
            payload_prediction_count += 1
            targets = dict(example.get("targets") or {})
            labels = dict(example.get("labels") or {})
            provenance = dict(example.get("provenance") or {})
            split = str(example.get("split") or "candidate")
            if split == "holdout":
                holdout_count += 1
            if provenance.get("ground_truth"):
                ground_truth_count += 1
            transition_error = self._latent_transition_error(
                predicted=dict(prediction.get("future_latent_state") or {}),
                target=dict(targets.get("future_latent_state") or {}),
            )
            if transition_error is not None:
                transition_errors.append(transition_error)
            if "constraint_violation_probability" in prediction and "constraint_violation_probability" in targets:
                constraint_errors.append(abs(float(safe_float(prediction.get("constraint_violation_probability"), 0.0) or 0.0) - float(safe_float(targets.get("constraint_violation_probability"), 0.0) or 0.0)))
            if "planning_utility_delta" in prediction and "planning_utility_delta" in targets:
                utility_errors.append(abs(float(safe_float(prediction.get("planning_utility_delta"), 0.0) or 0.0) - float(safe_float(targets.get("planning_utility_delta"), 0.0) or 0.0)))
                ranking_pairs.append((float(safe_float(prediction.get("planning_utility_delta"), 0.0) or 0.0), float(safe_float(labels.get("ranking_score"), 0.0) or 0.0)))
            uncertainty = dict(prediction.get("uncertainty") or {})
            if "confidence" in uncertainty:
                uncertainty_confidences.append(float(safe_float(uncertainty.get("confidence"), 0.0) or 0.0))
            predicted_mask = dict(prediction.get("action_mask") or {})
            target_mask = dict(targets.get("action_mask") or {})
            if predicted_mask or target_mask:
                action_mask_count += 1
                if bool(predicted_mask.get("allowed", True)) == bool(target_mask.get("allowed", True)):
                    action_mask_matches += 1
            scored_examples.append(example_id)
        metrics = {
            "evaluated_example_count": len(scored_examples),
            "ground_truth_example_count": ground_truth_count,
            "holdout_example_count": holdout_count,
            "mean_transition_error": self._mean(transition_errors),
            "mean_constraint_error": self._mean(constraint_errors),
            "mean_utility_error": self._mean(utility_errors),
            "ranking_correlation_proxy": self._ranking_correlation_proxy(ranking_pairs),
            "mean_confidence": self._mean(uncertainty_confidences),
            "action_mask_accuracy": round(action_mask_matches / max(1, action_mask_count), 4) if action_mask_count else None,
        }
        head_metrics = {
            "future_latent_state": {"count": len(transition_errors), "mean_error": metrics["mean_transition_error"]},
            "constraint_violation_probability": {"count": len(constraint_errors), "mae": metrics["mean_constraint_error"]},
            "planning_utility_delta": {"count": len(utility_errors), "mae": metrics["mean_utility_error"], "ranking_correlation_proxy": metrics["ranking_correlation_proxy"]},
            "uncertainty": {"count": len(uncertainty_confidences), "mean_confidence": metrics["mean_confidence"]},
            "action_mask": {"count": action_mask_count, "accuracy": metrics["action_mask_accuracy"]},
        }
        inventory = {
            "dataset_example_count": len(examples),
            "prediction_count": payload_prediction_count,
            "evaluated_example_ids": scored_examples[:50],
            "ground_truth_example_count": ground_truth_count,
            "holdout_example_count": holdout_count,
        }
        return metrics, head_metrics, inventory

    def _latent_transition_error(self, *, predicted: dict[str, Any], target: dict[str, Any]) -> float | None:
        observed = dict(target.get("observed_next") or target.get("projected") or {})
        pred = dict(predicted.get("observed_next") or predicted.get("projected") or predicted)
        observed_area = safe_float(observed.get("total_area_m2"), None)
        pred_area = safe_float(pred.get("total_area_m2"), None)
        if observed_area is not None and pred_area is not None:
            return round(abs(float(pred_area) - float(observed_area)) / max(abs(float(observed_area)), 1.0), 6)
        observed_types = dict(observed.get("land_space_types") or {})
        pred_types = dict(pred.get("land_space_types") or {})
        if observed_types and pred_types:
            errors = []
            for key in sorted(set(observed_types) | set(pred_types)):
                target_area = float(safe_float((observed_types.get(key) or {}).get("area_m2"), 0.0) or 0.0)
                pred_area_value = float(safe_float((pred_types.get(key) or {}).get("area_m2"), 0.0) or 0.0)
                errors.append(abs(pred_area_value - target_area) / max(abs(target_area), 1.0))
            return self._mean(errors)
        return None

    def _dynamics_evaluation_gate(
        self,
        *,
        readiness: dict[str, Any],
        candidate: dict[str, Any],
        metrics: dict[str, Any],
        eval_inventory: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = dict(payload.get("evaluation_thresholds") or {})
        min_ground_truth = safe_int(thresholds.get("min_ground_truth_examples"), 1) or 1
        max_transition_error = float(safe_float(thresholds.get("max_mean_transition_error"), 0.15) or 0.15)
        max_constraint_error = float(safe_float(thresholds.get("max_mean_constraint_error"), 0.2) or 0.2)
        max_utility_error = float(safe_float(thresholds.get("max_mean_utility_error"), 0.25) or 0.25)
        min_ranking_proxy = float(safe_float(thresholds.get("min_ranking_correlation_proxy"), 0.0) or 0.0)
        missing: list[str] = []
        blocked = False
        if readiness.get("status") != "pass":
            missing.append("readiness_pass")
        if candidate.get("is_scaffold_baseline"):
            missing.append("non_scaffold_candidate")
        if eval_inventory.get("ground_truth_example_count", 0) < min_ground_truth:
            missing.append("ground_truth_holdout_examples")
            blocked = True
        if eval_inventory.get("prediction_count", 0) == 0:
            missing.append("candidate_predictions")
            blocked = True
        transition_error = metrics.get("mean_transition_error")
        if transition_error is None:
            missing.append("future_latent_state_metric")
        elif transition_error > max_transition_error:
            missing.append("future_latent_state_error")
        constraint_error = metrics.get("mean_constraint_error")
        if constraint_error is not None and constraint_error > max_constraint_error:
            missing.append("constraint_error")
        utility_error = metrics.get("mean_utility_error")
        if utility_error is not None and utility_error > max_utility_error:
            missing.append("utility_error")
        ranking_proxy = metrics.get("ranking_correlation_proxy")
        if ranking_proxy is not None and ranking_proxy < min_ranking_proxy:
            missing.append("planning_ranking_lift")
        return {
            "passed": not missing,
            "blocked": blocked,
            "status": "pass" if not missing else ("blocked" if blocked else "review"),
            "missing": missing,
            "thresholds": {
                "min_ground_truth_examples": min_ground_truth,
                "max_mean_transition_error": max_transition_error,
                "max_mean_constraint_error": max_constraint_error,
                "max_mean_utility_error": max_utility_error,
                "min_ranking_correlation_proxy": min_ranking_proxy,
            },
        }

    def _dynamics_evaluation_recommendations(
        self,
        evidence_gate: dict[str, Any],
        candidate: dict[str, Any],
        eval_inventory: dict[str, Any],
    ) -> list[str]:
        missing = set(evidence_gate.get("missing") or [])
        recommendations: list[str] = []
        if "readiness_pass" in missing:
            recommendations.append("pass dynamics readiness before using model evaluation to upgrade planning claims")
        if "non_scaffold_candidate" in missing and candidate.get("is_scaffold_baseline"):
            recommendations.append("evaluate an explicit trainable dynamics candidate instead of the deterministic scaffold baseline")
        if "ground_truth_holdout_examples" in missing:
            recommendations.append("add observed holdout transitions with provenance.ground_truth=true before reporting model accuracy")
        if "candidate_predictions" in missing:
            recommendations.append("provide candidate predictions keyed by dynamics training example id")
        if "future_latent_state_error" in missing:
            recommendations.append("improve next-state latent prediction before using rollout or MPC claims")
        if "planning_ranking_lift" in missing:
            recommendations.append("optimize planning ranking loss; one-step fit alone is not sufficient")
        if not recommendations:
            recommendations.append("evaluation gate passed; next report planning lift on counterfactual rollout holdouts")
        recommendations.append(f"evaluated examples: {eval_inventory.get('prediction_count', 0)}; ground-truth examples: {eval_inventory.get('ground_truth_example_count', 0)}")
        return recommendations

    def _mean(self, values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 6)

    def _ranking_correlation_proxy(self, pairs: list[tuple[float, float]]) -> float | None:
        if len(pairs) < 2:
            return None
        predicted_order = sorted(range(len(pairs)), key=lambda idx: pairs[idx][0])
        target_order = sorted(range(len(pairs)), key=lambda idx: pairs[idx][1])
        disagreements = sum(1 for left, right in zip(predicted_order, target_order) if left != right)
        return round(1.0 - disagreements / max(1, len(pairs)), 4)

    def _latent_from_snapshot_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_land_type: dict[str, dict[str, Any]] = {}
        total_area = 0.0
        total_features = 0
        for row in rows:
            land_type = str(row.get("land_space_type") or "unknown")
            area = float(safe_float(row.get("area_m2"), 0.0) or 0.0)
            area_delta = float(safe_float(row.get("area_delta_m2"), 0.0) or 0.0)
            feature_count = safe_int(row.get("feature_count"), 0)
            total_area += area
            total_features += feature_count
            by_land_type[land_type] = {
                "feature_count": feature_count,
                "area_m2": round(area, 4),
                "area_delta_m2": round(area_delta, 4),
                "source_dataset": row.get("source_dataset") or "",
                "synthetic": truthy(row.get("synthetic")),
                "not_for_production": truthy(row.get("not_for_production")),
            }
        return {
            "land_space_types": by_land_type,
            "total_area_m2": round(total_area, 4),
            "total_feature_count": total_features,
        }

    def _snapshot_transition_delta(self, current: dict[str, Any], observed_next: dict[str, Any]) -> dict[str, Any]:
        current_types = current.get("land_space_types") or {}
        next_types = observed_next.get("land_space_types") or {}
        all_types = sorted(set(current_types) | set(next_types))
        by_land_type: dict[str, dict[str, Any]] = {}
        total_abs_delta = 0.0
        for land_type in all_types:
            before = float((current_types.get(land_type) or {}).get("area_m2") or 0.0)
            after = float((next_types.get(land_type) or {}).get("area_m2") or 0.0)
            delta = after - before
            total_abs_delta += abs(delta)
            by_land_type[land_type] = {
                "area_delta_m2": round(delta, 4),
                "relative_delta": round(delta / max(abs(before), 1.0), 6),
            }
        return {
            "by_land_space_type": by_land_type,
            "total_area_delta_m2": round(total_abs_delta, 4),
            "net_area_delta_m2": round(float(observed_next.get("total_area_m2") or 0.0) - float(current.get("total_area_m2") or 0.0), 4),
        }

    def _transition_treatment_proxy(self, transition_delta: dict[str, Any]) -> float:
        by_land_type = transition_delta.get("by_land_space_type") or {}
        agricultural = float((by_land_type.get("agricultural_space") or {}).get("area_delta_m2") or 0.0)
        ecological = float((by_land_type.get("ecological_space") or {}).get("area_delta_m2") or 0.0)
        total = max(float(transition_delta.get("total_area_delta_m2") or 0.0), 1.0)
        return max(-0.25, min(0.25, (agricultural + ecological) / total * 0.08))

    def _dominant_stage(self, rows: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = {}
        for row in rows:
            stage = str(row.get("temporal_stage") or "unknown")
            counts[stage] = counts.get(stage, 0) + 1
        return max(counts.items(), key=lambda item: item[1])[0] if counts else "unknown"

    def _temporal_holdout_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        policy = dict(payload.get("temporal_holdout") or {})
        holdout_year = safe_int(policy.get("holdout_year") or payload.get("holdout_year"), 0)
        return {
            "strategy": str(policy.get("strategy") or "last_year_holdout"),
            "holdout_year": holdout_year or None,
            "train_until_year": safe_int(policy.get("train_until_year"), 0) or None,
        }

    def _split_for_transition_year(self, next_year: int, holdout_policy: dict[str, Any]) -> str:
        holdout_year = holdout_policy.get("holdout_year")
        train_until_year = holdout_policy.get("train_until_year")
        if holdout_year and next_year >= int(holdout_year):
            return "holdout"
        if train_until_year and next_year > int(train_until_year):
            return "holdout"
        if holdout_policy.get("strategy") == "last_year_holdout":
            return "holdout"
        return "candidate"

    def _state_hierarchy_tokens(self, state: TwmStateVersion) -> dict[str, Any]:
        summary = dict(state.summary or {})
        return {
            "schema": "territory_world_model.hierarchy_tokens.v1",
            "object_counts_by_role": dict(summary.get("object_counts_by_role") or {}),
            "relation_counts_by_type": dict(summary.get("relation_counts_by_type") or {}),
            "metric_crs": summary.get("metric_crs", ""),
        }

    def _state_contract_hierarchy(
        self,
        state: TwmStateVersion,
        objects: list[TwmStateObject],
        relations: list[TwmStateRelation],
    ) -> dict[str, Any]:
        object_counts: dict[str, int] = {}
        for obj in objects:
            role = obj.canonical_role or obj.source_role or obj.object_type or "unknown"
            object_counts[role] = object_counts.get(role, 0) + 1
        relation_counts: dict[str, int] = {}
        for rel in relations:
            rel_type = rel.relation_type or rel.predicate or "unknown"
            relation_counts[rel_type] = relation_counts.get(rel_type, 0) + 1

        token_specs = [
            self._state_contract_token_spec(
                "parcel",
                object_counts,
                required=True,
                aliases=("parcel", "parcel_current"),
                relations=relation_counts,
                required_relations=("annual_change_of_parcel",),
            ),
            self._state_contract_token_spec(
                "block",
                object_counts,
                required=True,
                aliases=("block", "planning_zone"),
                relations=relation_counts,
                required_relations=("project_overlaps_planning_zone",),
                note="planning_zone is accepted only as a review-level block proxy until explicit block/township aggregation is available",
            ),
            self._state_contract_token_spec(
                "township",
                object_counts,
                required=True,
                aliases=("township",),
                fallback_aliases=("admin_unit",),
                note="admin_unit can support regional context, but does not prove township-scale tokenization without level metadata",
            ),
            {
                "level": "county",
                "status": "available" if state.project_id else "missing",
                "required": True,
                "object_count": 1 if state.project_id else 0,
                "source_roles": ["project.region_code"],
                "required_relations": [],
                "relation_count": 0,
                "claim": "county/context token is derived from the project and state version metadata",
            },
        ]
        missing_required = [item["level"] for item in token_specs if item.get("required") and item.get("status") == "missing"]
        review_required = [item["level"] for item in token_specs if item.get("status") == "review"]
        return {
            "schema": "territory_world_model.hierarchical_state_contract.v1",
            "state_version_id": state.id,
            "metric_crs": (state.summary or {}).get("metric_crs", ""),
            "tokens": token_specs,
            "object_counts_by_role": object_counts,
            "relation_counts_by_type": relation_counts,
            "missing_required_levels": missing_required,
            "review_required_levels": review_required,
            "flat_vector_allowed": False,
            "encoder_policy": "hierarchical parcel/block/township/county tokens with explicit GIS features and constraint masks",
        }

    def _state_contract_token_spec(
        self,
        level: str,
        object_counts: dict[str, int],
        *,
        required: bool,
        aliases: tuple[str, ...],
        relations: dict[str, int] | None = None,
        required_relations: tuple[str, ...] = (),
        fallback_aliases: tuple[str, ...] = (),
        note: str = "",
    ) -> dict[str, Any]:
        direct_count = sum(int(object_counts.get(alias, 0)) for alias in aliases)
        fallback_count = sum(int(object_counts.get(alias, 0)) for alias in fallback_aliases)
        status = "available" if direct_count > 0 else "review" if fallback_count > 0 else "missing"
        relation_counts = {name: int((relations or {}).get(name, 0)) for name in required_relations}
        return {
            "level": level,
            "status": status,
            "required": required,
            "object_count": direct_count or fallback_count,
            "source_roles": list(aliases if direct_count > 0 else fallback_aliases),
            "fallback_source_roles": list(fallback_aliases),
            "required_relations": list(required_relations),
            "relation_count": sum(relation_counts.values()),
            "relation_counts": relation_counts,
            "claim": "explicit token level available" if status == "available" else "review-only proxy available" if status == "review" else "required token level missing",
            "note": note,
        }

    def _state_contract_feature_channels(
        self,
        state: TwmStateVersion,
        objects: list[TwmStateObject],
        relations: list[TwmStateRelation],
    ) -> dict[str, Any]:
        quality_summary = dict(state.quality_summary or {})
        object_feature_keys = sorted({key for obj in objects[:500] for key in (obj.attributes or {})})[:40]
        relation_metric_keys = sorted({key for rel in relations[:500] for key in (rel.metrics or {})})[:40]
        not_for_production = sum(1 for obj in objects if obj.not_for_production)
        synthetic = sum(1 for obj in objects if obj.synthetic)
        return {
            "schema": "territory_world_model.state_feature_channels.v1",
            "explicit_gis_features": {
                "available": bool(object_feature_keys or relation_metric_keys),
                "object_attribute_keys_sample": object_feature_keys,
                "relation_metric_keys_sample": relation_metric_keys,
                "metric_crs": (state.summary or {}).get("metric_crs", ""),
            },
            "quality_features": {
                "quality_summary": quality_summary,
                "synthetic_object_count": synthetic,
                "not_for_production_object_count": not_for_production,
            },
            "state_inputs": [
                "object_attributes",
                "relation_metrics",
                "geometry_bbox",
                "quality_summary",
                "constraint_channels",
                "history_delta",
                "optional_geofm_embedding",
            ],
        }

    def _state_contract_constraint_channels(
        self,
        rule_hits: list[TwmRuleHit],
        evidence_items: list[TwmEvidenceItem],
        review_tasks: list[TwmReviewTask],
    ) -> dict[str, Any]:
        severity_counts: dict[str, int] = {}
        for hit in rule_hits:
            severity_counts[hit.severity or "unknown"] = severity_counts.get(hit.severity or "unknown", 0) + 1
        open_reviews = sum(1 for item in review_tasks if item.status not in {"approved", "closed", "resolved"})
        hard_hit_count = sum(severity_counts.get(item, 0) for item in ("blocking", "critical", "high"))
        return {
            "schema": "territory_world_model.constraint_channels.v1",
            "rule_hit_count": len(rule_hits),
            "severity_counts": severity_counts,
            "hard_or_high_risk_hit_count": hard_hit_count,
            "evidence_item_count": len(evidence_items),
            "review_task_count": len(review_tasks),
            "open_review_task_count": open_reviews,
            "channels": [
                "constraint_mask",
                "constraint_violation_probability_target",
                "rule_severity_counts",
                "evidence_coverage",
                "review_pressure",
                "approval_consistency",
            ],
            "status": "pass" if evidence_items and open_reviews == 0 else "review",
        }

    def _state_contract_temporal_support(self, state: TwmStateVersion, payload: dict[str, Any]) -> dict[str, Any]:
        bundle_root = self._state_bundle_root(state)
        snapshots_path = self._find_auxiliary_table(bundle_root, "state_snapshots.csv") if bundle_root else None
        row_count = 0
        year_count = 0
        synthetic_count = 0
        not_for_production_count = 0
        years: list[int] = []
        if snapshots_path is not None:
            try:
                rows = read_csv(snapshots_path)
            except Exception:
                rows = []
            row_count = len(rows)
            years = sorted({safe_int(row.get("snapshot_year"), -1) for row in rows if safe_int(row.get("snapshot_year"), -1) >= 0})
            year_count = len(years)
            synthetic_count = sum(1 for row in rows if truthy(row.get("synthetic")))
            not_for_production_count = sum(1 for row in rows if truthy(row.get("not_for_production")))
        min_years = safe_int((payload.get("thresholds") or {}).get("min_temporal_years"), 2) if isinstance(payload.get("thresholds"), dict) else 2
        status = "pass" if year_count >= int(min_years or 2) and not not_for_production_count else "review" if row_count else "missing"
        return {
            "schema": "territory_world_model.history_delta_contract.v1",
            "status": status,
            "source_table": str(snapshots_path) if snapshots_path else "",
            "row_count": row_count,
            "year_count": year_count,
            "years": years,
            "synthetic_row_count": synthetic_count,
            "not_for_production_row_count": not_for_production_count,
            "history_delta_available": year_count >= 2,
            "channels": ["observed_next_state", "delta_area_by_land_space_type", "temporal_stage", "holdout_split"],
        }

    def _state_contract_geofm_policy(self, state: TwmStateVersion, payload: dict[str, Any]) -> dict[str, Any]:
        geofm_report = payload.get("geofm_gate_report")
        if isinstance(geofm_report, dict):
            gate_status = str(geofm_report.get("gate_status") or geofm_report.get("status") or "review")
            decision = str(geofm_report.get("decision") or "review_required")
            vector_inventory = dict((geofm_report.get("summary") or {}).get("vector_inventory") or {})
        else:
            vector_inventory = self._geofm_vector_inventory(state)
            gate_status = "review"
            decision = "run_geofm_ablation_gate_before_using_embeddings"
        return {
            "schema": "territory_world_model.geofm_state_gate_policy.v1",
            "gate_status": gate_status,
            "decision": decision,
            "vector_inventory": vector_inventory,
            "default_role": "optional_enhancement",
            "retention_rule": "retain GeoFM embeddings only when B0/B1 downstream planning lift passes evidence gate",
            "state_encoder_policy": "explicit GIS features remain primary; GeoFM embedding is gated and ablatable",
        }

    def _state_contract_claim_boundary(
        self,
        *,
        token_contract: dict[str, Any],
        constraint_channels: dict[str, Any],
        temporal_support: dict[str, Any],
        geofm_policy: dict[str, Any],
    ) -> dict[str, Any]:
        missing = list(token_contract.get("missing_required_levels") or [])
        review_levels = list(token_contract.get("review_required_levels") or [])
        blockers: list[str] = []
        review: list[str] = []
        if missing:
            blockers.append("missing_required_hierarchy_tokens")
        if review_levels:
            review.append("review_required_hierarchy_tokens")
        if constraint_channels.get("evidence_item_count", 0) == 0:
            blockers.append("no_evidence_items")
        if constraint_channels.get("open_review_task_count", 0) > 0:
            review.append("open_review_tasks")
        if not temporal_support.get("history_delta_available"):
            review.append("history_delta_missing")
        elif temporal_support.get("status") != "pass":
            review.append("history_delta_review_only")
        if geofm_policy.get("gate_status") != "pass":
            review.append("geofm_not_promoted")
        status = "blocked" if blockers else "review" if review else "pass"
        return {
            "status": status,
            "claim_scope": "state_contract_ready_for_trainable_dynamics" if status == "pass" else "contract_or_review_only" if status == "review" else "insufficient_for_hierarchical_twm",
            "blockers": blockers,
            "review_items": review,
            "allowed_claims": [
                "hierarchical_state_scaffold",
                "deterministic_forecast_contract",
                "review_gated_planning_consumer",
            ]
            + (["trainable_dynamics_input_contract"] if status in {"pass", "review"} else []),
            "disallowed_claims": [
                "flat_vector_world_model",
                "ungated_geofm_world_model",
                "production_ready_trainable_dynamics",
            ],
        }

    def _state_contract_recommendations(
        self,
        *,
        token_contract: dict[str, Any],
        constraint_channels: dict[str, Any],
        temporal_support: dict[str, Any],
        geofm_policy: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        missing = list(token_contract.get("missing_required_levels") or [])
        if missing:
            recommendations.append(f"add explicit hierarchical token inputs for: {', '.join(missing)}")
        review_levels = list(token_contract.get("review_required_levels") or [])
        if review_levels:
            recommendations.append(f"replace review-level hierarchy proxies with authoritative tokens for: {', '.join(review_levels)}")
        if constraint_channels.get("open_review_task_count", 0) > 0:
            recommendations.append("resolve open review tasks before promoting the state contract to production training")
        if not temporal_support.get("history_delta_available"):
            recommendations.append("add observed state_snapshots.csv or equivalent temporal transitions for history_delta supervision")
        elif temporal_support.get("status") != "pass":
            recommendations.append("separate synthetic/not-for-production temporal rows from trainable history_delta labels")
        if geofm_policy.get("gate_status") != "pass":
            recommendations.append("run GeoFM B0/B1 downstream planning ablation before enabling embeddings in the state encoder")
        if not recommendations:
            recommendations.append("use this state contract as the canonical input schema for dynamics training and beam planning")
        return recommendations

    def _action_from_payload(self, payload: dict[str, Any]) -> TerritoryWorldModelAction:
        return TerritoryWorldModelAction(
            action_type=str(payload.get("action_type") or "inspect"),
            target_role=str(payload.get("target_role") or "project"),
            target_objects=[str(item) for item in payload.get("target_objects") or []],
            spatial_scope=dict(payload.get("spatial_scope") or {}),
            magnitude=float(payload.get("magnitude") or 1.0),
            scenario=str(payload.get("scenario") or "baseline"),
            description=str(payload.get("description") or ""),
            legal_intent=str(payload.get("legal_intent") or ""),
            execution_mask=dict(payload.get("execution_mask") or {}),
            parameters=dict(payload.get("parameters") or {}),
            treatment=str(payload.get("treatment") or ""),
        )

    def list_projects_summary(self) -> dict[str, Any]:
        projects = self.list_projects()
        bindings = [item.to_dict() for item in self.repository.list_layer_bindings()]
        states = [item.to_dict() for item in self.repository.list_state_versions()]
        return {
            "projects": projects,
            "layer_bindings": bindings,
            "states": states,
            "counts": {
                "project_count": len(projects),
                "layer_binding_count": len(bindings),
                "state_count": len(states),
            },
        }


def get_territory_world_model_service() -> TerritoryWorldModelService:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = TerritoryWorldModelService()
    return _INSTANCE


def reset_territory_world_model_service() -> None:
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None
