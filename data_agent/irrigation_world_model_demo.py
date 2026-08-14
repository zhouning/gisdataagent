"""Backend-authoritative irrigation scenario service for ODIWM.

The service is deliberately conservative: it runs a deterministic synthetic
network balance, records the semantic and model versions used, and produces a
reviewable Proposal. It is an integration reference, not a calibrated
hydrodynamic model and never exposes a device-control operation.
"""

from __future__ import annotations

import copy
import math
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .irrigation_hydrodynamic_model import run_dynamic_wave_scenario
from .irrigation_world_model_repository import (
    IrrigationPersistenceConflict,
    IrrigationPersistenceError,
    IrrigationPersistenceNotFound,
    PostgresIrrigationWorldModelRepository,
)
from .ontology.package_reader import OntologyPackageReader


class IrrigationWorldModelError(RuntimeError):
    status_code = 400


class IrrigationWorldModelNotFound(IrrigationWorldModelError):
    status_code = 404


class IrrigationWorldModelConflict(IrrigationWorldModelError):
    status_code = 409


class IrrigationWorldModelUnavailable(IrrigationWorldModelError):
    status_code = 503


ONTOLOGY_PROFILE = {
    "profile_id": "irrigation-district-water",
    "version": "0.1.0",
    "label": "灌区与水利工程本体（待领域审定）",
    "schema": "gda.irrigation-ontology-profile.v1",
    "authority": "hash_verified_immutable_package",
    "lifecycle_status": "draft_pending_domain_review",
    "namespace_uri": "https://ontology.gis-data-agent.local/water/irrigation/",
    "scope": "candidate_irrigation_domain_model",
    "ontology_api": "/api/ontologies/irrigation-district-water",
    "semantic_contract": [
        "Object",
        "Link",
        "State",
        "Action",
        "Constraint",
        "Evidence",
    ],
    "object_types": [
        {"type": "Reservoir", "label": "水库", "required_states": ["available_supply"]},
        {"type": "CanalSegment", "label": "渠段", "required_states": ["flow_rate"]},
        {"type": "ControlGate", "label": "控制闸", "required_states": ["allocation_ratio"]},
        {"type": "FieldBlock", "label": "田块", "required_states": ["water_demand"]},
    ],
    "link_types": [
        {"predicate": "flows_to", "directed": True, "meaning": "水流拓扑"},
        {"predicate": "supplies", "directed": True, "meaning": "供水关系"},
        {"predicate": "controls", "directed": True, "meaning": "控制关系"},
        {"predicate": "contains", "directed": True, "meaning": "组成关系"},
    ],
    "state_types": [
        {"type": "available_supply", "quantity": "volume_per_time", "unit": "m3/d"},
        {"type": "flow_rate", "quantity": "volume_per_time", "unit": "m3/d"},
        {"type": "allocation_ratio", "quantity": "dimensionless", "unit": "percent"},
        {"type": "water_demand", "quantity": "volume_per_time", "unit": "m3/d"},
    ],
    "action_types": [
        {"type": "SetBoundarySupply", "target_type": "Reservoir", "execution": "proposal_only"},
        {
            "type": "ShiftDeliveryWindow",
            "target_type": "CanalSegment",
            "execution": "proposal_only",
        },
        {"type": "SetBranchAllocation", "target_type": "ControlGate", "execution": "proposal_only"},
    ],
    "constraints": [
        {"type": "MassBalance", "severity": "hard", "scope": "network"},
        {"type": "CanalCapacity", "severity": "hard", "scope": "CanalSegment"},
        {"type": "ActionRange", "severity": "hard", "scope": "Action"},
    ],
    "evidence_requirements": [
        "stable_object_id",
        "source_authority",
        "effective_time",
        "quality_status",
        "model_version",
    ],
}
_ONTOLOGY_PACKAGE_MANIFEST = OntologyPackageReader(
    ontology_key="irrigation-district-water"
).manifest
ONTOLOGY_PROFILE["version"] = _ONTOLOGY_PACKAGE_MANIFEST.semantic_version
ONTOLOGY_PROFILE["package_id"] = _ONTOLOGY_PACKAGE_MANIFEST.package_id
ONTOLOGY_PROFILE["content_sha256"] = _ONTOLOGY_PACKAGE_MANIFEST.content_sha256

NODES = [
    {
        "id": "R1",
        "stable_id": "irrigation:R1",
        "label": "青源水库",
        "type": "Reservoir",
        "role": "供水源",
        "state": "可供水量",
        "value": "960 m³/d",
        "capacity": 1100,
        "children": ["C1"],
    },
    {
        "id": "C1",
        "stable_id": "irrigation:C1",
        "label": "总干渠",
        "type": "CanalSegment",
        "role": "主输水通道",
        "state": "入口流量",
        "value": "按情景变化",
        "capacity": 1000,
        "children": ["C2", "C3"],
    },
    {
        "id": "C2",
        "stable_id": "irrigation:C2",
        "label": "东支渠",
        "type": "CanalSegment",
        "role": "东向输水",
        "state": "分配流量",
        "value": "按比例分配",
        "capacity": 520,
        "children": ["D1"],
    },
    {
        "id": "C3",
        "stable_id": "irrigation:C3",
        "label": "西支渠",
        "type": "CanalSegment",
        "role": "西向输水",
        "state": "分配流量",
        "value": "按比例分配",
        "capacity": 480,
        "children": ["D2"],
    },
    {
        "id": "D1",
        "stable_id": "irrigation:D1",
        "label": "东一分水口",
        "type": "ControlGate",
        "role": "东支渠控制点",
        "state": "目标比例",
        "value": "45-55%",
        "children": ["F1", "F2"],
    },
    {
        "id": "D2",
        "stable_id": "irrigation:D2",
        "label": "西一分水口",
        "type": "ControlGate",
        "role": "西支渠控制点",
        "state": "目标比例",
        "value": "45-55%",
        "children": ["F3", "F4"],
    },
    {
        "id": "F1",
        "stable_id": "irrigation:F1",
        "label": "田块 F1",
        "type": "FieldBlock",
        "role": "东支渠末端",
        "state": "需水量",
        "value": "170 m³/d",
    },
    {
        "id": "F2",
        "stable_id": "irrigation:F2",
        "label": "田块 F2",
        "type": "FieldBlock",
        "role": "东支渠中段",
        "state": "需水量",
        "value": "150 m³/d",
    },
    {
        "id": "F3",
        "stable_id": "irrigation:F3",
        "label": "田块 F3",
        "type": "FieldBlock",
        "role": "西支渠中段",
        "state": "需水量",
        "value": "210 m³/d",
    },
    {
        "id": "F4",
        "stable_id": "irrigation:F4",
        "label": "田块 F4",
        "type": "FieldBlock",
        "role": "西支渠末端",
        "state": "需水量",
        "value": "190 m³/d",
    },
]

LINKS = [
    {
        "subject": "R1",
        "predicate": "flows_to",
        "object": "C1",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "R1",
        "predicate": "supplies",
        "object": "C1",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "C1",
        "predicate": "flows_to",
        "object": "C2",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "C1",
        "predicate": "flows_to",
        "object": "C3",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "C1",
        "predicate": "contains",
        "object": "C2",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "C1",
        "predicate": "contains",
        "object": "C3",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "D1",
        "predicate": "controls",
        "object": "C2",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "D2",
        "predicate": "controls",
        "object": "C3",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "D1",
        "predicate": "supplies",
        "object": "F1",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "D1",
        "predicate": "supplies",
        "object": "F2",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "D2",
        "predicate": "supplies",
        "object": "F3",
        "authority": "synthetic_topology_v0.1",
    },
    {
        "subject": "D2",
        "predicate": "supplies",
        "object": "F4",
        "authority": "synthetic_topology_v0.1",
    },
]

FIELD_DEMAND = {"F1": 170.0, "F2": 150.0, "F3": 210.0, "F4": 190.0}
FIELD_BRANCH = {"F1": "east", "F2": "east", "F3": "west", "F4": "west"}
FIELD_ORDER = ("F1", "F2", "F3", "F4")
MODES = (
    {"id": "baseline", "label": "Baseline", "note": "不调整"},
    {"id": "candidateA", "label": "Candidate A", "note": "仅时段调整"},
    {"id": "candidateB", "label": "Candidate B", "note": "时段 + 比例"},
)
MODE_LABELS = {mode["id"]: mode["label"] for mode in MODES}
DEFAULT_PARAMETERS = {
    "supply_drop_percent": 20.0,
    "west_shift_hours": 6,
    "candidate_east_ratio_percent": 45.0,
    "horizon_hours": 24,
}

STATE_SNAPSHOT = {
    "snapshot_id": "synthetic_state_snapshot_v0.1.0",
    "effective_at": "2026-08-14T00:00:00+08:00",
    "kind": "synthetic_scenario_state",
    "facts": 8,
    "estimates": 1,
    "observations_available": 8,
    "observations_expected": 9,
    "topology_status": "validated_for_reference_network",
    "parameter_status": "not_calibrated",
    "quality_label": "拓扑通过 · 观测 8/9 · 参数未校准",
}

REGISTERED_FUNCTIONS = [
    {
        "function_id": "manning_kinematic_storage_route",
        "version": "1.0",
        "role": "按 Manning 参数推导传播时间并执行有状态渠段蓄泄演算",
    },
    {
        "function_id": "action_conditioned_network_rollout",
        "version": "1.0",
        "role": "在同一状态快照上执行调度行动条件化反事实推演",
    },
    {"function_id": "continuity_ledger", "version": "1.0", "role": "逐步水量连续方程审计"},
    {
        "function_id": "hard_constraint_check",
        "version": "1.0",
        "role": "容量、动作范围与水量账门禁",
    },
    {"function_id": "candidate_comparison", "version": "1.0", "role": "同一冻结输入下比较有限候选"},
]

CLAIM_BOUNDARY = {
    "data": "synthetic_seed_dataset",
    "claim": "model_conditioned_scenario_only",
    "calibration": "not_calibrated_for_real_irrigation_district",
    "control": "proposal_only_no_device_execution",
    "excluded_claims": [
        "真实灌区预测精度",
        "动作因果收益",
        "全局最优调度",
        "跨灌区直接迁移",
        "生产控制安全性",
    ],
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(now: datetime | None = None) -> tuple[str, str]:
    value = now or _utc_now()
    return value.isoformat().replace("+00:00", "Z"), value.astimezone().strftime("%H:%M:%S")


def _audit_event(step: str, status: str, detail: str) -> dict[str, str]:
    timestamp, display_time = _timestamp()
    return {
        "timestamp": timestamp,
        "time": display_time,
        "step": step,
        "status": status,
        "detail": detail,
    }


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IrrigationWorldModelError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < low or result > high:
        raise IrrigationWorldModelError(f"{name} must be between {low:g} and {high:g}")
    return result


def _validated_parameters(payload: dict[str, Any]) -> dict[str, float | int]:
    if not isinstance(payload, dict):
        raise IrrigationWorldModelError("request body must be an object")
    supply_drop = _number(payload.get("supply_drop_percent", 20), "supply_drop_percent", 0, 40)
    west_shift = _number(payload.get("west_shift_hours", 6), "west_shift_hours", 0, 12)
    east_ratio = _number(
        payload.get("candidate_east_ratio_percent", 45), "candidate_east_ratio_percent", 40, 60
    )
    horizon = payload.get("horizon_hours", 24)
    if (
        isinstance(horizon, bool)
        or not isinstance(horizon, (int, float))
        or int(horizon) != horizon
        or int(horizon) not in {6, 12, 24}
    ):
        raise IrrigationWorldModelError("horizon_hours must be one of 6, 12, or 24")
    if int(west_shift) != west_shift or int(west_shift) % 2:
        raise IrrigationWorldModelError("west_shift_hours must be an even whole number")
    return {
        "supply_drop_percent": supply_drop,
        "west_shift_hours": int(west_shift),
        "candidate_east_ratio_percent": east_ratio,
        "horizon_hours": int(horizon),
    }


def _west_delay(mode: str, west_shift: int) -> float:
    return max(
        2.0, 12.0 - (0 if mode == "baseline" else west_shift) - (2 if mode == "candidateB" else 0)
    )


def _legacy_reference_scenario(mode: str, parameters: dict[str, float | int]) -> dict[str, Any]:
    """Run the deterministic, mass-conserving synthetic scenario kernel."""
    if mode not in MODE_LABELS:
        raise IrrigationWorldModelError(f"unsupported scenario mode: {mode}")
    supply_drop = float(parameters["supply_drop_percent"])
    west_shift = int(parameters["west_shift_hours"])
    east_ratio_input = float(parameters["candidate_east_ratio_percent"])
    horizon = int(parameters["horizon_hours"])

    reservoir_available = 960.0 * (1.0 - supply_drop / 100.0)
    trunk_efficiency = 0.96
    trunk_output = reservoir_available * trunk_efficiency
    branch_ratio = max(0.40, min(0.60, east_ratio_input / 100.0)) if mode == "candidateB" else 0.55
    west_efficiency = min(0.88, 0.82 + (0 if mode == "baseline" else west_shift * 0.005))
    east_output = trunk_output * branch_ratio
    west_output = trunk_output - east_output
    east_delivered = east_output * 0.90
    west_delivered = west_output * west_efficiency
    east_demand = FIELD_DEMAND["F1"] + FIELD_DEMAND["F2"]
    west_demand = FIELD_DEMAND["F3"] + FIELD_DEMAND["F4"]

    fields: dict[str, dict[str, float]] = {}
    for field_id in FIELD_ORDER:
        demand = FIELD_DEMAND[field_id]
        branch = FIELD_BRANCH[field_id]
        branch_total_demand = east_demand if branch == "east" else west_demand
        branch_delivered = east_delivered if branch == "east" else west_delivered
        delivered = min(demand, branch_delivered * demand / branch_total_demand)
        fields[field_id] = {
            "demand": demand,
            "delivered": delivered,
            "coverage": delivered / demand,
        }

    delivered_total = sum(item["delivered"] for item in fields.values())
    coverage = [item["coverage"] for item in fields.values()]
    mean = sum(coverage) / len(coverage)
    fairness_cv = (
        math.sqrt(sum((value - mean) ** 2 for value in coverage) / len(coverage)) / mean
        if mean
        else 0.0
    )
    capacity_violations = int(east_output > 520.0 + 1e-6) + int(west_output > 480.0 + 1e-6)
    trunk_loss = reservoir_available - trunk_output
    branch_loss = east_output - east_delivered + west_output - west_delivered
    unallocated = max(0.0, east_delivered - east_demand) + max(0.0, west_delivered - west_demand)
    residual = reservoir_available - trunk_loss - branch_loss - delivered_total - unallocated
    if abs(residual) < 0.0001:
        residual = 0.0

    node_states = {
        "R1": {"value": reservoir_available, "unit": "m³/d"},
        "C1": {"value": trunk_output, "unit": "m³/d"},
        "C2": {"value": east_output, "unit": "m³/d"},
        "C3": {"value": west_output, "unit": "m³/d"},
        "D1": {"value": branch_ratio * 100.0, "unit": "%"},
        "D2": {"value": (1.0 - branch_ratio) * 100.0, "unit": "%"},
        **{
            field_id: {
                "value": fields[field_id]["delivered"],
                "unit": "m³/d",
                "demand": fields[field_id]["demand"],
            }
            for field_id in FIELD_ORDER
        },
    }

    west_delay = _west_delay(mode, west_shift)
    timeline = []
    for hour in range(0, horizon + 1, 6):
        arrival = min(1.0, (hour + 6) / (west_delay + 6))
        tail_coverage = min(100.0, max(0.0, min(coverage) * 100.0 * (0.42 + 0.58 * arrival)))
        shortage = max(0.0, (east_demand + west_demand - delivered_total) * (1.15 - 0.45 * arrival))
        status = "等待到达" if arrival < 0.55 else "部分到达" if arrival < 0.95 else "可评估"
        timeline.append(
            {"hour": hour, "tailCoverage": tail_coverage, "shortage": shortage, "status": status}
        )

    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "branchRatio": branch_ratio,
        "delivered": delivered_total,
        "shortage": max(0.0, east_demand + west_demand - delivered_total),
        "tailCoverage": min(coverage) * 100.0,
        "fairnessCv": fairness_cv,
        "capacityViolations": capacity_violations,
        "residual": residual,
        "westDelay": west_delay,
        "westEfficiency": west_efficiency,
        "fields": fields,
        "nodeStates": node_states,
        "timeline": timeline,
        "waterBalance": {
            "boundarySupply": reservoir_available,
            "trunkLoss": trunk_loss,
            "branchLoss": branch_loss,
            "delivered": delivered_total,
            "unallocated": unallocated,
            "residual": residual,
        },
    }


def calculate_scenario(mode: str, parameters: dict[str, float | int]) -> dict[str, Any]:
    """Execute the stateful, action-conditioned irrigation rollout."""
    try:
        return run_dynamic_wave_scenario(mode, parameters)
    except (FloatingPointError, ValueError) as exc:
        raise IrrigationWorldModelError(f"irrigation model execution failed: {exc}") from exc


def _rank_scenarios(results: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ranked = []
    for result in results:
        feasible = (
            result["capacityViolations"] == 0
            and abs(result.get("residualVolumeM3", 0.0)) < 0.01
        )
        score = (
            float(result["shortageVolumeM3"])
            + 72.0 * float(result["fairnessCv"])
            + 10_000.0 * int(result["capacityViolations"])
            + 100.0 * abs(float(result.get("residualVolumeM3", 0.0)))
        )
        ranked.append(
            {
                "mode": result["mode"],
                "feasible": feasible,
                "objective": score,
                "shortage_volume_m3": result["shortageVolumeM3"],
                "fairness_cv": result["fairnessCv"],
            }
        )
    ranked.sort(key=lambda item: (not item["feasible"], item["objective"], item["mode"]))
    selected_mode = ranked[0]["mode"]
    return next(result for result in results if result["mode"] == selected_mode), ranked


def _planner_contract(
    results: list[dict[str, Any]],
    fallback_mode: str = "baseline",
    evidence_origin: str = "persisted",
) -> dict[str, Any]:
    """Build planner evidence, including for rows written before migration 165."""
    try:
        selected, ranking = _rank_scenarios(results)
    except (KeyError, TypeError, ValueError, StopIteration):
        selected = {"mode": fallback_mode}
        ranking = []
    return {
        "planner_id": "bounded-candidate-enumeration",
        "version": "1.0",
        "selected_mode": selected["mode"],
        "ranking": ranking,
        "global_optimum_claimed": False,
        "evidence_origin": evidence_origin if ranking else "legacy_run_reconstruction",
    }


@dataclass
class InMemoryIrrigationRunRepository:
    """Thread-safe test fixture; the formal service uses PostgreSQL."""

    max_runs_per_actor: int = 50
    _runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    _proposal_to_run: dict[str, str] = field(default_factory=dict)
    _actor_runs: dict[str, list[str]] = field(default_factory=dict)
    _actor_versions: dict[str, int] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def save(self, run: dict[str, Any], _tenant_id: str = "local-dev") -> dict[str, Any]:
        run_copy = copy.deepcopy(run)
        actor = run_copy["actor"]
        run_id = run_copy["run_id"]
        proposal_id = run_copy["proposal"]["proposal_id"]
        with self._lock:
            self._runs[run_id] = run_copy
            self._proposal_to_run[proposal_id] = run_id
            actor_runs = self._actor_runs.setdefault(actor, [])
            if run_id not in actor_runs:
                actor_runs.append(run_id)
            while len(actor_runs) > self.max_runs_per_actor:
                expired = actor_runs.pop(0)
                expired_run = self._runs.pop(expired, None)
                if expired_run:
                    self._proposal_to_run.pop(expired_run["proposal"]["proposal_id"], None)
        return copy.deepcopy(run_copy)

    def get(self, run_id: str, actor: str, _tenant_id: str = "local-dev") -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run["actor"] != actor:
                raise IrrigationWorldModelNotFound("irrigation scenario run not found")
            return copy.deepcopy(run)

    def latest(self, actor: str, _tenant_id: str = "local-dev") -> dict[str, Any] | None:
        with self._lock:
            ids = self._actor_runs.get(actor, [])
            return copy.deepcopy(self._runs[ids[-1]]) if ids else None

    def next_version(self, actor: str, _tenant_id: str = "local-dev") -> int:
        with self._lock:
            version = self._actor_versions.get(actor, 0) + 1
            self._actor_versions[actor] = version
            return version

    def update_proposal(
        self, proposal_id: str, actor: str, decision: str, note: str, _tenant_id: str = "local-dev"
    ) -> dict[str, Any]:
        with self._lock:
            run_id = self._proposal_to_run.get(proposal_id)
            run = self._runs.get(run_id or "")
            if not run or run["actor"] != actor:
                raise IrrigationWorldModelNotFound("irrigation Proposal not found")
            proposal = run["proposal"]
            if proposal["status"] != "pending":
                raise IrrigationWorldModelConflict(
                    "Proposal has already been reviewed; run a new scenario to create a new version"
                )
            proposal["status"] = decision
            proposal["review_note"] = note
            proposal["reviewed_by"] = actor
            proposal["reviewed_at"] = _timestamp()[0]
            proposal["execution_allowed"] = False
            run["audit_events"].append(
                _audit_event(
                    "人工审查",
                    "通过" if decision == "approved" else "记录",
                    "已通过审查（不执行）" if decision == "approved" else "已退回修改",
                )
            )
            return copy.deepcopy(run)


class IrrigationWorldModelService:
    def __init__(self, repository: Any | None = None):
        # The formal application uses PostgreSQL.  In-memory storage remains a
        # test fixture only and must be injected explicitly by unit tests.
        self.repository = repository or PostgresIrrigationWorldModelRepository()

    def _repository_error(self, exc: Exception) -> IrrigationWorldModelError:
        if isinstance(exc, IrrigationWorldModelError):
            return exc
        if isinstance(exc, (IrrigationPersistenceNotFound,)):
            return IrrigationWorldModelNotFound(str(exc))
        if isinstance(exc, (IrrigationPersistenceConflict,)):
            return IrrigationWorldModelConflict(str(exc))
        if isinstance(exc, IrrigationPersistenceError):
            return IrrigationWorldModelUnavailable(str(exc))
        return IrrigationWorldModelUnavailable("irrigation world-model persistence failed")

    def bootstrap(self, actor: str, tenant_id: str = "local-dev") -> dict[str, Any]:
        try:
            run = self.repository.latest(actor, tenant_id)
        except Exception as exc:
            raise self._repository_error(exc) from exc
        if run is None:
            run = self.run(DEFAULT_PARAMETERS, actor, tenant_id)
        elif not isinstance(run.get("planner"), dict) or not run["planner"].get("planner_id"):
            run["planner"] = _planner_contract(
                run.get("results", []),
                run.get("proposal", {}).get("candidate_mode", "baseline"),
                "legacy_run_reconstruction",
            )
        durable = isinstance(self.repository, PostgresIrrigationWorldModelRepository)
        return {
            "schema": "gda.irrigation-world-model.bootstrap.v1",
            "service": {
                "mode": "backend_authoritative",
                "repository": "gda_control.postgresql" if durable else "test_fixture_in_memory",
                "durability": "durable_across_service_restart" if durable else "test_process_only",
                "tenant_scoped": True,
            },
            "ontology_profile": copy.deepcopy(ONTOLOGY_PROFILE),
            "objects": copy.deepcopy(NODES),
            "links": copy.deepcopy(LINKS),
            "state_snapshot": copy.deepcopy(STATE_SNAPSHOT),
            "registered_functions": copy.deepcopy(REGISTERED_FUNCTIONS),
            "modes": copy.deepcopy(MODES),
            "default_parameters": copy.deepcopy(DEFAULT_PARAMETERS),
            "claim_boundary": copy.deepcopy(CLAIM_BOUNDARY),
            "run": run,
        }

    def run(
        self, payload: dict[str, Any], actor: str, tenant_id: str = "local-dev"
    ) -> dict[str, Any]:
        parameters = _validated_parameters(payload)
        try:
            version = self.repository.next_version(actor, tenant_id)
        except Exception as exc:
            raise self._repository_error(exc) from exc
        run_id = f"irr-run-{uuid.uuid4()}"
        proposal_id = f"irr-proposal-{uuid.uuid4()}"
        created_at, _ = _timestamp()
        results = [calculate_scenario(mode["id"], parameters) for mode in MODES]
        planner = _planner_contract(results)
        selected = next(result for result in results if result["mode"] == planner["selected_mode"])
        available_supply = 960.0 * (1.0 - float(parameters["supply_drop_percent"]) / 100.0)
        hard_constraints_pass = all(
            result["capacityViolations"] == 0
            and abs(result.get("residualVolumeM3", 0.0)) < 0.01
            for result in results
        )
        audit_events = [
            _audit_event(
                "语义 Grounding", "通过", f"{len(NODES)} 个对象、{len(LINKS)} 条关系已冻结"
            ),
            _audit_event("状态快照", "通过", STATE_SNAPSHOT["snapshot_id"]),
            _audit_event(
                "时序状态推演",
                "记录",
                "manning-kinematic-storage-network-v1 · "
                f"{sum(result['numerical']['timestep_count'] for result in results)} steps",
            ),
            _audit_event(
                "约束校核", "通过" if hard_constraints_pass else "记录", "容量、守恒、动作范围"
            ),
            _audit_event("人工审查", "待审查", "Proposal 尚未形成批准意见"),
        ]
        run = {
            "schema": "gda.irrigation-world-model.run.v1",
            "run_id": run_id,
            "version": version,
            "actor": actor,
            "created_at": created_at,
            "status": "awaiting_review",
            "parameters": parameters,
            "ontology_profile": {
                "profile_id": ONTOLOGY_PROFILE["profile_id"],
                "version": ONTOLOGY_PROFILE["version"],
                "content_sha256": ONTOLOGY_PROFILE["content_sha256"],
                "lifecycle_status": ONTOLOGY_PROFILE["lifecycle_status"],
            },
            "state_snapshot": copy.deepcopy(STATE_SNAPSHOT),
            "model": {
                "model_id": "manning-kinematic-storage-network",
                "version": "1.0",
                "model_class": "deterministic_physics_based_state_transition",
                "physics_scope": (
                    "continuity equation, Manning-derived kinematic celerity, "
                    "stateful reach storage routing, explicit branch actions"
                ),
                "not_included": [
                    "full Saint-Venant dynamic-wave junction solver",
                    "Richards soil-water solver",
                    "field-calibrated geometry and boundaries",
                    "learned JEPA state transition",
                ],
                "numerical_evidence": copy.deepcopy(selected["numerical"]),
            },
            "planner": planner,
            "pipeline": [
                {"index": 1, "key": "grounding", "label": "语义 Grounding", "status": "通过"},
                {"index": 2, "key": "snapshot", "label": "状态快照", "status": "通过"},
                {"index": 3, "key": "simulation", "label": "时序推演", "status": "完成"},
                {
                    "index": 4,
                    "key": "constraints",
                    "label": "约束校核",
                    "status": "通过" if hard_constraints_pass else "需复核",
                },
                {"index": 5, "key": "proposal", "label": "Proposal", "status": "待人工审查"},
                {"index": 6, "key": "execution", "label": "设备执行", "status": "禁止"},
            ],
            "results": results,
            "proposal": {
                "schema": "gda.irrigation-proposal.v1",
                "proposal_id": proposal_id,
                "version": version,
                "candidate_mode": selected["mode"],
                "status": "pending",
                "review_note": "待调度人员核对现场规则",
                "reviewed_by": None,
                "reviewed_at": None,
                "execution_allowed": False,
                "actions": [
                    {
                        "order": 1,
                        "action_type": "SetBoundarySupply",
                        "target": "R1",
                        "summary": f"固定 R1 → C1 的供水边界为 {available_supply:.0f} m³/d",
                    },
                    {
                        "order": 2,
                        "action_type": "ShiftDeliveryWindow",
                        "target": "C3",
                        "summary": (
                            f"西支渠供水时段后移 {parameters['west_shift_hours']} h"
                            if selected["mode"] != "baseline"
                            else "保持西支渠当前供水时段"
                        ),
                    },
                    {
                        "order": 3,
                        "action_type": "SetBranchAllocation",
                        "target": "D1,D2",
                        "summary": (
                            ("将" if selected["mode"] == "candidateB" else "保持")
                            + "东、西支渠配水比例为 "
                            f"{selected['branchRatio'] * 100:.1f}% / "
                            f"{(1 - selected['branchRatio']) * 100:.1f}%"
                        ),
                    },
                ],
                "result_summary": {
                    "delivered": selected["delivered"],
                    "shortage": selected["shortage"],
                    "tailCoverage": selected["tailCoverage"],
                    "capacityViolations": selected["capacityViolations"],
                    "residual": selected["residual"],
                    "residualVolumeM3": selected["residualVolumeM3"],
                    "runtimeMs": selected["numerical"]["runtime_ms"],
                },
                "claim_boundary": copy.deepcopy(CLAIM_BOUNDARY),
            },
            "audit_events": audit_events,
            "claim_boundary": copy.deepcopy(CLAIM_BOUNDARY),
        }
        try:
            return self.repository.save(run, tenant_id)
        except Exception as exc:
            raise self._repository_error(exc) from exc

    def get_run(self, run_id: str, actor: str, tenant_id: str = "local-dev") -> dict[str, Any]:
        if not isinstance(run_id, str) or not run_id.startswith("irr-run-"):
            raise IrrigationWorldModelError("invalid irrigation run id")
        try:
            return self.repository.get(run_id, actor, tenant_id)
        except Exception as exc:
            raise self._repository_error(exc) from exc

    def review_proposal(
        self, proposal_id: str, payload: dict[str, Any], actor: str, tenant_id: str = "local-dev"
    ) -> dict[str, Any]:
        if not isinstance(proposal_id, str) or not proposal_id.startswith("irr-proposal-"):
            raise IrrigationWorldModelError("invalid irrigation Proposal id")
        if not isinstance(payload, dict):
            raise IrrigationWorldModelError("request body must be an object")
        decision = payload.get("decision")
        if decision not in {"approved", "returned"}:
            raise IrrigationWorldModelError("decision must be approved or returned")
        note = payload.get("note", "")
        if not isinstance(note, str):
            raise IrrigationWorldModelError("note must be a string")
        note = note.strip()
        if not note:
            raise IrrigationWorldModelError("review note is required")
        if len(note) > 1000:
            raise IrrigationWorldModelError("review note must not exceed 1000 characters")
        try:
            return self.repository.update_proposal(proposal_id, actor, decision, note, tenant_id)
        except Exception as exc:
            raise self._repository_error(exc) from exc


IrrigationWorldModelDemoService = IrrigationWorldModelService


_service: IrrigationWorldModelService | None = None
_service_lock = threading.Lock()


def get_irrigation_world_model_service() -> IrrigationWorldModelService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = IrrigationWorldModelService()
    return _service


def get_irrigation_world_model_demo_service() -> IrrigationWorldModelService:
    """Compatibility alias for callers created before the durable service."""
    return get_irrigation_world_model_service()


def reset_irrigation_world_model_demo_service_for_tests() -> None:
    global _service
    with _service_lock:
        _service = None
