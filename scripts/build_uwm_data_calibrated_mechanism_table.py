"""Build UWM data-calibrated simulator mechanism table."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.data_calibrated_mechanism_table import (
    build_uwm_data_calibrated_mechanism_table,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06"
)
OUTPUT_PATH = OUTPUT_DIR / "uwm_data_calibrated_mechanism_table.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    table = build_uwm_data_calibrated_mechanism_table(
        evidence_gate_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json",
        noaa_weather_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/noaa_isd_weather_2024_07_01_07/noaa_isd_weather_proxy.json",
        admin_livability_panel_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/admin_livability_target_complete_bbox_2024_07_2026_07_05/uwm_admin_livability_target_complete_bbox_panel.json",
        table_id="uwm-data-calibrated-mechanism-table-2026-07-06",
        created_at="2026-07-06T18:30:00Z",
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(table, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    snapshot = {
        "snapshot_id": "uwm_data_calibrated_mechanism_table_2026_07_06",
        "created_at": "2026-07-06T18:30:00Z",
        "schema": table["schema"],
        "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_artifacts": table["source_artifacts"],
        "data_calibrated_mechanism_ready": table["data_calibrated_mechanism_ready"],
        "hardcoded_mechanism_replacement_ready": table[
            "hardcoded_mechanism_replacement_ready"
        ],
        "observed_policy_outcome_superiority_claim": table[
            "observed_policy_outcome_superiority_claim"
        ],
        "remaining_gates": table["remaining_gates"],
    }
    with MANIFEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
                "data_calibrated_mechanism_ready": table[
                    "data_calibrated_mechanism_ready"
                ],
                "hardcoded_mechanism_replacement_ready": table[
                    "hardcoded_mechanism_replacement_ready"
                ],
                "traffic_air_pollution_delta": table["mechanism_coefficients"][
                    "traffic_emission_control"
                ]["air_pollution_exposure_delta"],
                "green_heat_delta": table["mechanism_coefficients"][
                    "increase_green_infrastructure"
                ]["heat_risk_delta"],
                "service_accessibility_delta": table["mechanism_coefficients"][
                    "add_community_service"
                ]["service_accessibility_delta"],
                "observed_policy_outcome_superiority_claim": table[
                    "observed_policy_outcome_superiority_claim"
                ],
                "remaining_gates": table["remaining_gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
