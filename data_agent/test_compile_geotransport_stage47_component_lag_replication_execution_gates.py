from __future__ import annotations

from scripts import (
    compile_geotransport_stage47_component_lag_replication_execution_gates as gates,
)


def test_stage47_all_execution_gates_pass_with_targets_pending():
    report = gates.compile_report()

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 47
    assert sum(report["gates"].values()) == 47
    assert report["all_gates_passed"] is True
    assert report["decision"]["component_lag_replication_evidence_compiler_frozen"] is True
    assert report["decision"]["offline_assessment_runner_frozen"] is True
    assert report["decision"]["target_values_acquired"] is False
    assert report["decision"]["replication_test_executed"] is False
    assert report["decision"]["cohort_replication_admitted"] is False
    assert report["decision"]["runtime_operator_admitted"] is False
