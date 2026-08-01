"""Stage 43 public component-event empirical lag-support evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    component_discharge_value_support as component_support,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    empirical_lag_support as lag_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_blind_transfer_evidence as stage29,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_component_discharge_event_evidence as stage41,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_regime_transfer_evidence as stage30,
)
from scripts import acquire_geotransport_stage42_component_event_targets as acquire
from scripts import compile_geotransport_stage41_component_discharge_events as compile_stage41
from scripts import freeze_geotransport_stage42_component_event_target_protocol as freeze
from scripts import plan_geotransport_stage42_component_event_targets as planner

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE42_ROOT = freeze.STAGE42_ROOT
DEFAULT_SOURCE_ROOT = REPO_ROOT / STAGE42_ROOT
STAGE43_ROOT = (
    "data/geotransport_v0_1/"
    "stage43_center_hill_component_event_lag_support"
)
SCHEMA = "gwm.geotransport.public_component_event_lag_support_evidence.v1"
STATUS = (
    "stage43_component_event_local_lag_support_admitted_"
    "common_support_rejected"
)
EVENT_HOURS = 72
OBSERVATION_HOURS = 84
SOURCE_BOUNDARY_ID = "CETT1-CENTER_HILL"
SOURCE_SPATIAL_ROLE = "operational_tailwater_zone"
TARGET_SITE_ID = stage29.DOWNSTREAM_SITE_ID
TARGET_COMID = stage29.OUTLET_COMID
GRAPH_STATE_SITE_ID = stage29.TRIBUTARY_SITE_ID
GRAPH_STATE_COMID = stage29.TRIBUTARY_COMID

STAGE41_PROTOCOL_PATH = f"{stage41.STAGE41_ROOT}/{compile_stage41.PROTOCOL_NAME}"
STAGE41_CANDIDATE_LEDGER_PATH = (
    f"{stage41.STAGE41_ROOT}/{compile_stage41.CANDIDATE_LEDGER_NAME}"
)
STAGE41_MANIFEST_PATH = f"{stage41.STAGE41_ROOT}/{compile_stage41.MANIFEST_NAME}"
STAGE41_PUBLIC_LEDGER_PATH = freeze.STAGE41_LEDGER_PATH
STAGE41_GATES_PATH = freeze.STAGE41_GATES_PATH
STAGE42_PROTOCOL_PATH = f"{STAGE42_ROOT}/protocol.json"
STAGE42_PLAN_PATH = f"{STAGE42_ROOT}/target_acquisition_plan.json"
STAGE42_STATE_PATH = f"{STAGE42_ROOT}/{acquire.STATE_NAME}"
STAGE42_MANIFEST_PATH = f"{STAGE42_ROOT}/{acquire.MANIFEST_NAME}"
STAGE42_GATES_PATH = (
    "benchmarks/geotransport_v0_1/"
    "stage42_component_event_target_plan_gates.json"
)

EXPECTED_CHECKPOINT_SHA256 = {
    STAGE41_PROTOCOL_PATH: stage41.EXPECTED_PROTOCOL_SHA256,
    STAGE41_CANDIDATE_LEDGER_PATH: (
        stage41.EXPECTED_CANDIDATE_LEDGER_SHA256
    ),
    STAGE41_MANIFEST_PATH: stage41.EXPECTED_MANIFEST_SHA256,
    STAGE41_PUBLIC_LEDGER_PATH: (
        "6c859b4cc52455beea308e2418832c9ce71a679f9ca882d3bcea9facbaf7a1d3"
    ),
    STAGE41_GATES_PATH: (
        "46d92725139c4d9a93fadad708aea6ba9e4edcce93187cf2bcff945c1cbfe340"
    ),
    freeze.TARGET_OPERATOR_PATH: freeze.FROZEN_HASHES[
        freeze.TARGET_OPERATOR_PATH
    ],
    STAGE42_PROTOCOL_PATH: planner.FROZEN_PROTOCOL_SHA256,
    STAGE42_PLAN_PATH: acquire.FROZEN_PLAN_SHA256,
    STAGE42_GATES_PATH: (
        "4c23a499ed26e527808c83b77d863ccce2e8eb70ecca615f044941cf550dce19"
    ),
    STAGE42_STATE_PATH: (
        "b22afc9697c07d4578427a634eef907a51cca5f8e2ec6c2c59135d8003e39d8f"
    ),
    STAGE42_MANIFEST_PATH: (
        "55201c79b843a4d961efc2388d4e6bae54a4f505e50a8c429f634be048f20df7"
    ),
}

EXPECTED_RAW_SHA256 = {
    "usgs_03424860_component_total_step_20250415T1600Z": (
        "ecc5905e5c107c2e2876292f3261190233a17483bbbe9d56f42db7f32da931d3"
    ),
    "usgs_03424730_component_total_step_20250415T1600Z": (
        "bb626e6117fd1a78a8c6f16bdf7c8be2748f4bdffe62d8abc2b88183ae8464f6"
    ),
    "usgs_03424860_component_total_step_20230311T2000Z": (
        "fa2cf6ce989b1d5f8957466dbb07939fe360b6c21f3fc0db7b4fdc8f7af324ed"
    ),
    "usgs_03424730_component_total_step_20230311T2000Z": (
        "cf7b665bf7973c5699ebe92ba2b8c3214fe62b78ed86308ec350f78f3770e024"
    ),
    "usgs_03424860_component_total_step_20210112T1600Z": (
        "7a9cc15e0ea7728003c62617c10addaf11fdeb6212883b5d0690e295ed23b216"
    ),
    "usgs_03424730_component_total_step_20210112T1600Z": (
        "b26c0bc80f4791f2d69313dc0d94c5c01316a5fd824af48c48994c2b3b8d6183"
    ),
    "usgs_03424860_component_total_step_20210727T0300Z": (
        "ac961ff1db45d64d019d13f295a358a77a23bcdcd548845373941db2a205fa97"
    ),
    "usgs_03424730_component_total_step_20210727T0300Z": (
        "29920d027979780d4b04d7c004805be398af472c734c12fbd1f8bd6585077ea2"
    ),
}


@dataclass(frozen=True)
class TargetMetadataSummary:
    site_id: str
    site_role: str
    raw_sample_count: int
    approval_status_counts: tuple[tuple[str, int], ...]
    qualifier_none_count: int
    non_null_qualifier_count: int

    def __post_init__(self) -> None:
        if (
            self.site_role not in {"downstream_outcome", "observed_graph_state"}
            or self.raw_sample_count <= 0
            or sum(count for _, count in self.approval_status_counts)
            != self.raw_sample_count
            or self.qualifier_none_count + self.non_null_qualifier_count
            != self.raw_sample_count
        ):
            raise ValueError("component_event_target_metadata_invalid")

    @property
    def all_samples_report_approved(self) -> bool:
        return self.approval_status_counts == (
            ("Approved", self.raw_sample_count),
        )

    @property
    def all_qualifiers_are_none(self) -> bool:
        return self.qualifier_none_count == self.raw_sample_count

    def as_dict(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "site_role": self.site_role,
            "raw_sample_count": self.raw_sample_count,
            "approval_status_counts": dict(self.approval_status_counts),
            "qualifier_none_count": self.qualifier_none_count,
            "non_null_qualifier_count": self.non_null_qualifier_count,
            "all_samples_report_approved": self.all_samples_report_approved,
            "all_qualifiers_are_none": self.all_qualifiers_are_none,
            "quality_metadata_preserved": True,
            "quality_metadata_interpreted_as_scientific_approval": False,
        }


@dataclass(frozen=True)
class PublicComponentEventLagSupportEvidence:
    event_id: str
    selection_rank: int
    selection_stratum: str
    total_direction: str
    step_time_utc: str
    signed_total_step_m3s: float
    start_utc: str
    end_utc: str
    active_step_components: tuple[str, ...]
    dominant_step_component: str
    source_total_values_m3s: tuple[float, ...]
    source_component_quality_codes: tuple[tuple[str, tuple[int, ...]], ...]
    downstream_metadata: TargetMetadataSummary
    downstream_hourly: tuple[stage29.HourlyObservedDischarge, ...]
    lag_diagnostics: tuple[stage29.LagDiagnostic, ...]
    lag_support: lag_operator.EmpiricalLagSupport
    graph_relation: lag_operator.EmpiricalGraphRelationLagSupport
    graph_state_metadata: TargetMetadataSummary
    graph_states: stage30.ObservedGraphStateSeries
    source_artifacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if (
            self.selection_rank not in range(1, 5)
            or self.total_direction not in {"increase", "decrease"}
            or self.active_step_components != ("turbine",)
            or self.dominant_step_component != "turbine"
            or len(self.source_total_values_m3s) != EVENT_HOURS
            or any(
                not math.isfinite(value) or value < 0.0
                for value in self.source_total_values_m3s
            )
            or tuple(value.lag_hours for value in self.lag_diagnostics)
            != lag_operator.LAG_CANDIDATES_HOURS
            or any(value.pair_count != EVENT_HOURS for value in self.lag_diagnostics)
            or not self.lag_support.response_detectable
            or self.graph_relation.evidence_event_id != self.event_id
            or self.graph_relation.lag_support != self.lag_support
            or self.graph_states.event_id != self.event_id
            or self.downstream_metadata.site_id != TARGET_SITE_ID
            or self.graph_state_metadata.site_id != GRAPH_STATE_SITE_ID
            or len(self.source_artifacts) != 2
        ):
            raise ValueError("public_component_event_lag_support_event_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "role": "blind_component_total_event_lag_support",
            "selection_rank": self.selection_rank,
            "selection_stratum": self.selection_stratum,
            "selected_without_target_values": True,
            "target_operator_frozen_without_target_values": True,
            "total_direction": self.total_direction,
            "step_time_utc": self.step_time_utc,
            "signed_total_step_m3s": self.signed_total_step_m3s,
            "window": {
                "start_utc": self.start_utc,
                "source_end_utc": self.end_utc,
                "source_support_hour_count": EVENT_HOURS,
                "target_support_hour_count": OBSERVATION_HOURS,
            },
            "active_step_components": list(self.active_step_components),
            "dominant_step_component": self.dominant_step_component,
            "source_total_values_m3s": list(self.source_total_values_m3s),
            "source_component_quality_codes": {
                component: list(codes)
                for component, codes in self.source_component_quality_codes
            },
            "source_quality_codes_interpreted_as_approval": False,
            "downstream_metadata": self.downstream_metadata.as_dict(),
            "downstream_complete_hour_count": len(self.downstream_hourly),
            "downstream_missing_hour_count": (
                OBSERVATION_HOURS - len(self.downstream_hourly)
            ),
            "downstream_hourly": [
                value.as_dict() for value in self.downstream_hourly
            ],
            "lag_diagnostics": [
                value.as_dict() for value in self.lag_diagnostics
            ],
            "empirical_lag_support": self.lag_support.as_dict(),
            "graph_relation_lag_support": self.graph_relation.as_dict(),
            "graph_state_metadata": self.graph_state_metadata.as_dict(),
            "graph_states": self.graph_states.as_dict(),
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class PublicComponentEventLagSupportEvidenceLedger:
    checkpoint_artifacts: dict[str, dict[str, object]]
    source_artifacts: tuple[dict[str, object], ...]
    events: tuple[PublicComponentEventLagSupportEvidence, ...]
    actual_request_count: int
    actual_attempt_count: int
    actual_download_bytes: int
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            {
                path: descriptor["sha256"]
                for path, descriptor in self.checkpoint_artifacts.items()
            }
            != EXPECTED_CHECKPOINT_SHA256
            or len(self.source_artifacts) != 8
            or tuple(value.event_id for value in self.events)
            != stage41.EXPECTED_EVENT_IDS
            or tuple(value.selection_rank for value in self.events)
            != (1, 2, 3, 4)
            or self.actual_request_count != 8
            or self.actual_attempt_count != 8
            or self.actual_download_bytes != 1_112_317
        ):
            raise ValueError("public_component_event_lag_support_ledger_invalid")

    @property
    def all_events_have_detectable_response(self) -> bool:
        return all(value.lag_support.response_detectable for value in self.events)

    @property
    def common_supported_lags_hours(self) -> tuple[int, ...]:
        if not self.events:
            return ()
        common = set(self.events[0].lag_support.supported_lags_hours)
        for event in self.events[1:]:
            common.intersection_update(event.lag_support.supported_lags_hours)
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
                "component_event_common_empirical_support_unadmitted"
            )
        return self.common_supported_lags_hours

    def require_quality_approval_semantics(self) -> None:
        raise ValueError("component_event_quality_approval_semantics_unadmitted")

    def require_non_turbine_component_contrast(self) -> None:
        raise ValueError("component_event_non_turbine_contrast_unadmitted")

    def require_causal_response(self) -> None:
        raise ValueError("component_event_causal_response_unadmitted")

    def require_physical_travel_time(self) -> None:
        raise ValueError("component_event_empirical_set_is_not_physical_time")

    def require_hydraulic_edge_travel_time(self) -> None:
        raise ValueError("component_event_relation_is_not_hydraulic_edge_time")

    def require_tributary_mouth_flux(self) -> None:
        raise ValueError("component_event_graph_state_is_not_mouth_flux")

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("component_event_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        per_event_sets = [
            list(value.lag_support.supported_lags_hours)
            for value in self.events
        ]
        return {
            "schema": SCHEMA,
            "status": STATUS,
            "checkpoint_artifacts": self.checkpoint_artifacts,
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "acquisition_summary": {
                "logical_request_count": self.actual_request_count,
                "actual_attempt_count": self.actual_attempt_count,
                "actual_download_bytes": self.actual_download_bytes,
                "all_requests_succeeded_on_first_attempt": True,
                "unexpected_pagination_observed": False,
            },
            "graph_binding": {
                "source_boundary_id": SOURCE_BOUNDARY_ID,
                "source_spatial_role": SOURCE_SPATIAL_ROLE,
                "downstream_target_site_id": TARGET_SITE_ID,
                "downstream_target_comid": TARGET_COMID,
                "observed_graph_state_site_id": GRAPH_STATE_SITE_ID,
                "observed_graph_state_comid": GRAPH_STATE_COMID,
            },
            "events": [value.as_dict() for value in self.events],
            "lag_support_summary": {
                "event_count": len(self.events),
                "per_event_best_lag_hours": [
                    value.lag_support.best_lag_hours for value in self.events
                ],
                "per_event_best_lag_pearson_r": [
                    value.lag_support.best_pearson_r for value in self.events
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
                "stage41_events_and_target_operator_frozen_before_values": True,
                "stage42_protocol_plan_state_manifest_and_raw_hashes_bound": True,
                "source_total_is_exact_sum_of_four_synchronized_components": True,
                "source_quality_codes_are_not_approval_semantics": True,
                "target_quality_metadata_is_not_scientific_approval": True,
                "target_gaps_preserved_without_filling": True,
                "lag_output_is_discrete_empirical_support_set": True,
                "common_support_is_cross_event_set_intersection": True,
                "all_selected_steps_are_turbine_only": True,
                "empirical_lag_equals_physical_travel_time": False,
                "empirical_lag_is_hydraulic_edge_travel_time": False,
                "smith_fork_is_observed_state_at_comid_18421273": True,
                "smith_fork_is_tributary_mouth_flux": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "observed_downstream_response_evidence_admitted": True,
                "event_local_empirical_lag_support_admitted": True,
                "event_local_empirical_lag_support_count": len(self.events),
                "common_empirical_support_admitted": (
                    self.common_empirical_support_admitted
                ),
                "common_supported_lags_hours": list(
                    self.common_supported_lags_hours
                ),
                "observed_graph_state_contract_admitted": True,
                "non_turbine_component_contrast_admitted": False,
                "quality_approval_semantics_admitted": False,
                "causal_response_admitted": False,
                "physical_travel_time_admitted": False,
                "hydraulic_edge_travel_time_admitted": False,
                "tributary_mouth_flux_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_component_event_lag_support_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicComponentEventLagSupportEvidenceLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    checkpoint_artifacts = {
        path: _artifact(root / path, root)
        for path in EXPECTED_CHECKPOINT_SHA256
    }
    if {
        path: descriptor["sha256"]
        for path, descriptor in checkpoint_artifacts.items()
    } != EXPECTED_CHECKPOINT_SHA256:
        raise ValueError("component_event_checkpoint_artifact_drift")

    stage41_ledger = stage41.compile_public_component_discharge_event_evidence(
        root / stage41.STAGE41_ROOT,
        repo_root=root,
    )
    protocol = _read_json(source / "protocol.json")
    plan = _read_json(source / "target_acquisition_plan.json")
    state = _read_json(source / acquire.STATE_NAME)
    manifest = _read_json(source / acquire.MANIFEST_NAME)
    source_artifacts, payload_by_source = _validate_stage42_checkpoint(
        protocol=protocol,
        plan=plan,
        state=state,
        manifest=manifest,
        source=source,
        root=root,
        checkpoint_artifacts=checkpoint_artifacts,
    )
    values_by_component = _component_values()
    by_source = {
        str(value["source_id"]): value for value in source_artifacts
    }
    events = tuple(
        _compile_event(
            event,
            values_by_component=values_by_component,
            by_source=by_source,
            payload_by_source=payload_by_source,
        )
        for event in stage41_ledger.selection.selected_events
    )
    digest = hashlib.sha256(
        "|".join(
            str(value["sha256"])
            for value in (
                *checkpoint_artifacts.values(),
                *source_artifacts,
            )
        ).encode("ascii")
    ).hexdigest()
    return PublicComponentEventLagSupportEvidenceLedger(
        checkpoint_artifacts,
        source_artifacts,
        events,
        int(manifest["actual_request_count"]),
        int(manifest["actual_attempt_count"]),
        int(manifest["actual_download_bytes"]),
        f"center-hill-component-event-lag-support:{digest}",
    )


def _compile_event(
    event: dict[str, object],
    *,
    values_by_component: dict[
        str, dict[datetime, tuple[float | None, int]]
    ],
    by_source: dict[str, dict[str, object]],
    payload_by_source: dict[str, dict[str, Any]],
) -> PublicComponentEventLagSupportEvidence:
    event_id = str(event["event_id"])
    start = _parse_time(str(event["start_utc"]))
    end = _parse_time(str(event["end_utc"]))
    source_rows = tuple(
        _source_total_row(
            values_by_component,
            start + timedelta(hours=index),
        )
        for index in range(1, EVENT_HOURS + 1)
    )
    downstream_id = f"usgs_03424860_{event_id}"
    graph_state_id = f"usgs_03424730_{event_id}"
    downstream_record = by_source[downstream_id]
    graph_state_record = by_source[graph_state_id]
    downstream_payload = payload_by_source[downstream_id]
    graph_state_payload = payload_by_source[graph_state_id]
    downstream = stage29._compile_hourly_observations(
        downstream_payload,
        start=start,
        hour_count=OBSERVATION_HOURS,
    )
    graph_state_hourly = stage29._compile_hourly_observations(
        graph_state_payload,
        start=start,
        hour_count=OBSERVATION_HOURS,
    )
    releases = tuple(value[0] for value in source_rows)
    diagnostics = tuple(
        stage29._lag_diagnostic(releases, downstream, lag)
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
    if not support.response_detectable:
        raise ValueError("component_event_response_not_detectable")
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
            GRAPH_STATE_SITE_ID,
            GRAPH_STATE_COMID,
            "discharge",
            "m3/s",
            value.support_start_utc,
            value.support_end_utc,
            value.sample_times_utc,
            value.mean_m3s,
            value.approval_statuses,
            graph_state_id,
        )
        for value in graph_state_hourly
    )
    return PublicComponentEventLagSupportEvidence(
        event_id,
        int(event["selection_rank"]),
        str(event["selection_stratum"]),
        str(event["total_direction"]),
        str(event["step_time_utc"]),
        float(event["signed_total_step_m3s"]),
        _iso(start),
        _iso(end),
        tuple(str(value) for value in event["active_step_components"]),
        str(event["dominant_step_component"]),
        releases,
        tuple(
            (
                component,
                tuple(
                    sorted({row[1][component] for row in source_rows})
                ),
            )
            for component in component_support.catalog.EXPECTED_COMPONENTS
        ),
        _metadata_summary(downstream_payload, downstream_record),
        downstream,
        diagnostics,
        support,
        relation,
        _metadata_summary(graph_state_payload, graph_state_record),
        stage30.ObservedGraphStateSeries(
            event_id,
            OBSERVATION_HOURS,
            len(graph_state_payload["features"]),
            graph_states,
        ),
        (downstream_record, graph_state_record),
    )


def _source_total_row(
    values_by_component: dict[
        str, dict[datetime, tuple[float | None, int]]
    ],
    timestamp: datetime,
) -> tuple[float, dict[str, int]]:
    total = 0.0
    qualities = {}
    for component in component_support.catalog.EXPECTED_COMPONENTS:
        row = values_by_component[component].get(timestamp)
        if row is None or row[0] is None or float(row[0]) < 0.0:
            raise ValueError("component_event_source_total_support_invalid")
        total += float(row[0])
        qualities[component] = int(row[1])
    return total, qualities


def _component_values() -> dict[
    str, dict[datetime, tuple[float | None, int]]
]:
    payloads = compile_stage41._payloads()
    return {
        component: component_support._compile_component(
            component,
            payloads[component],
        )[1]
        for component in component_support.catalog.EXPECTED_COMPONENTS
    }


def _metadata_summary(
    payload: dict[str, Any], descriptor: dict[str, object]
) -> TargetMetadataSummary:
    properties = [value["properties"] for value in payload["features"]]
    statuses = Counter(str(value["approval_status"]) for value in properties)
    qualifier_none_count = sum(
        value.get("qualifiers") is None for value in properties
    )
    return TargetMetadataSummary(
        str(descriptor["site_id"]),
        str(descriptor["site_role"]),
        len(properties),
        tuple(sorted(statuses.items())),
        qualifier_none_count,
        len(properties) - qualifier_none_count,
    )


def _validate_stage42_checkpoint(
    *,
    protocol: dict[str, Any],
    plan: dict[str, Any],
    state: dict[str, Any],
    manifest: dict[str, Any],
    source: Path,
    root: Path,
    checkpoint_artifacts: dict[str, dict[str, object]],
) -> tuple[tuple[dict[str, object], ...], dict[str, dict[str, Any]]]:
    claims = manifest.get("claim_boundary") or {}
    if (
        protocol != freeze.build_protocol()
        or plan != planner.compile_plan()
        or manifest.get("schema") != acquire.SCHEMA
        or manifest.get("status")
        != "stage42_component_event_target_values_acquired"
        or manifest.get("frozen_target_acquisition_plan")
        != checkpoint_artifacts[STAGE42_PLAN_PATH]
        or manifest.get("acquisition_state_artifact")
        != checkpoint_artifacts[STAGE42_STATE_PATH]
        or manifest.get("actual_request_count") != 8
        or manifest.get("actual_attempt_count") != 8
        or manifest.get("actual_download_bytes") != 1_112_317
        or manifest.get("artifact_count") != 8
        or manifest.get("request_boundary") != plan["request_boundary"]
        or claims.get("stage41_events_and_target_operator_frozen_before_values")
        is not True
        or claims.get("downstream_target_values_acquired") is not True
        or claims.get("observed_graph_state_values_acquired") is not True
        or claims.get("target_coverage_compiled") is not False
        or claims.get("empirical_lag_support_sets_compiled") is not False
        or state.get("schema") != acquire.STATE_SCHEMA
        or state.get("frozen_plan_sha256") != acquire.FROZEN_PLAN_SHA256
    ):
        raise ValueError("component_event_stage42_checkpoint_invalid")

    plan_sources = plan["sources"]
    manifest_sources = manifest["artifacts"]
    if [value["source_id"] for value in manifest_sources] != [
        value["source_id"] for value in plan_sources
    ]:
        raise ValueError("component_event_stage42_source_order_invalid")
    manifest_by_source = {
        str(value["source_id"]): value for value in manifest_sources
    }
    state_by_source = state.get("sources")
    if not isinstance(state_by_source, dict) or set(state_by_source) != {
        str(value["source_id"]) for value in plan_sources
    }:
        raise ValueError("component_event_stage42_state_invalid")

    artifacts = []
    payload_by_source = {}
    for request_source in plan_sources:
        source_id = str(request_source["source_id"])
        record = manifest_by_source[source_id]
        state_record = state_by_source[source_id]
        raw_path = source / str(request_source["output_name"])
        artifact = _artifact(raw_path, root)
        if (
            artifact["sha256"] != EXPECTED_RAW_SHA256.get(source_id)
            or record.get("path") != artifact["path"]
            or record.get("sha256") != artifact["sha256"]
            or record.get("size_bytes") != artifact["size_bytes"]
            or record.get("event_id") != request_source["event_id"]
            or record.get("site_id") != request_source["site_id"]
            or record.get("site_role") != request_source["site_role"]
            or record.get("hash_verified") is not True
            or record.get("tls_hostname_verification_retained") is not True
            or record.get("attempt_count") != 1
            or record.get("failed_attempts") != []
            or state_record.get("attempt_count") != 1
            or state_record.get("failed_attempts") != []
            or state_record.get("success") is not True
            or state_record.get("sha256") != artifact["sha256"]
            or state_record.get("size_bytes") != artifact["size_bytes"]
        ):
            raise ValueError("component_event_stage42_raw_artifact_invalid")
        payload = _read_json(raw_path)
        acquire._validate_payload(payload, request_source)
        artifacts.append(dict(record))
        payload_by_source[source_id] = payload
    return tuple(artifacts), payload_by_source


def _artifact(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("component_event_artifact_outside_repo") from exc
    body = resolved.read_bytes()
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("component_event_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("component_event_timezone_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
