"""Typed public operational-boundary evidence and lag diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.public_spatial_boundary_evidence import (
    compile_public_spatial_boundary_evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage28_center_hill_operational_boundary_evidence"
)
PUBLIC_OPERATIONAL_BOUNDARY_EVIDENCE_SCHEMA = (
    "gwm.geotransport.public_operational_boundary_evidence.v1"
)
ACQUISITION_SCHEMA = (
    "gwm.geotransport.stage28_operational_boundary_acquisition.v1"
)
CWMS_LOCATION_ID = "CETT1-CENTER_HILL"
CWMS_SERIES_ID = (
    "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev"
)
CWMS_OFFICE = "LRN"
UPSTREAM_SITE_ID = "USGS-03424010"
DOWNSTREAM_SITE_ID = "USGS-03424860"
DOWNSTREAM_PARAMETER_CODE = "00060"
LAG_CANDIDATES_HOURS = tuple(range(13))
DEVELOPMENT_EVENT_ID = "high_release_2024"
TRANSFER_EVENT_ID = "low_release_2026"
CFS_TO_M3S = 0.028316846592
UPSTREAM_SITE_ZONE_RADIUS_M = 250.0


@dataclass(frozen=True)
class TailwaterSiteZoneBinding:
    cwms_location_id: str
    cwms_public_name: str
    cwms_coordinate_nad83: tuple[float, float]
    cwms_location_type: str
    upstream_monitoring_location_id: str
    upstream_name: str
    upstream_coordinate_wgs84: tuple[float, float]
    coordinate_distance_m: float
    zone_radius_m: float

    @property
    def within_upstream_site_zone(self) -> bool:
        return self.coordinate_distance_m <= self.zone_radius_m

    def as_dict(self) -> dict[str, object]:
        return {
            "cwms_location_id": self.cwms_location_id,
            "cwms_public_name": self.cwms_public_name,
            "cwms_coordinate": {
                "longitude": self.cwms_coordinate_nad83[0],
                "latitude": self.cwms_coordinate_nad83[1],
                "horizontal_datum": "NAD83",
            },
            "cwms_location_type": self.cwms_location_type,
            "stage27_upstream_site": {
                "monitoring_location_id": self.upstream_monitoring_location_id,
                "name": self.upstream_name,
                "coordinate_wgs84": list(self.upstream_coordinate_wgs84),
            },
            "coordinate_distance_m": self.coordinate_distance_m,
            "zone_radius_m": self.zone_radius_m,
            "within_upstream_site_zone": self.within_upstream_site_zone,
            "binding_method": (
                "nad83_to_wgs84_coordinate_proximity_without_datum_transform"
            ),
            "same_physical_tailwater_zone_admitted": (
                self.within_upstream_site_zone
            ),
            "same_sensor_or_measurement_process_admitted": False,
        }


@dataclass(frozen=True)
class ReleaseSeriesCatalogEvidence:
    name: str
    office: str
    units: str
    interval: str
    interval_offset_minutes: int
    time_zone: str
    earliest_time: str
    latest_time: str
    aliases: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "office": self.office,
            "units": self.units,
            "interval": self.interval,
            "interval_offset_minutes": self.interval_offset_minutes,
            "time_zone": self.time_zone,
            "earliest_time": self.earliest_time,
            "latest_time": self.latest_time,
            "aliases": [
                {"name": name, "value": value}
                for name, value in self.aliases
            ],
            "outflow_alias_present": any(
                value == "Outflow" for _, value in self.aliases
            ),
            "total_flow_alias_present": any(
                value == "Total Flow" for _, value in self.aliases
            ),
            "support_semantics": (
                "one_hour_average_with_timestamp_at_support_end"
            ),
            "quality_code_zero_interpreted_as_approved": False,
        }


@dataclass(frozen=True)
class HourlyRelease:
    support_start_utc: str
    support_end_utc: str
    value_m3s: float
    quality_code: int

    def as_dict(self) -> dict[str, object]:
        return {
            "support_start_utc": self.support_start_utc,
            "support_end_utc": self.support_end_utc,
            "value_m3s": self.value_m3s,
            "quality_code": self.quality_code,
        }


@dataclass(frozen=True)
class HourlyDownstreamObservation:
    support_start_utc: str
    support_end_utc: str
    sample_times_utc: tuple[str, ...]
    sample_values_cfs: tuple[float, ...]
    mean_value_m3s: float
    approval_statuses: tuple[str, ...]

    @property
    def fully_approved(self) -> bool:
        return all(value == "Approved" for value in self.approval_statuses)

    def as_dict(self) -> dict[str, object]:
        return {
            "support_start_utc": self.support_start_utc,
            "support_end_utc": self.support_end_utc,
            "sample_times_utc": list(self.sample_times_utc),
            "sample_values_cfs": list(self.sample_values_cfs),
            "sample_count": len(self.sample_times_utc),
            "mean_value_m3s": self.mean_value_m3s,
            "approval_statuses": list(self.approval_statuses),
            "fully_approved": self.fully_approved,
            "aggregation": "arithmetic_mean_of_observed_samples",
            "missing_values_filled": False,
        }


@dataclass(frozen=True)
class LagDiagnostic:
    lag_hours: int
    pair_count: int
    release_mean_m3s: float
    downstream_mean_m3s: float
    mean_bias_m3s: float
    mae_m3s: float
    rmse_m3s: float
    pearson_r: float | None
    release_standard_deviation_m3s: float
    downstream_standard_deviation_m3s: float

    def as_dict(self) -> dict[str, object]:
        return {
            "lag_hours": self.lag_hours,
            "pair_count": self.pair_count,
            "release_mean_m3s": self.release_mean_m3s,
            "downstream_mean_m3s": self.downstream_mean_m3s,
            "mean_bias_m3s": self.mean_bias_m3s,
            "mae_m3s": self.mae_m3s,
            "rmse_m3s": self.rmse_m3s,
            "pearson_r": self.pearson_r,
            "release_standard_deviation_m3s": (
                self.release_standard_deviation_m3s
            ),
            "downstream_standard_deviation_m3s": (
                self.downstream_standard_deviation_m3s
            ),
        }


@dataclass(frozen=True)
class OperationalBoundaryEventEvidence:
    event_id: str
    role: str
    start_utc: str
    end_utc: str
    raw_release_value_count: int
    raw_downstream_sample_count: int
    hourly_releases: tuple[HourlyRelease, ...]
    hourly_downstream: tuple[HourlyDownstreamObservation, ...]
    dropped_downstream_hour_count: int
    lag_diagnostics: tuple[LagDiagnostic, ...]
    selected_lag_hours: int | None
    lag_selection_status: str
    source_artifacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if (
            len(self.hourly_releases) != 72
            or len(self.hourly_downstream) != 72
            or self.dropped_downstream_hour_count != 0
            or tuple(value.lag_hours for value in self.lag_diagnostics)
            != LAG_CANDIDATES_HOURS
            or tuple(value.pair_count for value in self.lag_diagnostics)
            != tuple(72 - lag for lag in LAG_CANDIDATES_HOURS)
        ):
            raise ValueError("public_operational_boundary_event_invalid")

    @property
    def release_value_range_m3s(self) -> float:
        values = [value.value_m3s for value in self.hourly_releases]
        return max(values) - min(values)

    @property
    def downstream_fully_approved(self) -> bool:
        return all(value.fully_approved for value in self.hourly_downstream)

    def as_dict(self) -> dict[str, object]:
        selected = next(
            (
                value.as_dict()
                for value in self.lag_diagnostics
                if value.lag_hours == self.selected_lag_hours
            ),
            None,
        )
        return {
            "event_id": self.event_id,
            "role": self.role,
            "window": {
                "start_utc": self.start_utc,
                "end_utc": self.end_utc,
                "duration_hours": 72,
            },
            "raw_release_value_count": self.raw_release_value_count,
            "raw_downstream_sample_count": self.raw_downstream_sample_count,
            "hourly_release_count": len(self.hourly_releases),
            "hourly_downstream_count": len(self.hourly_downstream),
            "dropped_downstream_hour_count": self.dropped_downstream_hour_count,
            "release_value_range_m3s": self.release_value_range_m3s,
            "downstream_fully_approved": self.downstream_fully_approved,
            "hourly_releases": [
                value.as_dict() for value in self.hourly_releases
            ],
            "hourly_downstream": [
                value.as_dict() for value in self.hourly_downstream
            ],
            "lag_diagnostics": [
                value.as_dict() for value in self.lag_diagnostics
            ],
            "selected_lag_hours": self.selected_lag_hours,
            "selected_lag_diagnostic": selected,
            "lag_selection_status": self.lag_selection_status,
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class FieldReleaseComparison:
    event_id: str
    field_observation_time_utc: str
    field_discharge_cfs: float
    field_discharge_m3s: float
    field_approval_status: str
    release_support_start_utc: str
    release_support_end_utc: str
    release_m3s: float
    field_minus_release_m3s: float
    field_to_release_ratio: float

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "field_observation_time_utc": self.field_observation_time_utc,
            "field_discharge_cfs": self.field_discharge_cfs,
            "field_discharge_m3s": self.field_discharge_m3s,
            "field_approval_status": self.field_approval_status,
            "containing_release_support": {
                "start_utc": self.release_support_start_utc,
                "end_utc": self.release_support_end_utc,
                "release_m3s": self.release_m3s,
            },
            "field_minus_release_m3s": self.field_minus_release_m3s,
            "field_to_release_ratio": self.field_to_release_ratio,
            "comparison_role": "cross_source_consistency_diagnostic",
            "exact_sensor_crosswalk_claimed": False,
        }


@dataclass(frozen=True)
class PublicOperationalBoundaryEvidenceLedger:
    location_binding: TailwaterSiteZoneBinding
    series_catalog: ReleaseSeriesCatalogEvidence
    events: tuple[OperationalBoundaryEventEvidence, ...]
    field_release_comparisons: tuple[FieldReleaseComparison, ...]
    source_artifacts: tuple[dict[str, object], ...]
    request_boundary: dict[str, object]
    acquisition_plan: dict[str, object]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            tuple(value.event_id for value in self.events)
            != (DEVELOPMENT_EVENT_ID, TRANSFER_EVENT_ID)
            or not self.location_binding.within_upstream_site_zone
            or len(self.field_release_comparisons) != 2
            or len(self.source_artifacts) != 6
        ):
            raise ValueError("public_operational_boundary_evidence_ledger_invalid")

    @property
    def development_event(self) -> OperationalBoundaryEventEvidence:
        return self.events[0]

    @property
    def transfer_event(self) -> OperationalBoundaryEventEvidence:
        return self.events[1]

    def require_bounded_operational_release_windows(
        self,
    ) -> tuple[OperationalBoundaryEventEvidence, ...]:
        return self.events

    def require_exact_sensor_crosswalk(self) -> None:
        raise ValueError(
            "public_operational_boundary_exact_sensor_crosswalk_unproven"
        )

    def require_transfer_identified_lag(self) -> None:
        raise ValueError(
            "public_operational_boundary_transfer_release_variance_zero"
        )

    def require_stable_travel_time(self) -> None:
        raise ValueError(
            "public_operational_boundary_two_event_travel_time_unidentified"
        )

    def require_boundary_conditioned_rollout(self) -> None:
        raise ValueError(
            "public_operational_boundary_diagnostic_is_not_rollout"
        )

    def promote_lag_to_runtime_operator(self) -> None:
        raise ValueError(
            "public_operational_boundary_lag_operator_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        development = self.development_event
        transfer = self.transfer_event
        return {
            "schema": PUBLIC_OPERATIONAL_BOUNDARY_EVIDENCE_SCHEMA,
            "location_binding": self.location_binding.as_dict(),
            "series_catalog": self.series_catalog.as_dict(),
            "events": [value.as_dict() for value in self.events],
            "field_release_comparisons": [
                value.as_dict() for value in self.field_release_comparisons
            ],
            "request_boundary": self.request_boundary,
            "frozen_acquisition_plan": self.acquisition_plan,
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "diagnostic_summary": {
                "lag_candidates_hours": list(LAG_CANDIDATES_HOURS),
                "development_selected_lag_hours": (
                    development.selected_lag_hours
                ),
                "development_lag_selection_status": (
                    development.lag_selection_status
                ),
                "transfer_selected_lag_hours": transfer.selected_lag_hours,
                "transfer_lag_selection_status": transfer.lag_selection_status,
                "lag_stability_across_events_evaluable": False,
                "travel_time_identified": False,
            },
            "evidence_admission": {
                "public_operational_release_windows_admitted": True,
                "tailwater_location_bound_to_upstream_site_zone": True,
                "downstream_hourly_observations_admitted": True,
                "development_lag_diagnostic_admitted": True,
                "transfer_lag_diagnostic_identifiable": False,
                "exact_sensor_crosswalk_admitted": False,
                "stable_travel_time_admitted": False,
                "boundary_conditioned_rollout_admitted": False,
                "runtime_operator_admitted": False,
            },
            "claim_boundary": {
                "cwms_values_are_bounded_operational_release_evidence": True,
                "cwms_quality_code_zero_means_approved": False,
                "cwms_location_and_usgs_site_are_same_sensor": False,
                "field_measurements_validate_exact_sensor_crosswalk": False,
                "development_best_lag_is_calibrated_travel_time": False,
                "transfer_event_can_identify_lag": False,
                "travel_time_stable_across_events": False,
                "observed_spatial_rollout_completed": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "operational_boundary_evidence_admitted": True,
                "development_lag_diagnostic_admitted": True,
                "travel_time_admitted": False,
                "observed_spatial_rollout_completed": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_operational_boundary_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicOperationalBoundaryEvidenceLedger:
    repository = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    manifest = _read_json(source / "acquisition_manifest.json")
    _validate_manifest(manifest, repository)
    artifacts = _verify_artifacts(manifest, repository)
    by_source = {
        str(value["source_id"]): value for value in artifacts
    }

    stage27 = compile_public_spatial_boundary_evidence(repo_root=repository)
    upstream = next(
        value
        for value in stage27.candidates
        if value.monitoring_location_id == UPSTREAM_SITE_ID
    )
    location = _read_json(
        _resolve(by_source["cwms_tailwater_location"], repository)
    )
    cwms_coordinate = (
        float(location["longitude"]),
        float(location["latitude"]),
    )
    binding = TailwaterSiteZoneBinding(
        CWMS_LOCATION_ID,
        str(location["public-name"]),
        cwms_coordinate,
        str(location["location-type"]),
        upstream.monitoring_location_id,
        upstream.name,
        upstream.coordinate_wgs84,
        _great_circle_distance_m(
            cwms_coordinate, upstream.coordinate_wgs84
        ),
        UPSTREAM_SITE_ZONE_RADIUS_M,
    )
    catalog = _compile_catalog(
        _read_json(
            _resolve(by_source["cwms_release_series_catalog"], repository)
        )
    )
    event_specs = {
        str(value["event_id"]): value for value in manifest["events"]
    }
    events = tuple(
        _compile_event(
            event_specs[event_id],
            cwms_record=by_source[f"cwms_release_{event_id}"],
            usgs_record=by_source[f"usgs_downstream_{event_id}"],
            repository=repository,
        )
        for event_id in (DEVELOPMENT_EVENT_ID, TRANSFER_EVENT_ID)
    )
    snapshots = stage27.require_synchronized_spatial_snapshots()
    comparisons = tuple(
        _compile_field_release_comparison(event, snapshot)
        for event, snapshot in zip(events, snapshots, strict=True)
    )
    digest = hashlib.sha256(
        "|".join(sorted(str(value["sha256"]) for value in artifacts)).encode(
            "ascii"
        )
    ).hexdigest()
    return PublicOperationalBoundaryEvidenceLedger(
        binding,
        catalog,
        events,
        comparisons,
        tuple(artifacts),
        dict(manifest["request_boundary"]),
        dict(manifest["frozen_acquisition_plan"]),
        f"cwms-usgs-operational-boundary:center-hill:{digest}",
    )


def _compile_catalog(value: dict[str, Any]) -> ReleaseSeriesCatalogEvidence:
    entry = value["entries"][0]
    extents = entry["extents"]
    earliest = min(str(item["earliest-time"]) for item in extents)
    latest = max(str(item["latest-time"]) for item in extents)
    aliases = tuple(
        sorted(
            {
                (str(item["name"]), str(item["value"]))
                for item in entry["aliases"]
            }
        )
    )
    return ReleaseSeriesCatalogEvidence(
        str(entry["name"]),
        str(entry["office"]),
        str(entry["units"]),
        str(entry["interval"]),
        int(entry["interval-offset"]),
        str(entry["time-zone"]),
        earliest,
        latest,
        aliases,
    )


def _compile_event(
    spec: dict[str, Any],
    *,
    cwms_record: dict[str, object],
    usgs_record: dict[str, object],
    repository: Path,
) -> OperationalBoundaryEventEvidence:
    event_id = str(spec["event_id"])
    start = _parse_time(str(spec["start"]))
    end = _parse_time(str(spec["end"]))
    cwms = _read_json(_resolve(cwms_record, repository))
    usgs = _read_json(_resolve(usgs_record, repository))
    releases = tuple(
        HourlyRelease(
            _iso(timestamp - timedelta(hours=1)),
            _iso(timestamp),
            float(row[1]),
            int(row[2]),
        )
        for row in cwms["values"]
        for timestamp in (
            datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc),
        )
        if start < timestamp <= end
    )
    raw_samples = tuple(
        (
            _parse_time(str(feature["properties"]["time"])),
            float(feature["properties"]["value"]),
            str(feature["properties"]["approval_status"]),
        )
        for feature in usgs["features"]
    )
    downstream: list[HourlyDownstreamObservation] = []
    dropped = 0
    for index in range(1, 73):
        support_end = start + timedelta(hours=index)
        support_start = support_end - timedelta(hours=1)
        observed = tuple(
            value
            for value in raw_samples
            if support_start < value[0] <= support_end
        )
        expected_times = (
            support_end - timedelta(minutes=30),
            support_end,
        )
        if tuple(value[0] for value in observed) != expected_times:
            dropped += 1
            continue
        sample_values = tuple(value[1] for value in observed)
        downstream.append(
            HourlyDownstreamObservation(
                _iso(support_start),
                _iso(support_end),
                tuple(_iso(value[0]) for value in observed),
                sample_values,
                (sum(sample_values) / len(sample_values)) * CFS_TO_M3S,
                tuple(value[2] for value in observed),
            )
        )
    diagnostics = tuple(
        _compile_lag_diagnostic(releases, tuple(downstream), lag)
        for lag in LAG_CANDIDATES_HOURS
    )
    event_release_std = _standard_deviation(
        tuple(value.value_m3s for value in releases)
    )
    if event_release_std == 0.0:
        selected_lag = None
        status = "release_variance_zero_lag_unidentifiable"
    else:
        defined = [value for value in diagnostics if value.pearson_r is not None]
        selected = max(
            defined,
            key=lambda value: (
                float(value.pearson_r),
                -value.rmse_m3s,
                -value.lag_hours,
            ),
        )
        selected_lag = selected.lag_hours
        status = "development_correlation_lag_diagnostic_only"
    return OperationalBoundaryEventEvidence(
        event_id,
        str(spec["role"]),
        _iso(start),
        _iso(end),
        len(cwms["values"]),
        len(raw_samples),
        releases,
        tuple(downstream),
        dropped,
        diagnostics,
        selected_lag,
        status,
        (cwms_record, usgs_record),
    )


def _compile_lag_diagnostic(
    releases: tuple[HourlyRelease, ...],
    downstream: tuple[HourlyDownstreamObservation, ...],
    lag_hours: int,
) -> LagDiagnostic:
    outcome_by_end = {
        _parse_time(value.support_end_utc): value.mean_value_m3s
        for value in downstream
    }
    pairs = tuple(
        (release.value_m3s, outcome_by_end[target])
        for release in releases
        for target in (
            _parse_time(release.support_end_utc)
            + timedelta(hours=lag_hours),
        )
        if target in outcome_by_end
    )
    if not pairs:
        raise ValueError("public_operational_boundary_lag_pairs_missing")
    action = tuple(value[0] for value in pairs)
    outcome = tuple(value[1] for value in pairs)
    residual = tuple(b - a for a, b in pairs)
    action_mean = _mean(action)
    outcome_mean = _mean(outcome)
    action_std = _standard_deviation(action)
    outcome_std = _standard_deviation(outcome)
    pearson = None
    if action_std > 0.0 and outcome_std > 0.0:
        pearson = sum(
            (a - action_mean) * (b - outcome_mean)
            for a, b in pairs
        ) / (len(pairs) * action_std * outcome_std)
    return LagDiagnostic(
        lag_hours,
        len(pairs),
        action_mean,
        outcome_mean,
        _mean(residual),
        _mean(tuple(abs(value) for value in residual)),
        math.sqrt(_mean(tuple(value * value for value in residual))),
        pearson,
        action_std,
        outcome_std,
    )


def _compile_field_release_comparison(
    event: OperationalBoundaryEventEvidence, snapshot: Any
) -> FieldReleaseComparison:
    field = snapshot.candidate
    field_time = _parse_time(field.time)
    release = next(
        (
            value
            for value in event.hourly_releases
            if _parse_time(value.support_start_utc) < field_time
            <= _parse_time(value.support_end_utc)
        ),
        None,
    )
    if release is None:
        raise ValueError(
            "public_operational_boundary_field_release_support_missing"
        )
    field_m3s = field.value * CFS_TO_M3S
    return FieldReleaseComparison(
        event.event_id,
        field.time,
        field.value,
        field_m3s,
        field.approval_status,
        release.support_start_utc,
        release.support_end_utc,
        release.value_m3s,
        field_m3s - release.value_m3s,
        field_m3s / release.value_m3s,
    )


def _validate_manifest(
    manifest: dict[str, Any], repository: Path
) -> None:
    diagnostic = manifest.get("predeclared_diagnostic") or {}
    boundary = manifest.get("request_boundary") or {}
    claims = manifest.get("claim_boundary") or {}
    events = manifest.get("events") or []
    if (
        manifest.get("schema") != ACQUISITION_SCHEMA
        or manifest.get("mode") != "values"
        or diagnostic.get("lag_candidates_hours")
        != list(LAG_CANDIDATES_HOURS)
        or diagnostic.get("development_event_id") != DEVELOPMENT_EVENT_ID
        or diagnostic.get("transfer_event_id") != TRANSFER_EVENT_ID
        or [value.get("event_id") for value in events]
        != [DEVELOPMENT_EVENT_ID, TRANSFER_EVENT_ID]
        or boundary.get("workspace_or_private_data_sent") is not False
        or boundary.get("maximum_request_count") != 6
        or boundary.get(
            "cwms_fixed_ip_fallback_retains_tls_hostname_verification"
        )
        is not True
        or claims.get("source_values_acquired") is not True
        or claims.get("cwms_and_usgs_are_same_sensor") is not False
        or claims.get("travel_time_identified") is not False
        or manifest.get("artifact_count") != 6
        or manifest.get("actual_request_count") != 6
        or len(manifest.get("artifacts") or []) != 6
    ):
        raise ValueError(
            "public_operational_boundary_acquisition_manifest_invalid"
        )
    plan = manifest.get("frozen_acquisition_plan") or {}
    plan_body = _read_verified(plan, repository)
    plan_value = json.loads(plan_body)
    if (
        plan_value != manifest.get("frozen_acquisition_plan_content")
        or plan_value.get("mode") != "plan"
        or plan_value.get("predeclared_diagnostic", {}).get(
            "lag_candidates_hours"
        )
        != list(LAG_CANDIDATES_HOURS)
    ):
        raise ValueError("public_operational_boundary_frozen_plan_invalid")


def _verify_artifacts(
    manifest: dict[str, Any], repository: Path
) -> list[dict[str, object]]:
    verified: list[dict[str, object]] = []
    seen: set[str] = set()
    for descriptor in manifest["artifacts"]:
        source_id = str(descriptor["source_id"])
        if source_id in seen:
            raise ValueError(
                "public_operational_boundary_duplicate_source_artifact"
            )
        seen.add(source_id)
        _read_verified(descriptor, repository)
        if (
            descriptor.get("hash_verified") is not True
            or descriptor.get("tls_hostname_verification_retained") is not True
        ):
            raise ValueError(
                "public_operational_boundary_source_provenance_invalid"
            )
        verified.append(dict(descriptor))
    expected = {
        "cwms_tailwater_location",
        "cwms_release_series_catalog",
        "cwms_release_high_release_2024",
        "usgs_downstream_high_release_2024",
        "cwms_release_low_release_2026",
        "usgs_downstream_low_release_2026",
    }
    if seen != expected:
        raise ValueError("public_operational_boundary_source_set_invalid")
    return verified


def _read_verified(
    descriptor: dict[str, Any], repository: Path
) -> bytes:
    path = _resolve(descriptor, repository)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("public_operational_boundary_artifact_identity_mismatch")
    return body


def _resolve(descriptor: dict[str, Any], repository: Path) -> Path:
    path = (repository / str(descriptor["path"])).resolve()
    try:
        path.relative_to(repository)
    except ValueError as exc:
        raise ValueError(
            "public_operational_boundary_artifact_outside_repository"
        ) from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_operational_boundary_json_object_required")
    return value


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _standard_deviation(values: tuple[float, ...]) -> float:
    if max(values) == min(values):
        return 0.0
    mean = _mean(values)
    return math.sqrt(_mean(tuple((value - mean) ** 2 for value in values)))


def _great_circle_distance_m(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    lon1, lat1 = (math.radians(value) for value in first)
    lon2, lat2 = (math.radians(value) for value in second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * 6_371_008.8 * math.asin(math.sqrt(a))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_operational_boundary_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
