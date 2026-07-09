"""Build the full-admin UWM data-calibrated simulator mechanism table."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.data_calibrated_mechanism_table import (
    build_uwm_data_calibrated_mechanism_table,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "data_calibrated_mechanism_table_full_admin_graph_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_full_admin_graph_data_calibrated_mechanism_table.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    table = build_uwm_data_calibrated_mechanism_table(
        evidence_gate_path=DATA_ROOT
        / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json",
        noaa_weather_path=DATA_ROOT
        / "noaa_isd_weather_2024_07_01_07/noaa_isd_weather_proxy.json",
        admin_livability_panel_path=DATA_ROOT
        / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json",
        table_id="uwm-full-admin-graph-data-calibrated-mechanism-table-2026-07-08",
        created_at="2026-07-08T10:45:00+00:00",
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, table)
    _write_json(
        MANIFEST_PATH,
        {
            "snapshot_id": "uwm_full_admin_graph_data_calibrated_mechanism_table_2026_07_08",
            "created_at": table["created_at"],
            "schema": table["schema"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "source_artifacts": table["source_artifacts"],
            "admin_livability_row_count": table["calibration_evidence"][
                "admin_livability_row_count"
            ],
            "data_calibrated_mechanism_ready": table[
                "data_calibrated_mechanism_ready"
            ],
            "observed_policy_outcome_superiority_claim": table[
                "observed_policy_outcome_superiority_claim"
            ],
            "remaining_gates": table["remaining_gates"],
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "admin_livability_row_count": table["calibration_evidence"][
                    "admin_livability_row_count"
                ],
                "data_calibrated_mechanism_ready": table[
                    "data_calibrated_mechanism_ready"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
