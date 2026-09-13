#!/usr/bin/env python3
"""Extract paper evidence without retraining or modifying the V5 evaluator.

Reads:
- benchmarks/gwm_bench_foundation_v5_0_draft/final_results/action_transfer_results.json
- benchmarks/gwm_bench_foundation_v5_0_draft/final_results/completion_verification.json
- benchmarks/gwm_bench_foundation_v5_0_draft/runtime_r4_contract.json

Skipped intentionally: Chongqing data, synthetic fixtures and all model-training
entrypoints because the selected paper consumes the frozen NYC V5 result.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from data_agent.uwm.nyc_action_transfer_paper import build_frozen_evidence_tables


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"
SEED = 20260724


def main() -> int:
    np.random.seed(SEED)
    summary = build_frozen_evidence_tables(REPO_ROOT, RESULTS_ROOT)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

