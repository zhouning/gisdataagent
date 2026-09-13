"""Build empty input templates for authoritative UWM governance data."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.production_governance_input_templates import (
    build_uwm_production_governance_input_templates,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_governance_input_templates_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_production_governance_input_templates.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

GOVERNANCE_DATA_CONTRACT_PATH = (
    DATA_ROOT
    / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
)
GOVERNANCE_ADAPTER_READINESS_PATH = (
    DATA_ROOT
    / "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json"
)


def main() -> None:
    templates = build_uwm_production_governance_input_templates(
        template_pack_id="uwm-production-governance-input-templates-2026-07-08",
        created_at="2026-07-08T23:59:00Z",
        governance_data_contract=_read_json(GOVERNANCE_DATA_CONTRACT_PATH),
        adapter_readiness=_read_json(GOVERNANCE_ADAPTER_READINESS_PATH),
        output_dir=OUTPUT_DIR,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for table in templates["table_templates"]:
        _write_empty_csv_header(
            REPO_ROOT / table["template_relative_path"],
            table["header_fields"],
        )
    _write_json(OUTPUT_PATH, templates)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_production_governance_input_templates_2026_07_08",
            "created_at": templates["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": templates["experiment_scope"],
            "source_artifacts": {
                "production_governance_data_contract": str(
                    GOVERNANCE_DATA_CONTRACT_PATH.relative_to(REPO_ROOT)
                ),
                "production_governance_data_adapter_readiness": str(
                    GOVERNANCE_ADAPTER_READINESS_PATH.relative_to(REPO_ROOT)
                ),
            },
            "template_count": templates["summary"]["template_count"],
            "authoritative_input_claim": False,
            "production_readiness_claim": False,
            "observed_policy_outcome_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "template_count": templates["summary"]["template_count"],
                "required_field_count": templates["summary"][
                    "required_field_count"
                ],
                "adapter_ready_table_count": templates["summary"][
                    "adapter_ready_table_count"
                ],
                "adapter_missing_source_table_count": templates["summary"][
                    "adapter_missing_source_table_count"
                ],
                "template_dir_is_adapter_input_dir": templates["summary"][
                    "template_dir_is_adapter_input_dir"
                ],
                "authoritative_input_claim": False,
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


def _write_empty_csv_header(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)


if __name__ == "__main__":
    main()
