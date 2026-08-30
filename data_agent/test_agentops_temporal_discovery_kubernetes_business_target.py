from __future__ import annotations

import json

from data_agent.platform_contracts import canonical_json_fingerprint
from scripts.rehearse_agentops_temporal_discovery_kubernetes_business_target import (
    BusinessTargetRehearsalReport,
    _holder_code,
)


def test_business_target_rehearsal_report_is_hash_bound() -> None:
    report = {
        "checked_at": "2026-08-28T00:00:00Z",
        "namespace_ref": "gda-agentops-sandbox",
        "tenant_id": "local-dev",
        "workflow_id": "gda-agentops-k8s-business-target-test",
        "provider_run_id": "run-1",
        "temporal_server_version": "1.29.7",
        "temporal_sdk_version": "1.32.0",
        "first_claimed_by": "workload:agentops-discovery:holder",
        "takeover_claimed_by": "workload:agentops-discovery:discovery-1",
        "takeover_pod_name": "discovery-1",
        "first_claimed_at": "2026-08-28T00:00:00Z",
        "takeover_observed_at": "2026-08-28T00:01:02Z",
        "lease_wait_seconds": 62.0,
        "target_attempt_count": 2,
        "temporal_history_event_count": 4,
        "history_sha256": "a" * 64,
        "checks": {
            "first_discovery_pod_claimed_target": True,
            "second_worker_observed_temporal_input": True,
        },
        "passed": True,
        "failure_reasons": [],
        "production_readiness_claimed": False,
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    value = BusinessTargetRehearsalReport.model_validate(report)
    assert value.passed is True
    assert json.loads(value.model_dump_json())["target_attempt_count"] == 2


def test_business_target_holder_code_compiles() -> None:
    compile(_holder_code("00000000-0000-0000-0000-000000000001"), "<holder>", "exec")
