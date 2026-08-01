"""Stage 35 evidence for set-valued event-time uncertainty propagation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import event_time_uncertainty as time
from data_agent.uwm.geospatial_kernel_v2 import (
    public_temporal_response_semantics as stage34,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE35_ROOT = (
    "data/geotransport_v0_1/stage35_center_hill_event_time_uncertainty"
)
DEFAULT_SOURCE_ROOT = REPO_ROOT / STAGE35_ROOT
STAGE34_ROOT = "data/geotransport_v0_1/stage34_center_hill_temporal_semantics"
STAGE34_LEDGER_PATH = f"{STAGE34_ROOT}/temporal_response_semantics_ledger.json"
STAGE34_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage34_temporal_semantics_gates.json"
)
STAGE33_LEDGER_SUFFIX = (
    "stage33_center_hill_temporal_support_path/"
    "temporal_support_reconciliation_ledger.json"
)
STAGE32_LEDGER_SUFFIX = (
    "stage32_center_hill_lag_support_events/lag_support_evidence_ledger.json"
)
SCHEMA = "gwm.geotransport.public_event_time_uncertainty.v1"
PROTOCOL_SCHEMA = "gwm.geotransport.stage35_event_time_uncertainty_protocol.v1"
RELATION_ID = "center-hill-tailwater-to-stonewall"
PATH_ID = "center-hill-tailwater-to-stonewall-path"
EVENT_IDS = (
    "release_step_20220202T1900Z",
    "release_step_20220919T1500Z",
    "release_step_20230911T1500Z",
    "release_step_20210625T1600Z",
)


@dataclass(frozen=True)
class PublicEventTimeUncertaintyLedger:
    operator_artifact: dict[str, object]
    protocol_artifact: dict[str, object]
    stage34_ledger_artifact: dict[str, object]
    stage34_gates_artifact: dict[str, object]
    support_uncertainty: time.ObservationSupportUncertainty
    event_ids: tuple[str, ...]
    event_label_shift_sets: tuple[tuple[int, ...], ...]
    reconciliation: time.EventTimeUncertaintyReconciliation
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            self.event_ids != EVENT_IDS
            or len(self.event_label_shift_sets) != 4
            or len(self.source_artifacts) != 5
            or len(self.reconciliation.event_envelopes) != 4
            or self.reconciliation.empirical_union_envelope.path_id != PATH_ID
        ):
            raise ValueError("public_event_time_uncertainty_ledger_invalid")

    def require_common_event_delay_intervals(
        self,
    ) -> tuple[time.ClosedTemporalInterval, ...]:
        return self.reconciliation.require_common_event_delay_intervals()

    def require_physical_response_time(self) -> None:
        self.reconciliation.require_physical_response_time()

    def promote_to_runtime_transition(self) -> None:
        self.reconciliation.promote_to_runtime_transition()

    def as_dict(self) -> dict[str, object]:
        reconciliation = self.reconciliation
        compatibilities = reconciliation.compatibilities
        return {
            "schema": SCHEMA,
            "operator_artifact": self.operator_artifact,
            "protocol_artifact": self.protocol_artifact,
            "stage34_ledger_artifact": self.stage34_ledger_artifact,
            "stage34_gates_artifact": self.stage34_gates_artifact,
            "support_uncertainty": self.support_uncertainty.as_dict(),
            "event_ids": list(self.event_ids),
            "event_label_shift_sets_hours": [
                list(value) for value in self.event_label_shift_sets
            ],
            "reconciliation": reconciliation.as_dict(),
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "diagnostic_summary": {
                "event_delay_envelopes_hours": [
                    [
                        [interval.lower_hours, interval.upper_hours]
                        for interval in envelope.intervals
                    ]
                    for envelope in reconciliation.event_envelopes
                ],
                "empirical_union_delay_envelope_hours": [
                    [value.lower_hours, value.upper_hours]
                    for value in (
                        reconciliation.empirical_union_envelope.intervals
                    )
                ],
                "physics_quantities": [
                    value.physics_quantity for value in compatibilities
                ],
                "physics_intervals_hours": [
                    [
                        value.physics_interval.lower_hours,
                        value.physics_interval.upper_hours,
                    ]
                    for value in compatibilities
                ],
                "measurement_support_overlap": [
                    value.measurement_support_overlap
                    for value in compatibilities
                ],
                "minimum_separation_hours": [
                    value.minimum_separation_hours
                    for value in compatibilities
                ],
            },
            "claim_boundary": {
                "closed_supports_are_conservative_outer_bounds": True,
                "uncertainty_envelope_is_physical_delay": False,
                "empty_empirical_support_can_be_dilated": False,
                "numerical_overlap_overrides_process_semantics": False,
                "physical_response_time_admitted": False,
                "runtime_transition_admitted": False,
            },
            "decision": {
                "hash_bound_prior_evidence_verified": True,
                "event_time_uncertainty_propagation_admitted": True,
                "all_events_have_nonempty_support": (
                    reconciliation.all_events_have_nonempty_support
                ),
                "common_event_delay_intervals_admitted": bool(
                    reconciliation.common_event_delay_intervals
                ),
                "any_measurement_support_physics_overlap": any(
                    value.measurement_support_overlap
                    for value in compatibilities
                ),
                "semantic_equivalence_admitted": any(
                    value.semantic_equivalence_admitted
                    for value in compatibilities
                ),
                "physical_response_time_admitted": (
                    reconciliation.physical_response_time_admitted
                ),
                "runtime_transition_admitted": False,
            },
        }


def compile_public_event_time_uncertainty(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicEventTimeUncertaintyLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    protocol_path = source / "protocol.json"
    protocol = _read_json(protocol_path)
    _validate_protocol(protocol, root)

    stage34_path = root / STAGE34_LEDGER_PATH
    stage34_file = _read_json(stage34_path)
    stage34_compiled = stage34.compile_public_temporal_response_semantics(
        source_root=root / STAGE34_ROOT,
        repo_root=root,
    )
    if stage34_compiled.as_dict() != stage34_file:
        raise ValueError("public_event_time_stage34_ledger_not_reproducible")
    stage34_gates = _read_json(root / STAGE34_GATES_PATH)
    if (
        stage34_gates.get("all_gates_passed") is not True
        or stage34_gates.get("status")
        != "interval_label_shift_admitted_physical_response_semantics_rejected"
    ):
        raise ValueError("public_event_time_stage34_gate_invalid")

    stage33_record = _source_record(
        stage34_compiled.source_artifacts, STAGE33_LEDGER_SUFFIX
    )
    stage32_record = _source_record(
        stage34_compiled.source_artifacts, STAGE32_LEDGER_SUFFIX
    )
    stage33_file = json.loads(_read_verified(stage33_record, root))
    stage32_file = json.loads(_read_verified(stage32_record, root))

    support_model = protocol["observation_support_model"]
    support = time.ObservationSupportUncertainty(
        float(support_model["source_duration_hours"]),
        float(support_model["target_duration_hours"]),
        str(support_model["source_timestamp_position"]),
        str(support_model["target_timestamp_position"]),
        bool(support_model["conservative_closure_used"]),
    )
    empirical = protocol["frozen_empirical_support"]
    events = empirical["events"]
    event_ids = tuple(str(value["event_id"]) for value in events)
    event_supports = tuple(
        tuple(int(hour) for hour in value["label_shift_set_hours"])
        for value in events
    )
    _validate_prior_bindings(
        protocol,
        stage34_compiled,
        stage32_file,
        event_ids,
        event_supports,
    )
    envelopes = tuple(
        time.compile_relative_event_delay_envelope(
            RELATION_ID,
            PATH_ID,
            values,
            support,
            f"stage32:{event_id}",
        )
        for event_id, values in zip(event_ids, event_supports, strict=True)
    )
    union = time.compile_relative_event_delay_envelope(
        RELATION_ID,
        PATH_ID,
        tuple(int(value) for value in empirical["union_label_shift_set_hours"]),
        support,
        "stage32:empirical-union",
    )
    _validate_expected_envelopes(protocol, envelopes, union)

    semantic_by_quantity = {
        value.candidate.quantity: value
        for value in stage34_compiled.reconciliation.compatibilities
    }
    compatibilities = []
    for value in stage33_file["reconciliation"]["compatibilities"]:
        physics = value["physics_support"]
        quantity = str(physics["quantity"])
        semantic = semantic_by_quantity[quantity]
        lower, upper = physics["support_interval_hours"]
        compatibilities.append(
            time.EventTimePhysicsCompatibility(
                union,
                quantity,
                time.ClosedTemporalInterval(float(lower), float(upper)),
                bool(value["same_spatial_path"]),
                semantic.semantic_equivalence_admitted,
                semantic.candidate.admitted_as_physical_response_time,
            )
        )
    reconciliation = time.EventTimeUncertaintyReconciliation(
        envelopes,
        union,
        tuple(compatibilities),
        bool(empirical["all_event_common_empirical_support_admitted"]),
    )
    source_artifacts = (
        _artifact(protocol_path, root),
        _artifact(stage34_path, root),
        _artifact(root / STAGE34_GATES_PATH, root),
        dict(stage33_record),
        dict(stage32_record),
    )
    digest = hashlib.sha256(
        "|".join(str(value["sha256"]) for value in source_artifacts).encode(
            "ascii"
        )
    ).hexdigest()
    return PublicEventTimeUncertaintyLedger(
        dict(protocol["frozen_inputs"]["operator"]),
        source_artifacts[0],
        source_artifacts[1],
        source_artifacts[2],
        support,
        event_ids,
        event_supports,
        reconciliation,
        source_artifacts,
        f"center-hill-event-time-uncertainty:{digest}",
    )


def _validate_protocol(protocol: dict[str, Any], root: Path) -> None:
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("public_event_time_protocol_schema_invalid")
    boundary = protocol.get("data_boundary")
    if boundary != {
        "network_requests_allowed": False,
        "new_public_data_acquired": False,
        "private_or_workspace_data_requested": False,
        "release_or_downstream_outcome_values_requested": False,
        "post_stage34_calibration_allowed": False,
        "only_hash_bound_prior_artifacts_allowed": True,
    }:
        raise ValueError("public_event_time_protocol_data_boundary_invalid")
    inputs = protocol.get("frozen_inputs") or {}
    for name in ("operator", "stage34_ledger", "stage34_gates"):
        record = inputs.get(name)
        if not isinstance(record, dict):
            raise ValueError("public_event_time_protocol_input_missing")
        _read_verified(record, root)
    if inputs["stage34_ledger"]["path"] != STAGE34_LEDGER_PATH:
        raise ValueError("public_event_time_protocol_stage34_ledger_invalid")
    if inputs["stage34_gates"]["path"] != STAGE34_GATES_PATH:
        raise ValueError("public_event_time_protocol_stage34_gates_invalid")


def _validate_prior_bindings(
    protocol: dict[str, Any],
    stage34_ledger,
    stage32_file: dict[str, Any],
    event_ids: tuple[str, ...],
    event_supports: tuple[tuple[int, ...], ...],
) -> None:
    source = stage34_ledger.source_field.temporal_support
    target = stage34_ledger.target_field.temporal_support
    model = protocol["observation_support_model"]
    if (
        source.duration_seconds / 3600.0
        != model["source_duration_hours"]
        or target.duration_seconds / 3600.0
        != model["target_duration_hours"]
        or source.timestamp_position != model["source_timestamp_position"]
        or target.timestamp_position != model["target_timestamp_position"]
        or stage34_ledger.reconciliation.all_event_common_empirical_support
        is not False
    ):
        raise ValueError("public_event_time_stage34_support_binding_invalid")
    events = stage32_file.get("events") or []
    actual_ids = tuple(str(value["event_id"]) for value in events)
    actual_supports = tuple(
        tuple(
            int(hour)
            for hour in value["empirical_lag_support"][
                "supported_lags_hours"
            ]
        )
        for value in events
    )
    if actual_ids != event_ids or actual_supports != event_supports:
        raise ValueError("public_event_time_stage32_support_binding_invalid")


def _validate_expected_envelopes(
    protocol: dict[str, Any],
    envelopes: tuple[time.RelativeEventDelayEnvelope, ...],
    union: time.RelativeEventDelayEnvelope,
) -> None:
    events = protocol["frozen_empirical_support"]["events"]
    actual = [
        [[value.lower_hours, value.upper_hours] for value in envelope.intervals]
        for envelope in envelopes
    ]
    expected = [
        value["expected_relative_delay_envelope_hours"] for value in events
    ]
    union_actual = [
        [value.lower_hours, value.upper_hours] for value in union.intervals
    ]
    union_expected = protocol["frozen_empirical_support"][
        "expected_union_delay_envelope_hours"
    ]
    if actual != expected or union_actual != union_expected:
        raise ValueError("public_event_time_expected_envelope_mismatch")


def _source_record(
    records: tuple[dict[str, object], ...], suffix: str
) -> dict[str, object]:
    matches = [value for value in records if str(value["path"]).endswith(suffix)]
    if len(matches) != 1:
        raise ValueError("public_event_time_source_record_invalid")
    return dict(matches[0])


def _read_verified(record: dict[str, Any], root: Path) -> bytes:
    path = _resolve(record, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != record.get("sha256")
        or len(body) != record.get("size_bytes")
    ):
        raise ValueError(f"public_event_time_artifact_drift:{record.get('path')}")
    return body


def _resolve(record: dict[str, Any], root: Path) -> Path:
    path = Path(str(record["path"]))
    return path if path.is_absolute() else root / path


def _artifact(path: Path, root: Path) -> dict[str, object]:
    body = path.read_bytes()
    try:
        display = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        display = str(path.resolve())
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"public_event_time_json_object_required:{path}")
    return value
