from __future__ import annotations

from scripts.rehearse_agentops_temporal_flink_cancellation import _report_fingerprint


def test_flink_cancellation_report_fingerprint_excludes_previous_hash() -> None:
    report = {"schema": "test", "status": "passed", "checks": {"ok": True}}
    first = _report_fingerprint(report)
    report["report_sha256"] = first
    assert _report_fingerprint(report) == first
    report["report_sha256"] = "f" * 64
    assert _report_fingerprint(report) == first
