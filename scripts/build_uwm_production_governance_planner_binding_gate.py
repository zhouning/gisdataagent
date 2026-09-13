"""Build planner binding gate for authoritative UWM governance data closure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.production_governance_planner_binding_gate import (
    build_uwm_production_governance_planner_binding_gate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_governance_planner_binding_gate_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_production_governance_planner_binding_gate.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

PRODUCTION_ACTION_CATALOG_PATH = (
    DATA_ROOT
    / "production_action_catalog_2026_07_08/uwm_production_action_catalog.json"
)
GOVERNANCE_DATA_CONTRACT_PATH = (
    DATA_ROOT
    / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
)
GOVERNANCE_ADAPTER_READINESS_PATH = (
    DATA_ROOT
    / "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json"
)
GOVERNANCE_LINKAGE_AUDIT_PATH = (
    DATA_ROOT
    / "production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json"
)


def main() -> None:
    gate = build_uwm_production_governance_planner_binding_gate(
        gate_id="uwm-production-governance-planner-binding-gate-2026-07-08",
        created_at="2026-07-09T00:08:00Z",
        production_action_catalog=_read_json(PRODUCTION_ACTION_CATALOG_PATH),
        governance_data_contract=_read_json(GOVERNANCE_DATA_CONTRACT_PATH),
        adapter_readiness=_read_json(GOVERNANCE_ADAPTER_READINESS_PATH),
        linkage_audit=_read_json(GOVERNANCE_LINKAGE_AUDIT_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, gate)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_production_governance_planner_binding_gate_2026_07_08",
            "created_at": gate["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": gate["experiment_scope"],
            "source_artifacts": {
                "production_action_catalog": str(
                    PRODUCTION_ACTION_CATALOG_PATH.relative_to(REPO_ROOT)
                ),
                "production_governance_data_contract": str(
                    GOVERNANCE_DATA_CONTRACT_PATH.relative_to(REPO_ROOT)
                ),
                "production_governance_data_adapter_readiness": str(
                    GOVERNANCE_ADAPTER_READINESS_PATH.relative_to(REPO_ROOT)
                ),
                "production_governance_linkage_audit": str(
                    GOVERNANCE_LINKAGE_AUDIT_PATH.relative_to(REPO_ROOT)
                ),
            },
            "planner_governance_binding_ready": gate[
                "planner_governance_binding_ready"
            ],
            "production_readiness_claim": False,
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "required_gate_count": gate["summary"]["required_gate_count"],
                "passed_gate_count": gate["summary"]["passed_gate_count"],
                "blocking_gate_count": gate["summary"]["blocking_gate_count"],
                "missing_table_count": gate["summary"]["missing_table_count"],
                "accepted_authoritative_row_count": gate["summary"][
                    "accepted_authoritative_row_count"
                ],
                "linked_project_count": gate["summary"]["linked_project_count"],
                "planner_governance_binding_ready": gate[
                    "planner_governance_binding_ready"
                ],
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
