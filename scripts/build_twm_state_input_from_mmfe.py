"""Build a TWM state-input artifact from an MMFE semantic fusion bundle."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_TWM_STATE_INPUT_PATH = REPO_ROOT / "data_agent" / "fusion" / "twm_state_input.py"
_TWM_STATE_INPUT_SPEC = importlib.util.spec_from_file_location(
    "_mmfe_twm_state_input",
    _TWM_STATE_INPUT_PATH,
)
if _TWM_STATE_INPUT_SPEC is None or _TWM_STATE_INPUT_SPEC.loader is None:
    raise ImportError(f"cannot load TWM state input module: {_TWM_STATE_INPUT_PATH}")
_TWM_STATE_INPUT = importlib.util.module_from_spec(_TWM_STATE_INPUT_SPEC)
_TWM_STATE_INPUT_SPEC.loader.exec_module(_TWM_STATE_INPUT)

build_twm_state_input_from_semantic_product = _TWM_STATE_INPUT.build_twm_state_input_from_semantic_product
validate_twm_state_input = _TWM_STATE_INPUT.validate_twm_state_input
write_twm_state_input = _TWM_STATE_INPUT.write_twm_state_input


DEFAULT_MMFE_DIR = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmfe-dir", type=Path, default=DEFAULT_MMFE_DIR)
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--semantic-relations-path", type=Path, default=None)
    parser.add_argument("--input-contract-path", type=Path, default=None)
    parser.add_argument("--out-path", type=Path, default=None)
    args = parser.parse_args()

    mmfe_dir = args.mmfe_dir
    manifest_path = args.manifest_path or mmfe_dir / "twm_mmfe_semantic_product.json"
    relations_path = args.semantic_relations_path or mmfe_dir / "twm_mmfe_semantic_relations.csv"
    contract_path = args.input_contract_path or mmfe_dir / "twm_state_input_contract.json"
    out_path = args.out_path or mmfe_dir / "twm_state_input.json"

    manifest = _read_json(manifest_path)
    semantic_relations = _read_csv(relations_path)
    input_contract = _read_json(contract_path) if contract_path.exists() else None
    payload = build_twm_state_input_from_semantic_product(
        manifest,
        semantic_relations=semantic_relations,
        input_contract=input_contract,
    )
    validation = validate_twm_state_input(payload)
    write_twm_state_input(payload, out_path)

    print(json.dumps({
        "status": "ok" if validation["valid"] else "invalid",
        "schema": payload["schema"],
        "out_path": str(out_path),
        "valid": validation["valid"],
        "errors": validation["errors"],
        "product_id": payload["source_product"]["product_id"],
        "role_count": len(payload["object_role_registry"]),
        "relation_count": payload["semantic_relation_summary"]["total_relation_count"],
        "relation_type_count": payload["semantic_relation_summary"]["registered_relation_type_count"],
        "hard_constraint_relation_count": payload["state_components"]["hard_constraints"]["relation_count"],
        "objective_binding_count": len(payload["optimization_interface"]["objective_bindings"]),
        "warning_count": len(payload["warnings"]),
    }, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


if __name__ == "__main__":
    main()
