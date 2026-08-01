import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    DEFAULT_FREEZE_PATH,
    REPO_ROOT,
    SHADOW_RUNTIME_PATH,
    IssueTimeInputAttestation,
    load_frozen_action_innovation_shadow_runtime,
)

ISSUE = datetime(2022, 2, 1, tzinfo=UTC)
NETWORK_ID = "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"


def _state(*, evidence_level: str = "authoritative") -> OutletTransitionState:
    return OutletTransitionState(
        valid_at=ISSUE - timedelta(hours=1),
        available_at=ISSUE,
        discharge_m3s=100.0,
        provenance_id="outlet-observation-vintage-17",
        evidence_level=evidence_level,
        observed=True,
    )


def _inputs(*, verified: bool = True) -> HourlyActionForcingSeries:
    valid_times = tuple(ISSUE + timedelta(hours=index) for index in range(-8, 13))
    return HourlyActionForcingSeries(
        valid_times=valid_times,
        action_release_m3s=tuple(50.0 + float(index % 4) for index in range(len(valid_times))),
        nwm_lateral_inflow_m3s=tuple(2.0 for _ in valid_times),
        action_provenance_id="release-plan-vintage-42",
        forcing_provenance_id="nwm-forecast-vintage-81",
        action_plan_vintage_verified=verified,
        forcing_vintage_verified=verified,
    )


def _attestation(
    *, action_provenance_id: str = "release-plan-vintage-42"
) -> IssueTimeInputAttestation:
    return IssueTimeInputAttestation(
        issue_time=ISSUE,
        network_id=NETWORK_ID,
        action_provenance_id=action_provenance_id,
        action_plan_available_at=ISSUE - timedelta(minutes=30),
        forcing_provenance_id="nwm-forecast-vintage-81",
        forcing_forecast_available_at=ISSUE - timedelta(minutes=15),
        outlet_state_provenance_id="outlet-observation-vintage-17",
        outlet_state_available_at=ISSUE,
        verification_id="issue-time-vintage-audit-2022-02-01T00Z",
    )


def test_shadow_runtime_is_disabled_by_default() -> None:
    runtime = load_frozen_action_innovation_shadow_runtime()

    with pytest.raises(RuntimeError, match="shadow_runtime_disabled"):
        runtime.forecast(
            _state(),
            _inputs(),
            network_id=NETWORK_ID,
            issue_time=ISSUE,
            target_valid_times=(ISSUE + timedelta(hours=1),),
            input_attestation=_attestation(),
        )


def test_explicit_shadow_run_is_auditable_but_never_admitted() -> None:
    runtime = load_frozen_action_innovation_shadow_runtime(enabled=True)

    result = runtime.forecast(
        _state(),
        _inputs(),
        network_id=NETWORK_ID,
        issue_time=ISSUE,
        target_valid_times=tuple(ISSUE + timedelta(hours=value) for value in (1, 3, 6, 12)),
        input_attestation=_attestation(),
    )
    document = result.as_dict()

    assert result.forecast.operational_vintages_verified is True
    assert result.forecast.admitted is False
    assert document["mode"] == "shadow"
    assert document["production_eligible"] is False
    assert document["runtime_default_enabled"] is False
    assert document["admitted"] is False
    assert (
        document["runtime_sha256"] == hashlib.sha256(SHADOW_RUNTIME_PATH.read_bytes()).hexdigest()
    )
    assert document["forecast"]["target_valid_times"] == [
        (ISSUE + timedelta(hours=value)).isoformat() for value in (1, 3, 6, 12)
    ]


def test_shadow_runtime_rejects_unverified_archive_inputs() -> None:
    runtime = load_frozen_action_innovation_shadow_runtime(enabled=True)

    with pytest.raises(ValueError, match="input_vintages_not_verified"):
        runtime.forecast(
            _state(),
            _inputs(verified=False),
            network_id=NETWORK_ID,
            issue_time=ISSUE,
            target_valid_times=(ISSUE + timedelta(hours=1),),
            input_attestation=_attestation(),
        )


def test_shadow_runtime_rejects_attestation_provenance_mismatch() -> None:
    runtime = load_frozen_action_innovation_shadow_runtime(enabled=True)

    with pytest.raises(ValueError, match="attestation_provenance_mismatch"):
        runtime.forecast(
            _state(),
            _inputs(),
            network_id=NETWORK_ID,
            issue_time=ISSUE,
            target_valid_times=(ISSUE + timedelta(hours=1),),
            input_attestation=_attestation(action_provenance_id="different-release-plan"),
        )


def test_shadow_runtime_rejects_future_vintage_availability() -> None:
    with pytest.raises(ValueError, match="input_not_available_at_issue"):
        IssueTimeInputAttestation(
            issue_time=ISSUE,
            network_id=NETWORK_ID,
            action_provenance_id="release-plan-vintage-42",
            action_plan_available_at=ISSUE + timedelta(seconds=1),
            forcing_provenance_id="nwm-forecast-vintage-81",
            forcing_forecast_available_at=ISSUE,
            outlet_state_provenance_id="outlet-observation-vintage-17",
            outlet_state_available_at=ISSUE,
            verification_id="invalid-future-vintage",
        )


def test_shadow_runtime_rejects_wrong_geographic_network() -> None:
    runtime = load_frozen_action_innovation_shadow_runtime(enabled=True)

    with pytest.raises(ValueError, match="network_identity_mismatch"):
        runtime.forecast(
            _state(),
            _inputs(),
            network_id="different-basin:dam-to-gauge",
            issue_time=ISSUE,
            target_valid_times=(ISSUE + timedelta(hours=1),),
            input_attestation=_attestation(),
        )


def test_shadow_runtime_rejects_inflated_freeze_contract(tmp_path) -> None:
    freeze = json.loads(DEFAULT_FREEZE_PATH.read_bytes())
    freeze["admission_contract"]["runtime_default_enabled"] = True
    path = tmp_path / "inflated-freeze.json"
    path.write_text(json.dumps(freeze), encoding="utf-8")

    with pytest.raises(ValueError, match="shadow_freeze_contract_invalid"):
        load_frozen_action_innovation_shadow_runtime(
            freeze_path=path,
            repository_root=REPO_ROOT,
        )
