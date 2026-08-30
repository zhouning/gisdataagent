from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_ar0_first_vertical_slice_freeze import DEFAULT_MANIFEST, verify_manifest


def test_ar0_first_vertical_slice_manifest_is_valid_and_not_promotable() -> None:
    report = verify_manifest()

    assert report["valid"] is True
    assert report["status"] == "awaiting_business_approval"
    assert report["promotion_ready"] is False
    assert report["source_quality_verdict"] == "failed"
    assert report["checks"]["repair_diagnostic_fingerprint"] is True
    assert report["checks"]["repair_diagnostic_findings"] is True
    assert report["checks"]["semantic_candidate_audit_fingerprint"] is True
    assert report["checks"]["semantic_candidate_audit_identity"] is True
    assert report["checks"]["semantic_candidate_audit_findings"] is True
    assert report["checks"]["semantic_candidate_audit_read_only"] is True
    assert report["checks"]["transformation_impact_preview_fingerprint"] is True
    assert report["checks"]["transformation_impact_preview_read_only"] is True
    assert report["checks"]["transformation_impact_preview_identity"] is True
    assert report["checks"]["transformation_impact_preview_matrix"] is True
    assert report["checks"]["dolphinscheduler_runtime_binding"] is True
    assert report["checks"]["dolphinscheduler_runtime_certification"] is True
    assert report["checks"]["dolphinscheduler_runtime_fingerprint"] is True
    assert set(report["unresolved_approvals"]) == {
        "business_steward",
        "license_status",
        "slo_on_call",
    }


def test_ar0_promotable_status_fails_closed_until_evidence_and_approval_exist(
    tmp_path: Path,
) -> None:
    source = DEFAULT_MANIFEST
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["status"] = "promotable"
    candidate = tmp_path / source.name
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="promotable"):
        verify_manifest(candidate)


def test_ar0_manifest_rejects_repair_diagnostic_fingerprint_drift(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["evidence"]["quality_repair_diagnostic_sha256"] = "0" * 64
    candidate = tmp_path / DEFAULT_MANIFEST.name
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    report = verify_manifest(candidate)

    assert report["valid"] is False
    assert report["checks"]["repair_diagnostic_fingerprint"] is False
