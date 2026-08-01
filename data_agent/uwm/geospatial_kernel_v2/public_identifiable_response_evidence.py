"""Stage 31 blind evidence for release-supported response identifiability."""

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
from data_agent.uwm.geospatial_kernel_v2 import (
    public_regime_transfer_evidence as stage30,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    release_excitation_identifiability as excitation,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage31_center_hill_identifiable_response_events"
)
SCHEMA = "gwm.geotransport.public_identifiable_response_evidence.v1"
SELECTION_SCHEMA = "gwm.geotransport.stage31_identifiable_event_selection.v1"
OBSERVATION_SCHEMA = "gwm.geotransport.stage31_observation_acquisition.v1"
LAG_CANDIDATES_HOURS = tuple(range(13))
EVENT_HOURS = 72
OBSERVATION_HOURS = 84
TRIBUTARY_SITE_ID = stage29.TRIBUTARY_SITE_ID
TRIBUTARY_COMID = stage29.TRIBUTARY_COMID
OUTLET_COMID = stage29.OUTLET_COMID
STRATUM_ORDER = (
    "high_increase",
    "high_decrease",
    "low_increase",
    "low_decrease",
)


@dataclass(frozen=True)
class IdentifiableResponseEventEvidence:
    event_id: str
    selection_rank: int
    selection_stratum: str
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
    best_lag_hours: int
    second_best_lag_hours: int
    response_detectable: bool
    response_rejection_reasons: tuple[str, ...]
    exact_hour_resolved: bool
    graph_states: stage30.ObservedGraphStateSeries
    source_artifacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if (
            self.selection_stratum != STRATUM_ORDER[self.selection_rank - 1]
            or not self.release_support.blind_response_test_admissible
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
            raise ValueError("public_identifiable_response_event_invalid")

    @property
    def best_lag_diagnostic(self) -> stage29.LagDiagnostic:
        return self.lag_diagnostics[self.best_lag_hours]

    @property
    def second_best_lag_diagnostic(self) -> stage29.LagDiagnostic:
        return self.lag_diagnostics[self.second_best_lag_hours]

    @property
    def peak_margin_pearson_r(self) -> float:
        best = self.best_lag_diagnostic.pearson_r
        second = self.second_best_lag_diagnostic.pearson_r
        if best is None or second is None:
            return 0.0
        return best - second

    def require_exact_hour_lag(self) -> int:
        if not self.exact_hour_resolved:
            raise ValueError(
                "public_identifiable_response_exact_hour_not_resolved"
            )
        return self.best_lag_hours

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "role": "blind_identifiable_response",
            "selection_rank": self.selection_rank,
            "selection_stratum": self.selection_stratum,
            "selected_without_observation_values": True,
            "operator_frozen_without_observation_values": True,
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
            "downstream_complete_hour_count": len(
                self.downstream_hourly
            ),
            "lag_diagnostics": [
                value.as_dict() for value in self.lag_diagnostics
            ],
            "best_lag_hours": self.best_lag_hours,
            "best_lag_diagnostic": self.best_lag_diagnostic.as_dict(),
            "second_best_lag_hours": self.second_best_lag_hours,
            "second_best_lag_diagnostic": (
                self.second_best_lag_diagnostic.as_dict()
            ),
            "peak_margin_pearson_r": self.peak_margin_pearson_r,
            "response_detectable": self.response_detectable,
            "response_rejection_reasons": list(
                self.response_rejection_reasons
            ),
            "exact_hour_resolved": self.exact_hour_resolved,
            "physical_travel_time_admitted": False,
            "graph_states": self.graph_states.as_dict(),
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class PublicIdentifiableResponseEvidenceLedger:
    operator_artifact: dict[str, object]
    selection_plan_artifact: dict[str, object]
    observation_plan_artifact: dict[str, object]
    event_selection_manifest_artifact: dict[str, object]
    candidate_count: int
    tributary_binding: stage29.ObservedTributaryBinding
    events: tuple[IdentifiableResponseEventEvidence, ...]
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            len(self.events) != 4
            or tuple(value.selection_stratum for value in self.events)
            != STRATUM_ORDER
            or len(self.source_artifacts) != 9
            or self.tributary_binding.comid != TRIBUTARY_COMID
            or not self.tributary_binding.path_reaches_outlet
        ):
            raise ValueError("public_identifiable_response_ledger_invalid")

    @property
    def all_events_have_detectable_response(self) -> bool:
        return all(value.response_detectable for value in self.events)

    @property
    def all_events_resolve_exact_hour(self) -> bool:
        return all(value.exact_hour_resolved for value in self.events)

    def require_validated_release_support_gate(self) -> str:
        if not self.all_events_have_detectable_response:
            raise ValueError(
                "public_identifiable_response_release_gate_not_validated"
            )
        return excitation.SCHEMA

    def require_universal_exact_hour_lag(self) -> None:
        if not self.all_events_resolve_exact_hour:
            raise ValueError(
                "public_identifiable_response_exact_hour_not_universal"
            )

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "public_identifiable_response_empirical_lag_is_not_physical_time"
        )

    def require_tributary_mouth_flux(self) -> None:
        raise ValueError(
            "public_identifiable_response_graph_state_is_not_mouth_flux"
        )

    def promote_to_runtime_operator(self) -> None:
        raise ValueError(
            "public_identifiable_response_runtime_operator_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "operator_artifact": self.operator_artifact,
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
            "response_summary": {
                "event_count": len(self.events),
                "per_event_best_lag_hours": [
                    value.best_lag_hours for value in self.events
                ],
                "per_event_best_lag_pearson_r": [
                    value.best_lag_diagnostic.pearson_r
                    for value in self.events
                ],
                "per_event_response_detectable": [
                    value.response_detectable for value in self.events
                ],
                "all_events_have_detectable_response": (
                    self.all_events_have_detectable_response
                ),
                "per_event_peak_margin_pearson_r": [
                    value.peak_margin_pearson_r for value in self.events
                ],
                "per_event_exact_hour_resolved": [
                    value.exact_hour_resolved for value in self.events
                ],
                "all_events_resolve_exact_hour": (
                    self.all_events_resolve_exact_hour
                ),
            },
            "claim_boundary": {
                "operator_and_events_frozen_before_stage31_outcomes": True,
                "release_gate_is_input_support_not_response_model": True,
                "exact_hour_requires_outcome_peak_resolution": True,
                "empirical_lag_equals_physical_travel_time": False,
                "smith_fork_is_observed_state_at_comid_18421273": True,
                "smith_fork_is_tributary_mouth_flux": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "blind_identifiable_response_evidence_admitted": True,
                "release_support_gate_validated": (
                    self.all_events_have_detectable_response
                ),
                "universal_exact_hour_lag_admitted": (
                    self.all_events_resolve_exact_hour
                ),
                "physical_travel_time_admitted": False,
                "observed_graph_state_contract_admitted": True,
                "tributary_mouth_flux_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_identifiable_response_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicIdentifiableResponseEvidenceLedger:
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
    return PublicIdentifiableResponseEvidenceLedger(
        dict(selection["frozen_operator_artifact"]),
        dict(selection["frozen_selection_plan"]),
        dict(observations["frozen_observation_plan"]),
        dict(observations["frozen_event_selection_manifest"]),
        int(selection["eligible_candidate_count"]),
        stage30_ledger.stage29_tributary_binding,
        events,
        all_artifacts,
        f"cwms-usgs-identifiable-response:center-hill:{digest}",
    )


def _compile_event(
    event: dict[str, Any],
    *,
    release_by_time: dict[datetime, tuple[float, int]],
    by_source: dict[str, dict[str, object]],
    root: Path,
) -> IdentifiableResponseEventEvidence:
    event_id = str(event["event_id"])
    start = _parse_time(str(event["start_utc"]))
    end = _parse_time(str(event["end_utc"]))
    inclusive_rows = tuple(
        release_by_time[start + timedelta(hours=index)]
        for index in range(73)
    )
    support = excitation.compile_release_excitation_identifiability(
        tuple(value[0] for value in inclusive_rows)
    )
    if support.as_dict() != event["release_excitation_identifiability"]:
        raise ValueError(
            "public_identifiable_response_release_support_not_frozen"
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
        raise ValueError(
            "public_identifiable_response_downstream_hour_missing"
        )
    release_rows = inclusive_rows[1:]
    releases = tuple(value[0] for value in release_rows)
    diagnostics = tuple(
        stage29._lag_diagnostic(releases, downstream, lag)
        for lag in LAG_CANDIDATES_HOURS
    )
    ranked = sorted(
        (value for value in diagnostics if value.pearson_r is not None),
        key=lambda value: (
            -float(value.pearson_r),
            value.rmse_m3s,
            value.lag_hours,
        ),
    )
    best, second = ranked[:2]
    reasons = []
    if best.pearson_r is None or best.pearson_r < 0.8:
        reasons.append("best_lag_pearson_below_0_8")
    if best.lag_hours in {0, 12}:
        reasons.append("best_lag_is_search_boundary")
    if best.pair_count < 60:
        reasons.append("best_lag_pair_count_below_60")
    detectable = not reasons
    peak_margin = float(best.pearson_r) - float(second.pearson_r)
    exact_hour = detectable and peak_margin >= 0.02
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
    return IdentifiableResponseEventEvidence(
        event_id,
        int(event["selection_rank"]),
        str(event["selection_stratum"]),
        str(event["step_time_utc"]),
        float(event["signed_step_m3s"]),
        _iso(start),
        _iso(end),
        support,
        releases,
        tuple(value[1] for value in release_rows),
        len(downstream_payload["features"]),
        downstream,
        diagnostics,
        best.lag_hours,
        second.lag_hours,
        detectable,
        tuple(reasons),
        exact_hour,
        stage30.ObservedGraphStateSeries(
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
        != "identifiable_events_frozen_before_observations"
        or selection.get("selected_event_count") != 4
        or [
            value.get("selection_stratum")
            for value in selection.get("selected_events") or []
        ]
        != list(STRATUM_ORDER)
        or selection_after.get("operator_and_events_frozen") is not True
        or selection_after.get("downstream_values_acquired") is not False
        or observations.get("schema") != OBSERVATION_SCHEMA
        or observations.get("mode") != "observation_values"
        or observations.get("status")
        != "identifiable_response_observations_acquired"
        or observation_after.get(
            "operator_and_events_frozen_before_observation_values"
        )
        is not True
        or observations.get("artifact_count") != 8
    ):
        raise ValueError("public_identifiable_response_manifest_invalid")
    operator_body = _read_verified(
        selection["frozen_operator_artifact"], root
    )
    if hashlib.sha256(operator_body).hexdigest() != selection.get(
        "frozen_selection_plan_content", {}
    ).get("frozen_operator_artifact", {}).get("sha256"):
        raise ValueError("public_identifiable_response_operator_not_frozen")
    selection_body = _read_verified(
        observations["frozen_event_selection_manifest"], root
    )
    if json.loads(selection_body) != selection:
        raise ValueError("public_identifiable_response_selection_not_frozen")
    observation_plan_body = _read_verified(
        observations["frozen_observation_plan"], root
    )
    observation_plan = json.loads(observation_plan_body)
    if (
        observation_plan
        != observations.get("frozen_observation_plan_content")
        or observation_plan.get("request_boundary", {}).get(
            "support_gate_may_be_retuned_from_observations"
        )
        is not False
    ):
        raise ValueError(
            "public_identifiable_response_observation_plan_invalid"
        )
    selection_plan_body = _read_verified(
        selection["frozen_selection_plan"], root
    )
    selection_plan = json.loads(selection_plan_body)
    if (
        selection_plan != selection.get("frozen_selection_plan_content")
        or selection_plan.get("frozen_release_support_gate", {}).get(
            "outcome_values_used"
        )
        is not False
    ):
        raise ValueError(
            "public_identifiable_response_selection_plan_invalid"
        )


def _verify_artifacts(
    descriptors: list[dict[str, Any]], root: Path
) -> list[dict[str, object]]:
    result = []
    seen = set()
    for descriptor in descriptors:
        source_id = str(descriptor["source_id"])
        if source_id in seen:
            raise ValueError("public_identifiable_response_duplicate_source")
        seen.add(source_id)
        _read_verified(descriptor, root)
        if (
            descriptor.get("hash_verified") is not True
            or descriptor.get("tls_hostname_verification_retained")
            is not True
        ):
            raise ValueError(
                "public_identifiable_response_provenance_invalid"
            )
        result.append(dict(descriptor))
    return result


def _read_verified(descriptor: dict[str, Any], root: Path) -> bytes:
    path = _resolve(descriptor, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("public_identifiable_response_artifact_mismatch")
    return body


def _resolve(descriptor: dict[str, Any], root: Path) -> Path:
    path = (root / str(descriptor["path"])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "public_identifiable_response_artifact_outside_repository"
        ) from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_identifiable_response_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_identifiable_response_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
