"""Export a TWM MMFE semantic fusion directory as an OKF knowledge bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.fusion.okf_exporter import (
    export_semantic_product_okf_bundle,
    load_semantic_product_okf_inputs,
)


DEFAULT_MMFE_DIR = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion")
DEFAULT_OUT_DIR_NAME = "okf_bundle"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmfe-dir", type=Path, default=DEFAULT_MMFE_DIR)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    mmfe_dir = args.mmfe_dir
    out_dir = args.out_dir or mmfe_dir / DEFAULT_OUT_DIR_NAME
    inputs = load_semantic_product_okf_inputs(mmfe_dir)
    result = export_semantic_product_okf_bundle(
        inputs["manifest"],
        out_dir,
        field_semantics=inputs.get("field_semantics"),
        value_domain_audits=inputs.get("value_domain_audits"),
        standard_sources=inputs.get("standard_sources"),
        semantic_relations=inputs.get("semantic_relations"),
        input_contract=inputs.get("input_contract"),
        state_input=inputs.get("state_input"),
        semantic_graph=inputs.get("semantic_graph"),
        semantic_trace_cards=inputs.get("semantic_trace_cards"),
        semantic_ontology=inputs.get("semantic_ontology"),
        semantic_diagnostic=inputs.get("semantic_diagnostic"),
    )
    result["validation"] = {
        "valid": result.get("valid"),
        "errors": result.get("errors") or [],
        "concept_count": result.get("concept_count", 0),
    }
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
