import pytest

from scripts.rehearse_dolphinscheduler_governed_cancel import _cancel_blocker


@pytest.mark.parametrize(
    ("provider_state", "expected"),
    [
        ("READY_STOP", "remained READY_STOP"),
        ("FAILURE", "killed task as workflow FAILURE"),
        ("SUCCESS", "completed naturally"),
        ("PAUSE", "terminal observation was PAUSE"),
    ],
)
def test_cancel_blocker_reports_the_observed_provider_outcome(
    provider_state, expected
):
    assert expected in _cancel_blocker(provider_state)
