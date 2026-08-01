import copy
import inspect
import json
from datetime import UTC, datetime

import pytest

from scripts import (
    acquire_geospatial_kernel_horizon_assimilation_holdout_static_inputs as acquire,
)
from scripts import (
    freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze,
)
from scripts import (
    plan_geospatial_kernel_horizon_assimilation_holdout_inputs as frozen_plan,
)


def test_static_plan_recomputes_exact_frozen_nwm_and_action_requests() -> None:
    report, systems, _ = acquire.compile_static_plan()

    assert report["status"] == (
        "static_inputs_ready_to_acquire_issue_observations_deferred"
    )
    assert report["request_execution"] == {
        "frozen_total_request_count": 122,
        "static_request_count": 10,
        "nwm_request_count": 8,
        "cwms_request_count": 2,
        "usgs_issue_request_count_executed": 0,
        "usgs_issue_request_count_deferred": 112,
        "bulk_issue_observation_prefetch_permitted": False,
    }
    assert tuple(systems) == freeze.SYSTEM_IDS
    assert {(value["variable"], value["chunk_key"]) for value in report["nwm_requests"]} == {
        ("streamflow", "563.63"),
        ("streamflow", "563.87"),
        ("velocity", "563.63"),
        ("velocity", "563.87"),
        ("q_lateral", "564.63"),
        ("q_lateral", "564.87"),
        ("time", "563"),
        ("time", "564"),
    }
    for request in report["nwm_requests"]:
        assert request["url"].startswith(
            "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
        )
        assert int(request["maximum_bytes"]) > 0
    for system_id, system in report["systems"].items():
        assert system["action_url"].startswith(
            "https://cwms-data.usace.army.mil/"
        )
        assert system["feature_chunk_indices"] == list(
            systems[system_id]["feature_chunks"]
        )


def test_static_acquirer_has_no_issue_observation_or_score_input() -> None:
    parameters = set(inspect.signature(acquire.acquire_static_inputs).parameters)
    report, _, _ = acquire.compile_static_plan()

    assert not parameters.intersection(
        {"issue_observation", "usgs", "target", "outcome", "score", "loss"}
    )
    assert report["data_isolation"] == {
        "usgs_url_requested": False,
        "issue_observation_loaded": False,
        "future_target_loaded": False,
        "score_or_loss_loaded": False,
    }
    assert report["claim_boundary"]["candidate_promoted"] is False
    assert report["claim_boundary"]["runtime_default_enabled"] is False


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("request_counts", "nwm_unique_object_count", 9),
        (
            "issue_observation_request_contract",
            "bulk_prefetch_all_issue_observation_values_permitted",
            True,
        ),
    ],
)
def test_static_plan_rejects_tampered_frozen_request_plan(
    tmp_path,
    section: str,
    field: str,
    value: object,
) -> None:
    payload = json.loads(frozen_plan.DEFAULT_OUTPUT.read_bytes())
    payload[section][field] = value
    path = tmp_path / "tampered-input-plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="horizon_holdout_static_frozen_plan_invalid"):
        acquire.compile_static_plan(frozen_plan_path=path)


def test_static_plan_rejects_nwm_url_substitution(tmp_path) -> None:
    payload = json.loads(frozen_plan.DEFAULT_OUTPUT.read_bytes())
    payload["nwm_requests"][0]["url"] = "https://example.invalid/substituted"
    path = tmp_path / "substituted-input-plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="horizon_holdout_static_frozen_plan_invalid"):
        acquire.compile_static_plan(frozen_plan_path=path)


def test_static_plan_rejects_protocol_claim_promotion(tmp_path) -> None:
    payload = copy.deepcopy(json.loads(freeze.DEFAULT_OUTPUT.read_bytes()))
    payload["claim_boundary"]["candidate_promoted"] = True
    path = tmp_path / "promoted-protocol.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="horizon_holdout_input_plan_protocol_invalid"):
        acquire.compile_static_plan(protocol_path=path)


def test_static_plan_generated_at_is_not_scientific_input() -> None:
    first, _, _ = acquire.compile_static_plan()
    second, _, _ = acquire.compile_static_plan()

    first["generated_at"] = datetime(2026, 8, 1, 0, tzinfo=UTC).isoformat()
    second["generated_at"] = first["generated_at"]
    assert first == second
