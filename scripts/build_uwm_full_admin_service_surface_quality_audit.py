"""Build the full-admin service surface quality audit from the full local surface."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.full_admin_service_surface_quality import (
    build_full_admin_service_surface_quality_audit,
    validate_full_admin_service_surface_quality_audit,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
SURFACE_PATH = (
    DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
)
OUTPUT_DIR = DATA_ROOT / "full_admin_service_surface_quality_audit_2026_07_08"
OUTPUT_JSON = OUTPUT_DIR / "uwm_full_admin_service_surface_quality_audit.json"
OUTPUT_CSV = OUTPUT_DIR / "uwm_full_admin_service_surface_quality_audit_endpoints.csv"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    service_surface = _read_json(SURFACE_PATH)
    audit = build_full_admin_service_surface_quality_audit(
        service_surface=service_surface,
        audit_id="uwm-full-admin-service-surface-quality-audit-2026-07-08",
        created_at="2026-07-08T17:30:00Z",
        source_surface_path=str(SURFACE_PATH.relative_to(REPO_ROOT)),
    )
    validation = validate_full_admin_service_surface_quality_audit(audit)
    if not validation["valid"]:
        raise SystemExit(f"invalid full-admin service surface quality audit: {validation['errors']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_JSON, audit)
    _write_endpoint_csv(OUTPUT_CSV, audit["endpoint_evaluations"])
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_full_admin_service_surface_quality_audit_2026_07_08",
            "created_at": audit["created_at"],
            "source_artifacts": {
                "full_admin_service_accessibility_surface": str(
                    SURFACE_PATH.relative_to(REPO_ROOT)
                ),
            },
            "outputs": {
                "audit_json": str(OUTPUT_JSON.relative_to(REPO_ROOT)),
                "endpoint_csv": str(OUTPUT_CSV.relative_to(REPO_ROOT)),
            },
            "admin_unit_count": audit["admin_unit_count"],
            "endpoint_count": audit["endpoint_count"],
            "ready_endpoint_count": audit["ready_endpoint_count"],
            "supported_claim": audit["supported_claim"],
            "claim_boundary": audit["claim_boundary"],
            "limitations": audit["limitations"],
        },
    )
    endpoints = {
        endpoint["endpoint_id"]: endpoint
        for endpoint in audit["endpoint_evaluations"]
    }
    print(
        json.dumps(
            {
                "path": str(OUTPUT_JSON.relative_to(REPO_ROOT)),
                "admin_unit_count": audit["admin_unit_count"],
                "endpoint_count": audit["endpoint_count"],
                "ready_endpoint_count": audit["ready_endpoint_count"],
                "essential_service_model_mae": endpoints[
                    "essential_service_count_proxy"
                ]["model_mae"],
                "essential_service_best_baseline_mae": endpoints[
                    "essential_service_count_proxy"
                ]["best_baseline_mae"],
                "travel_time_model_mae": endpoints[
                    "estimated_nearest_essential_travel_time_proxy"
                ]["model_mae"],
                "travel_time_best_baseline_mae": endpoints[
                    "estimated_nearest_essential_travel_time_proxy"
                ]["best_baseline_mae"],
                "supported_claim": audit["supported_claim"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_endpoint_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "endpoint_id",
        "target",
        "model",
        "holdout_admin_unit_count",
        "model_mae",
        "best_baseline_id",
        "best_baseline_mae",
        "mae_reduction_vs_best_baseline",
        "target_rotation_negative_control_mae",
        "target_rotation_negative_control_margin",
        "beats_best_baseline",
        "target_rotation_negative_control_passed",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


if __name__ == "__main__":
    main()
