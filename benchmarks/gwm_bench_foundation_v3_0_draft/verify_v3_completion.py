#!/usr/bin/env python3
"""Verify the all-track V3 completion manifest without rescoring or retraining."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DRAFT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DRAFT_ROOT.parents[1]
FINAL_ROOT = DRAFT_ROOT / "final_results"
MANIFEST_PATH = FINAL_ROOT / "v3_completion_manifest.json"
DEFAULT_OUTPUT = FINAL_ROOT / "v3_completion_verification.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def verify(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    manifest = _load(MANIFEST_PATH)
    protocol = _load(DRAFT_ROOT / "suite_protocol.json")
    observed = _load(FINAL_ROOT / "final_results.json")
    c2 = _load(DRAFT_ROOT / "controlled_c2/controlled_c2_results.json")
    replay = _load(DRAFT_ROOT / "predictions/runtime_replay_report.json")
    identity = {
        key: value
        for key, value in manifest.items()
        if key not in {"created_at", "v3_completion_fingerprint"}
    }
    artifact_checks = {}
    all_artifacts_match = True
    for name, artifact in manifest["artifacts"].items():
        path = REPO_ROOT / artifact["path"]
        passed = (
            path.is_file()
            and path.stat().st_size == artifact["size_bytes"]
            and _sha256(path) == artifact["sha256"]
        )
        artifact_checks[name] = {
            "path": artifact["path"],
            "passed": passed,
        }
        all_artifacts_match &= passed
    checks = {
        "status_is_all_tracks_completed": manifest["status"]
        == "V3_ALL_TRACKS_COMPLETED_VERIFIED",
        "completion_fingerprint_matches": manifest["v3_completion_fingerprint"]
        == _fingerprint(identity),
        "completion_gate_names_match_frozen_protocol": list(
            manifest["completion_gates"]
        )
        == protocol["completion_gates"],
        "all_nine_completion_gates_pass": len(manifest["completion_gates"]) == 9
        and all(
            value["passed"] for value in manifest["completion_gates"].values()
        ),
        "all_completion_artifacts_match": all_artifacts_match,
        "runtime_track_matches": manifest["tracks"]["RUNTIME-R2"]["status"]
        == replay["status"],
        "observed_track_matches": manifest["tracks"]["OBSERVED-O3"][
            "final_results_fingerprint"
        ]
        == observed["final_results_fingerprint"],
        "controlled_track_matches": manifest["tracks"]["CONTROLLED-C2"][
            "controlled_c2_results_fingerprint"
        ]
        == c2["controlled_c2_results_fingerprint"],
        "controlled_stability_gate_matches": manifest["tracks"][
            "CONTROLLED-C2"
        ]["stability_pass_count"]
        == c2["stability_pass_count"]
        >= c2["required_stability_pass_count"],
        "observed_formal_scoring_event_remains_one": observed[
            "formal_scoring_event_count"
        ]
        == 1,
    }
    passed = all(checks.values())
    verification_identity = {
        "schema": "gwm_bench.foundation_v3_completion_verification.v1",
        "suite_id": manifest["suite_id"],
        "status": "PASS_V3_ALL_TRACKS_COMPLETION_VERIFIED"
        if passed
        else "FAIL_V3_ALL_TRACKS_COMPLETION_VERIFICATION",
        "checks": checks,
        "artifacts": artifact_checks,
        "v3_completion_fingerprint": manifest["v3_completion_fingerprint"],
        "observed_o3_final_results_fingerprint": observed[
            "final_results_fingerprint"
        ],
        "controlled_c2_results_fingerprint": c2[
            "controlled_c2_results_fingerprint"
        ],
    }
    report = {
        **verification_identity,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verification_fingerprint": _fingerprint(verification_identity),
    }
    _write_json_atomic(report, output_path)
    if not passed:
        raise RuntimeError(report["status"])
    print(report["status"])
    print(f"v3_completion_fingerprint: {manifest['v3_completion_fingerprint']}")
    print(f"verification: {output_path}")
    return report


if __name__ == "__main__":
    verify()
