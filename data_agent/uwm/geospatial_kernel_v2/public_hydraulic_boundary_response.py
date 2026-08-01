"""Stage 36 blind downstream evidence for hydraulic-boundary events."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    hydraulic_boundary_perturbation as perturbation,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_blind_transfer_evidence as stage29,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE36_ROOT = (
    "data/geotransport_v0_1/stage36_center_hill_hydraulic_boundary_events"
)
DEFAULT_SOURCE_ROOT = REPO_ROOT / STAGE36_ROOT
SCHEMA = "gwm.geotransport.public_hydraulic_boundary_response.v1"
SELECTION_SCHEMA = "gwm.geotransport.stage36_tailwater_event_selection.v1"
OBSERVATION_SCHEMA = (
    "gwm.geotransport.stage36_downstream_observation_acquisition.v1"
)
PROTOCOL_SCHEMA = (
    "gwm.geotransport.stage36_hydraulic_boundary_event_protocol.v1"
)
TARGET_SITE_ID = "USGS-03424860"
TARGET_PARAMETER_CODE = "00060"
TARGET_STATISTIC_ID = "00011"
TARGET_UNIT = "ft^3/s"
EXPECTED_EVENT_IDS = (
    "tailwater_stage_change_20231004T1730Z",
    "tailwater_stage_change_20210901T1530Z",
    "tailwater_stage_change_20210303T2330Z",
    "tailwater_stage_change_20220903T1630Z",
)
BASELINE_SUPPORT_REJECTION = "baseline_real_sample_count_below_30"


@dataclass(frozen=True)
class PublicHydraulicBoundaryResponseEvent:
    """One blind event evaluated on the frozen half-hour target grid."""

    event_id: str
    selection_rank: int
    marker_time_utc: str
    source_perturbation: dict[str, Any]
    raw_sample_count: int
    approved_sample_count: int
    discharge_grid_m3s: tuple[float | None, ...]
    baseline_real_sample_count: int
    search_real_sample_count: int
    target_report: perturbation.FirstPersistentDownstreamDeparture | None
    target_support_rejection_reasons: tuple[str, ...]
    source_artifact: dict[str, object]

    def __post_init__(self) -> None:
        if (
            self.event_id not in EXPECTED_EVENT_IDS
            or self.selection_rank not in range(1, 5)
            or len(self.discharge_grid_m3s)
            != perturbation.TARGET_INCLUSIVE_WINDOW_SAMPLE_COUNT
            or not 0 <= self.approved_sample_count <= self.raw_sample_count
            or self.approved_sample_count != self.raw_sample_count
            or self.baseline_real_sample_count
            != sum(
                value is not None
                for value in self.discharge_grid_m3s[
                    : perturbation.TARGET_BASELINE_END_INDEX
                ]
            )
            or self.search_real_sample_count
            != sum(
                value is not None
                for value in self.discharge_grid_m3s[
                    perturbation.TARGET_SOURCE_MARKER_INDEX + 1 :
                    perturbation.TARGET_SEARCH_END_INDEX + 1
                ]
            )
            or (
                self.target_report is None
                and self.target_support_rejection_reasons
                != (BASELINE_SUPPORT_REJECTION,)
            )
            or (
                self.target_report is not None
                and self.target_support_rejection_reasons
            )
            or self.source_perturbation.get("blind_target_test_admissible")
            is not True
        ):
            raise ValueError("public_hydraulic_boundary_response_event_invalid")

    @property
    def grid_real_sample_count(self) -> int:
        return sum(value is not None for value in self.discharge_grid_m3s)

    @property
    def grid_missing_sample_count(self) -> int:
        return len(self.discharge_grid_m3s) - self.grid_real_sample_count

    @property
    def target_functional_assessable(self) -> bool:
        return self.target_report is not None

    @property
    def statistical_departure_detected(self) -> bool:
        return self.target_report is not None and self.target_report.detected

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "role": "blind_hydraulic_boundary_response_test",
            "selection_rank": self.selection_rank,
            "marker_time_utc": self.marker_time_utc,
            "selected_without_downstream_values": True,
            "target_functional_frozen_before_downstream_values": True,
            "source_perturbation": self.source_perturbation,
            "raw_sample_count": self.raw_sample_count,
            "approved_sample_count": self.approved_sample_count,
            "expected_half_hour_grid_sample_count": len(
                self.discharge_grid_m3s
            ),
            "grid_real_sample_count": self.grid_real_sample_count,
            "grid_missing_sample_count": self.grid_missing_sample_count,
            "baseline_real_sample_count": self.baseline_real_sample_count,
            "search_real_sample_count": self.search_real_sample_count,
            "discharge_grid_m3s": list(self.discharge_grid_m3s),
            "missing_values_filled": False,
            "target_functional_assessable": (
                self.target_functional_assessable
            ),
            "target_support_rejection_reasons": list(
                self.target_support_rejection_reasons
            ),
            "statistical_departure_detected": (
                self.statistical_departure_detected
            ),
            "target_report": (
                None if self.target_report is None else self.target_report.as_dict()
            ),
            "source_artifact": self.source_artifact,
            "causal_release_response_admitted": False,
            "physical_first_arrival_admitted": False,
            "physical_travel_time_admitted": False,
        }


@dataclass(frozen=True)
class PublicHydraulicBoundaryResponseLedger:
    operator_artifact: dict[str, object]
    protocol_artifact: dict[str, object]
    selection_plan_artifact: dict[str, object]
    event_selection_manifest_artifact: dict[str, object]
    observation_plan_artifact: dict[str, object]
    observation_acquisition_manifest_artifact: dict[str, object]
    events: tuple[PublicHydraulicBoundaryResponseEvent, ...]
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            tuple(value.event_id for value in self.events)
            != EXPECTED_EVENT_IDS
            or tuple(value.selection_rank for value in self.events)
            != (1, 2, 3, 4)
            or len(self.source_artifacts) != 9
        ):
            raise ValueError("public_hydraulic_boundary_response_ledger_invalid")

    @property
    def assessable_event_count(self) -> int:
        return sum(value.target_functional_assessable for value in self.events)

    @property
    def detected_event_count(self) -> int:
        return sum(value.statistical_departure_detected for value in self.events)

    @property
    def all_events_target_functional_assessable(self) -> bool:
        return all(value.target_functional_assessable for value in self.events)

    @property
    def all_assessable_events_detect_departure(self) -> bool:
        return all(
            value.statistical_departure_detected
            for value in self.events
            if value.target_functional_assessable
        )

    @property
    def all_event_statistical_departure_support_admitted(self) -> bool:
        return (
            self.all_events_target_functional_assessable
            and all(
                value.statistical_departure_detected for value in self.events
            )
        )

    def require_all_event_statistical_departures(self) -> None:
        if not self.all_event_statistical_departure_support_admitted:
            raise ValueError(
                "hydraulic_boundary_all_event_departures_unadmitted"
            )

    def require_causal_release_response(self) -> None:
        raise ValueError(
            "hydraulic_boundary_statistical_departure_is_not_causal_response"
        )

    def require_physical_first_arrival(self) -> None:
        raise ValueError(
            "hydraulic_boundary_statistical_departure_is_not_physical_arrival"
        )

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "hydraulic_boundary_statistical_departure_is_not_physical_time"
        )

    def promote_to_runtime_operator(self) -> None:
        raise ValueError(
            "hydraulic_boundary_response_runtime_operator_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "operator_artifact": self.operator_artifact,
            "protocol_artifact": self.protocol_artifact,
            "selection_plan_artifact": self.selection_plan_artifact,
            "event_selection_manifest_artifact": (
                self.event_selection_manifest_artifact
            ),
            "observation_plan_artifact": self.observation_plan_artifact,
            "observation_acquisition_manifest_artifact": (
                self.observation_acquisition_manifest_artifact
            ),
            "events": [value.as_dict() for value in self.events],
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "diagnostic_summary": {
                "event_count": len(self.events),
                "assessable_event_count": self.assessable_event_count,
                "detected_event_count": self.detected_event_count,
                "per_event_target_functional_assessable": [
                    value.target_functional_assessable for value in self.events
                ],
                "per_event_statistical_departure_detected": [
                    value.statistical_departure_detected for value in self.events
                ],
                "per_event_first_departure_offset_minutes": [
                    None
                    if value.target_report is None
                    else value.target_report.first_departure_offset_minutes
                    for value in self.events
                ],
            },
            "claim_boundary": {
                "events_and_target_functional_frozen_before_outcomes": True,
                "missing_half_hour_samples_filled": False,
                "statistical_departure_is_causal_release_response": False,
                "statistical_departure_is_physical_first_arrival": False,
                "statistical_departure_is_physical_travel_time": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "blind_downstream_evidence_compiled": True,
                "assessable_event_count": self.assessable_event_count,
                "detected_event_count": self.detected_event_count,
                "all_events_target_functional_assessable": (
                    self.all_events_target_functional_assessable
                ),
                "all_assessable_events_detect_departure": (
                    self.all_assessable_events_detect_departure
                ),
                "all_event_statistical_departure_support_admitted": (
                    self.all_event_statistical_departure_support_admitted
                ),
                "causal_release_response_admitted": False,
                "physical_first_arrival_admitted": False,
                "physical_travel_time_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_hydraulic_boundary_response(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicHydraulicBoundaryResponseLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    protocol_path = source / "protocol.json"
    selection_plan_path = source / "selection_plan.json"
    selection_path = source / "event_selection_manifest.json"
    observation_plan_path = source / "observation_plan.json"
    observation_path = source / "observation_acquisition_manifest.json"
    protocol = _read_json(protocol_path)
    selection_plan = _read_json(selection_plan_path)
    selection = _read_json(selection_path)
    observation_plan = _read_json(observation_plan_path)
    observations = _read_json(observation_path)
    _validate_manifests(
        protocol,
        selection_plan,
        selection,
        observation_plan,
        observations,
        root,
    )
    selection_artifacts = _verify_artifacts(selection["artifacts"], root)
    observation_artifacts = _verify_artifacts(observations["artifacts"], root)
    by_event = {
        str(value["event_id"]): value for value in observation_artifacts
    }
    events = tuple(
        _compile_event(event, by_event=by_event, root=root)
        for event in selection["selected_events"]
    )
    source_artifacts = tuple(selection_artifacts + observation_artifacts)
    manifest_artifacts = (
        _artifact(protocol_path, root),
        _artifact(selection_plan_path, root),
        _artifact(selection_path, root),
        _artifact(observation_plan_path, root),
        _artifact(observation_path, root),
    )
    digest = hashlib.sha256(
        "|".join(
            str(value["sha256"])
            for value in (*manifest_artifacts, *source_artifacts)
        ).encode("ascii")
    ).hexdigest()
    return PublicHydraulicBoundaryResponseLedger(
        dict(selection["frozen_operator_artifact"]),
        manifest_artifacts[0],
        manifest_artifacts[1],
        manifest_artifacts[2],
        manifest_artifacts[3],
        manifest_artifacts[4],
        events,
        source_artifacts,
        f"center-hill-hydraulic-boundary-response:{digest}",
    )


def _compile_event(
    event: dict[str, Any],
    *,
    by_event: dict[str, dict[str, object]],
    root: Path,
) -> PublicHydraulicBoundaryResponseEvent:
    event_id = str(event["event_id"])
    record = by_event[event_id]
    payload = _read_json(_resolve(record, root))
    marker = _parse_time(str(event["marker_time_utc"]))
    begin = marker - timedelta(hours=24)
    grid_times = tuple(
        begin + timedelta(minutes=30 * index)
        for index in range(perturbation.TARGET_INCLUSIVE_WINDOW_SAMPLE_COUNT)
    )
    grid_set = set(grid_times)
    by_time: dict[datetime, float] = {}
    approved_count = 0
    features = payload.get("features") or []
    for feature in features:
        properties = feature.get("properties") or {}
        timestamp = _parse_time(str(properties.get("time")))
        value = float(properties.get("value"))
        if (
            properties.get("monitoring_location_id") != TARGET_SITE_ID
            or properties.get("parameter_code") != TARGET_PARAMETER_CODE
            or properties.get("statistic_id") != TARGET_STATISTIC_ID
            or properties.get("unit_of_measure") != TARGET_UNIT
            or properties.get("approval_status") != "Approved"
            or not math.isfinite(value)
            or timestamp not in grid_set
            or timestamp in by_time
        ):
            raise ValueError("public_hydraulic_boundary_observation_invalid")
        by_time[timestamp] = value * stage29.CFS_TO_M3S
        approved_count += 1
    grid = tuple(by_time.get(timestamp) for timestamp in grid_times)
    baseline_count = sum(
        value is not None
        for value in grid[: perturbation.TARGET_BASELINE_END_INDEX]
    )
    search_count = sum(
        value is not None
        for value in grid[
            perturbation.TARGET_SOURCE_MARKER_INDEX + 1 :
            perturbation.TARGET_SEARCH_END_INDEX + 1
        ]
    )
    report = None
    reasons: tuple[str, ...] = (BASELINE_SUPPORT_REJECTION,)
    if baseline_count >= perturbation.TARGET_MINIMUM_BASELINE_SAMPLE_COUNT:
        report = perturbation.compile_first_persistent_downstream_departure(grid)
        reasons = ()
    return PublicHydraulicBoundaryResponseEvent(
        event_id,
        int(event["selection_rank"]),
        str(event["marker_time_utc"]),
        dict(event["source_only_perturbation"]),
        len(features),
        approved_count,
        grid,
        baseline_count,
        search_count,
        report,
        reasons,
        record,
    )


def _validate_manifests(
    protocol: dict[str, Any],
    selection_plan: dict[str, Any],
    selection: dict[str, Any],
    observation_plan: dict[str, Any],
    observations: dict[str, Any],
    root: Path,
) -> None:
    selection_after = selection.get("claim_boundary_after_source_selection") or {}
    observation_after = observations.get("claim_boundary_after_observations") or {}
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or selection_plan.get("schema") != SELECTION_SCHEMA
        or selection.get("schema") != SELECTION_SCHEMA
        or selection.get("status")
        != "hydraulic_boundary_events_frozen_before_outcomes"
        or selection.get("selected_event_count") != 4
        or tuple(
            str(value.get("event_id"))
            for value in selection.get("selected_events") or []
        )
        != EXPECTED_EVENT_IDS
        or selection_after.get("events_selected_from_tailwater_elevation_only")
        is not True
        or selection_after.get("downstream_values_acquired") is not False
        or observation_plan.get("schema") != OBSERVATION_SCHEMA
        or observation_plan.get("mode") != "observation_plan"
        or observations.get("schema") != OBSERVATION_SCHEMA
        or observations.get("mode") != "observation_values"
        or observations.get("status")
        != "stage36_downstream_observations_acquired"
        or observations.get("selected_events") != selection.get("selected_events")
        or observations.get("artifact_count") != 4
        or observations.get("actual_request_count") != 4
        or not 4 <= int(observations.get("actual_attempt_count", 0)) <= 12
        or observation_after.get("downstream_values_acquired") is not True
        or observation_after.get("statistical_departures_compiled") is not False
        or observation_after.get("causal_response_admitted") is not False
        or observation_after.get("physical_first_arrival_admitted") is not False
        or observation_after.get("physical_travel_time_admitted") is not False
    ):
        raise ValueError("public_hydraulic_boundary_manifest_invalid")
    if (
        observation_plan.get("selected_events") != selection.get("selected_events")
        or observation_plan.get("frozen_protocol_artifact")
        != selection.get("frozen_protocol_artifact")
        or observation_plan.get("frozen_operator_artifact")
        != selection.get("frozen_operator_artifact")
        or observation_plan.get("request_boundary", {}).get(
            "event_selection_may_be_recomputed_from_outcomes"
        )
        is not False
        or observation_plan.get("request_boundary", {}).get(
            "source_or_target_threshold_retuning_allowed"
        )
        is not False
        or observations.get("frozen_observation_plan_content")
        != observation_plan
    ):
        raise ValueError("public_hydraulic_boundary_observation_plan_invalid")
    frozen_bindings = (
        (selection["frozen_protocol_artifact"], protocol),
        (selection["frozen_selection_plan"], selection_plan),
        (observation_plan["frozen_event_selection_manifest"], selection),
        (observations["frozen_observation_plan"], observation_plan),
    )
    for descriptor, expected in frozen_bindings:
        if json.loads(_read_verified(descriptor, root)) != expected:
            raise ValueError("public_hydraulic_boundary_frozen_binding_invalid")
    _read_verified(selection["frozen_operator_artifact"], root)


def _verify_artifacts(
    descriptors: list[dict[str, Any]], root: Path
) -> list[dict[str, object]]:
    result = []
    seen = set()
    for descriptor in descriptors:
        source_id = str(descriptor.get("source_id"))
        if source_id in seen:
            raise ValueError("public_hydraulic_boundary_duplicate_source")
        seen.add(source_id)
        _read_verified(descriptor, root)
        if (
            descriptor.get("hash_verified") is not True
            or descriptor.get("tls_hostname_verification_retained") is not True
        ):
            raise ValueError("public_hydraulic_boundary_provenance_invalid")
        result.append(dict(descriptor))
    return result


def _artifact(path: Path, root: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": str(path.resolve().relative_to(root)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_verified(descriptor: dict[str, Any], root: Path) -> bytes:
    path = _resolve(descriptor, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("public_hydraulic_boundary_artifact_mismatch")
    return body


def _resolve(descriptor: dict[str, Any], root: Path) -> Path:
    path = (root / str(descriptor["path"])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "public_hydraulic_boundary_artifact_outside_repository"
        ) from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_hydraulic_boundary_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_hydraulic_boundary_timezone_required")
    return parsed.astimezone(UTC)
