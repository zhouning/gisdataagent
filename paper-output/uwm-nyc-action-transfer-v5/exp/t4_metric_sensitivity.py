#!/usr/bin/env python3
"""Run non-retuned sensitivity checks on committed V5 predictions.

Reads the four committed model predictions and four held-out target/history
bundles from benchmarks/gwm_bench_foundation_v5_0_draft. It does not train,
select or modify a model. Synthetic and Chongqing data are intentionally skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from data_agent.uwm.nyc_action_transfer_sensitivity import build_metric_sensitivity


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"
SEED = 20260724


def main() -> int:
    np.random.seed(SEED)
    summary = build_metric_sensitivity(REPO_ROOT, RESULTS_ROOT)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

