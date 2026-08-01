"""Blind multi-event release-response and observed tributary evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage29_center_hill_blind_transfer_events"
)
SCHEMA = "gwm.geotransport.public_blind_transfer_evidence.v1"
SELECTION_SCHEMA = "gwm.geotransport.stage29_release_event_selection.v1"
OBSERVATION_SCHEMA = "gwm.geotransport.stage29_observation_acquisition.v1"
CWMS_SERIES_ID = "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev"
DOWNSTREAM_SITE_ID = "USGS-03424860"
TRIBUTARY_SITE_ID = "USGS-03424730"
TRIBUTARY_COMID = 18421273
OUTLET_COMID = 18421703
LAG_CANDIDATES_HOURS = tuple(range(13))
STAGE28_FIXED_LAG_HOURS = 6
CFS_TO_M3S = 0.028316846592
EVENT_HOURS = 72
OBSERVATION_HOURS = 84


@dataclass(frozen=True)
class ObservedTributaryBinding:
    site_id: str
    name: str
    coordinate_wgs84: tuple[float, float]
    drainage_area_square_miles: float
    comid: int
    reachcode: str
    downstream_path_feature_ids: tuple[int, ...]
    continuous_series_id: str
    begin_utc: str
    end_utc: str

    @property
    def path_reaches_outlet(self) -> bool:
        return (
            self.downstream_path_feature_ids[0] == self.comid
            and OUTLET_COMID in self.downstream_path_feature_ids
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "name": self.name,
            "coordinate_wgs84": list(self.coordinate_wgs84),
            "drainage_area_square_miles": self.drainage_area_square_miles,
            "comid": self.comid,
            "reachcode": self.reachcode,
            "downstream_path_feature_ids": list(
                self.downstream_path_feature_ids
            ),
            "path_reaches_outlet_comid": self.path_reaches_outlet,
            "continuous_series": {
                "id": self.continuous_series_id,
                "parameter_code": "00060",
                "unit": "ft^3/s",
                "statistic_id": "00011",
                "computation": "Instantaneous",
                "begin_utc": self.begin_utc,
                "end_utc": self.end_utc,
            },
            "admitted_role": "observed_tributary_state_at_gauge",
            "tributary_mouth_flux_admitted": False,
            "all_lateral_inflow_admitted": False,
        }


@dataclass(frozen=True)
class HourlyObservedDischarge:
    support_start_utc: str
    support_end_utc: str
    sample_times_utc: tuple[str, str]
    sample_values_cfs: tuple[float, float]
    mean_m3s: float
    approval_statuses: tuple[str, str]

    @property
    def fully_approved(self) -> bool:
        return self.approval_statuses == ("Approved", "Approved")

    def as_dict(self) -> dict[str, object]:
        return {
            "support_start_utc": self.support_start_utc,
            "support_end_utc": self.support_end_utc,
            "sample_times_utc": list(self.sample_times_utc),
            "sample_values_cfs": list(self.sample_values_cfs),
            "mean_m3s": self.mean_m3s,
            "approval_statuses": list(self.approval_statuses),
            "fully_approved": self.fully_approved,
            "missing_values_filled": False,
        }


@dataclass(frozen=True)
class LagDiagnostic:
    lag_hours: int
    pair_count: int
    release_mean_m3s: float
    downstream_mean_m3s: float
    bias_m3s: float
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
            "bias_m3s": self.bias_m3s,
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
class TributaryEventContext:
    raw_sample_count: int
    complete_hour_count: int
    missing_hour_count: int
    fully_approved_hour_count: int
    mean_m3s: float | None
    maximum_m3s: float | None
    hourly_observations: tuple[HourlyObservedDischarge, ...]

    @property
    def coverage_ratio(self) -> float:
        return self.complete_hour_count / OBSERVATION_HOURS

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_sample_count": self.raw_sample_count,
            "expected_hour_count": OBSERVATION_HOURS,
            "complete_hour_count": self.complete_hour_count,
            "missing_hour_count": self.missing_hour_count,
            "coverage_ratio": self.coverage_ratio,
            "fully_approved_hour_count": self.fully_approved_hour_count,
            "mean_m3s": self.mean_m3s,
            "maximum_m3s": self.maximum_m3s,
            "hourly_observations": [
                value.as_dict() for value in self.hourly_observations
            ],
            "missing_values_filled": False,
            "represents_all_lateral_inflow": False,
        }


@dataclass(frozen=True)
class BlindTransferEventEvidence:
    event_id: str
    selection_rank: int
    step_time_utc: str
    signed_step_m3s: float
    absolute_step_m3s: float
    window_range_m3s: float
    start_utc: str
    end_utc: str
    release_values_m3s: tuple[float, ...]
    release_quality_codes: tuple[int, ...]
    raw_downstream_sample_count: int
    downstream_hourly: tuple[HourlyObservedDischarge, ...]
    lag_diagnostics: tuple[LagDiagnostic, ...]
    best_lag_hours: int
    fixed_lag_supported: bool
    fixed_lag_support_reasons: tuple[str, ...]
    tributary_context: TributaryEventContext
    source_artifacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if (
            len(self.release_values_m3s) != EVENT_HOURS
            or len(self.release_quality_codes) != EVENT_HOURS
            or len(self.downstream_hourly) != OBSERVATION_HOURS
            or tuple(value.lag_hours for value in self.lag_diagnostics)
            != LAG_CANDIDATES_HOURS
            or any(value.pair_count != EVENT_HOURS for value in self.lag_diagnostics)
        ):
            raise ValueError("public_blind_transfer_event_invalid")

    @property
    def fixed_lag_diagnostic(self) -> LagDiagnostic:
        return self.lag_diagnostics[STAGE28_FIXED_LAG_HOURS]

    @property
    def best_lag_diagnostic(self) -> LagDiagnostic:
        return self.lag_diagnostics[self.best_lag_hours]

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "role": "blind_transfer",
            "selected_without_observation_values": True,
            "selection_rank": self.selection_rank,
            "step_time_utc": self.step_time_utc,
            "signed_step_m3s": self.signed_step_m3s,
            "absolute_step_m3s": self.absolute_step_m3s,
            "window_range_m3s": self.window_range_m3s,
            "window": {
                "start_utc": self.start_utc,
                "end_utc": self.end_utc,
                "release_support_hour_count": EVENT_HOURS,
                "observation_support_hour_count": OBSERVATION_HOURS,
            },
            "release_values_m3s": list(self.release_values_m3s),
            "release_quality_codes": list(self.release_quality_codes),
            "raw_downstream_sample_count": self.raw_downstream_sample_count,
            "downstream_complete_hour_count": len(self.downstream_hourly),
            "downstream_hourly": [
                value.as_dict() for value in self.downstream_hourly
            ],
            "lag_diagnostics": [
                value.as_dict() for value in self.lag_diagnostics
            ],
            "best_lag_hours": self.best_lag_hours,
            "best_lag_diagnostic": self.best_lag_diagnostic.as_dict(),
            "stage28_fixed_lag_hours": STAGE28_FIXED_LAG_HOURS,
            "fixed_lag_diagnostic": self.fixed_lag_diagnostic.as_dict(),
            "fixed_lag_supported": self.fixed_lag_supported,
            "fixed_lag_support_reasons": list(self.fixed_lag_support_reasons),
            "tributary_context": self.tributary_context.as_dict(),
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class PublicBlindTransferEvidenceLedger:
    selection_plan_artifact: dict[str, object]
    observation_plan_artifact: dict[str, object]
    event_selection_manifest_artifact: dict[str, object]
    candidate_count: int
    tributary_binding: ObservedTributaryBinding
    events: tuple[BlindTransferEventEvidence, ...]
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            len(self.events) != 3
            or tuple(value.selection_rank for value in self.events) != (1, 2, 3)
            or len(self.source_artifacts) != 11
            or not self.tributary_binding.path_reaches_outlet
        ):
            raise ValueError("public_blind_transfer_evidence_ledger_invalid")

    @property
    def all_events_support_fixed_lag(self) -> bool:
        return all(value.fixed_lag_supported for value in self.events)

    def require_stable_empirical_release_response_lag(self) -> int:
        if not self.all_events_support_fixed_lag:
            raise ValueError(
                "public_blind_transfer_fixed_lag_not_supported_by_all_events"
            )
        return STAGE28_FIXED_LAG_HOURS

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "public_blind_transfer_empirical_lag_is_not_physical_travel_time"
        )

    def require_tributary_mouth_flux(self) -> None:
        raise ValueError(
            "public_blind_transfer_gauge_is_not_tributary_mouth_flux"
        )

    def require_all_lateral_inflow(self) -> None:
        raise ValueError(
            "public_blind_transfer_single_tributary_is_not_lateral_inflow_total"
        )

    def require_boundary_conditioned_rollout(self) -> None:
        raise ValueError(
            "public_blind_transfer_evidence_is_not_spatial_rollout"
        )

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("public_blind_transfer_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "release_event_candidate_count": self.candidate_count,
            "selection_plan_artifact": self.selection_plan_artifact,
            "event_selection_manifest_artifact": (
                self.event_selection_manifest_artifact
            ),
            "observation_plan_artifact": self.observation_plan_artifact,
            "tributary_binding": self.tributary_binding.as_dict(),
            "events": [value.as_dict() for value in self.events],
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "transfer_summary": {
                "event_count": len(self.events),
                "stage28_fixed_lag_hours": STAGE28_FIXED_LAG_HOURS,
                "per_event_best_lag_hours": [
                    value.best_lag_hours for value in self.events
                ],
                "per_event_fixed_lag_supported": [
                    value.fixed_lag_supported for value in self.events
                ],
                "all_events_support_fixed_lag": (
                    self.all_events_support_fixed_lag
                ),
                "stable_empirical_release_response_lag_admitted": (
                    self.all_events_support_fixed_lag
                ),
                "physical_travel_time_admitted": False,
            },
            "evidence_admission": {
                "release_selected_blind_transfer_events_admitted": True,
                "observed_tributary_site_state_admitted": True,
                "stable_empirical_release_response_lag_admitted": (
                    self.all_events_support_fixed_lag
                ),
                "physical_travel_time_admitted": False,
                "tributary_mouth_flux_admitted": False,
                "all_lateral_inflow_admitted": False,
                "boundary_conditioned_rollout_admitted": False,
                "runtime_operator_admitted": False,
            },
            "claim_boundary": {
                "events_selected_without_stage29_observation_values": True,
                "observed_tributary_is_one_gauged_branch_state": True,
                "observed_tributary_is_mouth_boundary_flux": False,
                "observed_tributary_represents_all_lateral_inflow": False,
                "empirical_lag_equals_physical_travel_time": False,
                "observed_spatial_rollout_completed": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "blind_transfer_evidence_admitted": True,
                "stable_empirical_lag_admitted": (
                    self.all_events_support_fixed_lag
                ),
                "physical_travel_time_admitted": False,
                "observed_tributary_state_admitted": True,
                "observed_lateral_inflow_total_admitted": False,
                "observed_spatial_rollout_completed": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_blind_transfer_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicBlindTransferEvidenceLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    selection = _read_json(source / "event_selection_manifest.json")
    observations = _read_json(source / "observation_acquisition_manifest.json")
    _validate_manifests(selection, observations, root)
    selection_artifacts = _verify_artifacts(selection["artifacts"], root)
    observation_artifacts = _verify_artifacts(observations["artifacts"], root)
    all_artifacts = tuple(selection_artifacts + observation_artifacts)
    by_source = {str(value["source_id"]): value for value in all_artifacts}
    binding = _compile_tributary_binding(by_source, root)
    release_pool = _read_json(
        _resolve(by_source["cwms_release_candidate_pool"], root)
    )
    release_by_time = {
        datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc): (
            float(row[1]),
            int(row[2]),
        )
        for row in release_pool["values"]
    }
    events = tuple(
        _compile_event(
            event,
            release_by_time=release_by_time,
            by_source=by_source,
            root=root,
        )
        for event in selection["selected_events"]
    )
    digest = hashlib.sha256(
        "|".join(sorted(str(value["sha256"]) for value in all_artifacts)).encode(
            "ascii"
        )
    ).hexdigest()
    return PublicBlindTransferEvidenceLedger(
        dict(selection["frozen_selection_plan"]),
        dict(observations["frozen_observation_plan"]),
        dict(observations["frozen_event_selection_manifest"]),
        int(selection["eligible_candidate_count"]),
        binding,
        events,
        all_artifacts,
        f"cwms-usgs-blind-transfer:center-hill:{digest}",
    )


def _compile_tributary_binding(
    artifacts: dict[str, dict[str, object]], root: Path
) -> ObservedTributaryBinding:
    site = _read_json(_resolve(artifacts["usgs_smith_fork_site"], root))
    metadata = _read_json(
        _resolve(artifacts["usgs_smith_fork_series_metadata"], root)
    )
    nldi = _read_json(_resolve(artifacts["nldi_smith_fork_site"], root))
    path = _read_json(
        _resolve(artifacts["nldi_smith_fork_downstream_path"], root)
    )
    series = next(
        value
        for value in metadata["features"]
        if value["id"] == "c59c7559af4f4a0ebef64eb811803ea0"
    )
    nldi_properties = nldi["features"][0]["properties"]
    return ObservedTributaryBinding(
        str(site["id"]),
        str(site["properties"]["monitoring_location_name"]),
        tuple(float(value) for value in site["geometry"]["coordinates"]),
        float(site["properties"]["drainage_area"]),
        int(nldi_properties["comid"]),
        str(nldi_properties["reachcode"]),
        tuple(int(value["id"]) for value in path["features"]),
        str(series["id"]),
        str(series["properties"]["begin_utc"]),
        str(series["properties"]["end_utc"]),
    )


def _compile_event(
    event: dict[str, Any],
    *,
    release_by_time: dict[datetime, tuple[float, int]],
    by_source: dict[str, dict[str, object]],
    root: Path,
) -> BlindTransferEventEvidence:
    event_id = str(event["event_id"])
    start = _parse_time(str(event["start_utc"]))
    end = _parse_time(str(event["end_utc"]))
    release_rows = tuple(
        release_by_time[start + timedelta(hours=index)]
        for index in range(1, EVENT_HOURS + 1)
    )
    downstream_record = by_source[
        f"usgs_03424860_{event_id}"
    ]
    tributary_record = by_source[f"usgs_03424730_{event_id}"]
    downstream_payload = _read_json(_resolve(downstream_record, root))
    tributary_payload = _read_json(_resolve(tributary_record, root))
    downstream = _compile_hourly_observations(
        downstream_payload, start=start, hour_count=OBSERVATION_HOURS
    )
    tributary = _compile_hourly_observations(
        tributary_payload, start=start, hour_count=OBSERVATION_HOURS
    )
    if len(downstream) != OBSERVATION_HOURS:
        raise ValueError("public_blind_transfer_downstream_hour_missing")
    releases = tuple(value[0] for value in release_rows)
    diagnostics = tuple(
        _lag_diagnostic(releases, downstream, lag)
        for lag in LAG_CANDIDATES_HOURS
    )
    eligible = [value for value in diagnostics if value.pearson_r is not None]
    best = max(
        eligible,
        key=lambda value: (
            float(value.pearson_r),
            -value.rmse_m3s,
            -value.lag_hours,
        ),
    )
    fixed = diagnostics[STAGE28_FIXED_LAG_HOURS]
    reasons = []
    if abs(best.lag_hours - STAGE28_FIXED_LAG_HOURS) > 2:
        reasons.append("best_lag_more_than_two_hours_from_stage28")
    if fixed.pearson_r is None or fixed.pearson_r < 0.8:
        reasons.append("fixed_lag_pearson_below_0_8")
    if (
        fixed.pearson_r is None
        or best.pearson_r is None
        or best.pearson_r - fixed.pearson_r > 0.05
    ):
        reasons.append("best_minus_fixed_pearson_exceeds_0_05")
    if fixed.pair_count < 60:
        reasons.append("fixed_lag_pair_count_below_60")
    tributary_values = tuple(value.mean_m3s for value in tributary)
    context = TributaryEventContext(
        len(tributary_payload["features"]),
        len(tributary),
        OBSERVATION_HOURS - len(tributary),
        sum(value.fully_approved for value in tributary),
        _mean(tributary_values) if tributary_values else None,
        max(tributary_values) if tributary_values else None,
        tributary,
    )
    return BlindTransferEventEvidence(
        event_id,
        int(event["selection_rank"]),
        str(event["step_time_utc"]),
        float(event["signed_step_m3s"]),
        float(event["absolute_step_m3s"]),
        float(event["window_range_m3s"]),
        _iso(start),
        _iso(end),
        releases,
        tuple(value[1] for value in release_rows),
        len(downstream_payload["features"]),
        downstream,
        diagnostics,
        best.lag_hours,
        not reasons,
        tuple(reasons),
        context,
        (downstream_record, tributary_record),
    )


def _compile_hourly_observations(
    payload: dict[str, Any], *, start: datetime, hour_count: int
) -> tuple[HourlyObservedDischarge, ...]:
    samples = {
        _parse_time(str(value["properties"]["time"])): (
            float(value["properties"]["value"]),
            str(value["properties"]["approval_status"]),
        )
        for value in payload["features"]
    }
    result = []
    for index in range(1, hour_count + 1):
        support_end = start + timedelta(hours=index)
        times = (
            support_end - timedelta(minutes=30),
            support_end,
        )
        if any(value not in samples for value in times):
            continue
        values = (samples[times[0]], samples[times[1]])
        cfs = (values[0][0], values[1][0])
        result.append(
            HourlyObservedDischarge(
                _iso(support_end - timedelta(hours=1)),
                _iso(support_end),
                (_iso(times[0]), _iso(times[1])),
                cfs,
                _mean(cfs) * CFS_TO_M3S,
                (values[0][1], values[1][1]),
            )
        )
    return tuple(result)


def _lag_diagnostic(
    releases: tuple[float, ...],
    downstream: tuple[HourlyObservedDischarge, ...],
    lag: int,
) -> LagDiagnostic:
    outcome_by_end = {
        _parse_time(value.support_end_utc): value.mean_m3s
        for value in downstream
    }
    first_end = _parse_time(downstream[0].support_end_utc)
    pairs = tuple(
        (
            release,
            outcome_by_end[first_end + timedelta(hours=index - 1 + lag)],
        )
        for index, release in enumerate(releases, start=1)
    )
    left = tuple(value[0] for value in pairs)
    right = tuple(value[1] for value in pairs)
    residuals = tuple(b - a for a, b in pairs)
    left_mean = _mean(left)
    right_mean = _mean(right)
    left_std = _standard_deviation(left)
    right_std = _standard_deviation(right)
    pearson = None
    if left_std > 0.0 and right_std > 0.0:
        pearson = sum(
            (a - left_mean) * (b - right_mean) for a, b in pairs
        ) / (len(pairs) * left_std * right_std)
    return LagDiagnostic(
        lag,
        len(pairs),
        left_mean,
        right_mean,
        _mean(residuals),
        _mean(tuple(abs(value) for value in residuals)),
        math.sqrt(_mean(tuple(value * value for value in residuals))),
        pearson,
        left_std,
        right_std,
    )


def _validate_manifests(
    selection: dict[str, Any],
    observations: dict[str, Any],
    root: Path,
) -> None:
    selection_after = selection.get("claim_boundary_after_release_selection") or {}
    observation_after = observations.get("claim_boundary_after_observations") or {}
    if (
        selection.get("schema") != SELECTION_SCHEMA
        or selection.get("status")
        != "release_selected_events_frozen_before_observations"
        or selection.get("selected_event_count") != 3
        or selection_after.get("events_selected_from_release_only") is not True
        or selection_after.get("downstream_values_acquired") is not False
        or selection_after.get("tributary_values_acquired") is not False
        or observations.get("schema") != OBSERVATION_SCHEMA
        or observations.get("mode") != "observation_values"
        or observations.get("status") != "blind_transfer_observations_acquired"
        or observation_after.get(
            "events_hash_frozen_before_observation_values"
        )
        is not True
        or observation_after.get("downstream_values_acquired") is not True
        or observation_after.get("tributary_values_acquired") is not True
        or observations.get("artifact_count") != 6
    ):
        raise ValueError("public_blind_transfer_acquisition_manifest_invalid")
    selection_body = _read_verified(
        observations["frozen_event_selection_manifest"], root
    )
    if json.loads(selection_body) != selection:
        raise ValueError("public_blind_transfer_selection_manifest_not_frozen")
    plan_body = _read_verified(observations["frozen_observation_plan"], root)
    plan = json.loads(plan_body)
    if (
        plan != observations.get("frozen_observation_plan_content")
        or plan.get("mode") != "observation_plan"
        or plan.get("predeclared_transfer_diagnostic", {}).get(
            "stage28_fixed_lag_hours"
        )
        != STAGE28_FIXED_LAG_HOURS
    ):
        raise ValueError("public_blind_transfer_observation_plan_invalid")
    selection_plan_body = _read_verified(selection["frozen_selection_plan"], root)
    selection_plan = json.loads(selection_plan_body)
    if (
        selection_plan != selection.get("frozen_selection_plan_content")
        or selection_plan.get("request_boundary", {}).get(
            "downstream_or_tributary_observation_values_requested"
        )
        is not False
    ):
        raise ValueError("public_blind_transfer_selection_plan_invalid")


def _verify_artifacts(
    descriptors: list[dict[str, Any]], root: Path
) -> list[dict[str, object]]:
    result = []
    seen = set()
    for descriptor in descriptors:
        source_id = str(descriptor["source_id"])
        if source_id in seen:
            raise ValueError("public_blind_transfer_duplicate_source")
        seen.add(source_id)
        _read_verified(descriptor, root)
        if (
            descriptor.get("hash_verified") is not True
            or descriptor.get("tls_hostname_verification_retained") is not True
        ):
            raise ValueError("public_blind_transfer_source_provenance_invalid")
        result.append(dict(descriptor))
    return result


def _read_verified(descriptor: dict[str, Any], root: Path) -> bytes:
    path = _resolve(descriptor, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("public_blind_transfer_artifact_identity_mismatch")
    return body


def _resolve(descriptor: dict[str, Any], root: Path) -> Path:
    path = (root / str(descriptor["path"])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("public_blind_transfer_artifact_outside_repository") from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_blind_transfer_json_object_required")
    return value


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _standard_deviation(values: tuple[float, ...]) -> float:
    if max(values) == min(values):
        return 0.0
    mean = _mean(values)
    return math.sqrt(_mean(tuple((value - mean) ** 2 for value in values)))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_blind_transfer_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
