"""Build production action catalog contract for UWM livability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.production_action_catalog import (
    build_uwm_production_action_catalog,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_action_catalog_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_production_action_catalog.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_PATH = (
    DATA_ROOT
    / "production_state_action_space_assessment_2026_07_08/uwm_production_state_action_space_assessment.json"
)
FULL_ADMIN_ACTION_INVENTORY_PATH = (
    DATA_ROOT
    / "full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json"
)


def main() -> None:
    catalog = build_uwm_production_action_catalog(
        catalog_id="uwm-production-action-catalog-2026-07-08",
        created_at="2026-07-08T23:40:00Z",
        production_state_action_space_assessment=_read_json(
            PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_PATH
        ),
        full_admin_action_inventory=_read_json(FULL_ADMIN_ACTION_INVENTORY_PATH),
    )
    source_artifacts = {
        "production_state_action_space_assessment": str(
            PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_PATH.relative_to(REPO_ROOT)
        ),
        "full_admin_action_inventory": str(
            FULL_ADMIN_ACTION_INVENTORY_PATH.relative_to(REPO_ROOT)
        ),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, catalog)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_production_action_catalog_2026_07_08",
            "created_at": catalog["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": catalog["experiment_scope"],
            "source_artifacts": source_artifacts,
            "production_readiness_claim": False,
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "production_action_type_count": catalog["summary"][
                    "production_action_type_count"
                ],
                "currently_bound_action_type_count": catalog["summary"][
                    "currently_bound_action_type_count"
                ],
                "currently_bound_feasible_action_count": catalog["summary"][
                    "currently_bound_feasible_action_count"
                ],
                "current_candidate_binding_count": len(
                    catalog["current_candidate_bindings"]
                ),
                "production_readiness_claim": False,
                "observed_policy_outcome_superiority_claim": False,
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


if __name__ == "__main__":
    main()
