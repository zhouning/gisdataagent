import json

import pytest

from data_agent.paper9_agent_governance import (
    Paper9AuditPolicy,
    Paper9EpisodeStore,
    audit_paper9_run,
    evaluate_paper9_summary,
)


def _summary(*, cultivated=4.3, slope=-0.8, contiguity=0.02):
    return {
        "results": [
            {
                "episode": 0,
                "cultivated_area_change_ha": cultivated,
                "slope_change_pct": slope,
                "cont_change": contiguity,
                "baimu_area_change_ha": 34.6,
                "total_reward": 12.5,
                "steps_run": 50,
            }
        ]
    }


def test_hard_gate_passes_and_routes_to_verified_commit():
    result = evaluate_paper9_summary(_summary())

    assert result["hard_constraint_passed"] is True
    assert result["next_action"] == "commit_verified_episode"
    assert result["retryable"] is False


def test_first_hard_gate_failure_allows_one_bounded_replan():
    result = evaluate_paper9_summary(_summary(cultivated=-1.0), attempt=0)

    assert result["hard_constraint_passed"] is False
    assert result["next_action"] == "replan_once"
    assert result["retryable"] is True
    assert "below the required" in result["failure_reasons"][0]


def test_second_hard_gate_failure_stops_for_human_review():
    policy = Paper9AuditPolicy(max_replans=1)
    result = evaluate_paper9_summary(
        _summary(slope=0.1), policy=policy, attempt=1
    )

    assert result["hard_constraint_passed"] is False
    assert result["next_action"] == "stop_and_request_human_review"
    assert result["retryable"] is False


def test_run_audit_requires_summary_and_spatial_result(tmp_path):
    (tmp_path / "mpc_summary.json").write_text(
        json.dumps(_summary()), encoding="utf-8"
    )
    (tmp_path / "optimized_dltb.fgb").write_bytes(b"fgb")

    result = audit_paper9_run(tmp_path)

    assert result["hard_constraint_passed"] is True
    assert result["all_expected_outputs_exist"] is True
    assert result["artifacts"]["summary"]["sha256"]
    assert (tmp_path / "paper9_agent_audit.json").is_file()


def test_run_audit_fails_closed_when_spatial_result_is_missing(tmp_path):
    (tmp_path / "mpc_summary.json").write_text(
        json.dumps(_summary()), encoding="utf-8"
    )

    result = audit_paper9_run(tmp_path, write=False)

    assert result["hard_constraint_passed"] is False
    assert result["next_action"] == "stop_and_request_human_review"
    assert "No optimized spatial result" in result["failure_reasons"][-1]


def test_verified_episode_store_rejects_failed_runs(tmp_path):
    store = Paper9EpisodeStore(tmp_path / "episodes.jsonl")
    failed = evaluate_paper9_summary(_summary(slope=0.0))
    failed["all_expected_outputs_exist"] = True

    with pytest.raises(ValueError, match="hard-gate-passed"):
        store.commit(audit=failed, dataset="bishan", goal="optimize")


def test_verified_episode_store_is_idempotent_and_recallable(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "mpc_summary.json").write_text(
        json.dumps(_summary()), encoding="utf-8"
    )
    (run_dir / "optimized_dltb.fgb").write_bytes(b"fgb")
    audit = audit_paper9_run(run_dir)
    store = Paper9EpisodeStore(tmp_path / "episodes.jsonl")

    first = store.commit(
        audit=audit,
        dataset="bishan",
        goal="improve layout",
        plan_args={"horizon": 1, "top_k": 1},
        provenance={"algorithm_version": "2.2.3"},
    )
    second = store.commit(
        audit=audit,
        dataset="bishan",
        goal="improve layout",
        plan_args={"horizon": 1, "top_k": 1},
        provenance={"algorithm_version": "2.2.3"},
    )

    assert first["already_existed"] is False
    assert second["already_existed"] is True
    recalled = store.recall(dataset="bishan", limit=3)
    assert [item["episode_id"] for item in recalled] == [first["episode_id"]]
    assert recalled[0]["audit"]["hard_constraint_passed"] is True
