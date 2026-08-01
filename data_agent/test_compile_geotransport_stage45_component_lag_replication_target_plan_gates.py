from __future__ import annotations

from scripts import (
    compile_geotransport_stage45_component_lag_replication_target_plan_gates as gates,
)


def test_stage45_all_gates_pass_with_values_pending_approval():
    report = gates.compile_report()

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 45
    assert sum(report["gates"].values()) == 45
    assert report["all_gates_passed"] is True
    assert report["decision"]["replication_target_request_plan_frozen"] is True
    assert report["decision"]["request_execution_authorized"] is False
    assert report["decision"]["fresh_user_approval_required"] is True
    assert report["decision"]["target_values_acquired"] is False
    assert report["decision"]["stage43_pattern_replicated"] is False
    assert report["decision"]["runtime_operator_admitted"] is False
