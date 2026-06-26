from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from shapely.geometry.base import BaseGeometry
except Exception:  # pragma: no cover - shapely is an optional runtime dep in some contexts
    BaseGeometry = object  # type: ignore[misc,assignment]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, UUIDLike):
        return str(value)
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__geo_interface__"):
        return value.__geo_interface__
    if isinstance(value, BaseGeometry):
        try:
            return value.wkt
        except Exception:
            return str(value)
    return value


class UUIDLike(str):
    pass


def _uuid() -> str:
    return str(uuid4())


@dataclass
class TwmProject:
    id: str = field(default_factory=_uuid)
    name: str = ""
    description: str = ""
    region_code: str = ""
    business_scenario: str = "planning_supervision"
    owner_username: str = ""
    status: str = "draft"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)
    updated_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmLayerBinding:
    id: str = field(default_factory=_uuid)
    project_id: str = ""
    role: str = ""
    canonical_role: str = ""
    object_type: str = ""
    layer_alias: str = ""
    source_path: str = ""
    semantic_product_path: str = ""
    asset_id: int | None = None
    time_label: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    field_mapping: dict[str, str] = field(default_factory=dict)
    quality_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False
    not_for_production: bool = False
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmStateVersion:
    id: str = field(default_factory=_uuid)
    project_id: str = ""
    state_time: str = field(default_factory=now_utc_iso)
    label: str = ""
    source_manifest: dict[str, Any] = field(default_factory=dict)
    rule_set_id: str | None = None
    object_count: int = 0
    relation_count: int = 0
    quality_summary: dict[str, Any] = field(default_factory=dict)
    build_status: str = "building"
    build_log: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmStateObject:
    id: str = field(default_factory=_uuid)
    state_version_id: str = ""
    object_type: str = ""
    object_code: str = ""
    source_role: str = ""
    source_asset_id: int | None = None
    source_feature_id: str | None = None
    source_path: str = ""
    canonical_role: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    semantic_tags: list[str] = field(default_factory=list)
    quality_score: float | None = None
    synthetic: bool = False
    not_for_production: bool = False
    qa_use_for_rules: bool = True
    geometry_crs: str = "EPSG:4326"
    geom: Any | None = None
    bbox: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmStateRelation:
    id: str = field(default_factory=_uuid)
    state_version_id: str = ""
    subject_object_id: str = ""
    predicate: str = ""
    object_object_id: str = ""
    relation_type: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    geom: Any | None = None
    source_subject_role: str = ""
    source_target_role: str = ""
    synthetic: bool = False
    not_for_production: bool = False

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmRuleSet:
    id: str = field(default_factory=_uuid)
    name: str = ""
    version_label: str = ""
    source_std_version_id: str | None = None
    status: str = "draft"
    created_by: str = ""
    approved_by: str | None = None
    approved_at: str | None = None
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmPolicyRule:
    id: str = field(default_factory=_uuid)
    rule_set_id: str = ""
    rule_code: str = ""
    title: str = ""
    category: str = ""
    severity: str = "medium"
    rule_body: dict[str, Any] = field(default_factory=dict)
    legal_basis: dict[str, Any] = field(default_factory=dict)
    review_policy: str = "review_required"
    enabled: bool = True
    std_derived_link_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)
    updated_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmRuleHit:
    id: str = field(default_factory=_uuid)
    state_version_id: str = ""
    rule_id: str = ""
    subject_object_id: str = ""
    target_object_id: str | None = None
    hit_status: str = "open"
    severity: str = "medium"
    risk_score: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    geom: Any | None = None
    created_at: str = field(default_factory=now_utc_iso)
    reviewed_at: str | None = None
    review_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmEvidenceItem:
    id: str = field(default_factory=_uuid)
    rule_hit_id: str = ""
    evidence_type: str = ""
    source_system: str = "twm"
    source_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    checksum: str | None = None
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmReviewTask:
    id: str = field(default_factory=_uuid)
    rule_hit_id: str = ""
    assignee: str | None = None
    status: str = "pending"
    decision: str = ""
    comment: str = ""
    created_at: str = field(default_factory=now_utc_iso)
    updated_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmScenario:
    id: str = field(default_factory=_uuid)
    project_id: str = ""
    base_state_version_id: str = ""
    name: str = ""
    scenario_type: str = "baseline"
    input_changes: dict[str, Any] = field(default_factory=dict)
    source_model: str | None = None
    status: str = "draft"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmScenarioMetric:
    id: str = field(default_factory=_uuid)
    scenario_id: str = ""
    metric_code: str = ""
    metric_name: str = ""
    value: float = 0.0
    unit: str = ""
    benchmark_value: float | None = None
    direction: str = "lower_better"
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TerritoryWorldModelAction:
    action_type: str = "inspect"
    target_role: str = ""
    target_objects: list[str] = field(default_factory=list)
    spatial_scope: dict[str, Any] = field(default_factory=dict)
    magnitude: float = 1.0
    scenario: str = "baseline"
    description: str = ""
    legal_intent: str = ""
    execution_mask: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    treatment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TerritoryWorldModelForecast:
    action: TerritoryWorldModelAction = field(default_factory=TerritoryWorldModelAction)
    future_latent_state: dict[str, Any] = field(default_factory=dict)
    constraint_violation_probability: float = 0.0
    planning_utility_delta: float = 0.0
    uncertainty: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmScenarioPlan:
    state_version_id: str = ""
    action: TerritoryWorldModelAction = field(default_factory=TerritoryWorldModelAction)
    forecast: TerritoryWorldModelForecast = field(default_factory=TerritoryWorldModelForecast)
    candidate_metrics: list[TwmScenarioMetric] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmRolloutStep:
    step_index: int = 0
    arm: str = "baseline"
    action: TerritoryWorldModelAction = field(default_factory=TerritoryWorldModelAction)
    forecast: TerritoryWorldModelForecast = field(default_factory=TerritoryWorldModelForecast)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmCounterfactualRollout:
    state_version_id: str = ""
    scenario: str = "baseline"
    horizon: int = 1
    baseline_action: TerritoryWorldModelAction = field(default_factory=TerritoryWorldModelAction)
    intervention_actions: list[TerritoryWorldModelAction] = field(default_factory=list)
    baseline_steps: list[TwmRolloutStep] = field(default_factory=list)
    intervention_steps: list[TwmRolloutStep] = field(default_factory=list)
    deltas: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    calibration_summary: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmValidationStage:
    stage_code: str = ""
    stage_name: str = ""
    status: str = "review"
    claim: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmValidationReport:
    state_version_id: str = ""
    project_id: str = ""
    overall_status: str = "review"
    stages: list[TwmValidationStage] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmWorldModelCapability:
    axis: str = ""
    status: str = "review"
    interpretation: str = ""
    core_algorithm: dict[str, Any] = field(default_factory=dict)
    implemented_components: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmWorldModelProfile:
    state_version_id: str = ""
    project_id: str = ""
    taxonomy: str = "rendering_simulation_planning_evidence"
    capabilities: list[TwmWorldModelCapability] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmDynamicsTrainingExample:
    id: str = field(default_factory=_uuid)
    state_version_id: str = ""
    project_id: str = ""
    split: str = "candidate"
    sample_type: str = "action_conditioned_rollout"
    current_state_summary: dict[str, Any] = field(default_factory=dict)
    action: TerritoryWorldModelAction = field(default_factory=TerritoryWorldModelAction)
    scenario_context: dict[str, Any] = field(default_factory=dict)
    targets: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)
    losses: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    not_for_training_reasons: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmDynamicsTrainingDataset:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.dynamics_training_dataset.v1"
    examples: list[TwmDynamicsTrainingExample] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmDynamicsReadinessReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.dynamics_readiness_report.v1"
    status: str = "review"
    training_scope: str = "contract_only"
    sample_inventory: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    gate_results: dict[str, Any] = field(default_factory=dict)
    target_model_contract: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmDynamicsEvaluationReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.dynamics_evaluation_report.v1"
    status: str = "review"
    candidate: dict[str, Any] = field(default_factory=dict)
    evaluation_scope: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    target_head_metrics: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    sample_inventory: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmDynamicsFitReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.dynamics_fit_report.v1"
    status: str = "review"
    candidate: dict[str, Any] = field(default_factory=dict)
    readiness: dict[str, Any] = field(default_factory=dict)
    learned_parameters: dict[str, Any] = field(default_factory=dict)
    predictions: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmStateContractReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.state_contract_report.v1"
    status: str = "review"
    hierarchy: dict[str, Any] = field(default_factory=dict)
    feature_channels: dict[str, Any] = field(default_factory=dict)
    constraint_channels: dict[str, Any] = field(default_factory=dict)
    temporal_support: dict[str, Any] = field(default_factory=dict)
    geofm_policy: dict[str, Any] = field(default_factory=dict)
    downstream_consumers: list[str] = field(default_factory=list)
    claim_ladder: dict[str, Any] = field(default_factory=dict)
    claim_boundary: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmDynamicsBackendReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.dynamics_backend_report.v1"
    status: str = "review"
    backend: dict[str, Any] = field(default_factory=dict)
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    adapter_contract: dict[str, Any] = field(default_factory=dict)
    gate_results: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    claim_boundary: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmTrainingObjectiveReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.training_objective_report.v1"
    status: str = "review"
    objective_contract: dict[str, Any] = field(default_factory=dict)
    loss_components: dict[str, Any] = field(default_factory=dict)
    ranking_diagnostics: dict[str, Any] = field(default_factory=dict)
    calibration_diagnostics: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    sample_inventory: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmTrainDynamicsReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.train_dynamics_report.v1"
    status: str = "review"
    trainer: dict[str, Any] = field(default_factory=dict)
    objective: dict[str, Any] = field(default_factory=dict)
    learned_parameters: dict[str, Any] = field(default_factory=dict)
    predictions: dict[str, Any] = field(default_factory=dict)
    candidate_report: dict[str, Any] = field(default_factory=dict)
    backend_report: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmBeamPlanReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.beam_plan_report.v1"
    scenario: str = "baseline"
    status: str = "review"
    ranking_policy: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    ranking: list[dict[str, Any]] = field(default_factory=list)
    selected: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmGeoFMGateVariant:
    variant_id: str = ""
    label: str = ""
    uses_geofm: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmGeoFMGateReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.geofm_ablation_gate.v1"
    gate_status: str = "review"
    decision: str = "review_required"
    baseline: TwmGeoFMGateVariant = field(default_factory=TwmGeoFMGateVariant)
    augmented: TwmGeoFMGateVariant = field(default_factory=TwmGeoFMGateVariant)
    deltas: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmGeoFMDownstreamExperimentReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.geofm_downstream_experiment_report.v1"
    status: str = "review"
    experiment: dict[str, Any] = field(default_factory=dict)
    variants: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    gate_report: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmCausalCalibrationReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.causal_calibration_report.v1"
    status: str = "review"
    method: str = "stratified_observational_calibration"
    identification_strength: str = "observational"
    identification_note: str = "local calibration uses observed treatment/control histories and does not by itself prove randomized intervention effects"
    treatment: dict[str, Any] = field(default_factory=dict)
    outcome: dict[str, Any] = field(default_factory=dict)
    estimate: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmActionMaskReport:
    state_version_id: str = ""
    project_id: str = ""
    schema: str = "territory_world_model.action_mask_report.v1"
    action: TerritoryWorldModelAction = field(default_factory=TerritoryWorldModelAction)
    allowed: bool = True
    execution_mask: dict[str, Any] = field(default_factory=dict)
    target_summary: dict[str, Any] = field(default_factory=dict)
    blocking_hits: list[dict[str, Any]] = field(default_factory=list)
    required_reviews: list[dict[str, Any]] = field(default_factory=list)
    evidence_gate: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmScenarioSummary:
    scenario_id: str = ""
    metric_count: int = 0
    objective_count: int = 0
    constraint_violation_count: int = 0
    utility_delta: float = 0.0
    uncertainty: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmAuditReport:
    project_id: str = ""
    state_version_id: str = ""
    report_type: str = "territory_world_model_audit"
    rule_hit_count: int = 0
    confirmed_count: int = 0
    dismissed_count: int = 0
    mitigation_count: int = 0
    evidence_gate_passed: bool = False
    evidence_gate_summary: dict[str, Any] = field(default_factory=dict)
    source_summary: dict[str, Any] = field(default_factory=dict)
    rule_summary: dict[str, Any] = field(default_factory=dict)
    state_summary: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmRelationSpec:
    relation_type: str
    subject_roles: list[str]
    target_roles: list[str]
    predicate: str = "intersects"
    twm_usage: str = ""
    objective_id: str = ""
    rule_id: str | None = None
    evidence_type: str = "spatial_overlay"
    severity: str = "medium"
    review_policy: str = "review_required"
    min_overlap_area_m2: float = 0.0
    min_overlap_ratio: float = 0.0
    max_distance_m: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class StateBuildResult:
    project: TwmProject = field(default_factory=TwmProject)
    state_version: TwmStateVersion = field(default_factory=TwmStateVersion)
    objects: list[TwmStateObject] = field(default_factory=list)
    relations: list[TwmStateRelation] = field(default_factory=list)
    object_counts_by_role: dict[str, int] = field(default_factory=dict)
    relation_counts_by_type: dict[str, int] = field(default_factory=dict)
    hierarchy_tokens: dict[str, Any] = field(default_factory=dict)
    quality_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    relation_specs: list[TwmRelationSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmRuleEvaluationResult:
    state_version_id: str = ""
    rule_set_id: str = ""
    hits: list[TwmRuleHit] = field(default_factory=list)
    evidence_items: list[TwmEvidenceItem] = field(default_factory=list)
    review_tasks: list[TwmReviewTask] = field(default_factory=list)
    severity_distribution: dict[str, int] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmSemanticBundle:
    root_dir: Path = field(default_factory=Path)
    manifest_path: Path | None = None
    contract_path: Path | None = None
    relations_path: Path | None = None
    state_input_path: Path | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    contract: dict[str, Any] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)
    layer_bindings: list[TwmLayerBinding] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    source_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass
class TwmStateSource:
    id: str = field(default_factory=_uuid)
    role: str = ""
    source_path: str = ""
    semantic_product_path: str = ""
    asset_id: int | None = None
    object_type: str = ""
    canonical_role: str = ""
    field_mapping: dict[str, str] = field(default_factory=dict)
    quality_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False
    not_for_production: bool = False

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)
