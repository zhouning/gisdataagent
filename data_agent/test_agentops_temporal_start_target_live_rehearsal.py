from __future__ import annotations

import json
import os

import pytest

from data_agent.agentops_temporal_start_target_live_rehearsal import (
    AgentOpsTemporalStartTargetLiveRehearsalReport,
    _run_live,
)


def test_live_start_target_report_is_hash_bound(tmp_path) -> None:
    report = {
        "schema_id": "gda.agentops-temporal-start-target-live-rehearsal.v1",
        "checked_at": "2026-08-27T00:00:00Z",
        "frontend_target": "127.0.0.1:7233",
        "namespace_ref": "gda-agentops-sandbox",
        "workflow_id": "gda-agent-test-live",
        "provider_run_id": "run-1",
        "temporal_sdk_version": "1.32.0",
        "temporal_history_event_count": 5,
        "target_status": "ready",
        "target_start_reconciliation_verdict": "already_exists_matched",
        "checks": {"real_temporal_history_is_observed": True},
        "passed": True,
        "failure_reasons": [],
    }
    from data_agent.platform_contracts import canonical_json_fingerprint

    report["report_sha256"] = canonical_json_fingerprint(report)
    value = AgentOpsTemporalStartTargetLiveRehearsalReport.model_validate(report)
    target = tmp_path / "live-start-target.json"
    target.write_text(json.dumps(value.model_dump(mode="json")))
    assert json.loads(target.read_text())["target_status"] == "ready"


@pytest.mark.skipif(
    not (
        os.environ.get("DATABASE_URL")
        and os.environ.get("GDA_AGENTOPS_TEMPORAL_FRONTEND")
    ),
    reason="live Temporal and PostgreSQL endpoints are not configured",
)
def test_real_live_temporal_start_target_rehearsal() -> None:
    report = __import__("asyncio").run(
        _run_live(
            frontend_target=os.environ["GDA_AGENTOPS_TEMPORAL_FRONTEND"],
            namespace_ref=os.environ.get(
                "GDA_AGENTOPS_TEMPORAL_NAMESPACE", "gda-agentops-sandbox"
            ),
            admin_url=os.environ["DATABASE_URL"],
        )
    )
    assert report.passed, report.failure_reasons
