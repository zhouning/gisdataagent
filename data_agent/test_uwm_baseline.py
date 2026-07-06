from data_agent.uwm.baseline import (
    build_baseline_vs_uwm_capability_report,
    compute_traditional_livability_baseline,
)


def test_traditional_livability_baseline_scores_static_indicators():
    records = [
        {"unit_id": "grid-1", "heat": 0.9, "service_access": 0.2, "green": 0.1, "pollution": 0.8},
        {"unit_id": "grid-2", "heat": 0.2, "service_access": 0.8, "green": 0.9, "pollution": 0.3},
    ]
    indicators = {
        "heat": {"weight": 0.30, "direction": "negative"},
        "service_access": {"weight": 0.30, "direction": "positive"},
        "green": {"weight": 0.20, "direction": "positive"},
        "pollution": {"weight": 0.20, "direction": "negative"},
    }

    baseline = compute_traditional_livability_baseline(records, indicators)

    assert baseline["schema"] == "uwm.traditional_livability_baseline.v1"
    assert baseline["method"] == "static_weighted_indicator_overlay"
    assert baseline["action_conditioned"] is False
    assert baseline["dynamic_rollout"] is False
    assert baseline["scores"][0]["unit_id"] == "grid-2"
    assert baseline["scores"][0]["score"] > baseline["scores"][1]["score"]
    assert "no action-conditioned transition" in baseline["limitations"]


def test_baseline_vs_uwm_report_marks_world_model_requirements():
    baseline = {
        "schema": "uwm.traditional_livability_baseline.v1",
        "method": "static_weighted_indicator_overlay",
        "action_conditioned": False,
        "dynamic_rollout": False,
        "scores": [{"unit_id": "grid-1", "score": 0.5}],
    }
    observation = {
        "schema": "uwm.canonical_observation.v1",
        "graph_edges": [{"edge_type": "spatial_adjacency"}],
        "renderer_trace": [{"step": "load_mmfe_uwm_state_input"}],
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }

    report = build_baseline_vs_uwm_capability_report(baseline, observation)

    assert report["schema"] == "uwm.baseline_comparison_report.v1"
    assert report["traditional_baseline"]["static_scores_available"] is True
    assert report["traditional_baseline"]["action_conditioned"] is False
    assert report["uwm_contract"]["canonical_observation"] is True
    assert report["uwm_contract"]["graph_context"] is True
    assert report["uwm_contract"]["renderer_trace"] is True
    assert "dynamic_rollout_required_for_superiority_claim" in report["remaining_gates"]
