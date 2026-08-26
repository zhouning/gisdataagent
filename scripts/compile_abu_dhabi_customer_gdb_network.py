#!/usr/bin/env python3
"""Compile a private Abu Dhabi customer-GDB stormwater candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.customer_gdb_network import (
    CustomerGwmStaticTensorPolicy,
    compile_customer_gdb_network,
    compile_customer_gwm_static_tensors,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gdb", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--compile-gwm-static-tensors", action="store_true")
    parser.add_argument("--maximum-nodes-per-partition", type=int, default=8192)
    args = parser.parse_args()
    manifest = compile_customer_gdb_network(
        args.gdb,
        output_root=args.output_root,
        source_archive_path=args.source_archive,
    )
    tensor_manifest = None
    if args.compile_gwm_static_tensors:
        tensor_manifest = compile_customer_gwm_static_tensors(
            args.output_root,
            policy=CustomerGwmStaticTensorPolicy(
                maximum_nodes_per_partition=args.maximum_nodes_per_partition
            ),
        )
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "output_root": str(args.output_root.expanduser().resolve()),
                "pipeline_count": manifest["outputs"]["pipelines_private_geoparquet"][
                    "record_count"
                ],
                "node_count": manifest["outputs"]["nodes_private_geoparquet"][
                    "record_count"
                ],
                "diagnostic_only": manifest["diagnostic_only"],
                "admitted": manifest["admitted"],
                "gwm_static_tensors_compiled": tensor_manifest is not None,
                "gwm_partition_count": (
                    tensor_manifest["feature_contract"]["partition_count"]
                    if tensor_manifest is not None
                    else 0
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
