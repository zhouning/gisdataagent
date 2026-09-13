#!/usr/bin/env python3
"""Seal the V3 runtime, submission and evaluator contracts before predictions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = ROOT / "suite_protocol.json"
DEFAULT_OUTPUT = ROOT / "runtime_r2_evaluator_seal.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def freeze(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    state = protocol["current_state"]
    required_state = (
        protocol["status"]
        == "draft_runtime_r2_evaluator_sealed_predictions_pending"
        and state["protocol_frozen"]
        and state["phase_a_bundle_verified"]
        and state["runtime_r2_contract_frozen"]
        and state["submission_contract_frozen"]
        and state["evaluator_conformance_passed"]
        and state["evaluator_sealed"]
        and not state["predictions_committed"]
        and not state["target_labels_acquired"]
        and not state["scores_available"]
    )
    if not required_state:
        raise ValueError("runtime_r2_protocol_state_not_ready_for_seal")

    target_root = REPO_ROOT / protocol["dataset"]["phase_c_target_root"]
    target_files = (
        [path for path in target_root.rglob("*") if path.is_file()]
        if target_root.exists()
        else []
    )
    if target_files:
        raise RuntimeError("refusing_runtime_seal_after_target_acquisition")

    conformance_path = ROOT / "evaluator_conformance_report.json"
    conformance = _load_json(conformance_path)
    bundle_verification_path = ROOT / "phase_a_bundle_verification.json"
    bundle_verification = _load_json(bundle_verification_path)
    if conformance["status"] != "PASS_EVALUATOR_CONFORMANCE":
        raise ValueError("evaluator_conformance_not_passed")
    if bundle_verification["status"] != "PASS_PHASE_A_BUNDLE_VERIFIED":
        raise ValueError("phase_a_bundle_not_verified")

    paths_and_roles = [
        (ROOT / "runtime_r2_contract.json", "runtime_lifecycle_contract"),
        (ROOT / "submission_contract.json", "prediction_and_label_contract"),
        (ROOT / "observed_o3_evaluator.py", "sealed_reference_evaluator"),
        (ROOT / "run_evaluator_conformance.py", "evaluator_conformance_runner"),
        (conformance_path, "evaluator_conformance_evidence"),
        (ROOT / "phase_a_bundle/bundle_manifest.json", "phase_a_bundle_manifest"),
        (bundle_verification_path, "phase_a_bundle_verification"),
        (ROOT / "preflight_report.json", "label_firewall_preflight"),
    ]
    artifacts = {
        path.name: _artifact(path, role) for path, role in paths_and_roles
    }
    seal = {
        "schema": "gwm_bench.runtime_r2_evaluator_seal.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "RUNTIME_R2_AND_EVALUATOR_SEALED_PREDICTIONS_PENDING",
        "suite_protocol_sha256": _sha256(PROTOCOL_PATH),
        "bundle_fingerprint": bundle_verification["bundle_fingerprint"],
        "evaluator_conformance_check_count": conformance["check_count"],
        "artifacts": artifacts,
        "integrity": {
            "protocol_frozen": True,
            "predictions_committed": False,
            "target_file_count": 0,
            "target_pixels_read": False,
            "scoring_permitted": False,
        },
        "next_permitted_action": "Run and hash TWM, FLUS and three internal baseline predictions.",
    }
    seal["seal_fingerprint"] = _fingerprint(
        {
            "suite_id": seal["suite_id"],
            "suite_protocol_sha256": seal["suite_protocol_sha256"],
            "bundle_fingerprint": seal["bundle_fingerprint"],
            "artifacts": seal["artifacts"],
            "integrity": seal["integrity"],
        }
    )
    output_path.write_text(
        json.dumps(seal, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench V3 runtime/evaluator: {seal['status']}")
    print(f"Seal: {output_path}")
    return seal


if __name__ == "__main__":
    freeze()
