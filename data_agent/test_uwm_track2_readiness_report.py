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
        "bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority"
    )
    assert "observed_policy_outcome_superiority" in readiness["forbidden_claims"]

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority" in markdown
    assert "observed_policy_outcome_superiority" in markdown
    assert "tap_external_temporal_dynamics_advantage_without_spatial_claim" in markdown
