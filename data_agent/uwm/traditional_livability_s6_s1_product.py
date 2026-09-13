from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_facility_dictionary import (
    compute_canonical_content_digest,
)
from data_agent.uwm.traditional_livability_s1_profiles import (
    unavailable_s1_metric_profiles,
)


FACILITY_FILENAME = "uwm_traditional_livability_s6_s1_facility_product.json"
RESOURCE_FILENAME = "uwm_traditional_livability_s6_s1_resources.json"
PROFILE_FILENAME = "uwm_traditional_livability_s1_profiles.json"
MATRIX_FILENAME = "uwm_traditional_livability_s1_matrices.json"
MANIFEST_FILENAME = "uwm_traditional_livability_s6_s1_manifest.json"


def _digest(payload: Mapping[str, Any]) -> str:
    return compute_canonical_content_digest(payload)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def build_s6_s1_product_bundle(
    *,
    facility_product: Mapping[str, Any],
    s6_resources: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    facility = deepcopy(dict(facility_product))
    resources = deepcopy(dict(s6_resources))
    if facility.get("schema") != "uwm.traditional_livability.facility_product.v1":
        return {"ready": False, "blockers": ["facility_product_invalid"]}
    if resources.get("schema") != "uwm.traditional_livability.s6_fulu_resources.v1" or resources.get("ready") is not True:
        return {"ready": False, "blockers": ["s6_resources_invalid"]}
    identity = {
        "facility_product_id": facility.get("product_id"),
        "facility_count": len(facility.get("facilities") or []),
        "s6_resource_digest": resources.get("content_digest"),
        "planning_area_ids": sorted(row.get("planning_area_id") for row in resources.get("planning_areas") or []),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bundle_id = f"traditional-livability-s6-s1-{sha256(encoded).hexdigest()[:20]}"
    facility["bundle_id"] = bundle_id
    resources["bundle_id"] = bundle_id
    profiles = unavailable_s1_metric_profiles()
    profiles["bundle_id"] = bundle_id
    matrices = {
        "schema": "uwm.traditional_livability.s1_synthesis_matrix_collection.v1",
        "bundle_id": bundle_id,
        "status": "unavailable",
        "matrices": [],
        "blockers": ["authoritative_synthesis_matrix_missing"],
    }
    facility["content_digest"] = _digest(facility)
    resources["content_digest"] = _digest(resources)
    profiles["content_digest"] = _digest(profiles)
    matrices["content_digest"] = _digest(matrices)
    manifest = {
        "schema": "uwm.traditional_livability.s6_s1_product_manifest.v1",
        "bundle_id": bundle_id,
        "workflow_ready": True,
        "s1_execution_ready": False,
        "facility_inventory_complete": bool((facility.get("source_manifest") or {}).get("complete_inventory")),
        "planning_area_count": len(resources.get("planning_areas") or []),
        "facility_count": len(facility.get("facilities") or []),
        "local_s6_facility_count": len(resources.get("current_facilities") or []),
        "blockers": [
            "authoritative_s1_metric_profile_missing",
            "authoritative_synthesis_matrix_missing",
            "fulu_village_population_missing",
            "facility_area_and_capacity_missing",
            "facility_inventory_incomplete",
        ],
        "fabricated_values": [],
        "claim_boundary": {
            "workflow_contract_available": True,
            "s1_compliance_assessed": False,
            "uwm_rollout": False,
        },
    }
    manifest["content_digest"] = _digest(manifest)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename, payload in {
        FACILITY_FILENAME: facility,
        RESOURCE_FILENAME: resources,
        PROFILE_FILENAME: profiles,
        MATRIX_FILENAME: matrices,
        MANIFEST_FILENAME: manifest,
    }.items():
        _write(output / filename, payload)
    return {"ready": True, "bundle_id": bundle_id, "output_dir": str(output), "blockers": manifest["blockers"]}
