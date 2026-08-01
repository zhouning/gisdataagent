"""Stage 32 blind evidence for empirical graph-relation lag support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    empirical_lag_support as lag_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_blind_transfer_evidence as stage29,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_regime_transfer_evidence as stage30,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    release_excitation_identifiability as excitation,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage32_center_hill_lag_support_events"
)
SCHEMA = "gwm.geotransport.public_lag_support_evidence.v1"
SELECTION_SCHEMA = "gwm.geotransport.stage32_lag_support_selection.v1"
OBSERVATION_SCHEMA = (
    "gwm.geotransport.stage32_observation_acquisition.v1"
)
EVENT_HOURS = 72
OBSERVATION_HOURS = 84
SOURCE_BOUNDARY_ID = "CETT1-CENTER_HILL"
SOURCE_SPATIAL_ROLE = "operational_tailwater_zone"
TARGET_SITE_ID = "USGS-03424860"
TARGET_COMID = stage29.OUTLET_COMID
TRIBUTARY_SITE_ID = stage29.TRIBUTARY_SITE_ID
TRIBUTARY_COMID = stage29.TRIBUTARY_COMID


@dataclass(frozen=True)
class PublicLagSupportEventEvidence:
    event_id: str
    selection_rank: int
    release_direction: str
    step_time_utc: str
    signed_step_m3s: float
    start_utc: str
    end_utc: str
    release_support: excitation.ReleaseExcitationIdentifiability
    release_values_m3s: tuple[float, ...]
    release_quality_codes: tuple[int, ...]
    raw_downstream_sample_count: int
    downstream_hourly: tuple[stage29.HourlyObservedDischarge, ...]
    lag_diagnostics: tuple[stage29.LagDiagnostic, ...]
    lag_support: lag_operator.EmpiricalLagSupport
    graph_relation: lag_operator.EmpiricalGraphRelationLagSupport | None
    graph_states: stage30.ObservedGraphStateSeries
    source_artifacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if (
            self.selection_rank not in range(1, 5)
            or self.release_direction not in {"increase", "decrease"}
            or not self.release_support.blind_response_test_admissible
            or len(self.release_values_m3s) != EVENT_HOURS
            or len(self.release_quality_codes) != EVENT_HOURS
            or tuple(value.lag_hours for value in self.lag_diagnostics)
            != lag_operator.LAG_CANDIDATES_HOURS
            or any(
                not 0 < value.pair_count <= EVENT_HOURS
                for value in self.lag_diagnostics
            )
            or (
                self.graph_relation is not None
                and (
                    self.graph_relation.evidence_event_id != self.event_id
                    or self.graph_relation.lag_support != self.lag_support
                )
            )
            or (
                self.graph_relation is None
                and self.lag_support.response_detectable
            )
            or (
                self.graph_relation is not None
                and not self.lag_support.response_detectable
            )
        ):
            raise ValueError("public_lag_support_event_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "role": "blind_empirical_lag_support",
            "selection_rank": self.selection_rank,
            "release_direction": self.release_direction,
            "selected_without_observation_values": True,
            "operators_frozen_without_observation_values": True,
            "step_time_utc": self.step_time_utc,
            "signed_step_m3s": self.signed_step_m3s,
            "window": {
                "start_utc": self.start_utc,
                "end_utc": self.end_utc,
                "release_support_hour_count": EVENT_HOURS,
                "observation_support_hour_count": OBSERVATION_HOURS,
            },
            "release_excitation_identifiability": (
                self.release_support.as_dict()
            ),
            "release_values_m3s": list(self.release_values_m3s),
            "release_quality_codes": list(self.release_quality_codes),
            "raw_downstream_sample_count": (
                self.raw_downstream_sample_count
            ),
            "downstream_complete_hour_count": len(self.downstream_hourly),
            "downstream_missing_hour_count": (
                OBSERVATION_HOURS - len(self.downstream_hourly)
            ),
            "lag_diagnostics": [
                value.as_dict() for value in self.lag_diagnostics
            ],
            "empirical_lag_support": self.lag_support.as_dict(),
            "graph_relation_lag_support": (
                None
                if self.graph_relation is None
                else self.graph_relation.as_dict()
            ),
            "graph_states": self.graph_states.as_dict(),
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class PublicLagSupportEvidenceLedger:
    operator_artifacts: dict[str, dict[str, object]]
    selection_plan_artifact: dict[str, object]
    observation_plan_artifact: dict[str, object]
    event_selection_manifest_artifact: dict[str, object]
    candidate_count: int
    tributary_binding: stage29.ObservedTributaryBinding
    events: tuple[PublicLagSupportEventEvidence, ...]
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            len(self.events) != 4
            or tuple(value.selection_rank for value in self.events)
            != (1, 2, 3, 4)
            or len(self.source_artifacts) != 9
            or self.tributary_binding.comid != TRIBUTARY_COMID
            or not self.tributary_binding.path_reaches_outlet
        ):
            raise ValueError("public_lag_support_ledger_invalid")

    @property
    def all_events_have_detectable_response(self) -> bool:
        return all(
            value.lag_support.response_detectable for value in self.events
        )

    @property
    def common_supported_lags_hours(self) -> tuple[int, ...]:
        if not self.events:
            return ()
        common = set(self.events[0].lag_support.supported_lags_hours)
        for event in self.events[1:]:
            common.intersection_update(
                event.lag_support.supported_lags_hours
            )
        return tuple(sorted(common))

    @property
    def common_empirical_support_admitted(self) -> bool:
        return (
            self.all_events_have_detectable_response
            and bool(self.common_supported_lags_hours)
        )

    def require_common_empirical_support(self) -> tuple[int, ...]:
        if not self.common_empirical_support_admitted:
            raise ValueError(
                "public_lag_support_common_empirical_support_unadmitted"
            )
        return self.common_supported_lags_hours

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "public_lag_support_empirical_set_is_not_physical_time"
        )

    def require_hydraulic_edge_travel_time(self) -> None:
        raise ValueError(
            "public_lag_support_relation_is_not_hydraulic_edge_time"
        )

    def require_tributary_mouth_flux(self) -> None:
        raise ValueError(
            "public_lag_support_graph_state_is_not_mouth_flux"
        )

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("public_lag_support_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        per_event_sets = [
            list(value.lag_support.supported_lags_hours)
            for value in self.events
        ]
        return {
            "schema": SCHEMA,
            "operator_artifacts": self.operator_artifacts,
            "selection_plan_artifact": self.selection_plan_artifact,
            "event_selection_manifest_artifact": (
                self.event_selection_manifest_artifact
            ),
            "observation_plan_artifact": self.observation_plan_artifact,
            "release_event_candidate_count": self.candidate_count,
            "tributary_binding": self.tributary_binding.as_dict(),
            "events": [value.as_dict() for value in self.events],
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "lag_support_summary": {
                "event_count": len(self.events),
                "per_event_best_lag_hours": [
                    value.lag_support.best_lag_hours
                    for value in self.events
                ],
                "per_event_best_lag_pearson_r": [
                    value.lag_support.best_pearson_r
                    for value in self.events
                ],
                "per_event_response_detectable": [
                    value.lag_support.response_detectable
                    for value in self.events
                ],
                "all_events_have_detectable_response": (
                    self.all_events_have_detectable_response
                ),
                "per_event_supported_lags_hours": per_event_sets,
                "per_event_exact_hour_resolved": [
                    value.lag_support.exact_hour_resolved
                    for value in self.events
                ],
                "common_supported_lags_hours": list(
                    self.common_supported_lags_hours
                ),
                "common_empirical_support_admitted": (
                    self.common_empirical_support_admitted
                ),
            },
            "claim_boundary": {
                "operators_and_events_frozen_before_stage32_outcomes": True,
                "release_gate_is_input_support_not_response_model": True,
                "lag_output_is_discrete_empirical_support_set": True,
                "common_support_is_cross_event_set_intersection": True,
                "empirical_lag_equals_physical_travel_time": False,
                "empirical_lag_is_hydraulic_edge_travel_time": False,
                "smith_fork_is_observed_state_at_comid_18421273": True,
                "smith_fork_is_tributary_mouth_flux": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "blind_lag_support_evidence_admitted": True,
                "common_empirical_support_admitted": (
                    self.common_empirical_support_admitted
                ),
                "common_supported_lags_hours": list(
                    self.common_supported_lags_hours
                ),
                "physical_travel_time_admitted": False,
                "hydraulic_edge_travel_time_admitted": False,
                "observed_graph_state_contract_admitted": True,
                "tributary_mouth_flux_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_lag_support_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicLagSupportEvidenceLedger:
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
    stage30_ledger = stage30.compile_public_regime_transfer_evidence(
        repo_root=root
    )
    digest = hashlib.sha256(
        "|".join(
            sorted(str(value["sha256"]) for value in all_artifacts)
        ).encode("ascii")
    ).hexdigest()
    return PublicLagSupportEvidenceLedger(
        {
            key: dict(value)
            for key, value in selection["frozen_operator_artifacts"].items()
        },
        dict(selection["frozen_selection_plan"]),
        dict(observations["frozen_observation_plan"]),
        dict(observations["frozen_event_selection_manifest"]),
        int(selection["eligible_candidate_count"]),
        stage30_ledger.stage29_tributary_binding,
        events,
        all_artifacts,
        f"cwms-usgs-lag-support:center-hill:{digest}",
    )


def _compile_event(
    event: dict[str, Any],
    *,
    release_by_time: dict[datetime, tuple[float, int]],
    by_source: dict[str, dict[str, object]],
    root: Path,
) -> PublicLagSupportEventEvidence:
    event_id = str(event["event_id"])
    start = _parse_time(str(event["start_utc"]))
    end = _parse_time(str(event["end_utc"]))
    inclusive_rows = tuple(
        release_by_time[start + timedelta(hours=index)]
        for index in range(EVENT_HOURS + 1)
    )
    release_support = (
        excitation.compile_release_excitation_identifiability(
            tuple(value[0] for value in inclusive_rows)
        )
    )
    if (
        release_support.as_dict()
        != event["release_excitation_identifiability"]
    ):
        raise ValueError("public_lag_support_release_gate_not_frozen")
    downstream_record = by_source[f"usgs_03424860_{event_id}"]
    tributary_record = by_source[f"usgs_03424730_{event_id}"]
    downstream_payload = _read_json(_resolve(downstream_record, root))
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
    release_rows = inclusive_rows[1:]
    releases = tuple(value[0] for value in release_rows)
    diagnostics = tuple(
        _lag_diagnostic_with_gaps(
            releases,
            downstream,
            start=start,
            lag=lag,
        )
        for lag in lag_operator.LAG_CANDIDATES_HOURS
    )
    support = lag_operator.compile_empirical_lag_support(
        tuple(
            lag_operator.LagCorrelationEvidence(
                value.lag_hours,
                value.pair_count,
                value.pearson_r,
            )
            for value in diagnostics
        )
    )
    relation = None
    if support.response_detectable:
        relation = lag_operator.EmpiricalGraphRelationLagSupport(
            SOURCE_BOUNDARY_ID,
            SOURCE_SPATIAL_ROLE,
            TARGET_SITE_ID,
            TARGET_COMID,
            "empirical_downstream_response",
            event_id,
            support,
        )
    graph_states = tuple(
        stage30.ObservedGraphState(
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
    return PublicLagSupportEventEvidence(
        event_id,
        int(event["selection_rank"]),
        str(event["release_direction"]),
        str(event["step_time_utc"]),
        float(event["signed_step_m3s"]),
        _iso(start),
        _iso(end),
        release_support,
        releases,
        tuple(value[1] for value in release_rows),
        len(downstream_payload["features"]),
        downstream,
        diagnostics,
        support,
        relation,
        stage30.ObservedGraphStateSeries(
            event_id,
            OBSERVATION_HOURS,
            len(tributary_payload["features"]),
            graph_states,
        ),
        (downstream_record, tributary_record),
    )


def _lag_diagnostic_with_gaps(
    releases: tuple[float, ...],
    downstream: tuple[stage29.HourlyObservedDischarge, ...],
    *,
    start: datetime,
    lag: int,
) -> stage29.LagDiagnostic:
    outcome_by_end = {
        _parse_time(value.support_end_utc): value.mean_m3s
        for value in downstream
    }
    pairs = tuple(
        (release, outcome_by_end[outcome_end])
        for index, release in enumerate(releases, start=1)
        if (
            outcome_end := start + timedelta(hours=index + lag)
        ) in outcome_by_end
    )
    if not pairs:
        raise ValueError("public_lag_support_no_aligned_pairs")
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
    return stage29.LagDiagnostic(
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


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _standard_deviation(values: tuple[float, ...]) -> float:
    mean = _mean(values)
    return math.sqrt(_mean(tuple((value - mean) ** 2 for value in values)))


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
        != "lag_support_events_frozen_before_observations"
        or selection.get("selected_event_count") != 4
        or [
            value.get("selection_rank")
            for value in selection.get("selected_events") or []
        ]
        != [1, 2, 3, 4]
        or selection_after.get("events_selected_from_release_only")
        is not True
        or selection_after.get("operators_and_events_frozen") is not True
        or selection_after.get("downstream_values_acquired") is not False
        or selection_after.get("lag_support_sets_compiled") is not False
        or observations.get("schema") != OBSERVATION_SCHEMA
        or observations.get("mode") != "observation_values"
        or observations.get("status")
        != "lag_support_observations_acquired"
        or observation_after.get(
            "operators_and_events_frozen_before_observation_values"
        )
        is not True
        or observation_after.get("lag_support_sets_compiled") is not False
        or observations.get("artifact_count") != 8
    ):
        raise ValueError("public_lag_support_manifest_invalid")
    frozen_operators = selection.get("frozen_operator_artifacts") or {}
    if frozen_operators != observations.get("frozen_operator_artifacts"):
        raise ValueError("public_lag_support_operator_freeze_mismatch")
    for descriptor in frozen_operators.values():
        _read_verified(descriptor, root)
    selection_body = _read_verified(
        observations["frozen_event_selection_manifest"], root
    )
    if json.loads(selection_body) != selection:
        raise ValueError("public_lag_support_selection_not_frozen")
    observation_plan_body = _read_verified(
        observations["frozen_observation_plan"], root
    )
    observation_plan = json.loads(observation_plan_body)
    observation_boundary = observation_plan.get("request_boundary", {})
    if (
        observation_plan
        != observations.get("frozen_observation_plan_content")
        or observation_boundary.get(
            "event_selection_may_be_recomputed_from_observations"
        )
        is not False
        or observation_boundary.get("lag_support_operator_may_be_retuned")
        is not False
    ):
        raise ValueError("public_lag_support_observation_plan_invalid")
    selection_plan_body = _read_verified(
        selection["frozen_selection_plan"], root
    )
    selection_plan = json.loads(selection_plan_body)
    frozen_support = selection_plan.get("frozen_empirical_lag_support", {})
    if (
        selection_plan != selection.get("frozen_selection_plan_content")
        or frozen_support.get("outcome_values_used_during_event_selection")
        is not False
        or frozen_support.get("lag_candidates_hours")
        != list(lag_operator.LAG_CANDIDATES_HOURS)
        or frozen_support.get("minimum_pearson_r")
        != lag_operator.MINIMUM_PEARSON_R
        or frozen_support.get("maximum_best_loss_pearson_r")
        != lag_operator.MAXIMUM_BEST_LOSS_PEARSON_R
        or frozen_support.get("minimum_pair_count")
        != lag_operator.MINIMUM_PAIR_COUNT
        or frozen_support.get("best_lag_must_be_interior") is not True
    ):
        raise ValueError("public_lag_support_selection_plan_invalid")
    plan_operators = selection_plan.get("frozen_operator_artifacts") or {}
    if plan_operators != frozen_operators:
        raise ValueError("public_lag_support_plan_operator_not_frozen")


def _verify_artifacts(
    descriptors: list[dict[str, Any]], root: Path
) -> list[dict[str, object]]:
    result = []
    seen = set()
    for descriptor in descriptors:
        source_id = str(descriptor["source_id"])
        if source_id in seen:
            raise ValueError("public_lag_support_duplicate_source")
        seen.add(source_id)
        _read_verified(descriptor, root)
        if (
            descriptor.get("hash_verified") is not True
            or descriptor.get("tls_hostname_verification_retained")
            is not True
        ):
            raise ValueError("public_lag_support_provenance_invalid")
        result.append(dict(descriptor))
    return result


def _read_verified(descriptor: dict[str, Any], root: Path) -> bytes:
    path = _resolve(descriptor, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("public_lag_support_artifact_mismatch")
    return body


def _resolve(descriptor: dict[str, Any], root: Path) -> Path:
    path = (root / str(descriptor["path"])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("public_lag_support_artifact_outside_repository") \
            from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_lag_support_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_lag_support_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
