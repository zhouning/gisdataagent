#!/usr/bin/env python3
"""Verify CONTROLLED-C2 artifacts without retraining the ten formal models."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


DRAFT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DRAFT_ROOT.parents[1]
if str(DRAFT_ROOT) not in sys.path:
    sys.path.insert(0, str(DRAFT_ROOT))

from run_controlled_c2 import (
    CONTRACT_PATH,
    CORPUS_MANIFEST_PATH,
    FINAL_PATH,
    SEED_ROOT,
    _control_direction_checks,
    _fingerprint,
    _load_json,
    _sha256_file,
    _stability_checks,
    _utc_now,
    _write_json_atomic,
    build_corpus_manifest,
)


DEFAULT_OUTPUT = DRAFT_ROOT / "controlled_c2/controlled_c2_verification.json"


def _seed_identity(record: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "created_at",
        "wall_time_seconds",
        "peak_rss_bytes",
        "seed_result_fingerprint",
    }
    return {key: value for key, value in record.items() if key not in excluded}


def _final_identity(record: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "created_at",
        "environment",
        "controlled_c2_results_fingerprint",
    }
    return {key: value for key, value in record.items() if key not in excluded}


def verify(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    contract = _load_json(CONTRACT_PATH)
    final = _load_json(FINAL_PATH)
    stored_manifest = _load_json(CORPUS_MANIFEST_PATH)
    regenerated_manifest = build_corpus_manifest(contract)
    checks: dict[str, bool] = {
        "status_is_stability_pass": final["status"]
        == "CONTROLLED_C2_COMPLETED_STABILITY_PASS",
        "contract_hash_matches": final["contract_sha256"]
        == _sha256_file(CONTRACT_PATH),
        "runner_hash_matches": final["runner_sha256"]
        == _sha256_file(DRAFT_ROOT / "run_controlled_c2.py"),
        "final_fingerprint_matches": final["controlled_c2_results_fingerprint"]
        == _fingerprint(_final_identity(final)),
        "stored_manifest_fingerprint_matches": stored_manifest[
            "manifest_fingerprint"
        ]
        == _fingerprint(
            {
                key: value
                for key, value in stored_manifest.items()
                if key != "manifest_fingerprint"
            }
        ),
        "regenerated_manifest_matches": regenerated_manifest[
            "manifest_fingerprint"
        ]
        == stored_manifest["manifest_fingerprint"]
        == final["corpus_manifest_fingerprint"],
        "all_hidden_factor_checks_pass": all(
            regenerated_manifest["hidden_factor_checks"].values()
        ),
        "minimum_sample_count_met": final["sample_count"]
        >= int(contract["minimum_sample_count"]),
        "exact_formal_seed_set_present": final["fit_seeds"]
        == contract["fit_seeds"],
        "all_seed_artifacts_verify": True,
        "all_required_controls_reported": True,
        "stability_pass_count_recomputes": True,
        "all_recorded_code_artifacts_match": True,
    }
    seed_verification = {}
    recomputed_pass_count = 0
    required_variants = {
        "no_action_conditioning",
        "fixed_topology",
        "single_relation",
        "no_lag_structure",
    }
    required_corruptions = {
        "action_assignment_shuffle",
        "relation_type_shuffle",
        "spatial_target_rewire",
    }
    for seed in contract["fit_seeds"]:
        path = SEED_ROOT / f"seed_{seed}.json"
        artifact = final["seed_artifacts"].get(str(seed), {})
        path_exists = path.is_file()
        if not path_exists:
            checks["all_seed_artifacts_verify"] = False
            seed_verification[str(seed)] = {"path_exists": False}
            continue
        record = _load_json(path)
        fingerprint_matches = record["seed_result_fingerprint"] == _fingerprint(
            _seed_identity(record)
        )
        artifact_matches = (
            artifact.get("sha256") == _sha256_file(path)
            and artifact.get("seed_result_fingerprint")
            == record["seed_result_fingerprint"]
        )
        controls_reported = required_variants.issubset(record["variants"]) and (
            required_corruptions.issubset(record["input_corruption_controls"])
        )
        recomputed_controls = _control_direction_checks(
            variants=record["variants"],
            corruptions=record["input_corruption_controls"],
        )
        control_checks_match = recomputed_controls == record[
            "control_direction_checks"
        ]
        recomputed_stability_checks, recomputed_stability = _stability_checks(
            contract=contract,
            variants=record["variants"],
            control_checks=recomputed_controls,
        )
        stability_matches = (
            recomputed_stability_checks == record["stability_checks"]
            and recomputed_stability == record["stability_passed"]
        )
        code_artifacts_match = all(
            (REPO_ROOT / value["path"]).is_file()
            and _sha256_file(REPO_ROOT / value["path"]) == value["sha256"]
            for value in record["code_artifacts"].values()
        )
        passed = (
            fingerprint_matches
            and artifact_matches
            and controls_reported
            and control_checks_match
            and stability_matches
            and code_artifacts_match
        )
        checks["all_seed_artifacts_verify"] &= passed
        checks["all_required_controls_reported"] &= controls_reported
        checks["all_recorded_code_artifacts_match"] &= code_artifacts_match
        recomputed_pass_count += int(recomputed_stability)
        seed_verification[str(seed)] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": _sha256_file(path),
            "fingerprint_matches": fingerprint_matches,
            "artifact_matches": artifact_matches,
            "controls_reported": controls_reported,
            "control_checks_match": control_checks_match,
            "stability_matches": stability_matches,
            "code_artifacts_match": code_artifacts_match,
            "stability_passed": recomputed_stability,
            "passed": passed,
        }
    checks["stability_pass_count_recomputes"] = (
        recomputed_pass_count == final["stability_pass_count"]
        and recomputed_pass_count >= int(contract["required_stability_pass_count"])
    )
    passed = all(checks.values())
    identity = {
        "schema": "gwm_bench.foundation_v3_controlled_c2_verification.v1",
        "suite_id": contract["suite_id"],
        "track_id": contract["track_id"],
        "status": "PASS_CONTROLLED_C2_VERIFIED"
        if passed
        else "FAIL_CONTROLLED_C2_VERIFICATION",
        "checks": checks,
        "stability_pass_count": recomputed_pass_count,
        "required_stability_pass_count": int(
            contract["required_stability_pass_count"]
        ),
        "controlled_c2_results_fingerprint": final[
            "controlled_c2_results_fingerprint"
        ],
        "corpus_manifest_fingerprint": stored_manifest["manifest_fingerprint"],
        "seed_verification": seed_verification,
    }
    report = {
        **identity,
        "created_at": _utc_now(),
        "verification_fingerprint": _fingerprint(identity),
    }
    _write_json_atomic(report, output_path)
    if not passed:
        raise RuntimeError(report["status"])
    print(report["status"])
    print(f"stability: {recomputed_pass_count}/{len(contract['fit_seeds'])}")
    print(
        "controlled_c2_results_fingerprint: "
        f"{final['controlled_c2_results_fingerprint']}"
    )
    print(f"verification: {output_path}")
    return report


if __name__ == "__main__":
    verify()
