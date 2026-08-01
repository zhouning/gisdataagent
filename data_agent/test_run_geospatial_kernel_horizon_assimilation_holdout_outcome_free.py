import inspect
import json
from datetime import timedelta

import pytest

from scripts import (
    freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze,
)
from scripts import run_geospatial_kernel_horizon_assimilation_holdout_outcome_free as run


@pytest.fixture(scope="module")
def prepared():
    return run.prepare_execution()


@pytest.fixture(scope="module")
def offline_first_issue(prepared):
    preparation, contexts = prepared
    observations = {
        system_id: {
            "value_m3s": None,
            "exact_issue_timestamp_found": False,
            "fallback_reason": "offline_test_missing_observation",
            "qualifiers": [],
        }
        for system_id in freeze.SYSTEM_IDS
    }
    return run.execute_joint_issue(
        issue_index=0,
        issue_time=freeze.START,
        policy=preparation["policy"],
        contexts=contexts,
        observations=observations,
    )


def test_prepare_execution_binds_static_inputs_and_issue_order(prepared) -> None:
    preparation, contexts = prepared

    assert tuple(contexts) == freeze.SYSTEM_IDS
    assert len(contexts["center_hill"]["feature_ids"]) == 435
    assert len(contexts["j_percy_priest"]["feature_ids"]) == 43
    assert preparation["policy"].admitted is False
    assert preparation["policy"].runtime_default_enabled is False
    for context in contexts.values():
        assert tuple(context["request_by_issue"]) == tuple(
            preparation["protocol"]["window"]["issue_times_utc"]
        )


def test_offline_joint_issue_executes_all_modes_and_advances_nominal_state(
    offline_first_issue,
) -> None:
    systems, next_states = offline_first_issue

    for system_id in freeze.SYSTEM_IDS:
        system = systems[system_id]
        rollout = system["rollout"]
        assert [value["mode"] for value in rollout["mode_rollouts"]] == [
            "nominal",
            "outlet_only_observation_update",
            "linear_distance_localized_mainstem_update",
            "quadratic_distance_localized_mainstem_update",
        ]
        assert rollout["execution_gates"] == {
            "all_analysis_ledgers_passed": True,
            "all_physical_mass_balances_passed": True,
            "localized_updates_preserved_all_branch_states": True,
        }
        assert system["nominal_canonical_conformance"] == {
            "maximum_absolute_error_m3s": 0.0,
            "absolute_tolerance_m3s": 1e-12,
            "passed": True,
        }
        assert len(next_states[system_id].values) == {
            "center_hill": 435,
            "j_percy_priest": 43,
        }[system_id]


def test_runner_accepts_no_target_outcome_or_score_arguments() -> None:
    parameters = set(inspect.signature(run.run_chronological_holdout).parameters)
    issue_parameters = set(inspect.signature(run.execute_joint_issue).parameters)

    forbidden = {"target", "outcome", "score", "loss", "full_outcome"}
    assert not parameters.intersection(forbidden)
    assert not issue_parameters.intersection(forbidden)


def test_exact_approved_usgs_sample_is_converted_without_time_shift() -> None:
    payload = _usgs_payload(
        issue_time=freeze.START,
        value="1000",
        qualifiers=["A"],
    )

    parsed = run._parse_exact_issue_observation(
        payload,
        site_id="03424860",
        issue_time=freeze.START,
    )

    assert parsed["value_m3s"] == pytest.approx(28.316846592)
    assert parsed["raw_value_ft3s"] == 1000.0
    assert parsed["exact_issue_timestamp_found"] is True
    assert parsed["fallback_reason"] is None
    assert parsed["historical_publication_at_issue_time_verified"] is False


def test_usgs_parser_never_substitutes_nearby_or_unapproved_sample() -> None:
    nearby = _usgs_payload(
        issue_time=freeze.START - timedelta(minutes=5),
        value="900",
        qualifiers=["A"],
    )
    unapproved = _usgs_payload(
        issue_time=freeze.START,
        value="900",
        qualifiers=["P"],
    )

    nearby_result = run._parse_exact_issue_observation(
        nearby,
        site_id="03424860",
        issue_time=freeze.START,
    )
    unapproved_result = run._parse_exact_issue_observation(
        unapproved,
        site_id="03424860",
        issue_time=freeze.START,
    )

    assert nearby_result["value_m3s"] is None
    assert nearby_result["fallback_reason"] == "exact_issue_timestamp_missing"
    assert unapproved_result["value_m3s"] is None
    assert unapproved_result["fallback_reason"] == "issue_observation_not_approved"


def test_negative_approved_value_is_preserved_for_core_refusal() -> None:
    payload = _usgs_payload(
        issue_time=freeze.START,
        value="-10",
        qualifiers=["A"],
        site_id="03430200",
    )

    parsed = run._parse_exact_issue_observation(
        payload,
        site_id="03430200",
        issue_time=freeze.START,
    )

    assert parsed["value_m3s"] == pytest.approx(-0.28316846592)
    assert parsed["fallback_reason"] is None


def test_prepare_execution_rejects_tampered_static_claim(tmp_path) -> None:
    payload = json.loads(run.DEFAULT_STATIC_REPORT.read_bytes())
    payload["claim_boundary"]["issue_observations_acquired"] = True
    path = tmp_path / "tampered-static-report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="horizon_holdout_rollout_static_report_invalid"):
        run.prepare_execution(static_report_path=path)


def _usgs_payload(
    *,
    issue_time,
    value: str,
    qualifiers: list[str],
    site_id: str = "03424860",
) -> dict:
    return {
        "value": {
            "timeSeries": [
                {
                    "sourceInfo": {"siteCode": [{"value": site_id}]},
                    "variable": {
                        "variableCode": [{"value": "00060"}],
                        "unit": {"unitCode": "ft3/s"},
                        "noDataValue": -999999.0,
                    },
                    "values": [
                        {
                            "value": [
                                {
                                    "dateTime": run._iso(issue_time),
                                    "value": value,
                                    "qualifiers": qualifiers,
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    }
