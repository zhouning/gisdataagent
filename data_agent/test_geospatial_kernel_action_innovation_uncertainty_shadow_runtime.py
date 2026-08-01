import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_request import (
    ActionInnovationShadowRequest,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    REPO_ROOT,
    IssueTimeInputAttestation,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
    UNCERTAINTY_SHADOW_RUNTIME_PATH,
    load_frozen_action_innovation_uncertainty_shadow_runtime,
)
from scripts.run_geospatial_kernel_action_innovation_uncertainty_shadow import (
    compile_uncertainty_shadow_receipt,
    main,
)

ISSUE = datetime(2022, 2, 1, tzinfo=UTC)
HORIZONS = (1, 3, 6, 12)
NETWORK_ID = "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"


def _request() -> ActionInnovationShadowRequest:
    valid_times = tuple(ISSUE + timedelta(hours=index) for index in range(-8, 13))
    return ActionInnovationShadowRequest(
        request_id="center-hill-uncertainty-shadow-2022-02-01T00Z",
        network_id=NETWORK_ID,
        shadow_only_acknowledged=True,
        issue_time=ISSUE,
        target_valid_times=tuple(ISSUE + timedelta(hours=horizon) for horizon in HORIZONS),
        outlet_state=OutletTransitionState(
            valid_at=ISSUE - timedelta(hours=1),
            available_at=ISSUE,
            discharge_m3s=100.0,
            provenance_id="outlet-observation-vintage-17",
            evidence_level="authoritative",
            observed=True,
        ),
        hourly_inputs=HourlyActionForcingSeries(
            valid_times=valid_times,
            action_release_m3s=tuple(50.0 + float(index % 4) for index in range(len(valid_times))),
            nwm_lateral_inflow_m3s=tuple(2.0 for _ in valid_times),
            action_provenance_id="release-plan-vintage-42",
            forcing_provenance_id="nwm-forecast-vintage-81",
            action_plan_vintage_verified=True,
            forcing_vintage_verified=True,
        ),
        input_attestation=IssueTimeInputAttestation(
            issue_time=ISSUE,
            network_id=NETWORK_ID,
            action_provenance_id="release-plan-vintage-42",
            action_plan_available_at=ISSUE - timedelta(minutes=30),
            forcing_provenance_id="nwm-forecast-vintage-81",
            forcing_forecast_available_at=ISSUE - timedelta(minutes=15),
            outlet_state_provenance_id="outlet-observation-vintage-17",
            outlet_state_available_at=ISSUE,
            verification_id="issue-time-vintage-audit-2022-02-01T00Z",
        ),
    )


def _body() -> bytes:
    return (json.dumps(_request().as_dict(), ensure_ascii=False) + "\n").encode()


def test_uncertainty_shadow_runtime_is_disabled_by_default() -> None:
    runtime = load_frozen_action_innovation_uncertainty_shadow_runtime()
    request = _request()

    with pytest.raises(RuntimeError, match="uncertainty_shadow_runtime_disabled"):
        runtime.forecast(
            request.outlet_state,
            request.hourly_inputs,
            network_id=request.network_id,
            issue_time=request.issue_time,
            target_valid_times=request.target_valid_times,
            input_attestation=request.input_attestation,
        )


def test_uncertainty_shadow_emits_bound_point_and_intervals_without_admission() -> None:
    runtime = load_frozen_action_innovation_uncertainty_shadow_runtime(enabled=True)
    request = _request()

    result = runtime.forecast(
        request.outlet_state,
        request.hourly_inputs,
        network_id=request.network_id,
        issue_time=request.issue_time,
        target_valid_times=request.target_valid_times,
        input_attestation=request.input_attestation,
    )
    document = result.as_dict()
    point = result.point_shadow_forecast.forecast.target_discharge_m3s

    assert document["mode"] == "uncertainty_shadow"
    assert document["network_id"] == NETWORK_ID
    assert document["production_eligible"] is False
    assert document["runtime_default_enabled"] is False
    assert document["admitted"] is False
    assert document["finite_sample_coverage_guarantee_claimed"] is False
    assert result.interval_forecast.point_forecast is result.point_shadow_forecast.forecast
    assert all(
        lower <= center <= upper
        for lower, center, upper in zip(
            result.interval_forecast.lower_discharge_m3s,
            point,
            result.interval_forecast.upper_discharge_m3s,
            strict=True,
        )
    )
    assert (
        result.uncertainty_runtime_sha256
        == hashlib.sha256(UNCERTAINTY_SHADOW_RUNTIME_PATH.read_bytes()).hexdigest()
    )


def test_uncertainty_shadow_rejects_changed_frozen_radius(tmp_path) -> None:
    freeze = json.loads(DEFAULT_UNCERTAINTY_FREEZE_PATH.read_bytes())
    freeze["uncertainty_lock"]["absolute_error_radius_m3s"][0] += 1.0
    path = tmp_path / "changed-radius-freeze.json"
    path.write_text(json.dumps(freeze), encoding="utf-8")

    with pytest.raises(ValueError, match="parameter_freeze_mismatch"):
        load_frozen_action_innovation_uncertainty_shadow_runtime(
            uncertainty_freeze_path=path,
            repository_root=REPO_ROOT,
        )


def test_uncertainty_shadow_rejects_inflated_admission_contract(tmp_path) -> None:
    freeze = json.loads(DEFAULT_UNCERTAINTY_FREEZE_PATH.read_bytes())
    freeze["admission_contract"]["runtime_default_enabled"] = True
    path = tmp_path / "inflated-admission-freeze.json"
    path.write_text(json.dumps(freeze), encoding="utf-8")

    with pytest.raises(ValueError, match="freeze_contract_invalid"):
        load_frozen_action_innovation_uncertainty_shadow_runtime(
            uncertainty_freeze_path=path,
            repository_root=REPO_ROOT,
        )


def test_uncertainty_shadow_receipt_binds_both_freezes_and_claim_boundary() -> None:
    receipt = compile_uncertainty_shadow_receipt(_body(), enable_shadow=True)

    assert receipt["status"] == "uncertainty_shadow_forecast_complete_not_admitted"
    assert receipt["result"]["mode"] == "uncertainty_shadow"
    assert receipt["result"]["interval_forecast"]["admitted"] is False
    assert receipt["claim_boundary"] == {
        "shadow_only": True,
        "calibration_outcomes_used": True,
        "finite_sample_coverage_guarantee_claimed": False,
        "conditional_coverage_guarantee_claimed": False,
        "production_eligible": False,
        "runtime_default_enabled": False,
        "admitted": False,
    }
    assert set(receipt["execution_identity"]) == {
        "point_freeze_sha256",
        "point_parameter_sha256",
        "point_runtime_sha256",
        "uncertainty_freeze_sha256",
        "uncertainty_parameter_sha256",
        "uncertainty_runtime_sha256",
        "request_adapter_sha256",
        "runner_sha256",
    }
    assert all(len(value) == 64 for value in receipt["execution_identity"].values())


def test_uncertainty_shadow_receipt_requires_both_acknowledgements() -> None:
    with pytest.raises(RuntimeError, match="uncertainty_shadow_runtime_disabled"):
        compile_uncertainty_shadow_receipt(_body())

    payload = deepcopy(_request().as_dict())
    payload["shadow_only_acknowledged"] = False
    with pytest.raises(ValueError, match="shadow_only_acknowledgement_required"):
        compile_uncertainty_shadow_receipt(
            json.dumps(payload).encode(),
            enable_shadow=True,
        )


def test_uncertainty_shadow_cli_writes_once(tmp_path, monkeypatch) -> None:
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "receipt.json"
    request_path.write_bytes(_body())
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_geospatial_kernel_action_innovation_uncertainty_shadow.py",
            "--request",
            str(request_path),
            "--output",
            str(output_path),
            "--enable-shadow",
        ],
    )

    assert main() == 0
    receipt = json.loads(output_path.read_bytes())
    assert receipt["request_identity"]["request_id"] == _request().request_id
    assert receipt["claim_boundary"]["admitted"] is False

    with pytest.raises(ValueError, match="receipt_refuses_overwrite"):
        main()
