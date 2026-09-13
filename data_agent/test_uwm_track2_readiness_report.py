import json
from pathlib import Path

from scripts.build_uwm_track2_readiness_report import build_track2_readiness_report


def test_build_track2_readiness_report_writes_claim_safe_json_and_markdown(tmp_path):
    repo_root = Path(".")
    output_dir = tmp_path / "track2_readiness"

    result = build_track2_readiness_report(
        repo_root=repo_root,
        output_dir=output_dir,
        current_date="2026-07-06",
    )

    json_path = Path(result["json_path"])
    markdown_path = Path(result["markdown_path"])
    assert json_path.exists()
    assert markdown_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    readiness = payload["world_model_evidence_readiness"]
    assert readiness["traditional_method_comparison_ready"] is True
    assert readiness["policy_outcome_superiority_ready"] is False
    assert readiness["system_level_superiority_summary"] == (
        "bounded_final_endpoint_and_endpoint_aligned_planner_advantage_without_policy_outcome_superiority"
    )
    assert "observed_policy_outcome_superiority" in readiness["forbidden_claims"]

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "bounded_final_endpoint_and_endpoint_aligned_planner_advantage_without_policy_outcome_superiority" in markdown
    assert "Bounded final system superiority ready: `True`" in markdown
    assert "observed_policy_outcome_superiority" in markdown
    assert "tap_external_temporal_dynamics_advantage_without_spatial_claim" in markdown
    assert "OSM admin mobility crosswalk projected in scene: `True`" in markdown
    assert "OSM assigned road segments in scene: `45449`" in markdown
    assert "Building floor 2.5D morphology ready: `True`" in markdown
    assert "Building floor assigned buildings: `44887`" in markdown
    assert "Building floor total floors: `322665`" in markdown
    assert "Building floor max floor: `66`" in markdown
    assert "Building floor true 3D claim: `False`" in markdown
    assert "Final livability endpoint suite ready: `True`" in markdown
    assert "Final endpoint mean relative MAE reduction: `0.115337`" in markdown
    assert "Endpoint-aligned planner evaluator ready: `True`" in markdown
    assert "Endpoint-aligned planner advantage: `0.0007457`" in markdown
    assert "Spatial spillover planner evaluator ready: `True`" in markdown
    assert "Spatial neighbor livability delta advantage: `0.272680076`" in markdown
    assert "Final livability decision package ready: `True`" in markdown
    assert "Final decision action count: `2`" in markdown
    assert "Final decision endpoint advantage: `0.0007457`" in markdown
    assert "Final decision best single-action advantage: `0.003837146`" in markdown
    assert "Final decision single-action empirical p-value: `0.002809`" in markdown
    assert "Final decision endpoint weight sensitivity min advantage: `0.0007457`" in markdown
    assert "Final decision risk-adjusted advantage: `0.012777213`" in markdown
    assert "Final decision neighbor delta advantage: `0.272680076`" in markdown
    assert "GraphDQN training ready: `True`" in markdown
    assert "GraphDQN algorithm: `graph_dqn_fitted_q_model_based_rl`" in markdown
    assert "GraphDQN value network trained: `True`" in markdown
    assert "GraphDQN training samples: `3600`" in markdown
    assert "GraphDQN advantage over static: `0.005131954`" in markdown
