from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    component_lag_replication_assessment as assessment,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_component_lag_replication_evidence as evidence,
)
from scripts import assess_geotransport_stage47_component_lag_replication as runner


def _events_and_sources():
    manifest = evidence._read_json(evidence.REPO_ROOT / evidence.STAGE44_MANIFEST_PATH)
    plan = evidence.planner.compile_plan()
    return manifest["selected_events"], plan["sources"]


def _release_values() -> tuple[float, ...]:
    return tuple(
        20.0 + ((index * 37) % 101) + ((index * index * 13) % 29) / 10.0 for index in range(72)
    )


def _source_rows() -> tuple[tuple[float, dict[str, int]], ...]:
    return tuple(
        (
            value,
            {component: 0 for component in evidence.component_support.catalog.EXPECTED_COMPONENTS},
        )
        for value in _release_values()
    )


def _payload(
    source: dict[str, object],
    lag: int,
    *,
    missing_hours: tuple[int, ...] = (),
) -> dict[str, object]:
    releases = _release_values()
    start = evidence._parse_time(str(source["begin_utc"]))
    hourly = []
    for hour in range(1, 85):
        source_index = hour - lag
        if 1 <= source_index <= len(releases):
            value_m3s = releases[source_index - 1]
        else:
            value_m3s = 5.0 + ((hour * 19) % 47)
        hourly.append(value_m3s)
    features = []
    for position in range(169):
        timestamp = start + timedelta(minutes=30 * position)
        if position == 0:
            value_m3s = hourly[0]
            hour = 0
        else:
            hour = (position + 1) // 2
            value_m3s = hourly[hour - 1]
        if hour in missing_hours:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "time": evidence._iso(timestamp),
                    "value": value_m3s / evidence.CFS_TO_M3S,
                    "monitoring_location_id": source["site_id"],
                    "parameter_code": source["parameter_code"],
                    "statistic_id": "00011",
                    "unit_of_measure": "ft^3/s",
                    "approval_status": "Approved",
                    "qualifiers": None,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "numberReturned": len(features),
        "features": features,
        "links": [],
    }


def _compile_event(index: int, lag: int, *, missing_hours: tuple[int, ...] = ()):
    events, sources = _events_and_sources()
    event = events[index]
    source = sources[index]
    return evidence.compile_replication_event_evidence(
        event,
        source_record={"event_id": event["event_id"]},
        request_source=source,
        target_payload=_payload(source, lag, missing_hours=missing_hours),
        source_rows=_source_rows(),
    )


def test_stage47_synthetic_four_event_cohort_passes_support_membership():
    events = tuple(_compile_event(index, lag) for index, lag in enumerate((5, 5, 6, 6)))
    result = assessment.compile_component_lag_replication_assessment(
        tuple(value.result for value in events)
    )

    assert [value.result.lag_support.best_lag_hours for value in events] == [
        5,
        5,
        6,
        6,
    ]
    assert result.cohort_replication_admitted is True


def test_stage47_missing_target_hour_reduces_pairs_without_shifting_time_axis():
    event = _compile_event(0, 5, missing_hours=(10,))
    support = event.result.lag_support

    assert len(event.target_hourly) == 83
    assert event.as_dict()["target_missing_hour_count"] == 1
    assert support.best_lag_hours == 5
    assert support.candidates[5].pair_count == 71
    assert event.result.replication_passed is True


def test_stage47_rejects_detectable_shape_below_sixty_pairs():
    event = _compile_event(0, 5, missing_hours=tuple(range(6, 19)))
    support = event.result.lag_support

    assert support.best_lag_hours == 5
    assert support.candidates[5].pair_count == 59
    assert support.response_detectable is False
    assert support.response_rejection_reasons == ("best_lag_pair_count_below_60",)
    assert event.result.replication_passed is False


def test_stage47_one_wrong_direction_rejects_the_whole_cohort():
    events = tuple(_compile_event(index, lag) for index, lag in enumerate((5, 4, 6, 6)))
    result = assessment.compile_component_lag_replication_assessment(
        tuple(value.result for value in events)
    )

    assert result.high_flow_bidirectional_replication_passed is False
    assert result.low_flow_bidirectional_replication_passed is True
    assert result.cohort_replication_admitted is False
    assert result.failed_strata == ("high_decrease",)


def test_stage47_checkpoint_validator_binds_four_raw_hashes(tmp_path):
    plan, state, manifest, source = _checkpoint_fixture(tmp_path)

    artifacts, payloads = evidence._validate_stage45_checkpoint(
        plan=plan,
        state=state,
        manifest=manifest,
        source=source,
        root=tmp_path,
    )

    assert len(artifacts) == 4
    assert set(payloads) == {value["source_id"] for value in plan["sources"]}


def test_stage47_checkpoint_validator_rejects_raw_byte_drift(tmp_path):
    plan, state, manifest, source = _checkpoint_fixture(tmp_path)
    raw_path = source / str(plan["sources"][0]["output_name"])
    raw_path.write_bytes(raw_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="raw_artifact_invalid"):
        evidence._validate_stage45_checkpoint(
            plan=plan,
            state=state,
            manifest=manifest,
            source=source,
            root=tmp_path,
        )


def test_stage47_checkpoint_validator_rejects_missing_raw_file(tmp_path):
    plan, state, manifest, source = _checkpoint_fixture(tmp_path)
    raw_path = source / str(plan["sources"][0]["output_name"])
    raw_path.unlink()

    with pytest.raises(ValueError, match="raw_artifact_missing"):
        evidence._validate_stage45_checkpoint(
            plan=plan,
            state=state,
            manifest=manifest,
            source=source,
            root=tmp_path,
        )


def test_stage47_default_execution_fails_closed_before_target_checkpoint():
    with pytest.raises(ValueError, match="target_checkpoint_missing"):
        evidence.compile_public_component_lag_replication_evidence()


def test_stage47_runner_requires_explicit_flag_and_frozen_output():
    with pytest.raises(ValueError, match="explicit_frozen_assessment_flag_required"):
        runner._require_execution_flag(False)
    runner._require_execution_flag(True)
    with pytest.raises(ValueError, match="output_must_match_frozen_root"):
        runner._validate_output(evidence.REPO_ROOT / "data" / "wrong")


def _checkpoint_fixture(tmp_path):
    events, sources = _events_and_sources()
    plan = evidence.planner.compile_plan()
    source = tmp_path / evidence.STAGE45_ROOT
    source.mkdir(parents=True)
    _write_json(source / "target_acquisition_plan.json", plan)
    records = []
    state_records = {}
    for event, request in zip(events, sources, strict=True):
        raw_path = source / str(request["output_name"])
        _write_json(
            raw_path,
            _payload(
                request,
                evidence.assessment_operator.REQUIRED_LAG_BY_FLOW_CLASS[
                    str(request["antecedent_flow_class"])
                ],
            ),
        )
        body = raw_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        relative = raw_path.relative_to(tmp_path).as_posix()
        retrieval = {
            "url": request["url"],
            "final_url": request["url"],
            "transport": "fixture",
            "http_status": 200,
            "content_type": "application/json",
            "tls_hostname_verification_retained": True,
            "retrieved_at": "2026-07-30T00:00:00+00:00",
        }
        state_records[str(request["source_id"])] = {
            "attempt_count": 1,
            "failed_attempts": [],
            "success": True,
            "sha256": digest,
            "size_bytes": len(body),
            "retrieval": retrieval,
        }
        records.append(
            {
                "source_id": request["source_id"],
                "event_id": event["event_id"],
                "selection_rank": request["selection_rank"],
                "selection_stratum": request["selection_stratum"],
                "site_id": request["site_id"],
                "parameter_code": request["parameter_code"],
                "begin_utc": request["begin_utc"],
                "end_utc": request["end_utc"],
                "role": request["role"],
                "path": relative,
                "sha256": digest,
                "size_bytes": len(body),
                "hash_verified": True,
                "attempt_count": 1,
                "failed_attempts": [],
                **retrieval,
            }
        )
    state = {
        "schema": evidence.acquire.STATE_SCHEMA,
        "frozen_plan_sha256": evidence.acquire.FROZEN_PLAN_SHA256,
        "sources": state_records,
    }
    state_path = source / evidence.acquire.STATE_NAME
    _write_json(state_path, state)
    plan_artifact = evidence._artifact(source / "target_acquisition_plan.json", tmp_path)
    state_artifact = evidence._artifact(state_path, tmp_path)
    manifest = {
        "schema": evidence.acquire.SCHEMA,
        "status": "stage45_replication_target_values_acquired_assessment_pending",
        "frozen_target_acquisition_plan": plan_artifact,
        "acquisition_state_artifact": state_artifact,
        "actual_request_count": 4,
        "actual_attempt_count": 4,
        "actual_download_bytes": sum(value["size_bytes"] for value in records),
        "artifact_count": 4,
        "artifacts": records,
        "request_boundary": plan["request_boundary"],
        "claim_boundary": {
            "stage44_events_hypothesis_and_target_operator_frozen_before_values": True,
            "downstream_replication_target_values_acquired": True,
            "target_coverage_compiled": False,
            "replication_test_executed": False,
        },
    }
    return plan, state, manifest, source


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
