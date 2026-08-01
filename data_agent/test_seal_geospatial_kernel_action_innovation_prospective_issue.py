import hashlib
import json
from datetime import datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
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
from scripts.seal_geospatial_kernel_action_innovation_prospective_issue import (
    compile_prospective_issue_receipt,
    main,
)

NETWORK_ID = "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"
FROZEN_AT = datetime.fromisoformat(
    json.loads(DEFAULT_UNCERTAINTY_FREEZE_PATH.read_bytes())["frozen_at"]
)
ISSUE = FROZEN_AT + timedelta(hours=1)
STARTED_AT = ISSUE + timedelta(minutes=5)
GENERATED_AT = STARTED_AT + timedelta(seconds=1)


def _request(*, network_id: str = NETWORK_ID) -> ActionInnovationShadowRequest:
    valid_times = tuple(ISSUE + timedelta(hours=index) for index in range(-8, 13))
    return ActionInnovationShadowRequest(
        request_id="center-hill-live-prospective-issue-0001",
        network_id=network_id,
        shadow_only_acknowledged=True,
        issue_time=ISSUE,
        target_valid_times=tuple(ISSUE + timedelta(hours=horizon) for horizon in (1, 3, 6, 12)),
        outlet_state=OutletTransitionState(
            valid_at=ISSUE - timedelta(hours=1),
            available_at=ISSUE,
            discharge_m3s=100.0,
            provenance_id="outlet-observation-live-0001",
            evidence_level="authoritative",
            observed=True,
        ),
        hourly_inputs=HourlyActionForcingSeries(
            valid_times=valid_times,
            action_release_m3s=tuple(50.0 + float(index % 4) for index in range(len(valid_times))),
            nwm_lateral_inflow_m3s=tuple(2.0 for _ in valid_times),
            action_provenance_id="release-plan-live-0001",
            forcing_provenance_id="nwm-forecast-live-0001",
            action_plan_vintage_verified=True,
            forcing_vintage_verified=True,
        ),
        input_attestation=IssueTimeInputAttestation(
            issue_time=ISSUE,
            network_id=network_id,
            action_provenance_id="release-plan-live-0001",
            action_plan_available_at=ISSUE - timedelta(minutes=30),
            forcing_provenance_id="nwm-forecast-live-0001",
            forcing_forecast_available_at=ISSUE - timedelta(minutes=15),
            outlet_state_provenance_id="outlet-observation-live-0001",
            outlet_state_available_at=ISSUE,
            verification_id="live-prospective-vintage-audit-0001",
        ),
    )


def _body(*, network_id: str = NETWORK_ID) -> bytes:
    return (json.dumps(_request(network_id=network_id).as_dict()) + "\n").encode()


def _set_clock(monkeypatch, *, started_at: datetime = STARTED_AT) -> None:
    monkeypatch.setattr(
        "scripts.seal_geospatial_kernel_action_innovation_prospective_issue._now",
        lambda: started_at,
    )
    monkeypatch.setattr(
        "scripts.run_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: GENERATED_AT,
    )


def test_prospective_issue_seals_only_current_frozen_shadow(monkeypatch) -> None:
    _set_clock(monkeypatch)
    body = _body()

    receipt = compile_prospective_issue_receipt(
        body,
        enable_prospective_shadow=True,
    )

    assert receipt["status"] == "uncertainty_shadow_forecast_complete_not_admitted"
    assert receipt["generated_at"] == GENERATED_AT.isoformat()
    assert receipt["request_identity"]["network_id"] == NETWORK_ID
    assert receipt["request_identity"]["source_document_sha256"] == hashlib.sha256(body).hexdigest()
    assert receipt["result"]["production_eligible"] is False
    assert receipt["claim_boundary"]["admitted"] is False


def test_prospective_issue_requires_explicit_enablement() -> None:
    with pytest.raises(RuntimeError, match="prospective_issue_sealing_disabled"):
        compile_prospective_issue_receipt(_body())


@pytest.mark.parametrize(
    "started_at",
    [ISSUE - timedelta(seconds=1), ISSUE + timedelta(minutes=15, seconds=1)],
)
def test_prospective_issue_rejects_future_or_stale_issue(
    monkeypatch,
    started_at: datetime,
) -> None:
    _set_clock(monkeypatch, started_at=started_at)

    with pytest.raises(ValueError, match="prospective_issue_ordering_invalid"):
        compile_prospective_issue_receipt(
            _body(),
            enable_prospective_shadow=True,
        )


def test_prospective_issue_rejects_non_frozen_network(monkeypatch) -> None:
    _set_clock(monkeypatch)

    with pytest.raises(ValueError, match="network_identity_mismatch"):
        compile_prospective_issue_receipt(
            _body(network_id="different-basin:dam-to-gauge"),
            enable_prospective_shadow=True,
        )


def test_prospective_issue_rejects_selective_horizon_sealing(monkeypatch) -> None:
    _set_clock(monkeypatch)
    payload = _request().as_dict()
    payload["target_valid_times"] = payload["target_valid_times"][:1]

    with pytest.raises(ValueError, match="prospective_issue_horizons_invalid"):
        compile_prospective_issue_receipt(
            json.dumps(payload).encode(),
            enable_prospective_shadow=True,
        )


def test_prospective_issue_cli_writes_once(tmp_path, monkeypatch) -> None:
    _set_clock(monkeypatch)
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "receipt.json"
    request_path.write_bytes(_body())
    monkeypatch.setattr(
        "sys.argv",
        [
            "seal_geospatial_kernel_action_innovation_prospective_issue.py",
            "--request",
            str(request_path),
            "--output",
            str(output_path),
            "--enable-prospective-shadow",
        ],
    )

    assert main() == 0
    assert json.loads(output_path.read_bytes())["request_identity"]["network_id"] == NETWORK_ID

    with pytest.raises(ValueError, match="receipt_refuses_overwrite"):
        main()
