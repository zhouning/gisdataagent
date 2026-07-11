#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.livability_s2.scenario_service import S2ScenarioService


def verify_s2_fulu(*, product_dir: Path, requested_at: str) -> dict[str, Any]:
    service = S2ScenarioService(Path(product_dir))
    catalog = service.catalog()
    parcels = service.list_parcels().get("features") or []
    report = json.loads((Path(product_dir) / "uwm_livability_s2_build_report.json").read_text(encoding="utf-8"))
    cases: dict[str, dict[str, Any]] = {}
    for area_id in ("fulu_heping", "fulu_banzhu"):
        candidates = sorted(
            [feature for feature in parcels if (feature.get("properties") or {}).get("planning_area_id") == area_id],
            key=lambda feature: str(feature.get("id")),
        )
        selected = next(
            (
                feature
                for feature in candidates
                if _mapped_change_target(catalog, feature)
            ),
            None,
        )
        if selected is None:
            selected = next((feature for feature in candidates if _target_class(catalog, feature)), None)
        if selected is None:
            raise ValueError(f"verification_parcel_missing:{area_id}")
        current = str(selected["properties"]["current_land_use_class"])
        target = _mapped_change_target(catalog, selected) or _target_class(catalog, selected)
        run = service.rollout(
            parcel_id=str(selected["id"]),
            from_land_use_class=current,
            to_land_use_class=target,
            snapshot_digest=str(catalog["snapshot_digest"]),
            rationale=f"{area_id} real snapshot verification",
            requested_at=requested_at,
            actor_id="verification-runner",
            alternative_land_use_class=None,
        )
        rollout = run["rollout"]
        intervention_t2 = rollout["intervention"]["t2"]
        cases[area_id] = {
            "parcel_id": selected["id"],
            "current_land_use_class": current,
            "target_land_use_class": target,
            "transition_status": rollout["intervention"]["action_validation"]["transition"]["status"],
            "review_required": rollout["review_required"],
            "same_snapshot_for_baseline_and_intervention": rollout["baseline"]["t0_snapshot_digest"] == rollout["intervention"]["t0_snapshot_digest"] == catalog["snapshot_digest"],
            "direct_land_use_changed": rollout["direct_state_delta"]["land_use_changed"],
            "message_count": len(intervention_t2["messages"]),
            "message_digest": intervention_t2["message_digest"],
            "max_local_distance_m": intervention_t2["summary"]["max_local_distance_m"],
            "admin_propagation_stopped": intervention_t2["summary"]["admin_propagation_stopped"],
            "unsupported_prediction_heads_ready": rollout["unsupported_prediction_heads_ready"],
            "unavailable_effect_count": len(rollout["unavailable_effects"]),
            "claim_level": rollout["claim_boundary"]["max_claim_level"],
            "run_id": run["run_id"],
        }
    result = {
        "schema": "uwm.livability_s2.fulu_verification.v1",
        "ready": True,
        "snapshot_digest": catalog["snapshot_digest"],
        "kernel_version": catalog["kernel_version"],
        "cases_by_area": cases,
        "parcel_count": catalog["parcel_count"],
        "planning_resource_count": catalog["planning_resource_count"],
        "facility_count": catalog["facility_count"],
        "unmapped_planning_resource_count": report["planning_resource_unresolved_count"],
        "facility_inventory_complete": catalog["facility_inventory_complete"],
        "synthetic_parcels_created": report["synthetic_parcels_created"],
        "claim_boundary": catalog["claim_boundary"],
    }
    result["verification_digest"] = _digest(result)
    return result


def _target_class(catalog: dict[str, Any], feature: dict[str, Any]) -> str:
    current = str((feature.get("properties") or {}).get("current_land_use_class"))
    planned = str((feature.get("properties") or {}).get("planned_land_use_class") or "")
    if planned not in {"", "unavailable", current} and planned in catalog["land_use_classes"]:
        return planned
    return next((value for value in catalog["land_use_classes"] if value != current and value != "unavailable"), "")


def _mapped_change_target(catalog: dict[str, Any], feature: dict[str, Any]) -> str:
    properties = feature.get("properties") or {}
    current = str(properties.get("current_land_use_class") or "")
    planned = str(properties.get("planned_land_use_class") or "")
    unavailable = {"", "unresolved", "unavailable"}
    if (
        current not in unavailable
        and planned not in unavailable
        and current != planned
        and planned in catalog["land_use_classes"]
    ):
        return planned
    return ""


def _digest(payload: dict[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "verification_digest"}
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-dir", type=Path, required=True)
    parser.add_argument("--requested-at", default="2026-07-11T08:00:00Z")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_s2_fulu(product_dir=args.product_dir, requested_at=args.requested_at)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
