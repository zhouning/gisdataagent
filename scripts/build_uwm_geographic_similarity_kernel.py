"""Build full-admin geographic-configuration similarity kernel for UWM."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.geographic_similarity_kernel import (
    build_uwm_geographic_similarity_kernel,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "geographic_similarity_kernel_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_geographic_similarity_kernel.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
ADMIN_GRAPH_PATH = (
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
FULL_ADMIN_PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
)


def main() -> None:
    kernel = build_uwm_geographic_similarity_kernel(
        admin_livability_panel=_read_json(FULL_ADMIN_PANEL_PATH),
        admin_spatial_graph=_read_json(ADMIN_GRAPH_PATH),
        kernel_id="uwm-geographic-similarity-kernel-2026-07-08",
        created_at="2026-07-08T15:30:00Z",
        top_k=5,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, kernel)
    manifest = {
        "snapshot_id": "uwm_geographic_similarity_kernel_2026_07_08",
        "created_at": "2026-07-08T15:30:00Z",
        "kernel_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_admin_spatial_graph_path": str(
            ADMIN_GRAPH_PATH.relative_to(REPO_ROOT)
        ),
        "source_full_admin_livability_panel_path": str(
            FULL_ADMIN_PANEL_PATH.relative_to(REPO_ROOT)
        ),
        "geographic_similarity_kernel_ready": kernel[
            "geographic_similarity_kernel_ready"
        ],
        "panel_unit_count": kernel["summary"]["panel_unit_count"],
        "kernel_source_unit_count": kernel["summary"]["kernel_source_unit_count"],
        "similarity_edge_count": kernel["summary"]["similarity_edge_count"],
        "non_adjacent_similarity_edge_count": kernel["summary"][
            "non_adjacent_similarity_edge_count"
        ],
        "rotated_target_similarity_control_passed": kernel["negative_controls"][
            "rotated_target_similarity_control_passed"
        ],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "kernel_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "ready": kernel["geographic_similarity_kernel_ready"],
                "panel_unit_count": kernel["summary"]["panel_unit_count"],
                "kernel_source_unit_count": kernel["summary"][
                    "kernel_source_unit_count"
                ],
                "similarity_edge_count": kernel["summary"]["similarity_edge_count"],
                "non_adjacent_similarity_edge_count": kernel["summary"][
                    "non_adjacent_similarity_edge_count"
                ],
                "mean_configuration_similarity": kernel["summary"][
                    "mean_configuration_similarity"
                ],
                "rotated_target_similarity_control_passed": kernel[
                    "negative_controls"
                ]["rotated_target_similarity_control_passed"],
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
