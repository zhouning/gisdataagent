import hashlib
import json
from datetime import datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_prospective_verification import (
    action_innovation_prospective_outcomes_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_request import (
    ActionInnovationShadowRequest,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    IssueTimeInputAttestation,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
)
from scripts.build_geospatial_kernel_action_innovation_prospective_outcomes import (
    OBSERVATION_BATCH_SCHEMA,
    compile_prospective_outcomes,
    main,
)
from scripts.run_geospatial_kernel_action_innovation_uncertainty_shadow import (
    compile_uncertainty_shadow_receipt,
)

HORIZONS = (1, 3, 6, 12)
NETWORK_ID = "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"
FROZEN_AT = datetime.fromisoformat(
    json.loads(DEFAULT_UNCERTAINTY_FREEZE_PATH.read_bytes())["frozen_at"]
)
ISSUE = FROZEN_AT + timedelta(hours=1)
NOW = ISSUE + timedelta(hours=13)


def _request() -> ActionInnovationShadowRequest:
    valid_times = tuple(ISSUE + timedelta(hours=index) for index in range(-8, 13))
    return ActionInnovationShadowRequest(
        request_id="center-hill-prospective-observation-intake-0001",
        network_id=NETWORK_ID,
        shadow_only_acknowledged=True,
        issue_time=ISSUE,
        target_valid_times=tuple(ISSUE + timedelta(hours=value) for value in HORIZONS),
        outlet_state=OutletTransitionState(
            valid_at=ISSUE - timedelta(hours=1),
            available_at=ISSUE,
            discharge_m3s=100.0,
            provenance_id="outlet-observation-intake-0001",
            evidence_level="authoritative",
            observed=True,
        ),
        hourly_inputs=HourlyActionForcingSeries(
            valid_times=valid_times,
            action_release_m3s=tuple(50.0 + index % 4 for index in range(len(valid_times))),
            nwm_lateral_inflow_m3s=tuple(2.0 for _ in valid_times),
            action_provenance_id="release-plan-intake-0001",
            forcing_provenance_id="nwm-forecast-intake-0001",
            action_plan_vintage_verified=True,
            forcing_vintage_verified=True,
        ),
        input_attestation=IssueTimeInputAttestation(
            issue_time=ISSUE,
            network_id=NETWORK_ID,
            action_provenance_id="release-plan-intake-0001",
            action_plan_available_at=ISSUE - timedelta(minutes=30),
            forcing_provenance_id="nwm-forecast-intake-0001",
            forcing_forecast_available_at=ISSUE - timedelta(minutes=15),
            outlet_state_provenance_id="outlet-observation-intake-0001",
            outlet_state_available_at=ISSUE,
            verification_id="prospective-observation-intake-audit-0001",
        ),
    )


def _forecast_receipt_body() -> bytes:
    request_body = json.dumps(_request().as_dict()).encode()
    receipt = compile_uncertainty_shadow_receipt(request_body, enable_shadow=True)
    receipt["generated_at"] = (ISSUE + timedelta(minutes=5)).isoformat()
    return (json.dumps(receipt, sort_keys=True) + "\n").encode()


def _batch(forecast_body: bytes) -> dict:
    receipt = json.loads(forecast_body)
    point = receipt["result"]["interval_forecast"]["point_forecast"]
    return {
        "schema": OBSERVATION_BATCH_SCHEMA,
        "network_id": NETWORK_ID,
        "outlet_observation_provenance_id": "authoritative-outlet-series-0001",
        "outlet_observation_evidence_level": "authoritative",
        "retrieved_at": (ISSUE + timedelta(hours=12, minutes=10)).isoformat(),
        "observations": [
            {
                "target_valid_time": target,
                "observed_discharge_m3s": observed,
                "observation_available_at": (
                    datetime.fromisoformat(target) + timedelta(minutes=5)
                ).isoformat(),
            }
            for target, observed in zip(
                point["target_valid_times"],
                point["target_discharge_m3s"],
                strict=True,
            )
        ],
        "values_imputed": False,
    }


def _body(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _set_clock(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.build_geospatial_kernel_action_innovation_prospective_outcomes._now",
        lambda: NOW,
    )


def test_outcome_builder_binds_exact_forecast_and_observation_artifacts(monkeypatch) -> None:
    _set_clock(monkeypatch)
    forecast_body = _forecast_receipt_body()
    observation_body = _body(_batch(forecast_body))

    outcomes = compile_prospective_outcomes(forecast_body, observation_body)
    loaded = action_innovation_prospective_outcomes_from_dict(outcomes.as_dict())

    assert loaded == outcomes
    assert outcomes.request_id == "center-hill-prospective-observation-intake-0001"
    assert outcomes.forecast_receipt_sha256 == hashlib.sha256(forecast_body).hexdigest()
    assert outcomes.source_observation_artifact_sha256 == hashlib.sha256(
        observation_body
    ).hexdigest()
    assert outcomes.source_observation_artifact_size_bytes == len(observation_body)
    assert tuple(value.target_valid_time for value in outcomes.observations) == tuple(
        ISSUE + timedelta(hours=horizon) for horizon in HORIZONS
    )


def test_outcome_builder_rejects_wrong_network(monkeypatch) -> None:
    _set_clock(monkeypatch)
    forecast_body = _forecast_receipt_body()
    batch = _batch(forecast_body)
    batch["network_id"] = "different-basin:dam-to-gauge"

    with pytest.raises(ValueError, match="network_or_runtime_mismatch"):
        compile_prospective_outcomes(forecast_body, _body(batch))


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_outcome_builder_rejects_incomplete_or_duplicate_axis(
    monkeypatch,
    mutation: str,
) -> None:
    _set_clock(monkeypatch)
    forecast_body = _forecast_receipt_body()
    batch = _batch(forecast_body)
    if mutation == "missing":
        batch["observations"].pop()
        error = "batch_axis_invalid"
    else:
        batch["observations"][-1]["target_valid_time"] = batch["observations"][0][
            "target_valid_time"
        ]
        error = "batch_duplicate_target"

    with pytest.raises(ValueError, match=error):
        compile_prospective_outcomes(forecast_body, _body(batch))


def test_outcome_builder_rejects_imputed_or_early_observation(monkeypatch) -> None:
    _set_clock(monkeypatch)
    forecast_body = _forecast_receipt_body()
    imputed = _batch(forecast_body)
    imputed["values_imputed"] = True
    early = _batch(forecast_body)
    first = early["observations"][0]
    first["observation_available_at"] = (
        datetime.fromisoformat(first["target_valid_time"]) - timedelta(seconds=1)
    ).isoformat()

    with pytest.raises(ValueError, match="observation_batch_claims_invalid"):
        compile_prospective_outcomes(forecast_body, _body(imputed))
    with pytest.raises(ValueError, match="prospective_observation_invalid"):
        compile_prospective_outcomes(forecast_body, _body(early))


def test_outcome_builder_rejects_future_or_post_retrieval_availability(monkeypatch) -> None:
    _set_clock(monkeypatch)
    forecast_body = _forecast_receipt_body()
    future = _batch(forecast_body)
    future["retrieved_at"] = (NOW + timedelta(seconds=1)).isoformat()
    post_retrieval = _batch(forecast_body)
    post_retrieval["observations"][-1]["observation_available_at"] = (
        datetime.fromisoformat(post_retrieval["retrieved_at"]) + timedelta(seconds=1)
    ).isoformat()

    with pytest.raises(ValueError, match="batch_ordering_invalid"):
        compile_prospective_outcomes(forecast_body, _body(future))
    with pytest.raises(ValueError, match="batch_availability_invalid"):
        compile_prospective_outcomes(forecast_body, _body(post_retrieval))


def test_outcome_builder_rejects_tampered_frozen_identity(monkeypatch) -> None:
    _set_clock(monkeypatch)
    forecast_body = _forecast_receipt_body()
    receipt = json.loads(forecast_body)
    receipt["execution_identity"]["point_parameter_sha256"] = "f" * 64
    tampered_body = _body(receipt)

    with pytest.raises(ValueError, match="frozen_identity_mismatch"):
        compile_prospective_outcomes(tampered_body, _body(_batch(tampered_body)))


def test_outcome_builder_cli_writes_once(tmp_path, monkeypatch) -> None:
    _set_clock(monkeypatch)
    forecast_body = _forecast_receipt_body()
    forecast_path = tmp_path / "forecast.json"
    batch_path = tmp_path / "observations.json"
    output_path = tmp_path / "outcomes.json"
    forecast_path.write_bytes(forecast_body)
    batch_path.write_bytes(_body(_batch(forecast_body)))
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_geospatial_kernel_action_innovation_prospective_outcomes.py",
            "--forecast-receipt",
            str(forecast_path),
            "--observation-batch",
            str(batch_path),
            "--output",
            str(output_path),
        ],
    )

    assert main() == 0
    payload = json.loads(output_path.read_bytes())
    assert payload["values_imputed"] is False
    assert payload["source_observation_artifact_sha256"] == hashlib.sha256(
        batch_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="outcomes_refuses_overwrite"):
        main()
