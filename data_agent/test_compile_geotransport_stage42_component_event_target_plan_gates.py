from __future__ import annotations

from scripts import (
    compile_geotransport_stage42_component_event_target_plan_gates as gates,
)


def test_stage42_compiled_plan_report_requires_approval_and_rejects_promotions():
    report = gates.compile_report()

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 37
    assert sum(report["gates"].values()) == 37
    assert report["all_gates_passed"] is True
    assert report["decision"]["planned_logical_request_count"] == 8
    assert report["decision"]["target_values_acquired"] is False
    assert report["decision"][
        "fresh_user_approval_required_before_target_requests"
    ] is True
    assert report["decision"]["non_turbine_component_contrast_admitted"] is False
    assert report["decision"]["physical_response_time_admitted"] is False
