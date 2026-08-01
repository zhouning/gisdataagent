"""Stage 41 public source-only component-discharge event evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from data_agent.uwm.geospatial_kernel_v2 import (
    component_discharge_event_selection as selection_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_component_discharge_value_support as stage40_evidence,
)
from scripts import compile_geotransport_stage41_component_discharge_events as compile_stage41
from scripts import (
    freeze_geotransport_stage41_component_discharge_event_protocol as freeze,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE41_ROOT = freeze.STAGE41_ROOT
DEFAULT_STAGE41_ROOT = REPO_ROOT / STAGE41_ROOT
PROTOCOL_PATH = f"{STAGE41_ROOT}/{compile_stage41.PROTOCOL_NAME}"
CANDIDATE_LEDGER_PATH = f"{STAGE41_ROOT}/{compile_stage41.CANDIDATE_LEDGER_NAME}"
MANIFEST_PATH = f"{STAGE41_ROOT}/{compile_stage41.MANIFEST_NAME}"
EXPECTED_PROTOCOL_SHA256 = "e5da6a7c3a8b9dba355f41e92114cf3ae8bd726c2c6026fdb1d8fd4b5ed88f33"
EXPECTED_CANDIDATE_LEDGER_SHA256 = (
    "625b1bee79ccf1eb83059a906250497c3460eb247cdfe06d6b3fb3ef8bcab60f"
)
EXPECTED_MANIFEST_SHA256 = "3ffecd85ce74147eb11e1ccc084b4ac5b2774bae81511a416c54735b156d7e6a"
SCHEMA = "gwm.geotransport.public_component_discharge_event_evidence.v1"
STATUS = "stage41_complete_source_only_total_discharge_events_admitted"
EXPECTED_EVENT_IDS = (
    "component_total_step_20250415T1600Z",
    "component_total_step_20230311T2000Z",
    "component_total_step_20210112T1600Z",
    "component_total_step_20210727T0300Z",
)


@dataclass(frozen=True)
class PublicComponentDischargeEventEvidenceLedger:
    protocol_artifact: dict[str, object]
    candidate_ledger_artifact: dict[str, object]
    event_selection_manifest_artifact: dict[str, object]
    stage40_ledger_artifact: dict[str, object]
    stage40_gates_artifact: dict[str, object]
    source_artifacts: tuple[dict[str, object], ...]
    selection: selection_operator.ComponentDischargeEventSelection
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            self.protocol_artifact["sha256"] != EXPECTED_PROTOCOL_SHA256
            or self.candidate_ledger_artifact["sha256"]
            != EXPECTED_CANDIDATE_LEDGER_SHA256
            or self.event_selection_manifest_artifact["sha256"]
            != EXPECTED_MANIFEST_SHA256
            or self.stage40_ledger_artifact["sha256"]
            != freeze.FROZEN_HASHES[freeze.STAGE40_LEDGER_PATH]
            or self.stage40_gates_artifact["sha256"]
            != freeze.FROZEN_HASHES[freeze.STAGE40_GATES_PATH]
            or len(self.source_artifacts) != 20
            or len(self.selection.candidates) != 2_547
            or tuple(
                str(value["event_id"])
                for value in self.selection.selected_events
            )
            != EXPECTED_EVENT_IDS
        ):
            raise ValueError("public_component_discharge_event_evidence_invalid")

    def require_quality_approval_semantics(self) -> None:
        self.selection.require_quality_approval_semantics()

    def require_non_turbine_component_contrast(self) -> None:
        self.selection.require_non_turbine_component_contrast()

    def require_gate_command(self) -> None:
        self.selection.require_gate_command()

    def require_human_action(self) -> None:
        self.selection.require_human_action()

    def require_observed_downstream_response(self) -> None:
        self.selection.require_observed_downstream_response()

    def require_causal_intervention(self) -> None:
        self.selection.require_causal_intervention()

    def require_physical_response_time(self) -> None:
        self.selection.require_physical_response_time()

    def promote_to_runtime_operator(self) -> None:
        self.selection.promote_to_runtime_operator()

    def as_dict(self) -> dict[str, object]:
        summary = self.selection.as_dict()
        return {
            "schema": SCHEMA,
            "status": STATUS,
            "protocol_artifact": self.protocol_artifact,
            "candidate_ledger_artifact": self.candidate_ledger_artifact,
            "event_selection_manifest_artifact": (
                self.event_selection_manifest_artifact
            ),
            "stage40_ledger_artifact": self.stage40_ledger_artifact,
            "stage40_gates_artifact": self.stage40_gates_artifact,
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "selection": summary,
            "decision": {
                "event_protocol_frozen": True,
                "stage40_source_support_preserved": True,
                "source_artifact_count": len(self.source_artifacts),
                "new_network_request_count": 0,
                "synchronized_total_discharge_derivation_admitted": True,
                "full_derived_total_series_persisted": False,
                "eligible_source_event_count": len(self.selection.candidates),
                "source_only_total_discharge_event_count": len(
                    self.selection.selected_events
                ),
                "source_only_total_discharge_events_admitted": True,
                "selected_dominant_components": list(
                    self.selection.selected_dominant_components
                ),
                "non_turbine_component_contrast_admitted": False,
                "quality_code_approval_semantics_admitted": False,
                "target_functional_frozen": True,
                "downstream_or_tributary_values_acquired": False,
                "observed_downstream_response_admitted": False,
                "gate_commands_admitted": False,
                "human_actions_admitted": False,
                "causal_interventions_admitted": False,
                "physical_response_time_admitted": False,
                "runtime_operators_admitted": False,
                "fresh_approval_required_for_target_acquisition": True,
            },
        }


def compile_public_component_discharge_event_evidence(
    source_root: Path = DEFAULT_STAGE41_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicComponentDischargeEventEvidenceLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    artifacts = (
        _artifact(source / compile_stage41.PROTOCOL_NAME, root),
        _artifact(source / compile_stage41.CANDIDATE_LEDGER_NAME, root),
        _artifact(source / compile_stage41.MANIFEST_NAME, root),
        _artifact(root / freeze.STAGE40_LEDGER_PATH, root),
        _artifact(root / freeze.STAGE40_GATES_PATH, root),
    )
    if tuple(value["sha256"] for value in artifacts[:3]) != (
        EXPECTED_PROTOCOL_SHA256,
        EXPECTED_CANDIDATE_LEDGER_SHA256,
        EXPECTED_MANIFEST_SHA256,
    ):
        raise ValueError("public_component_event_frozen_artifact_invalid")
    protocol = _read_json(source / compile_stage41.PROTOCOL_NAME)
    candidate_ledger = _read_json(
        source / compile_stage41.CANDIDATE_LEDGER_NAME
    )
    manifest = _read_json(source / compile_stage41.MANIFEST_NAME)
    if protocol != freeze.build_protocol():
        raise ValueError("public_component_event_protocol_not_reproducible")
    compiled = compile_stage41.compile_selection()
    _validate_compiled_artifacts(
        protocol,
        candidate_ledger,
        manifest,
        artifacts,
        compiled,
    )
    stage40 = stage40_evidence.compile_public_component_discharge_value_support()
    if tuple(manifest["inherited_source_artifacts"]) != stage40.source_artifacts:
        raise ValueError("public_component_event_source_artifacts_invalid")
    digest = hashlib.sha256(
        "|".join(str(value["sha256"]) for value in artifacts).encode("ascii")
    ).hexdigest()
    return PublicComponentDischargeEventEvidenceLedger(
        artifacts[0],
        artifacts[1],
        artifacts[2],
        artifacts[3],
        artifacts[4],
        stage40.source_artifacts,
        compiled,
        f"center-hill-component-discharge-events:{digest}",
    )


def _validate_compiled_artifacts(
    protocol: dict[str, object],
    candidate_ledger: dict[str, object],
    manifest: dict[str, object],
    artifacts: tuple[dict[str, object], ...],
    compiled: selection_operator.ComponentDischargeEventSelection,
) -> None:
    summary = compiled.as_dict()
    if (
        candidate_ledger.get("schema") != compile_stage41.CANDIDATE_SCHEMA
        or candidate_ledger.get("protocol_artifact") != artifacts[0]
        or candidate_ledger.get("eligible_candidate_count") != 2_547
        or candidate_ledger.get("eligible_candidates")
        != list(compiled.candidates)
        or candidate_ledger.get("selected_events")
        != list(compiled.selected_events)
        or candidate_ledger.get("network_request_count") != 0
        or manifest.get("schema") != compile_stage41.MANIFEST_SCHEMA
        or manifest.get("status") != compile_stage41.STATUS
        or manifest.get("protocol_artifact") != artifacts[0]
        or manifest.get("candidate_ledger_artifact") != artifacts[1]
        or manifest.get("stage40_artifacts")
        != {"ledger": artifacts[3], "gates": artifacts[4]}
        or manifest.get("selected_events") != summary["selected_events"]
        or manifest.get("target_functional")
        != protocol["predeclared_target_functional"]
        or manifest.get("data_boundary", {}).get("network_request_count") != 0
        or manifest.get("claim_boundary") != summary["claim_boundary"]
    ):
        raise ValueError("public_component_event_manifest_invalid")


def _artifact(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("public_component_event_artifact_outside_repo") from exc
    body = resolved.read_bytes()
    return {
        "path": str(relative),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_component_event_json_object_required")
    return value
