#!/usr/bin/env python3
"""Compile local SmartMakani/registered Makani stormwater crosswalks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.registered_network_compiler import (
    compile_registered_network_candidate,
    compile_registered_network_crosswalks,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    audit = compile_registered_network_crosswalks(
        args.dataset_root,
        output_root=args.output_root,
    )
    network = compile_registered_network_candidate(
        args.dataset_root,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "pipeline_crosswalk_count": audit["geometry_crosswalk"][
                    "accepted_crosswalk_count"
                ],
                "facility_attachment_count": audit["facility_attachments"][
                    "attachment_count"
                ],
                "registered_network_pipeline_count": network["pipeline_count"],
                "registered_network_node_count": network["node_count"],
                "node_facility_candidate_count": network[
                    "node_facility_candidate_count"
                ],
                "admitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
