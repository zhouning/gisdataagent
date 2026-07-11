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

from data_agent.uwm.traditional_livability_s7_gated_product import (
    GATE_FILENAME, MANIFEST_FILENAME, SITING_FILENAME,
)


def verify_product(product_dir: Path) -> dict:
    gate = json.loads((product_dir / GATE_FILENAME).read_text(encoding="utf-8"))
    siting = json.loads((product_dir / SITING_FILENAME).read_text(encoding="utf-8"))
    manifest = json.loads((product_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    ranked = siting.get("ranked_candidates") or []
    selected = siting.get("selected_sites") or []
    checks = {
        "single_bundle": len({gate.get("bundle_id"), siting.get("bundle_id"), manifest.get("bundle_id")}) == 1,
        "need_unresolved": gate.get("state") == "need_unresolved",
        "conditional_only": siting.get("recommendation_status") == "conditional_candidate_ranking_available",
        "all_ranked_not_recommendations": bool(ranked) and all(row.get("not_a_site_recommendation") is True for row in ranked),
        "all_selected_not_recommendations": all(row.get("not_a_site_recommendation") is True for row in selected),
        "authoritative_recommendation_disabled": manifest.get("authoritative_recommendation_available") is False,
        "no_fabricated_values": manifest.get("fabricated_values") == [],
        "uwm_claim_disabled": (manifest.get("claim_boundary") or {}).get("uwm_rollout") is False,
    }
    result = {
        "schema": "uwm.traditional_livability.s7_gated_verification.v1",
        "passed": all(checks.values()),
        "bundle_id": manifest.get("bundle_id"),
        "checks": checks,
        "planning_area_count": manifest.get("planning_area_count"),
        "ranked_candidate_count": len(ranked),
        "selected_conditional_count": len(selected),
        "blockers": manifest.get("blockers"),
        "claim_boundary": manifest.get("claim_boundary"),
    }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result["verification_digest"] = f"sha256:{sha256(encoded).hexdigest()}"
    return result


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
