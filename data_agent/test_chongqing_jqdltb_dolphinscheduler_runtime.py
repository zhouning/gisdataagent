from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from data_agent.platform_contracts import canonical_json_fingerprint
from scripts.certify_chongqing_jqdltb_dolphinscheduler_runtime import certify

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_certification_accepts_real_receipts_and_preserves_quality_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    runtime = ROOT / ".tmp/dolphinscheduler-sandbox"
    profile = runtime / "profile.json"
    required = [
        runtime / "jqdltb-deployment-report.json",
        runtime / "jqdltb-run-submission-report.json",
        runtime / "jqdltb-finalization-report.json",
    ]
    if not profile.is_file() or not all(path.is_file() for path in required):
        return

    # Keep the contract test deterministic; the CLI separately performs the
    # live HTTP/Docker health observation.
    monkeypatch.setattr(
        "scripts.certify_chongqing_jqdltb_dolphinscheduler_runtime._health",
        lambda profile: {"reachable": True, "status": "UP", "observation_source": "test"},
    )
    output = tmp_path / "runtime-certification.json"
    report = certify(profile_path=profile, runtime_dir=runtime, output=output)

    assert report["status"] == "passed"
    assert report["promotion_ready"] is False
    assert report["quality_verdict"] == "failed"
    assert report["data_product_version_created"] is False
    assert report["checks"]["provider_success"] is True
    assert report["checks"]["provider_health"] is True
    payload = json.loads(output.read_text(encoding="utf-8"))
    fingerprint = payload.pop("report_sha256")
    assert fingerprint == canonical_json_fingerprint(payload)


def test_runtime_certification_can_record_idempotent_run_bound_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    runtime = ROOT / ".tmp/dolphinscheduler-sandbox"
    profile = runtime / "profile.json"
    required = [
        runtime / "jqdltb-deployment-report.json",
        runtime / "jqdltb-run-submission-report.json",
        runtime / "jqdltb-finalization-report.json",
    ]
    if not profile.is_file() or not all(path.is_file() for path in required):
        return

    captured = []

    class FakeGateway:
        def record_artifact(self, artifact):
            captured.append(artifact)
            return SimpleNamespace(created=len(captured) == 1)

    monkeypatch.setattr(
        "scripts.certify_chongqing_jqdltb_dolphinscheduler_runtime._health",
        lambda profile: {"reachable": True, "status": "UP", "observation_source": "test"},
    )
    monkeypatch.setattr(
        "scripts.certify_chongqing_jqdltb_dolphinscheduler_runtime.PlatformGateway",
        FakeGateway,
    )
    output = tmp_path / "runtime-certification.json"
    report = certify(
        profile_path=profile,
        runtime_dir=runtime,
        output=output,
        record_artifact=True,
    )

    assert report["artifact_recorded"] is True
    assert report["artifact_created"] is True
    assert len(captured) == 1
    assert captured[0].run_id is not None
    assert captured[0].resource_version_id is not None
    assert captured[0].manifest["quality_verdict"] == "failed"

    replay = certify(
        profile_path=profile,
        runtime_dir=runtime,
        output=output,
        record_artifact=True,
    )

    assert replay["artifact_recorded"] is True
    assert replay["artifact_created"] is False
    assert len(captured) == 2
    assert captured[0].model_dump(mode="json") == captured[1].model_dump(mode="json")
