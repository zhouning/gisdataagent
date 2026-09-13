"""Build UWM causal policy evidence from Paper6 real result artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.causal_policy_evidence import build_uwm_causal_policy_evidence_gate


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAPER6_RESULTS_ROOT = (
    REPO_ROOT.parent
    / "paper6-spatial-causal-inference/paper/ijgis_submission_20260605/07_results"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/causal_policy_evidence_2026_07_06"
)
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "uwm_causal_policy_evidence_gate.json"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "snapshot_manifest.json"


def build_causal_policy_evidence(
    *,
    paper6_results_root: str | Path = DEFAULT_PAPER6_RESULTS_ROOT,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    gate_id: str = "uwm-causal-policy-evidence-paper6-real-artifacts-2026-07-06",
    created_at: str = "2026-07-06T11:55:00Z",
) -> dict[str, Any]:
    """Write the UWM causal policy evidence gate and a snapshot manifest."""

    results_root = Path(paper6_results_root)
    if not results_root.exists():
        raise FileNotFoundError(f"Paper6 results root not found: {results_root}")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    gate = build_uwm_causal_policy_evidence_gate(
        paper6_results_root=results_root,
        gate_id=gate_id,
        created_at=created_at,
    )
    gate_path = out / DEFAULT_OUTPUT_PATH.name
    manifest_path = out / DEFAULT_MANIFEST_PATH.name
    with gate_path.open("w", encoding="utf-8") as handle:
        json.dump(gate, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    manifest = {
        "schema": "uwm.causal_policy_evidence_snapshot_manifest.v1",
        "created_at": created_at,
        "source_results_root": str(results_root),
        "outputs": {
            "causal_policy_evidence_gate": str(gate_path.relative_to(REPO_ROOT)),
        },
        "source_artifacts": gate["source_artifacts"],
        "algorithmic_causal_diagnostic_ready": gate[
            "algorithmic_causal_diagnostic_ready"
        ],
        "observed_policy_outcome_superiority_claim": gate[
            "observed_policy_outcome_superiority_claim"
        ],
        "limitations": gate["limitations"],
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "gate_path": str(gate_path),
        "manifest_path": str(manifest_path),
        "gate": gate,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper6-results-root", default=str(DEFAULT_PAPER6_RESULTS_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--gate-id",
        default="uwm-causal-policy-evidence-paper6-real-artifacts-2026-07-06",
    )
    parser.add_argument("--created-at", default="2026-07-06T11:55:00Z")
    args = parser.parse_args()
    result = build_causal_policy_evidence(
        paper6_results_root=args.paper6_results_root,
        output_dir=args.output_dir,
        gate_id=args.gate_id,
        created_at=args.created_at,
    )
    gate = result["gate"]
    print(
        json.dumps(
            {
                "path": str(Path(result["gate_path"]).relative_to(REPO_ROOT)),
                "manifest_path": str(Path(result["manifest_path"]).relative_to(REPO_ROOT)),
                "algorithmic_causal_diagnostic_ready": gate[
                    "algorithmic_causal_diagnostic_ready"
                ],
                "observed_policy_outcome_superiority_claim": gate[
                    "observed_policy_outcome_superiority_claim"
                ],
                "claim_level": gate["claim_boundary"]["max_claim_level"],
                "remaining_gates": gate["remaining_gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
