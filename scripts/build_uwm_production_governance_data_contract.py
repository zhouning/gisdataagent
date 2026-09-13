"""Build production governance data contract for UWM livability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.production_governance_data_contract import (
    build_uwm_production_governance_data_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_governance_data_contract_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_production_governance_data_contract.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

PRODUCTION_ACTION_CATALOG_PATH = (
    DATA_ROOT / "production_action_catalog_2026_07_08/uwm_production_action_catalog.json"
)
DATA_FOUNDATION_EVIDENCE_GATE_PATH = (
    DATA_ROOT
    / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
)


def main() -> None:
    contract = build_uwm_production_governance_data_contract(
        contract_id="uwm-production-governance-data-contract-2026-07-08",
        created_at="2026-07-08T23:55:00Z",
        production_action_catalog=_read_json(PRODUCTION_ACTION_CATALOG_PATH),
        data_foundation_evidence_gate=_read_json(DATA_FOUNDATION_EVIDENCE_GATE_PATH),
    )
    source_artifacts = {
        "production_action_catalog": str(
            PRODUCTION_ACTION_CATALOG_PATH.relative_to(REPO_ROOT)
        ),
        "data_foundation_evidence_gate": str(
            DATA_FOUNDATION_EVIDENCE_GATE_PATH.relative_to(REPO_ROOT)
        ),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, contract)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_production_governance_data_contract_2026_07_08",
            "created_at": contract["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": contract["experiment_scope"],
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
                "production_action_type_count": contract["summary"][
                    "production_action_type_count"
                ],
                "currently_bound_feasible_action_count": contract["summary"][
                    "currently_bound_feasible_action_count"
                ],
                "required_governance_table_count": contract["summary"][
                    "required_governance_table_count"
                ],
                "ready_governance_table_count": contract["summary"][
                    "ready_governance_table_count"
                ],
                "planning_sample_source_count": contract["summary"][
                    "planning_sample_source_count"
                ],
                "planner_governance_binding_ready": False,
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
