from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from data_agent.uwm.abu_dhabi_flood import (
    build_k0_data_request_receipt,
    default_k0_data_request_package,
    evaluate_k0_data_request,
    verify_k0_data_request_receipt,
)


def test_default_k0_request_is_blocked_but_complete_as_a_customer_checklist():
    package = default_k0_data_request_package()
    quality = evaluate_k0_data_request(package)

    assert len(package.requests) == 8
    assert quality["passed"] is False
    assert quality["admission_effect"] == "none_customer_data_request_only"
    assert set(quality["missing_request_ids"]) == {
        "engineering-surface-vertical-datum",
        "drainage-network-topology-units",
        "event-rainfall-forcing",
        "coastal-boundary-time-series",
        "pump-gate-operation-history",
        "timed-inundation-observations",
        "common-geography-overlay-rule",
        "liveability-exposure-semantics",
    }
    assert package.claim_boundary()["k0_opened"] is False
    assert package.claim_boundary()["city_scale_prediction_claim_allowed"] is False


def test_request_item_rejects_invalid_priority_status_and_empty_acceptance():
    item = default_k0_data_request_package().requests[0]
    with pytest.raises(ValueError, match="k0_data_request_priority_invalid"):
        replace(item, priority=4)
    with pytest.raises(ValueError, match="k0_data_request_current_status_invalid"):
        replace(item, current_status="approved_by_assumption")
    with pytest.raises(ValueError, match="k0_data_request_minimum_acceptance_invalid"):
        replace(item, minimum_acceptance=" ")


def test_package_rejects_duplicate_requests_wrong_crs_and_admission_bypass():
    package = default_k0_data_request_package()
    with pytest.raises(ValueError, match="k0_data_request_ids_must_be_unique"):
        replace(package, requests=(package.requests[0], package.requests[0]))
    with pytest.raises(ValueError, match="k0_data_request_crs_must_be_epsg32640"):
        replace(package, target_crs="EPSG:4326")
    with pytest.raises(
        ValueError, match="k0_data_request_contract_cannot_grant_admission"
    ):
        replace(package, k0_opened=True)


def test_all_items_admitted_does_not_open_k0_automatically():
    package = default_k0_data_request_package()
    admitted = replace(
        package,
        requests=tuple(
            replace(item, current_status="admitted") for item in package.requests
        ),
    )
    quality = evaluate_k0_data_request(admitted)

    assert quality["passed"] is True
    assert quality["missing_request_ids"] == []
    assert admitted.claim_boundary()["k0_opened"] is False
    assert quality["admission_effect"] == "none_customer_data_request_only"


def test_request_receipt_is_self_hashed_and_contains_no_source_execution():
    receipt = build_k0_data_request_receipt(default_k0_data_request_package())
    verify_k0_data_request_receipt(receipt)

    assert receipt["status"] == "k0_data_request_contract_blocked_not_admitted"
    assert receipt["execution"] == {
        "customer_rows_consumed": False,
        "database_connection_executed": False,
        "credentials_recorded": False,
        "k0_gate_opened": False,
        "contract_only_checklist": True,
    }
    assert receipt["quality_gates"]["passed"] is False
    assert receipt["admission"]["traditional_model_admitted"] is False
    assert receipt["admission"]["gwm_training_admitted"] is False


def test_request_receipt_hash_mismatch_and_boundary_tampering_are_rejected():
    receipt = build_k0_data_request_receipt(default_k0_data_request_package())
    tampered = deepcopy(receipt)
    tampered["quality_gates"]["missing_request_ids"] = []
    with pytest.raises(ValueError, match="k0_data_request_receipt_sha256_mismatch"):
        verify_k0_data_request_receipt(tampered)

    forged = deepcopy(receipt)
    forged["admission"]["k0_opened"] = True
    with pytest.raises(ValueError, match="k0_data_request_receipt_sha256_mismatch"):
        verify_k0_data_request_receipt(forged)
