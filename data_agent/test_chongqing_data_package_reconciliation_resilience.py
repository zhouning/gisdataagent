from __future__ import annotations

import json

from data_agent.chongqing_data_package_reconciliation_resilience import (
    SCENARIOS,
    run_chongqing_reconciliation_resilience_rehearsal,
    write_chongqing_reconciliation_resilience_report,
)
from data_agent.platform_contracts import canonical_json_fingerprint


def test_rehearsal_covers_all_declared_failure_boundaries():
    report = run_chongqing_reconciliation_resilience_rehearsal(iterations=5)

    assert report.failed_count == 0
    assert report.passed_count == len(SCENARIOS)
    assert {item.scenario for item in report.scenario_results} == set(SCENARIOS)
    assert report.production_capacity_certified is False
    assert report.capacity_scope == "in_memory_worker_orchestration_only"


def test_rehearsal_report_is_fingerprinted_and_serializable(tmp_path):
    report = run_chongqing_reconciliation_resilience_rehearsal(iterations=3)
    target = write_chongqing_reconciliation_resilience_report(
        report,
        tmp_path / "resilience.json",
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    supplied = payload.pop("report_sha256")

    assert supplied == canonical_json_fingerprint(payload)
    assert payload["decision_status"] == "assisted_precheck_not_for_production_decision"
