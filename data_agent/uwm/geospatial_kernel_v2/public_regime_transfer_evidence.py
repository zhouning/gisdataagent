"""Typed Stage 30 evidence for a regime lag rule and graph observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_blind_transfer_evidence as stage29,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage30_center_hill_regime_validation_events"
)
SCHEMA = "gwm.geotransport.public_regime_transfer_evidence.v1"
SELECTION_SCHEMA = "gwm.geotransport.stage30_regime_event_selection.v1"
OBSERVATION_SCHEMA = "gwm.geotransport.stage30_observation_acquisition.v1"
CWMS_SERIES_ID = stage29.CWMS_SERIES_ID
DOWNSTREAM_SITE_ID = stage29.DOWNSTREAM_SITE_ID
TRIBUTARY_SITE_ID = stage29.TRIBUTARY_SITE_ID
TRIBUTARY_COMID = stage29.TRIBUTARY_COMID
OUTLET_COMID = stage29.OUTLET_COMID
LAG_CANDIDATES_HOURS = tuple(range(13))
EVENT_HOURS = 72
OBSERVATION_HOURS = 84
HIGH_FLOW_THRESHOLD_M3S = 200.0
HIGH_FLOW_LAG_HOURS = 5
LOW_FLOW_LAG_HOURS = 6
STRATUM_ORDER = (
    "high_increase",
    "high_decrease",
    "low_increase",
    "low_decrease",
)


@dataclass(frozen=True)
class ObservedGraphState:
    """One support-aware observation at a bound graph node."""

    site_id: str
    comid: int
    variable: str
    unit: str
    support_start_utc: str
    support_end_utc: str
    native_sample_times_utc: tuple[str, str]
    value_m3s: float
    approval_statuses: tuple[str, str]
    source_id: str

    def __post_init__(self) -> None:
        if (
            self.site_id != TRIBUTARY_SITE_ID
            or self.comid != TRIBUTARY_COMID
            or self.variable != "discharge"
            or self.unit != "m3/s"
            or self.value_m3s < 0.0
            or len(self.native_sample_times_utc) != 2
            or len(self.approval_statuses) != 2
        ):
            raise ValueError("public_regime_transfer_graph_state_invalid")

    @property
    def fully_approved(self) -> bool:
        return set(self.approval_statuses) == {"Approved"}

    def require_tributary_mouth_flux(self) -> None:
        raise ValueError(
            "public_regime_transfer_node_state_is_not_tributary_mouth_flux"
        )

    def require_conservation_oracle(self) -> None:
        raise ValueError(
            "public_regime_transfer_node_state_is_not_conservation_oracle"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "comid": self.comid,
            "graph_role": "observed_node_state",
            "spatial_support": "gauge_point_bound_to_comid",
            "variable": self.variable,
            "unit": self.unit,
            "temporal_support": {
                "start_utc": self.support_start_utc,
                "end_utc": self.support_end_utc,
                "native_sample_times_utc": list(
                    self.native_sample_times_utc
                ),
            },
            "value_m3s": self.value_m3s,
            "approval_statuses": list(self.approval_statuses),
            "fully_approved": self.fully_approved,
            "source_id": self.source_id,
            "admitted_consumers": [
                "support_aware_graph_state_analysis",
                "graph_state_diagnostic",
            ],
            "forbidden_consumers": [
                "tributary_mouth_flux",
                "total_lateral_inflow",
                "mass_conservation_oracle",
            ],
        }


@dataclass(frozen=True)
class ObservedGraphStateSeries:
    event_id: str
    expected_hour_count: int
    raw_sample_count: int
    states: tuple[ObservedGraphState, ...]

    def __post_init__(self) -> None:
        if (
            self.expected_hour_count != OBSERVATION_HOURS
            or len({value.support_end_utc for value in self.states})
            != len(self.states)
            or any(value.comid != TRIBUTARY_COMID for value in self.states)
        ):
            raise ValueError("public_regime_transfer_graph_series_invalid")

    @property
    def missing_hour_count(self) -> int:
        return self.expected_hour_count - len(self.states)

    @property
    def coverage_ratio(self) -> float:
        return len(self.states) / self.expected_hour_count

    def require_total_lateral_inflow(self) -> None:
        raise ValueError(
            "public_regime_transfer_one_node_is_not_total_lateral_inflow"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "site_id": TRIBUTARY_SITE_ID,
            "comid": TRIBUTARY_COMID,
            "graph_role": "observed_node_state_series",
            "expected_hour_count": self.expected_hour_count,
            "raw_sample_count": self.raw_sample_count,
            "complete_hour_count": len(self.states),
            "missing_hour_count": self.missing_hour_count,
            "coverage_ratio": self.coverage_ratio,
            "missing_values_filled": False,
            "tributary_mouth_flux_admitted": False,
            "total_lateral_inflow_admitted": False,
            "mass_conservation_oracle_admitted": False,
            "states": [value.as_dict() for value in self.states],
        }


@dataclass(frozen=True)
class RegimeValidationEventEvidence:
    event_id: str
    selection_rank: int
    selection_stratum: str
    antecedent_flow_class: str
    antecedent_release_mean_m3s: float
    release_direction: str
    step_magnitude_class: str
    step_time_utc: str
    signed_step_m3s: float
    absolute_step_m3s: float
    window_range_m3s: float
    start_utc: str
    end_utc: str
    predicted_lag_hours: int
    release_values_m3s: tuple[float, ...]
    release_quality_codes: tuple[int, ...]
    raw_downstream_sample_count: int
    downstream_hourly: tuple[stage29.HourlyObservedDischarge, ...]
    lag_diagnostics: tuple[stage29.LagDiagnostic, ...]
    best_lag_hours: int
    rule_supported: bool
    rule_support_reasons: tuple[str, ...]
    graph_states: ObservedGraphStateSeries
    source_artifacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        expected_lag = (
            HIGH_FLOW_LAG_HOURS
            if self.antecedent_release_mean_m3s
            >= HIGH_FLOW_THRESHOLD_M3S
            else LOW_FLOW_LAG_HOURS
        )
        if (
            self.selection_stratum != STRATUM_ORDER[self.selection_rank - 1]
            or self.predicted_lag_hours != expected_lag
            or len(self.release_values_m3s) != EVENT_HOURS
            or len(self.release_quality_codes) != EVENT_HOURS
            or len(self.downstream_hourly) != OBSERVATION_HOURS
            or tuple(value.lag_hours for value in self.lag_diagnostics)
            != LAG_CANDIDATES_HOURS
            or any(
                value.pair_count != EVENT_HOURS
                for value in self.lag_diagnostics
            )
        ):
            raise ValueError("public_regime_transfer_event_invalid")

    @property
    def predicted_lag_diagnostic(self) -> stage29.LagDiagnostic:
        return self.lag_diagnostics[self.predicted_lag_hours]

    @property
    def best_lag_diagnostic(self) -> stage29.LagDiagnostic:
        return self.lag_diagnostics[self.best_lag_hours]

    @property
    def fixed_six_hour_diagnostic(self) -> stage29.LagDiagnostic:
        return self.lag_diagnostics[6]

    def as_dict(self) -> dict[str, object]:
        predicted_r = self.predicted_lag_diagnostic.pearson_r
        fixed_r = self.fixed_six_hour_diagnostic.pearson_r
        return {
            "event_id": self.event_id,
            "role": "blind_regime_validation",
            "selection_rank": self.selection_rank,
            "selection_stratum": self.selection_stratum,
            "selected_without_observation_values": True,
            "rule_frozen_without_observation_values": True,
            "antecedent_flow_class": self.antecedent_flow_class,
            "antecedent_release_mean_m3s": (
                self.antecedent_release_mean_m3s
            ),
            "release_direction": self.release_direction,
            "step_magnitude_class": self.step_magnitude_class,
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
            "raw_downstream_sample_count": (
                self.raw_downstream_sample_count
            ),
            "downstream_complete_hour_count": len(
                self.downstream_hourly
            ),
            "lag_diagnostics": [
                value.as_dict() for value in self.lag_diagnostics
            ],
            "best_lag_hours": self.best_lag_hours,
            "best_lag_diagnostic": self.best_lag_diagnostic.as_dict(),
            "predicted_lag_hours": self.predicted_lag_hours,
            "predicted_lag_diagnostic": (
                self.predicted_lag_diagnostic.as_dict()
            ),
            "fixed_six_hour_diagnostic": (
                self.fixed_six_hour_diagnostic.as_dict()
            ),
            "predicted_minus_fixed_six_pearson_r": (
                None
                if predicted_r is None or fixed_r is None
                else predicted_r - fixed_r
            ),
            "rule_supported": self.rule_supported,
            "rule_support_reasons": list(self.rule_support_reasons),
            "graph_states": self.graph_states.as_dict(),
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class PublicRegimeTransferEvidenceLedger:
    selection_plan_artifact: dict[str, object]
    observation_plan_artifact: dict[str, object]
    event_selection_manifest_artifact: dict[str, object]
    candidate_count: int
    stage29_tributary_binding: stage29.ObservedTributaryBinding
    events: tuple[RegimeValidationEventEvidence, ...]
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            len(self.events) != 4
            or tuple(value.selection_stratum for value in self.events)
            != STRATUM_ORDER
            or len(self.source_artifacts) != 9
            or self.stage29_tributary_binding.comid != TRIBUTARY_COMID
            or not self.stage29_tributary_binding.path_reaches_outlet
        ):
            raise ValueError("public_regime_transfer_ledger_invalid")

    @property
    def all_strata_support_rule(self) -> bool:
        return all(value.rule_supported for value in self.events)

    def require_regime_conditioned_lag_rule(self) -> dict[str, int]:
        if not self.all_strata_support_rule:
            raise ValueError(
                "public_regime_transfer_rule_not_supported_by_all_strata"
            )
        return {"high": HIGH_FLOW_LAG_HOURS, "low": LOW_FLOW_LAG_HOURS}

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "public_regime_transfer_empirical_lag_is_not_physical_time"
        )

    def require_tributary_mouth_flux(self) -> None:
        raise ValueError(
            "public_regime_transfer_graph_state_is_not_mouth_flux"
        )

    def require_total_lateral_inflow(self) -> None:
        raise ValueError(
            "public_regime_transfer_graph_state_is_not_lateral_total"
        )

    def require_conservation_oracle(self) -> None:
        raise ValueError(
            "public_regime_transfer_graph_state_is_not_conservation_oracle"
        )

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("public_regime_transfer_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "release_event_candidate_count": self.candidate_count,
            "selection_plan_artifact": self.selection_plan_artifact,
            "event_selection_manifest_artifact": (
                self.event_selection_manifest_artifact
            ),
            "observation_plan_artifact": self.observation_plan_artifact,
            "frozen_regime_lag_rule": {
                "antecedent_support_hours": 24,
                "high_flow_threshold_m3s": HIGH_FLOW_THRESHOLD_M3S,
                "high_flow_predicted_lag_hours": HIGH_FLOW_LAG_HOURS,
                "low_flow_predicted_lag_hours": LOW_FLOW_LAG_HOURS,
            },
            "stage29_tributary_binding": (
                self.stage29_tributary_binding.as_dict()
            ),
            "events": [value.as_dict() for value in self.events],
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "transfer_summary": {
                "event_count": len(self.events),
                "per_event_strata": [
                    value.selection_stratum for value in self.events
                ],
                "per_event_predicted_lag_hours": [
                    value.predicted_lag_hours for value in self.events
                ],
                "per_event_best_lag_hours": [
                    value.best_lag_hours for value in self.events
                ],
                "per_event_rule_supported": [
                    value.rule_supported for value in self.events
                ],
                "all_strata_support_rule": self.all_strata_support_rule,
            },
            "claim_boundary": {
                "regime_rule_derived_without_stage30_outcomes": True,
                "events_selected_without_stage30_observations": True,
                "smith_fork_is_observed_state_at_comid_18421273": True,
                "smith_fork_is_tributary_mouth_flux": False,
                "smith_fork_represents_all_lateral_inflow": False,
                "smith_fork_is_mass_conservation_oracle": False,
                "empirical_lag_equals_physical_travel_time": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "blind_regime_validation_admitted": True,
                "regime_conditioned_empirical_lag_admitted": (
                    self.all_strata_support_rule
                ),
                "physical_travel_time_admitted": False,
                "observed_graph_state_contract_admitted": True,
                "tributary_mouth_flux_admitted": False,
                "observed_lateral_inflow_total_admitted": False,
                "mass_conservation_oracle_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_regime_transfer_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicRegimeTransferEvidenceLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    selection = _read_json(source / "event_selection_manifest.json")
    observations = _read_json(
        source / "observation_acquisition_manifest.json"
    )
    _validate_manifests(selection, observations, root)
    selection_artifacts = _verify_artifacts(selection["artifacts"], root)
    observation_artifacts = _verify_artifacts(
        observations["artifacts"], root
    )
    all_artifacts = tuple(selection_artifacts + observation_artifacts)
    by_source = {
        str(value["source_id"]): value for value in all_artifacts
    }
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
    stage29_ledger = stage29.compile_public_blind_transfer_evidence(
        repo_root=root
    )
    digest = hashlib.sha256(
        "|".join(
            sorted(str(value["sha256"]) for value in all_artifacts)
        ).encode("ascii")
    ).hexdigest()
    return PublicRegimeTransferEvidenceLedger(
        dict(selection["frozen_selection_plan"]),
        dict(observations["frozen_observation_plan"]),
        dict(observations["frozen_event_selection_manifest"]),
        int(selection["eligible_candidate_count"]),
        stage29_ledger.tributary_binding,
        events,
        all_artifacts,
        f"cwms-usgs-regime-validation:center-hill:{digest}",
    )


def _compile_event(
    event: dict[str, Any],
    *,
    release_by_time: dict[datetime, tuple[float, int]],
    by_source: dict[str, dict[str, object]],
    root: Path,
) -> RegimeValidationEventEvidence:
    event_id = str(event["event_id"])
    start = _parse_time(str(event["start_utc"]))
    end = _parse_time(str(event["end_utc"]))
    release_rows = tuple(
        release_by_time[start + timedelta(hours=index)]
        for index in range(1, EVENT_HOURS + 1)
    )
    downstream_record = by_source[f"usgs_03424860_{event_id}"]
    tributary_record = by_source[f"usgs_03424730_{event_id}"]
    downstream_payload = _read_json(
        _resolve(downstream_record, root)
    )
    tributary_payload = _read_json(_resolve(tributary_record, root))
    downstream = stage29._compile_hourly_observations(
        downstream_payload,
        start=start,
        hour_count=OBSERVATION_HOURS,
    )
    tributary = stage29._compile_hourly_observations(
        tributary_payload,
        start=start,
        hour_count=OBSERVATION_HOURS,
    )
    if len(downstream) != OBSERVATION_HOURS:
        raise ValueError("public_regime_transfer_downstream_hour_missing")
    releases = tuple(value[0] for value in release_rows)
    diagnostics = tuple(
        stage29._lag_diagnostic(releases, downstream, lag)
        for lag in LAG_CANDIDATES_HOURS
    )
    best = max(
        (value for value in diagnostics if value.pearson_r is not None),
        key=lambda value: (
            float(value.pearson_r),
            -value.rmse_m3s,
            -value.lag_hours,
        ),
    )
    predicted_lag = int(event["predicted_lag_hours"])
    predicted = diagnostics[predicted_lag]
    reasons = []
    if abs(best.lag_hours - predicted_lag) > 1:
        reasons.append("best_lag_more_than_one_hour_from_prediction")
    if predicted.pearson_r is None or predicted.pearson_r < 0.8:
        reasons.append("predicted_lag_pearson_below_0_8")
    if (
        predicted.pearson_r is None
        or best.pearson_r is None
        or best.pearson_r - predicted.pearson_r > 0.05
    ):
        reasons.append("best_minus_predicted_pearson_exceeds_0_05")
    if predicted.pair_count < 60:
        reasons.append("predicted_lag_pair_count_below_60")
    graph_states = tuple(
        ObservedGraphState(
            TRIBUTARY_SITE_ID,
            TRIBUTARY_COMID,
            "discharge",
            "m3/s",
            value.support_start_utc,
            value.support_end_utc,
            value.sample_times_utc,
            value.mean_m3s,
            value.approval_statuses,
            str(tributary_record["source_id"]),
        )
        for value in tributary
    )
    return RegimeValidationEventEvidence(
        event_id,
        int(event["selection_rank"]),
        str(event["selection_stratum"]),
        str(event["antecedent_flow_class"]),
        float(event["antecedent_release_mean_m3s"]),
        str(event["release_direction"]),
        str(event["step_magnitude_class"]),
        str(event["step_time_utc"]),
        float(event["signed_step_m3s"]),
        float(event["absolute_step_m3s"]),
        float(event["window_range_m3s"]),
        _iso(start),
        _iso(end),
        predicted_lag,
        releases,
        tuple(value[1] for value in release_rows),
        len(downstream_payload["features"]),
        downstream,
        diagnostics,
        best.lag_hours,
        not reasons,
        tuple(reasons),
        ObservedGraphStateSeries(
            event_id,
            OBSERVATION_HOURS,
            len(tributary_payload["features"]),
            graph_states,
        ),
        (downstream_record, tributary_record),
    )


def _validate_manifests(
    selection: dict[str, Any],
    observations: dict[str, Any],
    root: Path,
) -> None:
    selection_after = selection.get(
        "claim_boundary_after_release_selection"
    ) or {}
    observation_after = observations.get(
        "claim_boundary_after_observations"
    ) or {}
    if (
        selection.get("schema") != SELECTION_SCHEMA
        or selection.get("status")
        != "regime_events_frozen_before_observations"
        or selection.get("selected_event_count") != 4
        or [
            value.get("selection_stratum")
            for value in selection.get("selected_events") or []
        ]
        != list(STRATUM_ORDER)
        or selection_after.get("events_selected_from_release_only")
        is not True
        or selection_after.get("downstream_values_acquired") is not False
        or observations.get("schema") != OBSERVATION_SCHEMA
        or observations.get("mode") != "observation_values"
        or observations.get("status")
        != "regime_validation_observations_acquired"
        or observation_after.get(
            "events_hash_frozen_before_observation_values"
        )
        is not True
        or observation_after.get(
            "regime_rule_frozen_before_observation_values"
        )
        is not True
        or observations.get("artifact_count") != 8
    ):
        raise ValueError("public_regime_transfer_manifest_invalid")
    selection_body = _read_verified(
        observations["frozen_event_selection_manifest"], root
    )
    if json.loads(selection_body) != selection:
        raise ValueError("public_regime_transfer_selection_not_frozen")
    observation_plan_body = _read_verified(
        observations["frozen_observation_plan"], root
    )
    observation_plan = json.loads(observation_plan_body)
    if (
        observation_plan
        != observations.get("frozen_observation_plan_content")
        or observation_plan.get("mode") != "observation_plan"
        or observation_plan.get("request_boundary", {}).get(
            "regime_rule_may_be_retuned_from_observations"
        )
        is not False
    ):
        raise ValueError("public_regime_transfer_observation_plan_invalid")
    selection_plan_body = _read_verified(
        selection["frozen_selection_plan"], root
    )
    selection_plan = json.loads(selection_plan_body)
    rule = selection_plan.get("frozen_regime_lag_rule") or {}
    if (
        selection_plan != selection.get("frozen_selection_plan_content")
        or rule.get("high_flow_threshold_m3s")
        != HIGH_FLOW_THRESHOLD_M3S
        or rule.get("high_flow_predicted_lag_hours")
        != HIGH_FLOW_LAG_HOURS
        or rule.get("low_flow_predicted_lag_hours")
        != LOW_FLOW_LAG_HOURS
        or rule.get("outcome_values_used") is not False
    ):
        raise ValueError("public_regime_transfer_selection_plan_invalid")


def _verify_artifacts(
    descriptors: list[dict[str, Any]], root: Path
) -> list[dict[str, object]]:
    result = []
    seen = set()
    for descriptor in descriptors:
        source_id = str(descriptor["source_id"])
        if source_id in seen:
            raise ValueError("public_regime_transfer_duplicate_source")
        seen.add(source_id)
        _read_verified(descriptor, root)
        if (
            descriptor.get("hash_verified") is not True
            or descriptor.get("tls_hostname_verification_retained")
            is not True
        ):
            raise ValueError("public_regime_transfer_provenance_invalid")
        result.append(dict(descriptor))
    return result


def _read_verified(descriptor: dict[str, Any], root: Path) -> bytes:
    path = _resolve(descriptor, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("public_regime_transfer_artifact_mismatch")
    return body


def _resolve(descriptor: dict[str, Any], root: Path) -> Path:
    path = (root / str(descriptor["path"])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "public_regime_transfer_artifact_outside_repository"
        ) from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_regime_transfer_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_regime_transfer_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
