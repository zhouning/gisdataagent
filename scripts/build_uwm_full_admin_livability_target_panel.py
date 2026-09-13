"""Build the full-admin UWM livability target panel without dropping service gaps."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.admin_livability_targeting import (
    build_admin_livability_target_panel,
    validate_admin_livability_target_panel,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
EXPOSURE_PANEL_PATH = (
    DATA_ROOT
    / "admin_exposure_equity_2024_07_01_07/uwm_admin_exposure_equity_panel.json"
)
SERVICE_PANEL_PATH = (
    DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
)
OUTPUT_DIR = (
    DATA_ROOT / "admin_livability_target_full_admin_graph_2024_07_2026_07_08"
)
OUTPUT_JSON = OUTPUT_DIR / "uwm_admin_livability_target_full_admin_graph_panel.json"
OUTPUT_CSV = OUTPUT_DIR / "uwm_admin_livability_target_full_admin_graph_panel.csv"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    exposure_panel = _read_json(EXPOSURE_PANEL_PATH)
    service_panel = _read_json(SERVICE_PANEL_PATH)
    panel = build_admin_livability_target_panel(
        exposure_equity_panel=exposure_panel,
        admin_service_panel=service_panel,
        panel_id="uwm-admin-livability-target-full-admin-graph-2026-07-08",
        created_at="2026-07-08T10:30:00+00:00",
        experiment_scope="full_admin_graph",
    )
    validation = validate_admin_livability_target_panel(panel)
    if not validation["valid"]:
        raise SystemExit(f"invalid full admin livability target panel: {validation['errors']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_JSON, panel)
    _write_csv(OUTPUT_CSV, panel["admin_livability_target_rows"])
    _write_json(
        MANIFEST_PATH,
        {
            "dataset_id": "admin_livability_target_full_admin_graph_2024_07",
            "created_at": panel["created_at"],
            "schema": "uwm.snapshot_manifest.v1",
            "source_artifacts": {
                "admin_exposure_equity_panel": str(
                    EXPOSURE_PANEL_PATH.relative_to(REPO_ROOT)
                ),
                "full_admin_service_accessibility_surface": str(
                    SERVICE_PANEL_PATH.relative_to(REPO_ROOT)
                ),
            },
            "outputs": {
                "panel_json": str(OUTPUT_JSON.relative_to(REPO_ROOT)),
                "panel_csv": str(OUTPUT_CSV.relative_to(REPO_ROOT)),
            },
            "experiment_scope": panel["experiment_scope"],
            "source_admin_count": panel["source_admin_count"],
            "joined_admin_count": panel["joined_admin_count"],
            "service_matched_admin_count": panel["service_matched_admin_count"],
            "service_missing_admin_count": panel["service_missing_admin_count"],
            "claim_boundary": panel["claim_boundary"],
            "limitations": panel["limitations"],
        },
    )
    print(json.dumps({
        "output": str(OUTPUT_JSON.relative_to(REPO_ROOT)),
        "joined_admin_count": panel["joined_admin_count"],
        "service_missing_admin_count": panel["service_missing_admin_count"],
    }, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "admin_unit_id",
        "county",
        "township",
        "exposure_priority_score",
        "service_point_count",
        "essential_service_count",
        "service_coverage_status",
        "sample_gap_flag",
        "interpretable_as_true_service_absence",
        "livability_need_score",
        "target_candidate",
        "target_flags",
        "exposure_norm",
        "service_gap_norm",
        "essential_gap_norm",
        "service_accessibility_score",
        "service_gap_score",
        "estimated_nearest_essential_travel_time_min",
        "road_segment_count",
        "road_length_km",
        "mean_road_speed_kmh",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            components = row.get("score_components") or {}
            writer.writerow(
                {
                    "admin_unit_id": row.get("admin_unit_id"),
                    "county": row.get("county"),
                    "township": row.get("township"),
                    "exposure_priority_score": row.get("exposure_priority_score"),
                    "service_point_count": row.get("service_point_count"),
                    "essential_service_count": row.get("essential_service_count"),
                    "service_coverage_status": row.get("service_coverage_status"),
                    "sample_gap_flag": row.get("sample_gap_flag"),
                    "interpretable_as_true_service_absence": row.get(
                        "interpretable_as_true_service_absence"
                    ),
                    "livability_need_score": row.get("livability_need_score"),
                    "target_candidate": row.get("target_candidate"),
                    "target_flags": ";".join(row.get("target_flags") or []),
                    "exposure_norm": components.get("exposure_norm"),
                    "service_gap_norm": components.get("service_gap_norm"),
                    "essential_gap_norm": components.get("essential_gap_norm"),
                    "service_accessibility_score": row.get("service_accessibility_score"),
                    "service_gap_score": row.get("service_gap_score"),
                    "estimated_nearest_essential_travel_time_min": row.get(
                        "estimated_nearest_essential_travel_time_min"
                    ),
                    "road_segment_count": row.get("road_segment_count"),
                    "road_length_km": row.get("road_length_km"),
                    "mean_road_speed_kmh": row.get("mean_road_speed_kmh"),
                }
            )


if __name__ == "__main__":
    main()
