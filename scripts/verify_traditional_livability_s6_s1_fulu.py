#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.traditional_livability_s6_s1_product import (
    FACILITY_FILENAME, MANIFEST_FILENAME, MATRIX_FILENAME, PROFILE_FILENAME, RESOURCE_FILENAME,
)


def verify_product(product_dir: Path) -> dict:
    payloads = {
        name: json.loads((product_dir / name).read_text(encoding="utf-8"))
        for name in [FACILITY_FILENAME, RESOURCE_FILENAME, PROFILE_FILENAME, MATRIX_FILENAME, MANIFEST_FILENAME]
    }
    bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    manifest = payloads[MANIFEST_FILENAME]
    checks = {
        "single_bundle_id": len(bundle_ids) == 1 and None not in bundle_ids,
        "two_planning_areas": manifest.get("planning_area_count") == 2,
        "real_facility_inventory_present": manifest.get("facility_count", 0) > 0,
        "profiles_unavailable_without_authority": payloads[PROFILE_FILENAME].get("status") == "unavailable",
        "s1_execution_blocked": manifest.get("s1_execution_ready") is False,
        "no_fabricated_values": manifest.get("fabricated_values") == [],
        "world_model_claim_disabled": (manifest.get("claim_boundary") or {}).get("uwm_rollout") is False,
    }
    summary = {
        "schema": "uwm.traditional_livability.s6_s1_verification.v1",
        "passed": all(checks.values()),
        "bundle_id": next(iter(bundle_ids)) if len(bundle_ids) == 1 else None,
        "checks": checks,
        "facility_count": manifest.get("facility_count"),
        "local_s6_facility_count": manifest.get("local_s6_facility_count"),
        "planning_area_count": manifest.get("planning_area_count"),
        "blockers": manifest.get("blockers"),
        "claim_boundary": manifest.get("claim_boundary"),
    }
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    summary["verification_digest"] = f"sha256:{sha256(encoded).hexdigest()}"
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_product(args.product_dir)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
