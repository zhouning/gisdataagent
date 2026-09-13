"""Build cross-table linkage audit for authoritative UWM governance inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.production_governance_linkage_audit import (
    build_uwm_production_governance_linkage_audit,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_governance_linkage_audit_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_production_governance_linkage_audit.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

GOVERNANCE_ADAPTER_READINESS_PATH = (
    DATA_ROOT
    / "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json"
)
GOVERNANCE_INPUT_DIR = DATA_ROOT / "authoritative_governance_inputs_2026_07_08"


def main() -> None:
    audit = build_uwm_production_governance_linkage_audit(
        audit_id="uwm-production-governance-linkage-audit-2026-07-08",
        created_at="2026-07-08T23:59:30Z",
        adapter_readiness=_read_json(GOVERNANCE_ADAPTER_READINESS_PATH),
        governance_input_dir=GOVERNANCE_INPUT_DIR,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, audit)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_production_governance_linkage_audit_2026_07_08",
            "created_at": audit["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": audit["experiment_scope"],
            "source_artifacts": {
                "production_governance_data_adapter_readiness": str(
                    GOVERNANCE_ADAPTER_READINESS_PATH.relative_to(REPO_ROOT)
                ),
                "governance_input_dir": str(
                    GOVERNANCE_INPUT_DIR.relative_to(REPO_ROOT)
                ),
            },
            "governance_linkage_ready": audit["governance_linkage_ready"],
            "planner_governance_binding_ready": False,
            "production_readiness_claim": False,
            "observed_policy_outcome_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "expected_table_count": audit["summary"]["expected_table_count"],
                "present_table_count": audit["summary"]["present_table_count"],
                "missing_table_count": audit["summary"]["missing_table_count"],
                "linked_project_count": audit["summary"]["linked_project_count"],
                "governance_linkage_ready": audit["governance_linkage_ready"],
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
