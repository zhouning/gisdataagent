import copy
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel.state_prior_p1_prospective_protocol import (
    STATE_PRIOR_P1_PROSPECTIVE_PROTOCOL_SCHEMA,
    build_state_prior_p1_prospective_protocol,
    compute_state_prior_p1_prospective_protocol_sha256,
    validate_state_prior_p1_prospective_protocol,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central"
    / "geospatial_state_prior_next_p1_protocol_2024_07_02_07"
    / "uwm_geospatial_state_prior_p1_prospective_protocol.json"
)


def test_next_p1_protocol_freezes_fresh_window_without_authorizing_execution():
    protocol = _protocol()

    assert protocol["schema"] == STATE_PRIOR_P1_PROSPECTIVE_PROTOCOL_SCHEMA
    assert validate_state_prior_p1_prospective_protocol(protocol) == {
        "valid": True,
        "errors": [],
    }
    assert protocol["window_design"]["development_window"] == {
        "start_date": "2018-10-18",
        "end_date": "2018-10-23",
        "role": "opened_posthoc_development_only",
        "eligible_for_scientific_claim": False,
    }
    assert protocol["window_design"]["final_holdout_window"]["start_date"] == ("2024-07-02")
    assert protocol["feature_freeze"]["source_allowlist_closed"] is True
    assert (
        protocol["evaluation_design"]["candidate_must_beat_every_required_baseline_on_every_split"]
        is True
    )
    assert protocol["evaluation_design"]["minimum_coverage_threshold"] == 0.85
    assert protocol["p1_execution_permitted"] is False
    assert protocol["p2_admission_permitted"] is False
    assert protocol["claim_boundary"]["max_claim_level"] == "not_for_claim"


def test_protocol_cannot_self_activate_or_escalate_after_digest_recomputation():
    protocol = _protocol()
    forged = copy.deepcopy(protocol)
    forged["activation_gates"]["external_registration_receipt_verified"] = True
    forged["p1_execution_permitted"] = True
    forged["p2_admission_permitted"] = True
    forged["claim_boundary"]["external_preregistration_verified"] = True
    forged["claim_boundary"]["max_claim_level"] = "bounded_support"
    forged["evaluation_design"]["minimum_relative_improvement"] = 0.0
    forged["protocol_sha256"] = compute_state_prior_p1_prospective_protocol_sha256(forged)

    validation = validate_state_prior_p1_prospective_protocol(forged)

    assert not validation["valid"]
    assert "p1_prospective_protocol_activation_gates_must_start_false" in validation["errors"]
    assert "p1_prospective_protocol_cannot_self_authorize_execution" in validation["errors"]
    assert "p1_prospective_protocol_cannot_permit_p2_admission" in validation["errors"]
    assert "p1_prospective_protocol_claim_boundary_invalid" in validation["errors"]
    assert "p1_prospective_protocol_improvement_threshold_invalid" in validation["errors"]
    assert "p1_prospective_protocol_sha256_mismatch" not in validation["errors"]


def test_protocol_rejects_overlapping_development_and_holdout_windows():
    with pytest.raises(ValueError, match="windows_overlap_or_out_of_order"):
        _protocol(
            development_window={
                "start_date": "2024-07-01",
                "end_date": "2024-07-03",
            }
        )


def test_protocol_rejects_target_values_in_an_input_route():
    sources = _sources()
    sources["admin"]["uses_target_values"] = True

    with pytest.raises(ValueError, match="admin_uses_target_values_invalid"):
        _protocol(eligible_feature_sources=sources)


def test_checked_in_next_p1_protocol_is_valid_but_not_activated():
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))

    assert validate_state_prior_p1_prospective_protocol(protocol) == {
        "valid": True,
        "errors": [],
    }
    assert protocol["protocol_sha256"] == (
        "ee52b37d10bda4b7f64fea960254312806bcefaea8ef9220630226001df37488"
    )
    assert not any(protocol["activation_gates"].values())
    assert protocol["p1_execution_permitted"] is False


def _protocol(**overrides) -> dict:
    values = {
        "protocol_id": "chongqing-next-observed-p1-test",
        "created_at": "2026-08-04T22:05:00Z",
        "frozen_at": "2026-08-04T22:10:00Z",
        "prior_diagnostic_sha256": "1" * 64,
        "development_window": {
            "start_date": "2018-10-18",
            "end_date": "2018-10-23",
        },
        "final_holdout_window": {
            "start_date": "2024-07-02",
            "end_date": "2024-07-07",
        },
        "eligible_feature_sources": _sources(),
        "evidence_refs": ["artifact://failed-p1-diagnostic"],
    }
    values.update(overrides)
    return build_state_prior_p1_prospective_protocol(**values)


def _sources() -> dict:
    return {
        "target": _source("observed-target", ["daily_pm25"]),
        "raster": _source("lagged-raster", ["lag1_pm25", "grid_distance"]),
        "admin": _source("static-admin", ["area", "perimeter"]),
        "graph_object": _source("static-graph", ["degree"]),
    }


def _source(source_id: str, feature_names: list[str]) -> dict:
    return {
        "source_id": source_id,
        "source_role": "frozen-test-role",
        "feature_names": feature_names,
        "temporal_rule": "frozen-test-rule",
        "uses_target_values": False,
        "limitations": ["fixture_contract_only"],
    }
