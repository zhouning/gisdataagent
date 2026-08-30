#!/usr/bin/env python3
"""Build the reviewed-input catalog used by an isolated GIS Data Agent host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.standard_contracts import build_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GIS Data Agent standard contract catalog")
    parser.add_argument("--shp-workbook", required=True, type=Path)
    parser.add_argument("--inventory-workbook", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    catalog = build_catalog(args.shp_workbook, args.inventory_workbook)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "contract_count": len(catalog["contracts"]),
                "inventory_items": (catalog.get("data_inventory") or {}).get("item_count", 0),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
