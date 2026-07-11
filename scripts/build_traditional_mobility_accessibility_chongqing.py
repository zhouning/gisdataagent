from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.traditional_mobility_accessibility import build_mobility_accessibility_product


def build_product(*, source_root: Path, output_dir: Path) -> dict:
    base = Path(source_root) / "data/uwm_public_proxy/chongqing_central"
    paths = {
        "surface": base / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json",
        "mobility_graph": base / "full_admin_mobility_graph_2026_07_10/full_admin_mobility_graph.json",
        "quality_audit": base / "full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return {"ready": False, "exit_code": 2, "blockers": [f"missing_{name}" for name in missing]}
    product = build_mobility_accessibility_product(**{name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()})
    bundle_id = "traditional-mobility-" + hashlib.sha256(product["product_digest"].encode()).hexdigest()[:20]
    payloads = {
        "overview.json": {"schema":"traditional_livability.mobility_overview.v1","bundle_id":bundle_id,"summary":product["summary"],"source_dataset_ids":product["source_dataset_ids"],"quality_evidence":product["quality_evidence"],"claim_boundary":product["claim_boundary"],"limitations":product["limitations"],"ranking_method":product["ranking_method"],"fabricated_value_count":0},
        "admin_units.json": {"schema":"traditional_livability.mobility_admin_units.v1","bundle_id":bundle_id,"admin_units":product["admin_units"]},
        "channel_readiness.json": {"schema":"traditional_livability.mobility_channel_readiness.v1","bundle_id":bundle_id,"channels":product["channel_readiness"]},
        "map.json": {"schema":"map_update.v1","bundle_id":bundle_id,"summary":{"title":"重庆服务可达性与路网代理差距"},"layers":[{"name":"行政单元可达性代理","type":"geojson","geojsonData":{"type":"FeatureCollection","features":[_feature(row) for row in product["admin_units"] if row["centroid"]["longitude"] is not None and row["centroid"]["latitude"] is not None]}}]},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = []
    try:
        for filename, payload in payloads.items():
            path = output_dir / f"{filename}.tmp"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
            temporary.append(path)
        for path in temporary:
            os.replace(path, output_dir / path.name.removesuffix(".tmp"))
    finally:
        for path in temporary:
            if path.exists(): path.unlink()
    return {"ready": True, "exit_code": 0, "bundle_id": bundle_id, "output_dir": str(output_dir)}


def _feature(row: dict) -> dict:
    return {"type":"Feature","properties":{"admin_unit_id":row["admin_unit_id"],"county":row["county"],"township":row["township"],"service_accessibility_score":row["service_accessibility_score"],"accessibility_gap_rank":row["accessibility_gap_rank"],"network_proxy_not_observed_walk_time":True},"geometry":{"type":"Point","coordinates":[row["centroid"]["longitude"],row["centroid"]["latitude"]]}}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--source-root",type=Path,required=True); parser.add_argument("--output-dir",type=Path,required=True); args=parser.parse_args()
    result=build_product(source_root=args.source_root,output_dir=args.output_dir); print(json.dumps(result,ensure_ascii=False,indent=2)); return int(result["exit_code"])


if __name__ == "__main__": raise SystemExit(main())
