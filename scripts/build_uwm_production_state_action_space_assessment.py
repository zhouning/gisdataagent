"""Build production state/action space gap assessment for UWM livability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.production_state_action_space import (
    build_uwm_production_state_action_space_assessment,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_state_action_space_assessment_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_production_state_action_space_assessment.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

DATA_FOUNDATION_EVIDENCE_GATE_PATH = (
    DATA_ROOT
    / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
)
FULL_ADMIN_ACTION_INVENTORY_PATH = (
    DATA_ROOT
    / "full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json"
)
FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_PATH = (
    DATA_ROOT
    / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json"
)


def main() -> None:
    assessment = build_uwm_production_state_action_space_assessment(
        assessment_id="uwm-production-state-action-space-assessment-2026-07-08",
        created_at="2026-07-08T22:30:00Z",
        data_foundation_evidence_gate=_read_json(DATA_FOUNDATION_EVIDENCE_GATE_PATH),
        full_admin_action_inventory=_read_json(FULL_ADMIN_ACTION_INVENTORY_PATH),
        full_admin_livability_decision_package=_read_json(
            FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_PATH
        ),
    )
    source_artifacts = {
        "data_foundation_evidence_gate": str(
            DATA_FOUNDATION_EVIDENCE_GATE_PATH.relative_to(REPO_ROOT)
        ),
        "full_admin_action_inventory": str(
            FULL_ADMIN_ACTION_INVENTORY_PATH.relative_to(REPO_ROOT)
        ),
        "full_admin_livability_decision_package": str(
            FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_PATH.relative_to(REPO_ROOT)
        ),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, assessment)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_production_state_action_space_assessment_2026_07_08",
            "created_at": assessment["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": assessment["experiment_scope"],
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
                "graph_node_count": assessment["current_implemented_scope"][
                    "graph_node_count"
                ],
                "available_action_count": assessment["current_action_space"][
                    "implemented_feasible_action_count"
                ],
                "implemented_action_type_count": assessment["current_action_space"][
                    "implemented_action_type_count"
                ],
                "production_action_type_target_count": assessment[
                    "production_action_type_target_count"
                ],
                "state_space_blocking_gap_count": assessment[
                    "production_gap_summary"
                ]["state_space_blocking_gap_count"],
                "action_space_blocking_gap_count": assessment[
                    "production_gap_summary"
                ]["action_space_blocking_gap_count"],
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
