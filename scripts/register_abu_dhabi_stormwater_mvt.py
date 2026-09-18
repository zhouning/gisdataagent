#!/usr/bin/env python3
"""Register durable local MVT layers for the Abu Dhabi stormwater map.

The hydraulic models continue to consume the authoritative full-resolution
assets. This command publishes the same full geometry through the local
PostGIS-backed MVT endpoints so the browser requests only visible tiles.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from data_agent.tile_server import create_tile_layer


ASSETS = (
    {
        "filename": "abu_dhabi_customer_stormwater_gdb_pipeline_full.fgb",
        "layer_id": "abu-stormwater-pipelines-v1",
        "table_name": "_mvt_abu_stormwater_pipelines_v1",
        "layer_name": "stormwater_pipelines",
    },
    {
        "filename": "abu_dhabi_customer_stormwater_topology_nodes_full.fgb",
        "layer_id": "abu-stormwater-nodes-v1",
        "table_name": "_mvt_abu_stormwater_nodes_v1",
        "layer_name": "stormwater_nodes",
    },
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--asset-root",
        type=Path,
        default=Path("data_agent/uploads/admin"),
    )
    parser.add_argument("--owner", default="admin")
    args = parser.parse_args()

    expires_at = datetime(2099, 12, 31, 23, 59, 59)
    for asset in ASSETS:
        path = args.asset_root / asset["filename"]
        if not path.is_file():
            raise FileNotFoundError(path)
        metadata = create_tile_layer(
            str(path),
            args.owner,
            asset["layer_name"],
            layer_id=asset["layer_id"],
            table_name=asset["table_name"],
            expires_at=expires_at,
        )
        print(
            f"registered {metadata['layer_id']}: "
            f"{metadata['feature_count']} features, bounds={metadata['bounds']}"
        )


if __name__ == "__main__":
    main()
