"""Build readiness audit for authoritative UWM governance data adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.production_governance_data_adapter import (
    build_uwm_production_governance_data_adapter_readiness,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_governance_data_adapter_readiness_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_production_governance_data_adapter_readiness.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

GOVERNANCE_DATA_CONTRACT_PATH = (
    DATA_ROOT
    / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
)
EXPECTED_INPUT_DIR = DATA_ROOT / "authoritative_governance_inputs_2026_07_08"


def main() -> None:
    readiness = build_uwm_production_governance_data_adapter_readiness(
        audit_id="uwm-production-governance-data-adapter-readiness-2026-07-08",
        created_at="2026-07-08T23:58:00Z",
        governance_data_contract=_read_json(GOVERNANCE_DATA_CONTRACT_PATH),
        expected_input_dir=EXPECTED_INPUT_DIR,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, readiness)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_production_governance_data_adapter_readiness_2026_07_08",
            "created_at": readiness["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": readiness["experiment_scope"],
            "source_artifacts": {
                "production_governance_data_contract": str(
                    GOVERNANCE_DATA_CONTRACT_PATH.relative_to(REPO_ROOT)
                ),
                "expected_input_dir": str(EXPECTED_INPUT_DIR.relative_to(REPO_ROOT)),
            },
            "production_readiness_claim": False,
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "expected_table_count": readiness["summary"][
                    "expected_table_count"
                ],
                "ready_table_count": readiness["summary"]["ready_table_count"],
                "missing_source_table_count": readiness["summary"][
                    "missing_source_table_count"
                ],
                "accepted_authoritative_row_count": readiness["summary"][
                    "accepted_authoritative_row_count"
                ],
                "planner_governance_binding_ready": readiness[
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
