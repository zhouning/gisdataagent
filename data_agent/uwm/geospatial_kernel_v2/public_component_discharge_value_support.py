"""Stage 40 public source-only component-discharge value support evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from data_agent.uwm.geospatial_kernel_v2 import (
    component_discharge_value_support as support_operator,
)
from scripts import acquire_geotransport_stage39_component_discharge_values as acquire
from scripts import freeze_geotransport_stage39_component_discharge_value_protocol as freeze
from scripts import plan_geotransport_stage39_component_discharge_values as planner

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE40_ROOT = "data/geotransport_v0_1/stage40_center_hill_component_discharge_value_support"
STAGE39_ROOT = freeze.STAGE39_ROOT
DEFAULT_STAGE39_ROOT = REPO_ROOT / STAGE39_ROOT
PROTOCOL_PATH = f"{STAGE39_ROOT}/protocol.json"
PLAN_PATH = f"{STAGE39_ROOT}/value_acquisition_plan.json"
STATE_PATH = f"{STAGE39_ROOT}/{acquire.STATE_NAME}"
MANIFEST_PATH = f"{STAGE39_ROOT}/{acquire.MANIFEST_NAME}"
EXPECTED_PROTOCOL_SHA256 = planner.FROZEN_PROTOCOL_SHA256
EXPECTED_PLAN_SHA256 = acquire.FROZEN_PLAN_SHA256
EXPECTED_STATE_SHA256 = "683837d491b41e02103aeca85851eeb07aee27f17f49947b37a49421f24d36cf"
EXPECTED_MANIFEST_SHA256 = "ed77dacf3743713817177ba6fd7e553c71823693d831af5d38523dbb5fb45a0b"
SCHEMA = "gwm.geotransport.public_component_discharge_value_support.v1"
STATUS = "stage40_complete_component_discharge_source_support_admitted"


@dataclass(frozen=True)
class PublicComponentDischargeValueSupportLedger:
    protocol_artifact: dict[str, object]
    plan_artifact: dict[str, object]
    acquisition_state_artifact: dict[str, object]
    acquisition_manifest_artifact: dict[str, object]
    source_artifacts: tuple[dict[str, object], ...]
    support: support_operator.SynchronizedComponentDischargeSupport
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            self.protocol_artifact["sha256"] != EXPECTED_PROTOCOL_SHA256
            or self.plan_artifact["sha256"] != EXPECTED_PLAN_SHA256
            or self.acquisition_state_artifact["sha256"] != EXPECTED_STATE_SHA256
            or self.acquisition_manifest_artifact["sha256"] != EXPECTED_MANIFEST_SHA256
            or len(self.source_artifacts) != 20
            or not self.support.synchronized_support_complete
        ):
            raise ValueError("public_component_discharge_value_support_invalid")

    def require_quality_approval_semantics(self) -> None:
        self.support.require_quality_approval_semantics()

    def require_total_discharge_values(self) -> None:
        self.support.require_total_discharge_values()

    def require_event_selection(self) -> None:
        self.support.require_event_selection()

    def require_gate_command(self) -> None:
        self.support.require_gate_command()

    def require_human_action(self) -> None:
        self.support.require_human_action()

    def require_causal_intervention(self) -> None:
        self.support.require_causal_intervention()

    def require_physical_response_time(self) -> None:
        self.support.require_physical_response_time()

    def promote_to_runtime_operator(self) -> None:
        self.support.promote_to_runtime_operator()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "status": STATUS,
            "protocol_artifact": self.protocol_artifact,
            "plan_artifact": self.plan_artifact,
            "acquisition_state_artifact": self.acquisition_state_artifact,
            "acquisition_manifest_artifact": (self.acquisition_manifest_artifact),
            "source_artifacts": list(self.source_artifacts),
            "support": self.support.as_dict(),
            "provenance_id": self.provenance_id,
            "decision": {
                "component_value_artifacts_acquired": True,
                "logical_request_count": 20,
                "actual_attempt_count": 20,
                "actual_download_bytes": 4_225_697,
                "per_component_complete_hourly_coverage_admitted": True,
                "synchronized_four_component_value_support_admitted": True,
                "quality_code_approval_semantics_admitted": False,
                "synchronized_total_discharge_values_compiled": False,
                "component_discharge_event_admitted": False,
                "downstream_outcome_values_acquired": False,
                "gate_commands_admitted": False,
                "human_actions_admitted": False,
                "causal_interventions_admitted": False,
                "physical_response_time_admitted": False,
                "runtime_operators_admitted": False,
                "separate_event_selection_protocol_required": True,
            },
        }


def compile_public_component_discharge_value_support(
    source_root: Path = DEFAULT_STAGE39_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicComponentDischargeValueSupportLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    artifacts = (
        _artifact(source / "protocol.json", root),
        _artifact(source / "value_acquisition_plan.json", root),
        _artifact(source / acquire.STATE_NAME, root),
        _artifact(source / acquire.MANIFEST_NAME, root),
    )
    if tuple(value["sha256"] for value in artifacts) != (
        EXPECTED_PROTOCOL_SHA256,
        EXPECTED_PLAN_SHA256,
        EXPECTED_STATE_SHA256,
        EXPECTED_MANIFEST_SHA256,
    ):
        raise ValueError("public_component_discharge_frozen_artifact_invalid")
    plan = _read_json(source / "value_acquisition_plan.json")
    manifest = _read_json(source / acquire.MANIFEST_NAME)
    if plan != planner.compile_plan():
        raise ValueError("public_component_discharge_plan_not_reproducible")
    _validate_manifest(manifest, plan)

    raw_artifacts = []
    payloads_by_component: dict[str, list[dict[str, object]]] = {
        component: [] for component in support_operator.catalog.EXPECTED_COMPONENTS
    }
    manifest_by_source = {str(value["source_id"]): value for value in manifest["artifacts"]}
    for request_source in plan["sources"]:
        source_id = str(request_source["source_id"])
        manifest_source = manifest_by_source.get(source_id)
        if not isinstance(manifest_source, dict):
            raise ValueError("public_component_discharge_manifest_source_missing")
        raw_path = source / str(request_source["output_name"])
        artifact = _artifact(raw_path, root)
        if (
            artifact["path"] != manifest_source.get("path")
            or artifact["sha256"] != manifest_source.get("sha256")
            or artifact["size_bytes"] != manifest_source.get("size_bytes")
            or manifest_source.get("hash_verified") is not True
        ):
            raise ValueError("public_component_discharge_raw_artifact_invalid")
        payload = _read_json(raw_path)
        acquire._validate_payload(payload, request_source)
        raw_artifacts.append({**artifact, "source_id": source_id})
        payloads_by_component[str(request_source["component"])].append(payload)
    compiled = support_operator.compile_synchronized_component_discharge_support(
        {component: tuple(payloads) for component, payloads in payloads_by_component.items()}
    )
    provenance_artifacts = (*artifacts, *raw_artifacts)
    digest = hashlib.sha256(
        "|".join(str(value["sha256"]) for value in provenance_artifacts).encode("ascii")
    ).hexdigest()
    return PublicComponentDischargeValueSupportLedger(
        artifacts[0],
        artifacts[1],
        artifacts[2],
        artifacts[3],
        tuple(raw_artifacts),
        compiled,
        f"center-hill-component-discharge-value-support:{digest}",
    )


def _validate_manifest(manifest: dict[str, object], plan: dict[str, object]) -> None:
    claims = manifest.get("claim_boundary")
    if (
        manifest.get("schema") != acquire.SCHEMA
        or manifest.get("actual_request_count") != 20
        or manifest.get("actual_attempt_count") != 20
        or manifest.get("actual_download_bytes") != 4_225_697
        or manifest.get("artifact_count") != 20
        or manifest.get("request_boundary") != plan["request_boundary"]
        or not isinstance(manifest.get("artifacts"), list)
        or not isinstance(claims, dict)
        or claims.get("component_values_acquired") is not True
        or claims.get("coverage_or_quality_support_compiled") is not False
        or claims.get("synchronized_total_discharge_compiled") is not False
        or claims.get("component_discharge_event_selected") is not False
        or claims.get("downstream_outcome_values_acquired") is not False
    ):
        raise ValueError("public_component_discharge_manifest_invalid")


def _artifact(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("public_component_discharge_artifact_outside_repo") from exc
    body = resolved.read_bytes()
    return {
        "path": str(relative),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_component_discharge_json_object_required")
    return value
