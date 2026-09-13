import json
from pathlib import Path

import pytest

from data_agent.uwm.public_feedback_readiness_service import PublicFeedbackReadinessService


FILES = ("overview", "capabilities", "feedback_channels", "data_contracts", "analysis_gate", "map")


def test_service_loads_consistent_closed_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "feedback-test"}
        if name == "feedback_channels": payload["feedback_channels"] = {"resident_surveys": {"status": "unavailable", "value": None}}
        if name == "analysis_gate": payload["analysis_gate"] = {"status": "closed", "mechanisms": {"sentiment_estimation": "closed"}}
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    service = PublicFeedbackReadinessService(tmp_path)
    assert service.feedback_channels()["feedback_channels"]["resident_surveys"]["value"] is None
    assert service.analysis_gate()["analysis_gate"]["status"] == "closed"


def test_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES): (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": str(index)}))
    with pytest.raises(ValueError, match="public_feedback_bundle_mismatch"):
        PublicFeedbackReadinessService(tmp_path)


def test_real_service_has_capabilities_but_no_public_feedback_observations():
    service = PublicFeedbackReadinessService(Path("data/uwm_public_proxy/chongqing_central/public_feedback_readiness_chongqing"))
    assert service.overview()["summary"]["capability_count"] == 7
    assert service.overview()["summary"]["published_feedback_observation_count"] == 0
    assert all(channel["value"] is None for channel in service.feedback_channels()["feedback_channels"].values())
    assert service.analysis_gate()["analysis_gate"]["uwm_observation_status"] == "closed"
