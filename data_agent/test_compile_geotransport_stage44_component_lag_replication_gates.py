from __future__ import annotations

from scripts import (
    compile_geotransport_stage44_component_lag_replication_gates as gates,
)


def test_stage44_all_gates_pass_with_replication_still_pending():
    report = gates.compile_report()

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 44
    assert sum(report["gates"].values()) == 44
    assert report["all_gates_passed"] is True
    assert report["decision"]["source_only_replication_cohort_frozen"] is True
    assert report["decision"]["target_request_plan_created"] is False
    assert report["decision"]["stage43_pattern_replicated"] is False
    assert report["decision"]["stage30_historical_falsification_overturned"] is False
    assert report["decision"]["runtime_operator_admitted"] is False
