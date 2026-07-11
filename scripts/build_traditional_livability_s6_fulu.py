#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm import traditional_livability_s6_fulu_adapter as s6_adapter
from data_agent.uwm.traditional_livability_facility_dictionary import (
    unavailable_compatibility_matrix,
    unavailable_facility_dictionary,
    validate_compatibility_matrix,
    validate_facility_dictionary,
)


SCOPE = "fulu_heping_and_banzhu_planning_samples_only"
RESOURCE_FILENAME = "uwm_traditional_livability_s6_resources.json"
DICTIONARY_FILENAME = "uwm_traditional_livability_s6_dictionary.json"
COMPATIBILITY_FILENAME = "uwm_traditional_livability_s6_compatibility.json"
MANIFEST_FILENAME = "uwm_traditional_livability_s6_build_manifest.json"


def build_s6_fulu(
    *,
    source_root: Path,
    facility_product: Mapping[str, Any] | None,
    output_dir: Path,
    facility_dictionary: Mapping[str, Any] | None = None,
    compatibility_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if facility_product is None:
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": ["facility_product_missing"],
        }

    resources = s6_adapter.build_fulu_s6_resources(
        source_root=Path(source_root),
        facility_product=facility_product,
    )
    if not resources.get("ready"):
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": list(
                (resources.get("source_manifest") or {}).get("blockers") or []
            ),
        }

    public_resources = _public_payload(resources)
    dictionary = (
        validate_facility_dictionary(facility_dictionary)
        if facility_dictionary is not None
        else unavailable_facility_dictionary()
    )
    compatibility = (
        validate_compatibility_matrix(compatibility_matrix)
        if compatibility_matrix is not None
        else unavailable_compatibility_matrix()
    )
    manifest = _build_manifest(public_resources, dictionary, compatibility)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    snapshots = {
        RESOURCE_FILENAME: public_resources,
        DICTIONARY_FILENAME: dictionary,
        COMPATIBILITY_FILENAME: compatibility,
        MANIFEST_FILENAME: manifest,
    }
    for filename, payload in snapshots.items():
        _atomic_json(output_path / filename, payload)

    return {
        "ready": True,
        "exit_code": 0,
        "output_dir": str(output_path),
        "blockers": [],
    }


def _build_manifest(
    resources: Mapping[str, Any],
    dictionary: Mapping[str, Any],
    compatibility: Mapping[str, Any],
) -> dict[str, Any]:
    planning_resources = list(resources.get("planning_resources") or [])
    current_facilities = list(resources.get("current_facilities") or [])
    planning_areas = list(resources.get("planning_areas") or [])
    facility_inventory = resources.get("facility_inventory") or {}
    return {
        "schema": "uwm.traditional_livability.s6_fulu_build_manifest.v1",
        "scope": SCOPE,
        "spatial_screening_ready": bool(resources.get("ready")),
        "facility_inventory_complete": bool(
            facility_inventory.get("complete_inventory")
        ),
        "planning_resource_count": len(planning_resources),
        "planning_resource_unresolved_count": sum(
            row.get("resource_domain") == "unresolved"
            for row in planning_resources
        ),
        "current_facility_count": len(current_facilities),
        "current_facility_unresolved_count": sum(
            row.get("mapping_status") == "unmapped"
            or row.get("association_status") != "single_area_intersection"
            for row in current_facilities
        ),
        "planning_area_count": len(planning_areas),
        "planning_coverage": [
            {
                "planning_area_id": row.get("planning_area_id"),
                "distance_crs": row.get("distance_crs"),
            }
            for row in planning_areas
        ],
        "dictionary_ready": bool(dictionary.get("ready")),
        "dictionary_status": dictionary.get("status"),
        "compatibility_ready": bool(compatibility.get("ready")),
        "compatibility_status": compatibility.get("status"),
    }


def _public_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _remove_private_paths(deepcopy(dict(payload)))


def _remove_private_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_private_paths(item)
            for key, item in value.items()
            if key not in {"absolute_path", "source_root"}
        }
    if isinstance(value, list):
        return [_remove_private_paths(item) for item in value]
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--facility-product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--facility-dictionary", type=Path)
    parser.add_argument("--compatibility-matrix", type=Path)
    args = parser.parse_args(argv)

    if not args.facility_product.is_file():
        result = {
            "ready": False,
            "exit_code": 2,
            "blockers": ["facility_product_missing"],
        }
    else:
        result = build_s6_fulu(
            source_root=args.source_root,
            facility_product=_load_json(args.facility_product),
            output_dir=args.output,
            facility_dictionary=(
                _load_json(args.facility_dictionary)
                if args.facility_dictionary is not None
                else None
            ),
            compatibility_matrix=(
                _load_json(args.compatibility_matrix)
                if args.compatibility_matrix is not None
                else None
            ),
        )
    print(json.dumps(result, ensure_ascii=False))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
