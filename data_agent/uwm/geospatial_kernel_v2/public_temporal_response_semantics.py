"""Stage 34 public observation and response-time semantics evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.contracts import TemporalSupport
from data_agent.uwm.geospatial_kernel_v2 import (
    public_lag_support_evidence as stage32,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_temporal_support_reconciliation as stage33,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    temporal_response_semantics as semantics,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage34_center_hill_temporal_semantics"
)
STAGE32_LEDGER_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/stage32_center_hill_lag_support_events/"
    "lag_support_evidence_ledger.json"
)
STAGE33_LEDGER_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/stage33_center_hill_temporal_support_path/"
    "temporal_support_reconciliation_ledger.json"
)
STAGE33_GATES_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage33_temporal_support_gates.json"
)
SMOKE_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_smoke_panel_report.json"
)
STAGE27_MANIFEST_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/stage27_center_hill_spatial_boundary_evidence/"
    "acquisition_manifest.json"
)
SCHEMA = "gwm.geotransport.public_temporal_response_semantics.v1"
ACQUISITION_SCHEMA = (
    "gwm.geotransport.stage34_temporal_semantics_acquisition.v1"
)
SOURCE_SERIES_ID = "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev"
TARGET_SITE_ID = "USGS-03424860"
TARGET_SERIES_ID = "1eed13fd6d90461fa6a04892af197e6d"
PATH_ID = "center-hill-tailwater-to-stonewall-path"


@dataclass(frozen=True)
class PublicTemporalResponseSemanticsLedger:
    operator_artifact: dict[str, object]
    acquisition_plan_artifact: dict[str, object]
    acquisition_manifest_artifact: dict[str, object]
    document_findings: dict[str, object]
    source_field: semantics.TemporalFieldSemantics
    target_field: semantics.TemporalFieldSemantics
    stage32_downstream_complete_hours: tuple[int, ...]
    stage32_downstream_missing_hours: tuple[int, ...]
    reconciliation: semantics.GeospatialResponseSemanticReconciliation
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            len(self.source_artifacts) != 9
            or self.stage32_downstream_complete_hours != (84, 84, 77, 84)
            or self.stage32_downstream_missing_hours != (0, 0, 7, 0)
            or self.reconciliation.source_field != self.source_field
            or self.reconciliation.target_field != self.target_field
        ):
            raise ValueError("public_temporal_response_semantics_ledger_invalid")

    def require_label_shift_grid_seconds(self) -> float:
        return self.reconciliation.require_label_shift_grid_seconds()

    def require_release_actuation_instant(self) -> None:
        self.source_field.require_actuation_instant()

    def require_target_continuous_interval_average(self) -> None:
        self.target_field.require_continuous_interval_average()

    def require_physical_observation_equivalence(self) -> None:
        self.source_field.require_physical_observation_equivalence(
            self.target_field
        )

    def require_physical_response_time(self) -> None:
        self.reconciliation.require_physical_response_time()

    def promote_to_runtime_transition(self) -> None:
        self.reconciliation.promote_to_runtime_transition()

    def as_dict(self) -> dict[str, object]:
        report = self.reconciliation.as_dict()
        return {
            "schema": SCHEMA,
            "operator_artifact": self.operator_artifact,
            "acquisition_plan_artifact": self.acquisition_plan_artifact,
            "acquisition_manifest_artifact": (
                self.acquisition_manifest_artifact
            ),
            "document_findings": self.document_findings,
            "source_field": self.source_field.as_dict(),
            "target_field": self.target_field.as_dict(),
            "stage32_observation_support": {
                "event_complete_hours": list(
                    self.stage32_downstream_complete_hours
                ),
                "event_missing_hours": list(
                    self.stage32_downstream_missing_hours
                ),
                "compiled_hour_native_sample_count": 2,
                "native_sampling_interval_seconds": 1800.0,
                "missing_values_filled": False,
                "all_compiled_samples_approved": True,
            },
            "response_semantic_reconciliation": report,
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "claim_boundary": {
                "same_path_and_time_dimension_imply_same_process": False,
                "cwms_interval_end_label_is_actuation_instant": False,
                "two_instantaneous_samples_equal_continuous_hour_mean": False,
                "label_shift_diagnostic_is_physical_response_time": False,
                "runtime_transition_admitted": False,
            },
            "decision": {
                "public_temporal_semantics_evidence_admitted": True,
                "interval_end_label_shift_diagnostic_admitted": (
                    self.reconciliation.label_shift_diagnostic_admitted
                ),
                "label_shift_grid_seconds": (
                    self.require_label_shift_grid_seconds()
                ),
                "release_actuation_instant_admitted": False,
                "target_continuous_interval_average_admitted": False,
                "physical_observation_equivalence_admitted": False,
                "physical_response_time_admitted": (
                    self.reconciliation.physical_response_time_admitted
                ),
                "runtime_transition_admitted": False,
            },
        }


def compile_public_temporal_response_semantics(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicTemporalResponseSemanticsLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    manifest_path = source / "acquisition_manifest.json"
    manifest = _read_json(manifest_path)
    plan = json.loads(
        _read_verified(manifest["frozen_acquisition_plan"], root)
    )
    document_record = manifest["artifacts"][0]
    document = _read_verified(document_record, root).decode("utf-8")
    findings = _validate_acquisition_and_document(manifest, plan, document)

    stage33_file = _read_json(STAGE33_LEDGER_PATH)
    stage33_compiled = stage33.compile_public_temporal_support_reconciliation(
        repo_root=root
    )
    if stage33_compiled.as_dict() != stage33_file:
        raise ValueError("public_temporal_response_stage33_not_reproducible")
    stage33_gates = _read_json(STAGE33_GATES_PATH)
    if (
        stage33_gates.get("all_gates_passed") is not True
        or stage33_gates.get("status")
        != "spatial_path_admitted_temporal_reconciliation_rejected"
    ):
        raise ValueError("public_temporal_response_stage33_gate_invalid")

    stage32_file = _read_json(STAGE32_LEDGER_PATH)
    stage32_compiled = stage32.compile_public_lag_support_evidence(
        repo_root=root
    )
    if stage32_compiled.as_dict() != stage32_file:
        raise ValueError("public_temporal_response_stage32_not_reproducible")
    smoke = _read_json(SMOKE_REPORT_PATH)
    _validate_smoke_report(smoke)
    cwms_record = stage32_compiled.source_artifacts[0]
    cwms_payload = json.loads(_read_verified(cwms_record, root))
    _validate_cwms_source(cwms_payload)
    metadata_record, metadata = _load_target_metadata(root)
    _validate_target_metadata(metadata)
    _validate_stage32_observation_support(stage32_compiled)

    source_field = semantics.TemporalFieldSemantics(
        "cwms-center-hill-release",
        "operational_tailwater_zone",
        "discharge",
        "m3/s",
        "interval_average",
        _temporal_support(smoke["temporal_supports"]["action_release_m3s"]),
        None,
        None,
        f"cwms:{SOURCE_SERIES_ID}:{cwms_record['sha256']}",
    )
    target_field = semantics.TemporalFieldSemantics(
        "usgs-stonewall-hourly-sample-mean",
        "observed_outlet_node",
        "discharge",
        "m3/s",
        "instantaneous_sample_mean",
        _temporal_support(
            smoke["temporal_supports"][
                "outcome_discharge_interval_sample_mean_m3s"
            ]
        ),
        1800.0,
        2,
        f"usgs:{TARGET_SITE_ID}:{TARGET_SERIES_ID}:{metadata_record['sha256']}",
    )
    empirical_value = stage33_compiled.reconciliation.empirical
    empirical = semantics.ResponseTimeSemantics(
        empirical_value.quantity,
        stage33_compiled.reconciliation.path_id,
        "discharge_series",
        "interval_end_label_step",
        "windowed_linear_association_peak",
        False,
        empirical_value.outcome_derived,
        False,
        empirical_value.provenance_id,
    )
    compatibilities = []
    for value in stage33_compiled.reconciliation.compatibilities:
        physics = value.physics
        carrier, source_marker, target_functional = (
            semantics.PROCESS_SEMANTICS[physics.quantity]
        )
        candidate = semantics.ResponseTimeSemantics(
            physics.quantity,
            physics.path_id,
            carrier,
            source_marker,
            target_functional,
            physics.state_dependent,
            physics.outcome_calibrated,
            physics.admitted_as_physical_time,
            physics.provenance_id,
        )
        compatibilities.append(
            semantics.compile_response_semantic_compatibility(
                empirical,
                candidate,
                same_spatial_path=value.same_spatial_path,
                numerical_overlap=value.numerical_overlap,
            )
        )
    reconciliation = semantics.GeospatialResponseSemanticReconciliation(
        source_field,
        target_field,
        empirical,
        tuple(compatibilities),
        stage33_compiled.reconciliation.all_event_common_empirical_support,
    )
    complete = tuple(
        len(value.downstream_hourly) for value in stage32_compiled.events
    )
    missing = tuple(84 - value for value in complete)
    sources = (
        _artifact(source / "acquisition_plan.json", root),
        _artifact(manifest_path, root),
        dict(document_record),
        _artifact(STAGE33_LEDGER_PATH, root),
        _artifact(STAGE33_GATES_PATH, root),
        _artifact(STAGE32_LEDGER_PATH, root),
        dict(cwms_record),
        dict(metadata_record),
        _artifact(SMOKE_REPORT_PATH, root),
    )
    digest = hashlib.sha256(
        "|".join(str(value["sha256"]) for value in sources).encode("ascii")
    ).hexdigest()
    return PublicTemporalResponseSemanticsLedger(
        dict(plan["frozen_operator_artifact"]),
        dict(manifest["frozen_acquisition_plan"]),
        _artifact(manifest_path, root),
        findings,
        source_field,
        target_field,
        complete,
        missing,
        reconciliation,
        sources,
        f"public-temporal-response-semantics:center-hill:{digest}",
    )


def _validate_acquisition_and_document(
    manifest: dict[str, Any],
    plan: dict[str, Any],
    document: str,
) -> dict[str, object]:
    after = manifest.get("claim_boundary_after_acquisition") or {}
    folded = document.casefold()
    required_fragments = {
        "instantaneous_definition": (
            "sample is not a composite of inputs over time"
        ),
        "default_end_of_period_storage": (
            "for composite samples stores at the \"\"end of period\"\" by default"
        ),
        "one_hour_composite_definition": (
            "sample is a composite of input data over a 1 hour window"
        ),
        "utc_storage_statement": (
            "stored data in cwms is stored at the non-ambiguous utc time"
        ),
    }
    if (
        manifest.get("schema") != ACQUISITION_SCHEMA
        or manifest.get("status")
        != "temporal_semantics_document_acquired"
        or manifest.get("artifact_count") != 1
        or manifest.get("actual_request_count") != 1
        or plan != manifest.get("frozen_acquisition_plan_content")
        or after.get("operator_frozen_before_document_values") is not True
        or after.get("release_or_downstream_outcome_values_acquired")
        is not False
        or any(value not in folded for value in required_fragments.values())
    ):
        raise ValueError("public_temporal_response_acquisition_invalid")
    return {
        "source_commit": manifest["document_commit"],
        "instantaneous_is_not_composite": True,
        "composite_default_timestamp_position": "end",
        "one_hour_duration_is_composite_window_seconds": 3600,
        "cwms_storage_time_basis": "UTC",
        "matched_casefolded_fragments": required_fragments,
    }


def _validate_smoke_report(value: dict[str, Any]) -> None:
    supports = value.get("temporal_supports") or {}
    checks = value.get("checks") or {}
    if (
        value.get("schema") != "gwm.geotransport.center_hill_smoke_panel.v2"
        or value.get("status") != "compiled_not_admitted"
        or checks.get("cwms_eop_labels_mapped_to_preceding_hour_support")
        is not True
        or checks.get("usgs_half_hour_samples_aggregated_open_left_closed_right")
        is not True
        or supports.get("action_release_m3s", {}).get("kind")
        != "interval_mean"
        or supports.get(
            "outcome_discharge_interval_sample_mean_m3s", {}
        ).get("kind")
        != "interval_sample_mean"
    ):
        raise ValueError("public_temporal_response_smoke_report_invalid")


def _validate_cwms_source(value: dict[str, Any]) -> None:
    if (
        value.get("name") != SOURCE_SERIES_ID
        or value.get("units") != "cms"
        or value.get("interval") != "PT1H"
        or value.get("interval-offset") != 0
        or value.get("time-zone") != "US/Central"
        or value.get("total") != 43_825
        or len(value.get("values") or []) != 43_825
    ):
        raise ValueError("public_temporal_response_cwms_source_invalid")


def _load_target_metadata(
    root: Path,
) -> tuple[dict[str, object], dict[str, Any]]:
    manifest = _read_json(STAGE27_MANIFEST_PATH)
    record = next(
        value
        for value in manifest["artifacts"]
        if value["source_id"] == "usgs_time_series_metadata_03424860"
    )
    return dict(record), json.loads(_read_verified(record, root))


def _validate_target_metadata(value: dict[str, Any]) -> None:
    matches = [
        feature["properties"]
        for feature in value.get("features") or []
        if feature.get("id") == TARGET_SERIES_ID
    ]
    if len(matches) != 1:
        raise ValueError("public_temporal_response_target_series_not_unique")
    item = matches[0]
    if (
        item.get("monitoring_location_id") != TARGET_SITE_ID
        or item.get("parameter_code") != "00060"
        or item.get("statistic_id") != "00011"
        or item.get("computation_period_identifier") != "Points"
        or item.get("computation_identifier") != "Instantaneous"
        or item.get("unit_of_measure") != "ft^3/s"
    ):
        raise ValueError("public_temporal_response_target_metadata_invalid")


def _validate_stage32_observation_support(ledger) -> None:
    for event in ledger.events:
        for value in event.downstream_hourly:
            start = _parse_time(value.support_start_utc)
            end = _parse_time(value.support_end_utc)
            samples = tuple(_parse_time(item) for item in value.sample_times_utc)
            if (
                end.timestamp() - start.timestamp() != 3600.0
                or samples != (
                    end - timedelta(minutes=30),
                    end,
                )
                or value.approval_statuses != ("Approved", "Approved")
            ):
                raise ValueError(
                    "public_temporal_response_observation_support_invalid"
                )
def _temporal_support(value: dict[str, Any]) -> TemporalSupport:
    return TemporalSupport(
        str(value["kind"]),
        float(value["duration_seconds"]),
        str(value["timestamp_position"]),
        str(value["provenance_id"]),
        str(value["evidence_level"]),
    )


def _read_verified(record: dict[str, Any], root: Path) -> bytes:
    path = _resolve(record, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != record.get("sha256")
        or len(body) != record.get("size_bytes")
    ):
        raise ValueError("public_temporal_response_artifact_identity_mismatch")
    return body


def _resolve(record: dict[str, Any], root: Path) -> Path:
    path = (root / str(record["path"])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "public_temporal_response_artifact_outside_repository"
        ) from exc
    return path


def _artifact(path: Path, root: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.resolve().relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_temporal_response_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_temporal_response_timezone_required")
    return parsed.astimezone(timezone.utc)
