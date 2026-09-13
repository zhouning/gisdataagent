import pytest

from data_agent.uwm.public_feedback_readiness import build_public_feedback_readiness_product


def test_public_feedback_product_is_fail_closed_without_customer_corpus():
    product = build_public_feedback_readiness_product(
        capabilities=[{"capability_id": "geocoding", "source_path": "geocoding.py", "status": "implemented_capability"}],
        source_artifacts=["geocoding.py"],
    )
    assert product["schema"] == "uwm.public_feedback_readiness.v1"
    assert all(channel["status"] == "unavailable" and channel["value"] is None for channel in product["feedback_channels"].values())
    assert all(value == "closed" for value in product["analysis_gate"]["mechanisms"].values())
    assert product["claim_boundary"]["agent_vote_not_urban_public_opinion"] is True
    assert product["claim_boundary"]["missing_feedback_not_absence_of_concern"] is True
    assert product["fabricated_value_count"] == 0


def test_platform_feedback_capability_cannot_be_public_observation():
    with pytest.raises(ValueError, match="platform_feedback_not_public_observation"):
        build_public_feedback_readiness_product(
            capabilities=[{"capability_id": "agent-votes", "source_path": "feedback.py", "status": "observed_public_feedback"}],
            source_artifacts=["feedback.py"],
        )
