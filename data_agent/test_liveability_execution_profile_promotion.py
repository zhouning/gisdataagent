from __future__ import annotations

import copy

from data_agent import liveability_execution_profile_promotion as promotion


def test_current_liveability_promotion_binds_to_the_deployed_semantic_artifact() -> None:
    approved = promotion.load_liveability_execution_profile_promotion()

    assert approved["status"] == "approved"
    assert approved["authorization"]["source_id"] == 12
    assert approved["authorization"]["default_execution_profile"] == (
        "semantic_ir_experimental"
    )
    assert promotion.resolve_liveability_default_execution_profile() == (
        "semantic_ir_experimental"
    )


def test_default_profile_falls_back_when_promotion_record_is_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(promotion, "PROMOTION_PATH", tmp_path / "missing-promotion.json")

    assert promotion.resolve_liveability_default_execution_profile() == "baseline_sql"


def test_default_profile_falls_back_when_current_semantic_artifact_drifts(monkeypatch) -> None:
    current = promotion.current_artifact_manifest("liveability")
    drifted = copy.deepcopy(current)
    drifted["artifacts"]["semantic"]["sha256"] = "0" * 64
    monkeypatch.setattr(
        promotion,
        "current_artifact_manifest",
        lambda source_key: drifted,
    )

    assert promotion.resolve_liveability_default_execution_profile() == "baseline_sql"
