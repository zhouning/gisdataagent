from __future__ import annotations

from scripts.run_abu_dhabi_gwm_confirmatory_physics_batch import (
    DEFAULT_IMPLEMENTATION_ROOT,
    REPOSITORY_ROOT,
    select_pixel_qc_events,
)


def test_default_implementation_root_is_current_repository() -> None:
    assert DEFAULT_IMPLEMENTATION_ROOT == REPOSITORY_ROOT


def test_select_pixel_qc_events_excludes_failed_pixel_quality() -> None:
    receipt = {
        "events": [
            {"event_id": "admitted", "status": "completed", "pixel_qc_passed": True},
            {"event_id": "cloudy", "status": "completed", "pixel_qc_passed": False},
            {"event_id": "failed", "status": "failed", "pixel_qc_passed": True},
        ]
    }

    selected = select_pixel_qc_events(receipt)

    assert [event["event_id"] for event in selected] == ["admitted"]
