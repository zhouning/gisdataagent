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
    action_innovation_shadow_request_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    IssueTimeInputAttestation,
)
from scripts.run_geospatial_kernel_action_innovation_shadow import (
    compile_shadow_receipt,
    main,
)

ISSUE = datetime(2022, 2, 1, tzinfo=UTC)
NETWORK_ID = "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"


def _request() -> ActionInnovationShadowRequest:
    valid_times = tuple(ISSUE + timedelta(hours=index) for index in range(-8, 13))
    return ActionInnovationShadowRequest(
        request_id="center-hill-shadow-2022-02-01T00Z",
        network_id=NETWORK_ID,
        shadow_only_acknowledged=True,
        issue_time=ISSUE,
        target_valid_times=tuple(ISSUE + timedelta(hours=value) for value in (1, 3, 6, 12)),
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
    return (json.dumps(_request().as_dict(), ensure_ascii=False, indent=2) + "\n").encode()


def test_shadow_request_round_trips_without_weakening_fields() -> None:
    original = _request()

    loaded = action_innovation_shadow_request_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()
    assert len(loaded.normalized_sha256()) == 64


def test_shadow_receipt_executes_end_to_end_and_binds_request() -> None:
    body = _body()

    receipt = compile_shadow_receipt(body, enable_shadow=True)

    assert receipt["status"] == "shadow_forecast_complete_not_admitted"
    assert receipt["request_identity"]["source_document_sha256"] == hashlib.sha256(body).hexdigest()
    assert receipt["request_identity"]["source_document_size_bytes"] == len(body)
    assert receipt["request_identity"]["network_id"] == NETWORK_ID
    assert receipt["result"]["mode"] == "shadow"
    assert receipt["result"]["forecast"]["operational_vintages_verified"] is True
    assert receipt["claim_boundary"] == {
        "shadow_only": True,
        "production_eligible": False,
        "runtime_default_enabled": False,
        "admitted": False,
    }
    assert all(len(value) == 64 for value in receipt["execution_identity"].values())


def test_shadow_receipt_requires_command_side_enablement() -> None:
    with pytest.raises(RuntimeError, match="shadow_runtime_disabled"):
        compile_shadow_receipt(_body())


def test_shadow_request_requires_document_side_acknowledgement() -> None:
    payload = _request().as_dict()
    payload["shadow_only_acknowledged"] = False

    with pytest.raises(ValueError, match="shadow_only_acknowledgement_required"):
        compile_shadow_receipt(json.dumps(payload).encode(), enable_shadow=True)


def test_shadow_request_rejects_unknown_fields() -> None:
    payload = deepcopy(_request().as_dict())
    payload["production_enabled"] = True

    with pytest.raises(ValueError, match="request_document_fields_invalid"):
        action_innovation_shadow_request_from_dict(payload)


def test_shadow_request_rejects_loose_numeric_types() -> None:
    payload = deepcopy(_request().as_dict())
    payload["outlet_state"]["discharge_m3s"] = "100.0"

    with pytest.raises(ValueError, match="outlet_state_discharge_number_invalid"):
        action_innovation_shadow_request_from_dict(payload)


def test_shadow_cli_writes_once_and_refuses_overwrite(tmp_path, monkeypatch) -> None:
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "receipt.json"
    request_path.write_bytes(_body())
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_geospatial_kernel_action_innovation_shadow.py",
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
