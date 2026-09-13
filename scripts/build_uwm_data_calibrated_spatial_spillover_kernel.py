"""Build data-calibrated spatial spillover kernel for UWM livability planning."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.spatial_spillover_kernel import (
    build_uwm_data_calibrated_spatial_spillover_kernel,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "data_calibrated_spatial_spillover_kernel_2026_07_07"
OUTPUT_PATH = OUTPUT_DIR / "uwm_data_calibrated_spatial_spillover_kernel.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
ADMIN_GRAPH_PATH = (
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
ADMIN_PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)


def main() -> None:
    kernel = build_uwm_data_calibrated_spatial_spillover_kernel(
        admin_spatial_graph=_read_json(ADMIN_GRAPH_PATH),
        admin_livability_panel=_read_json(ADMIN_PANEL_PATH),
        kernel_id="uwm-data-calibrated-spatial-spillover-kernel-2026-07-07",
        created_at="2026-07-07T18:45:00Z",
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, kernel)
    manifest = {
        "snapshot_id": "uwm_data_calibrated_spatial_spillover_kernel_2026_07_07",
        "created_at": "2026-07-07T18:45:00Z",
        "kernel_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_admin_spatial_graph_path": str(
            ADMIN_GRAPH_PATH.relative_to(REPO_ROOT)
        ),
        "source_admin_livability_panel_path": str(
            ADMIN_PANEL_PATH.relative_to(REPO_ROOT)
        ),
        "data_calibrated_spatial_spillover_kernel_ready": kernel[
            "data_calibrated_spatial_spillover_kernel_ready"
        ],
        "directional_edge_count": kernel["summary"]["directional_edge_count"],
        "kernel_source_unit_count": kernel["summary"]["kernel_source_unit_count"],
        "max_spillover_factor": kernel["summary"]["max_spillover_factor"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "kernel_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "ready": kernel["data_calibrated_spatial_spillover_kernel_ready"],
                "directional_edge_count": kernel["summary"]["directional_edge_count"],
                "kernel_source_unit_count": kernel["summary"]["kernel_source_unit_count"],
                "min_spillover_factor": kernel["summary"]["min_spillover_factor"],
                "max_spillover_factor": kernel["summary"]["max_spillover_factor"],
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
