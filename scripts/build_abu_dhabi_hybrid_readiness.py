#!/usr/bin/env python3
"""Build the Abu Dhabi traditional/GWM hybrid readiness audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.readiness import write_hybrid_readiness

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = write_hybrid_readiness(args.dataset_root, output_path=args.output)
    print(
        json.dumps(
            {
                "status": "ok",
                "output": payload["output"],
                "k0_status": payload["admission"]["k0_status"],
                "traditional_model_admitted": payload["admission"][
                    "traditional_model_admitted"
                ],
                "gwm_training_admitted": payload["admission"]["gwm_training_admitted"],
            }
        )
    )


if __name__ == "__main__":
    main()
