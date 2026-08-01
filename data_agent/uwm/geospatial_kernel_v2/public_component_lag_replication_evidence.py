"""Stage 47 confirmatory component-lag replication evidence compiler."""

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
    component_lag_replication_assessment as assessment_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    empirical_lag_support as lag_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_component_discharge_value_support as stage40_evidence,
)
from scripts import acquire_geotransport_stage45_component_lag_replication_targets as acquire
from scripts import compile_geotransport_stage41_component_discharge_events as compile_stage41
from scripts import freeze_geotransport_stage45_component_lag_replication_target_protocol as stage45
from scripts import (
    freeze_geotransport_stage46_component_lag_replication_assessment_protocol as stage46,
)
from scripts import plan_geotransport_stage45_component_lag_replication_targets as planner

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE45_ROOT = stage45.STAGE45_ROOT
DEFAULT_SOURCE_ROOT = REPO_ROOT / STAGE45_ROOT
STAGE47_ROOT = "data/geotransport_v0_1/stage47_center_hill_component_lag_replication_evidence"
SCHEMA = "gwm.geotransport.public_component_lag_replication_evidence.v1"
EVENT_HOURS = 72
TARGET_HOURS = 84
CFS_TO_M3S = 0.028316846592

STAGE40_LEDGER_PATH = stage46.STAGE40_LEDGER_PATH
STAGE40_GATES_PATH = stage46.STAGE40_GATES_PATH
STAGE44_PROTOCOL_PATH = stage46.STAGE44_PROTOCOL_PATH
STAGE44_CANDIDATE_PATH = stage46.STAGE44_CANDIDATE_PATH
STAGE44_MANIFEST_PATH = stage46.STAGE44_MANIFEST_PATH
STAGE44_GATES_PATH = stage46.STAGE44_GATES_PATH
STAGE45_PROTOCOL_PATH = stage46.STAGE45_PROTOCOL_PATH
STAGE45_PLAN_PATH = stage46.STAGE45_PLAN_PATH
STAGE45_GATES_PATH = stage46.STAGE45_GATES_PATH
STAGE46_PROTOCOL_PATH = f"{stage46.STAGE46_ROOT}/protocol.json"
STAGE46_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage46_component_lag_replication_assessment_protocol_gates.json"
)

EXPECTED_CHECKPOINT_SHA256 = {
    (
        "data_agent/uwm/geospatial_kernel_v2/component_discharge_value_support.py"
    ): "7ae1c6358c560db3acd7743bc983e551d67c9d90ae11b48e27b43b9661041cea",
    (
        "data_agent/uwm/geospatial_kernel_v2/public_component_discharge_value_support.py"
    ): "6421089b14d6b82df51225f62058ede76f92b0060bd2fa3aca86230f5afe07e3",
    (
        "scripts/compile_geotransport_stage41_component_discharge_events.py"
    ): "7e4b26113692a3eebb8f0353a7ca96c08ec182d1cccfad21ef64a8b468734190",
    (
        "data_agent/uwm/geospatial_kernel_v2/empirical_lag_support.py"
    ): "43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc",
    (
        "data_agent/uwm/geospatial_kernel_v2/component_lag_replication_assessment.py"
    ): "8370ad5889ec0e39aff8a13492d63fcf50709a1d89a74d18c7674bc38f4104c3",
    STAGE40_LEDGER_PATH: ("d4d8b1b145ddd9f45e6c5d0905d6d5cabbdf99da0414cacaa43f6c0798d70de1"),
    STAGE40_GATES_PATH: ("6d9c78138d635467814a372b2faafb9eb534fd6c8cc66ebe4063e933f5a72dec"),
    STAGE44_PROTOCOL_PATH: ("ee84167cf3b58b6ce1721795286f6539448f9fec5d781cd2212abfc67e47006d"),
    STAGE44_CANDIDATE_PATH: ("8ee23589977a0bf0520da90a4fb062b72f7448ba05fca4cda2ad84da2564f12b"),
    STAGE44_MANIFEST_PATH: ("b98851b30c5c3556eb52daff493546d7832e072beee256d9a6dd82e5c99abe9f"),
    STAGE44_GATES_PATH: ("1481f7426bd0102a2f1661a6de9c903c99d20ef1607d122989ec2f76f7107a49"),
    STAGE45_PROTOCOL_PATH: planner.FROZEN_PROTOCOL_SHA256,
    STAGE45_PLAN_PATH: acquire.FROZEN_PLAN_SHA256,
    STAGE45_GATES_PATH: ("6324d80b982f7364f98af972ac451418fb66ec3a82ac2de5a89e9990735ae4a3"),
    (
        "scripts/acquire_geotransport_stage45_component_lag_replication_targets.py"
    ): "1bab223eb4e85cd12e47ae6d57ecddde28979341721a71c5bf9002d95c75b348",
    STAGE46_PROTOCOL_PATH: ("a5c976927bde7084047e29f6b20ac75806ca41457562f91f2c049bdeca793803"),
    STAGE46_GATES_PATH: ("d4297f065b1b15136db4befe65300fc3705ee292e7d4a964b53d45a83a43de22"),
}


@dataclass(frozen=True)
class ReplicationTargetHour:
    support_start_utc: str
    support_end_utc: str
    sample_times_utc: tuple[str, str]
    sample_values_cfs: tuple[float, float]
    mean_m3s: float
    approval_statuses: tuple[str, str]

    def __post_init__(self) -> None:
        start = _parse_time(self.support_start_utc)
        end = _parse_time(self.support_end_utc)
        times = tuple(_parse_time(value) for value in self.sample_times_utc)
        if (
            end - start != timedelta(hours=1)
            or times != (end - timedelta(minutes=30), end)
            or any(not math.isfinite(value) for value in self.sample_values_cfs)
            or not math.isfinite(self.mean_m3s)
            or any(not value for value in self.approval_statuses)
        ):
            raise ValueError("component_lag_replication_target_hour_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "support_start_utc": self.support_start_utc,
            "support_end_utc": self.support_end_utc,
            "sample_times_utc": list(self.sample_times_utc),
            "sample_values_cfs": list(self.sample_values_cfs),
            "mean_m3s": self.mean_m3s,
            "approval_statuses": list(self.approval_statuses),
            "missing_values_filled": False,
        }


@dataclass(frozen=True)
class ReplicationTargetMetadata:
    site_id: str
    raw_sample_count: int
    approval_status_counts: tuple[tuple[str, int], ...]
    qualifier_none_count: int
    non_null_qualifier_count: int

    def __post_init__(self) -> None:
        if (
            self.site_id != "USGS-03424860"
            or self.raw_sample_count <= 0
            or sum(value for _, value in self.approval_status_counts) != self.raw_sample_count
            or self.qualifier_none_count + self.non_null_qualifier_count != self.raw_sample_count
        ):
            raise ValueError("component_lag_replication_target_metadata_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "raw_sample_count": self.raw_sample_count,
            "approval_status_counts": dict(self.approval_status_counts),
            "qualifier_none_count": self.qualifier_none_count,
            "non_null_qualifier_count": self.non_null_qualifier_count,
            "quality_metadata_preserved": True,
            "quality_metadata_is_scientific_approval": False,
        }


@dataclass(frozen=True)
class PublicComponentLagReplicationEventEvidence:
    result: assessment_operator.ComponentLagReplicationEventResult
    step_time_utc: str
    source_start_utc: str
    source_end_utc: str
    source_total_values_m3s: tuple[float, ...]
    source_component_quality_codes: tuple[tuple[str, tuple[int, ...]], ...]
    target_metadata: ReplicationTargetMetadata
    target_hourly: tuple[ReplicationTargetHour, ...]
    source_artifact: dict[str, object]

    def __post_init__(self) -> None:
        components = tuple(value[0] for value in self.source_component_quality_codes)
        if (
            len(self.source_total_values_m3s) != EVENT_HOURS
            or any(
                not math.isfinite(value) or value < 0.0 for value in self.source_total_values_m3s
            )
            or components != component_support.catalog.EXPECTED_COMPONENTS
            or any(len(value[1]) != EVENT_HOURS for value in self.source_component_quality_codes)
            or len(self.target_hourly) > TARGET_HOURS
            or tuple(value.lag_hours for value in self.result.lag_support.candidates)
            != lag_operator.LAG_CANDIDATES_HOURS
            or str(self.source_artifact.get("event_id")) != self.result.event_id
        ):
            raise ValueError("public_component_lag_replication_event_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            **self.result.as_dict(),
            "role": "confirmatory_component_total_lag_replication_event",
            "selected_without_target_values": True,
            "assessment_operator_frozen_before_target_values": True,
            "step_time_utc": self.step_time_utc,
            "source_start_utc": self.source_start_utc,
            "source_end_utc": self.source_end_utc,
            "source_total_values_m3s": list(self.source_total_values_m3s),
            "source_component_quality_codes": {
                component: list(values) for component, values in self.source_component_quality_codes
            },
            "source_quality_codes_are_scientific_approval": False,
            "target_metadata": self.target_metadata.as_dict(),
            "target_complete_hour_count": len(self.target_hourly),
            "target_missing_hour_count": TARGET_HOURS - len(self.target_hourly),
            "target_hourly": [value.as_dict() for value in self.target_hourly],
            "source_artifact": self.source_artifact,
        }


@dataclass(frozen=True)
class PublicComponentLagReplicationEvidenceLedger:
    checkpoint_artifacts: dict[str, dict[str, object]]
    acquisition_manifest_artifact: dict[str, object]
    acquisition_state_artifact: dict[str, object]
    source_artifacts: tuple[dict[str, object], ...]
    events: tuple[PublicComponentLagReplicationEventEvidence, ...]
    assessment: assessment_operator.ComponentLagReplicationAssessment
    actual_attempt_count: int
    actual_download_bytes: int
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            {path: value["sha256"] for path, value in self.checkpoint_artifacts.items()}
            != EXPECTED_CHECKPOINT_SHA256
            or len(self.source_artifacts) != 4
            or tuple(value.result for value in self.events) != self.assessment.events
            or tuple(value.result.event_id for value in self.events) != stage45.EXPECTED_EVENT_IDS
            or not 4 <= self.actual_attempt_count <= 12
            or not 0 < self.actual_download_bytes <= planner.MAXIMUM_PERSISTED_DOWNLOAD_BYTES
        ):
            raise ValueError("public_component_lag_replication_ledger_invalid")

    @property
    def status(self) -> str:
        if self.assessment.cohort_replication_admitted:
            return "stage47_component_lag_replication_scoped_cohort_admitted"
        return "stage47_component_lag_replication_rejected"

    def as_dict(self) -> dict[str, object]:
        assessment = self.assessment.as_dict()
        return {
            "schema": SCHEMA,
            "status": self.status,
            "checkpoint_artifacts": self.checkpoint_artifacts,
            "acquisition_manifest_artifact": self.acquisition_manifest_artifact,
            "acquisition_state_artifact": self.acquisition_state_artifact,
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "acquisition_summary": {
                "logical_request_count": 4,
                "actual_attempt_count": self.actual_attempt_count,
                "actual_download_bytes": self.actual_download_bytes,
                "unexpected_pagination_observed": False,
            },
            "events": [value.as_dict() for value in self.events],
            "assessment": assessment,
            "decision": assessment["decision"],
            "claim_boundary": {
                "stage44_events_frozen_before_target_values": True,
                "stage45_plan_manifest_state_and_raw_hashes_bound": True,
                "stage46_assessment_operator_frozen_before_target_values": True,
                "source_total_is_exact_sum_of_four_synchronized_components": True,
                "source_quality_codes_are_scientific_approval": False,
                "target_quality_metadata_is_scientific_approval": False,
                "target_gaps_preserved_without_filling_or_time_shift": True,
                "support_membership_not_exact_best_lag_equality": True,
                "admitted_scope_on_pass": (
                    "center_hill_component_total_flow_class_cohort_replication_only"
                ),
                "universal_lag_admitted": False,
                "stage30_historical_falsification_overturned": False,
                "non_turbine_component_contrast_admitted": False,
                "causal_or_physical_relation_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_component_lag_replication_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicComponentLagReplicationEvidenceLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    if source != root / STAGE45_ROOT:
        raise ValueError("stage47_source_root_must_match_stage45")
    state_path = source / acquire.STATE_NAME
    manifest_path = source / acquire.MANIFEST_NAME
    if not state_path.is_file() or not manifest_path.is_file():
        raise ValueError("stage47_stage45_target_checkpoint_missing")
    checkpoint_artifacts = {
        path: _artifact(root / path, root) for path in EXPECTED_CHECKPOINT_SHA256
    }
    if {
        path: value["sha256"] for path, value in checkpoint_artifacts.items()
    } != EXPECTED_CHECKPOINT_SHA256:
        raise ValueError("stage47_checkpoint_artifact_drift")

    stage40_evidence.compile_public_component_discharge_value_support()
    stage44_manifest = _read_json(root / STAGE44_MANIFEST_PATH)
    stage45_protocol = _read_json(source / "protocol.json")
    stage45_plan = _read_json(source / "target_acquisition_plan.json")
    stage46_protocol = _read_json(root / STAGE46_PROTOCOL_PATH)
    state = _read_json(state_path)
    manifest = _read_json(manifest_path)
    if (
        stage45_protocol != stage45.build_protocol()
        or stage45_plan != planner.compile_plan()
        or stage46_protocol != stage46.build_protocol()
    ):
        raise ValueError("stage47_frozen_protocol_or_plan_invalid")
    source_artifacts, payload_by_source = _validate_stage45_checkpoint(
        plan=stage45_plan,
        state=state,
        manifest=manifest,
        source=source,
        root=root,
    )
    values_by_component = _component_values()
    by_source = {str(value["source_id"]): value for value in source_artifacts}
    events = tuple(
        compile_replication_event_evidence(
            event,
            source_record=by_source[str(request["source_id"])],
            request_source=request,
            target_payload=payload_by_source[str(request["source_id"])],
            source_rows=_source_rows(
                values_by_component,
                _parse_time(str(event["start_utc"])),
            ),
        )
        for event, request in zip(
            stage44_manifest["selected_events"],
            stage45_plan["sources"],
            strict=True,
        )
    )
    assessment = assessment_operator.compile_component_lag_replication_assessment(
        tuple(value.result for value in events)
    )
    acquisition_manifest_artifact = _artifact(manifest_path, root)
    acquisition_state_artifact = _artifact(state_path, root)
    digest = hashlib.sha256(
        "|".join(
            str(value["sha256"])
            for value in (
                *checkpoint_artifacts.values(),
                acquisition_state_artifact,
                acquisition_manifest_artifact,
                *source_artifacts,
            )
        ).encode("ascii")
    ).hexdigest()
    return PublicComponentLagReplicationEvidenceLedger(
        checkpoint_artifacts,
        acquisition_manifest_artifact,
        acquisition_state_artifact,
        source_artifacts,
        events,
        assessment,
        int(manifest["actual_attempt_count"]),
        int(manifest["actual_download_bytes"]),
        f"center-hill-component-lag-replication:{digest}",
    )


def compile_replication_event_evidence(
    event: dict[str, object],
    *,
    source_record: dict[str, object],
    request_source: dict[str, object],
    target_payload: dict[str, Any],
    source_rows: tuple[tuple[float, dict[str, int]], ...],
) -> PublicComponentLagReplicationEventEvidence:
    start = _parse_time(str(event["start_utc"]))
    source_end = _parse_time(str(event["end_utc"]))
    if (
        str(event["event_id"]) != request_source.get("event_id")
        or int(event["selection_rank"]) != request_source.get("selection_rank")
        or str(event["selection_stratum"]) != request_source.get("selection_stratum")
        or str(event["antecedent_flow_class"]) != request_source.get("antecedent_flow_class")
        or str(event["start_utc"]) != request_source.get("begin_utc")
        or source_end - start != timedelta(hours=EVENT_HOURS)
        or _parse_time(str(request_source["end_utc"])) - start != timedelta(hours=TARGET_HOURS)
        or len(source_rows) != EVENT_HOURS
    ):
        raise ValueError("stage47_event_source_contract_invalid")
    acquire._validate_payload(target_payload, request_source)
    target_hourly = compile_target_hourly(
        target_payload,
        start=start,
        hour_count=TARGET_HOURS,
    )
    source_total = tuple(value[0] for value in source_rows)
    candidates = compile_lag_correlations(
        source_total,
        target_hourly,
        start=start,
    )
    lag_support = lag_operator.compile_empirical_lag_support(candidates)
    result = assessment_operator.ComponentLagReplicationEventResult(
        str(event["event_id"]),
        int(event["selection_rank"]),
        str(event["selection_stratum"]),
        lag_support,
    )
    properties = [value["properties"] for value in target_payload["features"]]
    statuses = Counter(str(value["approval_status"]) for value in properties)
    qualifier_none_count = sum(value.get("qualifiers") is None for value in properties)
    return PublicComponentLagReplicationEventEvidence(
        result,
        str(event["step_time_utc"]),
        _iso(start),
        _iso(source_end),
        source_total,
        tuple(
            (
                component,
                tuple(value[1][component] for value in source_rows),
            )
            for component in component_support.catalog.EXPECTED_COMPONENTS
        ),
        ReplicationTargetMetadata(
            str(request_source["site_id"]),
            len(properties),
            tuple(sorted(statuses.items())),
            qualifier_none_count,
            len(properties) - qualifier_none_count,
        ),
        target_hourly,
        source_record,
    )


def compile_target_hourly(
    payload: dict[str, Any],
    *,
    start: datetime,
    hour_count: int,
) -> tuple[ReplicationTargetHour, ...]:
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
        sample_times = (
            support_end - timedelta(minutes=30),
            support_end,
        )
        if any(value not in samples for value in sample_times):
            continue
        first, second = (samples[value] for value in sample_times)
        values_cfs = (first[0], second[0])
        result.append(
            ReplicationTargetHour(
                _iso(support_end - timedelta(hours=1)),
                _iso(support_end),
                tuple(_iso(value) for value in sample_times),
                values_cfs,
                _mean(values_cfs) * CFS_TO_M3S,
                (first[1], second[1]),
            )
        )
    return tuple(result)


def compile_lag_correlations(
    source_total_values_m3s: tuple[float, ...],
    target_hourly: tuple[ReplicationTargetHour, ...],
    *,
    start: datetime,
) -> tuple[lag_operator.LagCorrelationEvidence, ...]:
    if len(source_total_values_m3s) != EVENT_HOURS:
        raise ValueError("stage47_seventy_two_source_values_required")
    target_by_end = {_parse_time(value.support_end_utc): value.mean_m3s for value in target_hourly}
    result = []
    for lag in lag_operator.LAG_CANDIDATES_HOURS:
        pairs = tuple(
            (source_value, target_by_end[target_end])
            for index, source_value in enumerate(source_total_values_m3s, start=1)
            if (target_end := start + timedelta(hours=index + lag)) in target_by_end
        )
        pearson = _pearson(pairs)
        result.append(lag_operator.LagCorrelationEvidence(lag, len(pairs), pearson))
    return tuple(result)


def _validate_stage45_checkpoint(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    manifest: dict[str, Any],
    source: Path,
    root: Path,
) -> tuple[tuple[dict[str, object], ...], dict[str, dict[str, Any]]]:
    plan_artifact = _artifact(source / "target_acquisition_plan.json", root)
    state_artifact = _artifact(source / acquire.STATE_NAME, root)
    claims = manifest.get("claim_boundary") or {}
    plan_sources = plan["sources"]
    attempts = manifest.get("actual_attempt_count")
    downloaded = manifest.get("actual_download_bytes")
    if (
        manifest.get("schema") != acquire.SCHEMA
        or manifest.get("status") != "stage45_replication_target_values_acquired_assessment_pending"
        or manifest.get("frozen_target_acquisition_plan") != plan_artifact
        or manifest.get("acquisition_state_artifact") != state_artifact
        or manifest.get("actual_request_count") != 4
        or not isinstance(attempts, int)
        or not 4 <= attempts <= 12
        or not isinstance(downloaded, int)
        or not 0 < downloaded <= planner.MAXIMUM_PERSISTED_DOWNLOAD_BYTES
        or manifest.get("artifact_count") != 4
        or manifest.get("request_boundary") != plan["request_boundary"]
        or claims.get("stage44_events_hypothesis_and_target_operator_frozen_before_values")
        is not True
        or claims.get("downstream_replication_target_values_acquired") is not True
        or claims.get("target_coverage_compiled") is not False
        or claims.get("replication_test_executed") is not False
        or state.get("schema") != acquire.STATE_SCHEMA
        or state.get("frozen_plan_sha256") != acquire.FROZEN_PLAN_SHA256
    ):
        raise ValueError("stage47_stage45_checkpoint_invalid")
    records = manifest.get("artifacts")
    state_records = state.get("sources")
    if (
        not isinstance(records, list)
        or [value.get("source_id") for value in records]
        != [value["source_id"] for value in plan_sources]
        or not isinstance(state_records, dict)
        or list(state_records) != [value["source_id"] for value in plan_sources]
    ):
        raise ValueError("stage47_stage45_source_order_invalid")

    artifacts = []
    payload_by_source = {}
    for request_source, record in zip(plan_sources, records, strict=True):
        source_id = str(request_source["source_id"])
        state_record = state_records[source_id]
        raw_path = source / str(request_source["output_name"])
        if not raw_path.is_file():
            raise ValueError("stage47_stage45_raw_artifact_missing")
        artifact = _artifact(raw_path, root)
        attempt_count = record.get("attempt_count")
        if (
            record.get("path") != artifact["path"]
            or record.get("sha256") != artifact["sha256"]
            or record.get("size_bytes") != artifact["size_bytes"]
            or record.get("source_id") != source_id
            or record.get("event_id") != request_source["event_id"]
            or record.get("selection_rank") != request_source["selection_rank"]
            or record.get("selection_stratum") != request_source["selection_stratum"]
            or record.get("site_id") != request_source["site_id"]
            or record.get("parameter_code") != request_source["parameter_code"]
            or record.get("begin_utc") != request_source["begin_utc"]
            or record.get("end_utc") != request_source["end_utc"]
            or record.get("role") != request_source["role"]
            or record.get("url") != request_source["url"]
            or record.get("hash_verified") is not True
            or record.get("tls_hostname_verification_retained") is not True
            or record.get("http_status") != 200
            or not isinstance(attempt_count, int)
            or not 1 <= attempt_count <= planner.MAXIMUM_ATTEMPTS_PER_REQUEST
            or not isinstance(record.get("failed_attempts"), list)
            or len(record["failed_attempts"]) != attempt_count - 1
            or state_record.get("attempt_count") != attempt_count
            or state_record.get("failed_attempts") != record["failed_attempts"]
            or state_record.get("success") is not True
            or state_record.get("sha256") != artifact["sha256"]
            or state_record.get("size_bytes") != artifact["size_bytes"]
        ):
            raise ValueError("stage47_stage45_raw_artifact_invalid")
        payload = _read_json(raw_path)
        acquire._validate_payload(payload, request_source)
        artifacts.append(dict(record))
        payload_by_source[source_id] = payload
    if (
        sum(int(value["attempt_count"]) for value in artifacts) != attempts
        or sum(int(value["size_bytes"]) for value in artifacts) != downloaded
    ):
        raise ValueError("stage47_stage45_acquisition_totals_invalid")
    return tuple(artifacts), payload_by_source


def _component_values() -> dict[str, dict[datetime, tuple[float | None, int]]]:
    payloads = compile_stage41._payloads()
    return {
        component: component_support._compile_component(
            component,
            payloads[component],
        )[1]
        for component in component_support.catalog.EXPECTED_COMPONENTS
    }


def _source_rows(
    values_by_component: dict[str, dict[datetime, tuple[float | None, int]]],
    start: datetime,
) -> tuple[tuple[float, dict[str, int]], ...]:
    result = []
    for index in range(1, EVENT_HOURS + 1):
        timestamp = start + timedelta(hours=index)
        total = 0.0
        qualities = {}
        for component in component_support.catalog.EXPECTED_COMPONENTS:
            row = values_by_component[component].get(timestamp)
            if (
                row is None
                or row[0] is None
                or not math.isfinite(float(row[0]))
                or float(row[0]) < 0.0
            ):
                raise ValueError("stage47_source_component_support_invalid")
            total += float(row[0])
            qualities[component] = int(row[1])
        result.append((total, qualities))
    return tuple(result)


def _pearson(pairs: tuple[tuple[float, float], ...]) -> float | None:
    if not pairs:
        return None
    left = tuple(value[0] for value in pairs)
    right = tuple(value[1] for value in pairs)
    left_mean = _mean(left)
    right_mean = _mean(right)
    left_std = math.sqrt(_mean(tuple((value - left_mean) ** 2 for value in left)))
    right_std = math.sqrt(_mean(tuple((value - right_mean) ** 2 for value in right)))
    if left_std == 0.0 or right_std == 0.0:
        return None
    return sum(
        (left_value - left_mean) * (right_value - right_mean) for left_value, right_value in pairs
    ) / (len(pairs) * left_std * right_std)


def _mean(values: tuple[float, ...]) -> float:
    if not values:
        raise ValueError("stage47_nonempty_values_required")
    return sum(values) / len(values)


def _artifact(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("stage47_artifact_outside_repo") from exc
    body = resolved.read_bytes()
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage47_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage47_timezone_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
