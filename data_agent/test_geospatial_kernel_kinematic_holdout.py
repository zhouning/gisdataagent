from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

import numpy as np

from scripts.acquire_geotransport_kinematic_wave_holdout_v1_inputs import (
    compile_plan,
)
from scripts.freeze_geotransport_kinematic_wave_holdout_v1 import (
    CORE_CODE_PATHS,
    compile_protocol,
)
from scripts.run_geotransport_kinematic_wave_holdout_v1_outcome_free import (
    _seal_payload,
)
from scripts.score_geotransport_kinematic_wave_holdout_v1 import _score_system
from scripts.acquire_geotransport_kinematic_wave_holdout_v2_inputs import (
    compile_plan as compile_v2_plan,
)
from scripts.freeze_geotransport_kinematic_wave_holdout_v2 import (
    DEFAULT_OUTPUT as V2_PROTOCOL_PATH,
    compile_protocol as compile_v2_protocol,
)
from scripts.run_geotransport_kinematic_wave_holdout_v2_outcome_free import (
    _TwoUlpNumpyProxy,
)


def test_kinematic_holdout_protocol_and_input_plan_are_outcome_free(
    tmp_path,
) -> None:
    protocol = compile_protocol()
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    plan, systems, _ = compile_plan(protocol_path=protocol_path)

    assert protocol["window"]["hour_count"] == 672
    assert set(protocol["frozen_code"]) == set(CORE_CODE_PATHS)
    assert protocol["operator_lock"]["operator_form_admitted_before_holdout"] is False
    assert protocol["scoring_lock"]["native_cadence_rule"].endswith("(t-1h,t]")
    assert plan["nwm_unique_object_count"] == 6
    assert plan["action_request_count"] == 2
    assert plan["data_isolation"] == {
        "outcome_url_requested": False,
        "outcome_path_accepted": False,
        "outcome_values_loaded": False,
        "outcome_artifacts_present": False,
    }
    assert {(row["variable"], row["chunk_key"]) for row in plan["nwm_requests"]} == {
        ("q_lateral", "570.63"),
        ("q_lateral", "570.87"),
        ("streamflow", "569.63"),
        ("streamflow", "569.87"),
        ("time", "569"),
        ("time", "570"),
    }
    assert all("usgs" not in row["url"].lower() for row in plan["nwm_requests"])
    assert all(row["variable"] != "velocity" for row in plan["nwm_requests"])
    assert len(systems["center_hill"]["feature_ids"]) == 435
    assert len(systems["j_percy_priest"]["feature_ids"]) == 43


def test_kinematic_holdout_joint_seal_commits_to_both_predictions() -> None:
    predictions = {
        "center_hill": {"path": "center.csv", "sha256": "a", "size_bytes": 1},
        "j_percy_priest": {
            "path": "jpp.csv",
            "sha256": "b",
            "size_bytes": 2,
        },
    }
    original = _seal_payload(
        protocol_sha256="protocol",
        input_report_sha256="inputs",
        predictions=predictions,
    )
    changed = _seal_payload(
        protocol_sha256="protocol",
        input_report_sha256="inputs",
        predictions={
            **predictions,
            "j_percy_priest": {
                **predictions["j_percy_priest"],
                "sha256": "changed",
            },
        },
    )

    assert original == _seal_payload(
        protocol_sha256="protocol",
        input_report_sha256="inputs",
        predictions=predictions,
    )
    assert hashlib.sha256(original).digest() != hashlib.sha256(changed).digest()


def test_kinematic_holdout_primary_gate_is_noncompensatory_persistence_test() -> None:
    rows = []
    observations = {}
    start = datetime(2022, 10, 13, 1, tzinfo=timezone.utc)
    for index in range(673):
        timestamp = (start + timedelta(hours=index)).isoformat().replace(
            "+00:00", "Z"
        )
        observations[timestamp] = float(index + 10)
        if index < 672:
            next_timestamp = (start + timedelta(hours=index + 1)).isoformat().replace(
                "+00:00", "Z"
            )
            rows.append(
                {
                    "support_start_utc": timestamp,
                    "support_end_utc": next_timestamp,
                    "kinematic_wave_m3s": str(index + 11),
                    "branch_silent_negative_control_m3s": str(index + 9),
                    "action_input_m3s": str(index + 8),
                }
            )

    score = _score_system(
        system_id="synthetic",
        prediction_rows=rows,
        observations=observations,
        rollout_system={"invariants": {"all_execution_gates_passed": True}},
        protocol={"scoring_lock": {"minimum_scored_hours_per_system": 600}},
        outcome_system={
            "quality": {
                "native_sample_cadence_seconds": 900,
                "native_cadence_predeclared": True,
                "expected_native_samples_per_complete_hour": 4,
            }
        },
    )

    assert score["scored_hour_count"] == 672
    assert score["gates"]["kinematic_beats_observed_persistence_rmse"] is True
    assert score["gates"]["all_predictive_and_execution_gates_passed"] is True


def test_kinematic_holdout_v2_moves_to_unseen_chunks_and_remains_outcome_free(
    tmp_path,
) -> None:
    if V2_PROTOCOL_PATH.exists():
        protocol = json.loads(V2_PROTOCOL_PATH.read_text(encoding="utf-8"))
        plan = json.loads(
            (V2_PROTOCOL_PATH.parent / "kinematic_wave_holdout_v2_inputs_plan.json")
            .read_text(encoding="utf-8")
        )
    else:
        protocol = compile_v2_protocol()
        protocol_path = tmp_path / "v2-protocol.json"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        plan, _, _ = compile_v2_plan(protocol_path=protocol_path)

    assert protocol["window"] == {
        "initial_state_valid_at": "2022-11-10T00:00:00Z",
        "start_inclusive": "2022-11-10T01:00:00Z",
        "end_exclusive": "2022-12-08T01:00:00Z",
        "hour_count": 672,
        "time_step": "PT1H",
        "initial_state_time_chunk_index": 570,
        "forcing_time_chunk_index": 571,
    }
    assert {(row["variable"], row["chunk_key"]) for row in plan["nwm_requests"]} == {
        ("q_lateral", "571.63"),
        ("q_lateral", "571.87"),
        ("streamflow", "570.63"),
        ("streamflow", "570.87"),
        ("time", "570"),
        ("time", "571"),
    }
    assert plan["data_isolation"]["outcome_url_requested"] is False
    assert protocol["protocol_lineage"]["v2_dynamic_inputs_requested_before_freeze"] is False


def test_kinematic_holdout_v2_numpy_proxy_changes_only_nextafter_count() -> None:
    proxy = _TwoUlpNumpyProxy(np)
    one_ulp = np.nextafter(np.float64(0.8), np.inf)
    two_ulps = np.nextafter(one_ulp, np.inf)

    assert proxy.nextafter(np.float64(0.8), np.inf) == two_ulps
    assert np.array_equal(proxy.zeros(3), np.zeros(3))
    assert proxy.asarray([1.0, 2.0]).tolist() == [1.0, 2.0]
