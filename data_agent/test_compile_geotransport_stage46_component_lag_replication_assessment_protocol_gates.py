from __future__ import annotations

from scripts import (
    compile_geotransport_stage46_component_lag_replication_assessment_protocol_gates as gates,
)


def test_stage46_all_protocol_gates_pass_with_targets_pending():
    report = gates.compile_report()

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 46
    assert sum(report["gates"].values()) == 46
    assert report["all_gates_passed"] is True
    assert report["decision"]["component_lag_replication_assessment_operator_frozen"] is True
    assert report["decision"]["assessment_protocol_frozen_before_target_values"] is True
    assert report["decision"]["target_values_acquired"] is False
    assert report["decision"]["replication_test_executed"] is False
    assert report["decision"]["cohort_replication_admitted"] is False
    assert report["decision"]["runtime_operator_admitted"] is False
