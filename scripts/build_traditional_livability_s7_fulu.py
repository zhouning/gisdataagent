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

from data_agent.uwm.traditional_livability_s7 import build_s7_primary_school_siting
from data_agent.uwm.traditional_livability_s7_fulu_adapter import (
    classify_primary_school_supply,
    load_fulu_s7_planning_inputs,
)


def build_s7_fulu(
    *,
    source_root: Path,
    facility_product: dict[str, Any],
    output_dir: Path,
    coverage_distance_m: float,
    max_sites: int,
) -> dict[str, Any]:
    planning_inputs = load_fulu_s7_planning_inputs(source_root)
    if not planning_inputs.get("ready"):
        return {"ready": False, "blockers": list((planning_inputs.get("manifest") or {}).get("blockers") or [])}
    supply = classify_primary_school_supply(facility_product=facility_product, planning_inputs=planning_inputs)
    snapshot = build_s7_primary_school_siting(
        siting_id=f"traditional-livability-s7-fulu-{_utc_now()[:10]}",
        created_at=_utc_now(),
        planning_inputs=planning_inputs,
        school_supply=supply,
        coverage_distance_m=coverage_distance_m,
        max_sites=max_sites,
    )
    snapshot["data_support"]["facility_product_complete_inventory"] = bool(
        (facility_product.get("source_manifest") or {}).get("complete_inventory")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "uwm_traditional_livability_s7.json", snapshot)
    return {"ready": True, "output_dir": str(output_dir), "recommendation_status": snapshot["recommendation_status"], "selected_site_count": len(snapshot["selected_sites"])}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _json_default(value):
    if hasattr(value, "__geo_interface__"):
        return value.__geo_interface__
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--facility-product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage-distance-m", type=float, default=1500)
    parser.add_argument("--max-sites", type=int, default=3)
    args = parser.parse_args()
    product = json.loads(args.facility_product.read_text(encoding="utf-8"))
    result = build_s7_fulu(source_root=args.source_root, facility_product=product, output_dir=args.output, coverage_distance_m=args.coverage_distance_m, max_sites=args.max_sites)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
