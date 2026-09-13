#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm import traditional_livability_source_adapter as source_adapter
from data_agent.uwm.traditional_livability_facility_product import build_facility_data_product
from data_agent.uwm.traditional_livability_s1 import build_s1_facility_assessment


def build_phase1a(
    *,
    source_root: Path,
    output_dir: Path,
    max_poi_features: int | None = None,
    max_aoi_features: int | None = None,
) -> dict[str, Any]:
    manifest = source_adapter.inspect_traditional_livability_sources(source_root)
    if not manifest["ready"]:
        return manifest
    loaded = source_adapter.load_traditional_livability_source_rows(
        source_root,
        max_poi_features=max_poi_features,
        max_aoi_features=max_aoi_features,
    )
    created_at = _utc_now()
    product = build_facility_data_product(
        product_id=f"traditional-livability-facility-product-{created_at[:10]}",
        created_at=created_at,
        poi_rows=loaded["poi_rows"],
        aoi_rows=loaded["aoi_rows"],
        population_rows=loaded["population_rows"],
        source_manifest=loaded["manifest"],
    )
    assessment = build_s1_facility_assessment(
        assessment_id=f"traditional-livability-s1-{created_at[:10]}",
        created_at=created_at,
        facility_product=product,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "uwm_traditional_livability_source_manifest.json", loaded["manifest"])
    _atomic_json(output_dir / "uwm_traditional_livability_facility_product.json", product)
    _atomic_json(output_dir / "uwm_traditional_livability_s1.json", assessment)
    return {
        "ready": True,
        "output_dir": str(output_dir),
        "complete_inventory": loaded["manifest"]["complete_inventory"],
        "facility_count": len(product["facilities"]),
        "supply_metric_count": len(assessment["supply_metrics"]),
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-poi-features", type=int)
    parser.add_argument("--max-aoi-features", type=int)
    args = parser.parse_args()
    result = build_phase1a(
        source_root=args.source_root,
        output_dir=args.output,
        max_poi_features=args.max_poi_features,
        max_aoi_features=args.max_aoi_features,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
