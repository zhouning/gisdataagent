import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FULL_PANEL_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
)


def test_full_admin_livability_target_panel_uses_all_admin_exposure_rows():
    assert FULL_PANEL_PATH.exists()
    panel = json.loads(FULL_PANEL_PATH.read_text(encoding="utf-8"))

    assert panel["schema"] == "uwm.admin_livability_target_panel.v1"
    assert panel["experiment_scope"] == "full_admin_graph"
    assert panel["source_admin_count"] == 1017
    assert panel["joined_admin_count"] == 1017
    assert len(panel["admin_livability_target_rows"]) == 1017
    assert panel["service_matched_admin_count"] == 1017
    assert panel["service_missing_admin_count"] == 0
    assert "full_admin_service_accessibility_surface_2026_07_08" in panel["source_dataset_ids"]
    assert panel["summary"]["service_surface_type"] == (
        "full_admin_local_poi_road_accessibility_surface"
    )
    assert panel["summary"]["service_accessibility_score_available_count"] == 1017
    assert "partial_service_panel_retained_as_missing_not_dropped" not in panel["limitations"]
    assert "service_sample_gap_not_true_absence" not in panel["limitations"]
    assert "service_accessibility_surface_is_proxy_not_observed_travel_time" in panel["limitations"]
    sample_row = panel["admin_livability_target_rows"][0]
    assert "service_accessibility_score" in sample_row
    assert "service_gap_score" in sample_row
    assert "estimated_nearest_essential_travel_time_min" in sample_row
    assert "road_segment_count" in sample_row
    assert panel["empirical_superiority_claim"] is False
