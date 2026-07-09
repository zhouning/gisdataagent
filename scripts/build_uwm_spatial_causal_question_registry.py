"""Build UWM spatial causal question and estimand registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.spatial_causal_question_registry import (
    build_uwm_spatial_causal_question_registry,
    validate_uwm_spatial_causal_question_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_OUTPUT_DIR = (
    DATA_ROOT / "spatial_causal_question_registry_2026_07_09"
)
DEFAULT_OUTPUT_PATH = (
    DEFAULT_OUTPUT_DIR / "uwm_spatial_causal_question_registry.json"
)
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "snapshot_manifest.json"
DEFAULT_PRODUCTION_ACTION_CATALOG_PATH = (
    DATA_ROOT
    / "production_action_catalog_2026_07_08/uwm_production_action_catalog.json"
)
DEFAULT_GOVERNANCE_DATA_CONTRACT_PATH = (
    DATA_ROOT
    / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
)
DEFAULT_CAUSAL_POLICY_EVIDENCE_PATH = (
    DATA_ROOT / "causal_policy_evidence_2026_07_06/uwm_causal_policy_evidence_gate.json"
)
DEFAULT_DATA_FOUNDATION_EVIDENCE_GATE_PATH = (
    DATA_ROOT
    / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
)


def build_spatial_causal_question_registry(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    registry_id: str = "uwm-spatial-causal-question-registry-2026-07-09",
    created_at: str = "2026-07-09T09:15:00Z",
    production_action_catalog_path: str
    | Path = DEFAULT_PRODUCTION_ACTION_CATALOG_PATH,
    governance_data_contract_path: str
    | Path = DEFAULT_GOVERNANCE_DATA_CONTRACT_PATH,
    causal_policy_evidence_path: str | Path = DEFAULT_CAUSAL_POLICY_EVIDENCE_PATH,
    data_foundation_evidence_gate_path: str
    | Path = DEFAULT_DATA_FOUNDATION_EVIDENCE_GATE_PATH,
) -> dict[str, Any]:
    """Write the registry and snapshot manifest."""

    production_action_catalog_path = Path(production_action_catalog_path)
    governance_data_contract_path = Path(governance_data_contract_path)
    causal_policy_evidence_path = Path(causal_policy_evidence_path)
    data_foundation_evidence_gate_path = Path(data_foundation_evidence_gate_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    registry = build_uwm_spatial_causal_question_registry(
        registry_id=registry_id,
        created_at=created_at,
        production_action_catalog=_read_json(production_action_catalog_path),
        governance_data_contract=_read_json(governance_data_contract_path),
        causal_policy_evidence_gate=_read_json(causal_policy_evidence_path),
        data_foundation_evidence_gate=_read_json(data_foundation_evidence_gate_path),
    )
    validation = validate_uwm_spatial_causal_question_registry(registry)
    if not validation["valid"]:
        raise ValueError(f"invalid spatial causal registry: {validation['errors']}")

    registry_path = out / DEFAULT_OUTPUT_PATH.name
    manifest_path = out / DEFAULT_MANIFEST_PATH.name
    _write_json(registry_path, registry)
    manifest = {
        "schema": "uwm.spatial_causal_question_registry_snapshot_manifest.v1",
        "created_at": created_at,
        "outputs": {
            "spatial_causal_question_registry": str(
                registry_path.relative_to(REPO_ROOT)
            ),
        },
        "source_artifacts": {
            "production_action_catalog": str(
                production_action_catalog_path.relative_to(REPO_ROOT)
            ),
            "governance_data_contract": str(
                governance_data_contract_path.relative_to(REPO_ROOT)
            ),
            "causal_policy_evidence_gate": str(
                causal_policy_evidence_path.relative_to(REPO_ROOT)
            ),
            "data_foundation_evidence_gate": str(
                data_foundation_evidence_gate_path.relative_to(REPO_ROOT)
            ),
        },
        "summary": registry["summary"],
        "claim_boundary": registry["claim_boundary"],
        "observed_policy_outcome_superiority_claim": registry[
            "observed_policy_outcome_superiority_claim"
        ],
        "empirical_superiority_claim": registry["empirical_superiority_claim"],
    }
    _write_json(manifest_path, manifest)
    return {
        "registry_path": str(registry_path),
        "manifest_path": str(manifest_path),
        "registry": registry,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--registry-id",
        default="uwm-spatial-causal-question-registry-2026-07-09",
    )
    parser.add_argument("--created-at", default="2026-07-09T09:15:00Z")
    parser.add_argument(
        "--production-action-catalog-path",
        default=str(DEFAULT_PRODUCTION_ACTION_CATALOG_PATH),
    )
    parser.add_argument(
        "--governance-data-contract-path",
        default=str(DEFAULT_GOVERNANCE_DATA_CONTRACT_PATH),
    )
    parser.add_argument(
        "--causal-policy-evidence-path",
        default=str(DEFAULT_CAUSAL_POLICY_EVIDENCE_PATH),
    )
    parser.add_argument(
        "--data-foundation-evidence-gate-path",
        default=str(DEFAULT_DATA_FOUNDATION_EVIDENCE_GATE_PATH),
    )
    args = parser.parse_args()
    result = build_spatial_causal_question_registry(
        output_dir=args.output_dir,
        registry_id=args.registry_id,
        created_at=args.created_at,
        production_action_catalog_path=args.production_action_catalog_path,
        governance_data_contract_path=args.governance_data_contract_path,
        causal_policy_evidence_path=args.causal_policy_evidence_path,
        data_foundation_evidence_gate_path=args.data_foundation_evidence_gate_path,
    )
    registry = result["registry"]
    print(
        json.dumps(
            {
                "path": str(Path(result["registry_path"]).relative_to(REPO_ROOT)),
                "manifest_path": str(
                    Path(result["manifest_path"]).relative_to(REPO_ROOT)
                ),
                "active_causal_question_count": registry["summary"][
                    "active_causal_question_count"
                ],
                "underidentified_policy_effect_question_count": registry[
                    "summary"
                ]["underidentified_policy_effect_question_count"],
                "claim_level": registry["claim_boundary"]["max_claim_level"],
                "observed_policy_outcome_superiority_claim": registry[
                    "observed_policy_outcome_superiority_claim"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
