#!/usr/bin/env python3
"""Build the Abu Dhabi v2 data-request readiness audit and customer summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.data_request_readiness import (
    write_data_request_readiness,
    write_data_request_readiness_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"
DEFAULT_MARKDOWN = ROOT / (
    "docs/customer/abu_dhabi_liveability_site_validation/"
    "abu_dhabi_data_request_readiness_v2.md"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    dataset_root = args.dataset_root.resolve()
    payload = write_data_request_readiness(dataset_root, output_path=args.output)
    markdown = args.markdown.resolve()
    write_data_request_readiness_markdown(payload, markdown)
    print(
        json.dumps(
            {
                "status": "ok",
                "json_output": payload["output"],
                "markdown_output": str(markdown),
                "summary": payload["summary"],
                "model_gate_summary": payload["model_gate_summary"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
