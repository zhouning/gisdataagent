import importlib.util
import json
from pathlib import Path

from data_agent.test_uwm_livability_s2_scenario import _product_dir

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_uwm_livability_s2_fulu.py"
SPEC = importlib.util.spec_from_file_location("verify_uwm_livability_s2_fulu", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_verifier_selects_both_villages_and_preserves_claim_boundaries(tmp_path, monkeypatch):
    product_dir = _product_dir(tmp_path, monkeypatch)
    result = MODULE.verify_s2_fulu(product_dir=product_dir, requested_at="2026-07-11T08:00:00Z")

    assert result["ready"] is True
    assert set(result["cases_by_area"]) == {"fulu_heping", "fulu_banzhu"}
    for area_id, case in result["cases_by_area"].items():
        assert case["parcel_id"]
        assert case["current_land_use_class"] != case["target_land_use_class"]
        assert case["current_land_use_class"] not in {"unresolved", "unavailable"}
        assert case["target_land_use_class"] not in {"unresolved", "unavailable"}
        assert case["transition_status"] == "unresolved"
        assert case["review_required"] is True
        assert case["same_snapshot_for_baseline_and_intervention"] is True
        assert case["max_local_distance_m"] == 300.0
        assert case["admin_propagation_stopped"] is True
        assert case["unsupported_prediction_heads_ready"] is False
        assert case["unavailable_effect_count"] == 8
        assert case["claim_level"] == "bounded_action_conditioned_spatial_scenario"
    assert result["unmapped_planning_resource_count"] > 0
    assert result["synthetic_parcels_created"] is False


def test_verifier_is_deterministic_for_same_snapshot(tmp_path, monkeypatch):
    product_dir = _product_dir(tmp_path, monkeypatch)
    first = MODULE.verify_s2_fulu(product_dir=product_dir, requested_at="2026-07-11T08:00:00Z")
    second = MODULE.verify_s2_fulu(product_dir=product_dir, requested_at="2026-07-11T08:00:00Z")

    assert first["verification_digest"] == second["verification_digest"]
    assert first["cases_by_area"] == second["cases_by_area"]
