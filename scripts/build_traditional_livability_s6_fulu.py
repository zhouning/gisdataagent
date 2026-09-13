#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
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
RESOURCE_DIGEST_CONTRACT = {
    "algorithm": "sha256",
    "encoding": "utf-8",
    "serialization": "canonical_json_sorted_keys_compact_separators_preserve_list_order",
    "covered_fields": "all_top_level_public_resource_snapshot_fields_and_nested_values",
    "excluded_top_level_fields": ["content_digest"],
}


def build_s6_fulu(
    *,
    source_root: Path,
    facility_product: Mapping[str, Any] | None,
    output_dir: Path,
    facility_dictionary: Mapping[str, Any] | None = None,
    compatibility_matrix: Mapping[str, Any] | None = None,
    facility_dictionary_error: str | None = None,
    compatibility_matrix_error: str | None = None,
) -> dict[str, Any]:
    if facility_product is None:
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": ["facility_product_missing"],
        }
    if not _valid_facility_product(facility_product):
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": ["facility_product_invalid"],
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
    public_resources["digest_contract"] = deepcopy(RESOURCE_DIGEST_CONTRACT)
    try:
        public_resources["content_digest"] = _resource_content_digest(
            public_resources
        )
    except (TypeError, ValueError):
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": ["snapshot_serialization_failed"],
        }
    dictionary = _dictionary_contract(
        facility_dictionary, facility_dictionary_error
    )
    compatibility = _compatibility_contract(
        compatibility_matrix, compatibility_matrix_error
    )
    manifest = _build_manifest(public_resources, dictionary, compatibility)

    output_path = Path(output_dir)
    snapshots = {
        RESOURCE_FILENAME: public_resources,
        DICTIONARY_FILENAME: dictionary,
        COMPATIBILITY_FILENAME: compatibility,
        MANIFEST_FILENAME: manifest,
    }
    try:
        _write_snapshots_atomic(output_path, snapshots)
    except (TypeError, ValueError):
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": ["snapshot_serialization_failed"],
        }

    authority_blockers = []
    if facility_dictionary_error is not None:
        authority_blockers.append(facility_dictionary_error)
    elif facility_dictionary is not None and not dictionary.get("ready"):
        authority_blockers.append("facility_dictionary_invalid")
    if compatibility_matrix_error is not None:
        authority_blockers.append(compatibility_matrix_error)
    elif compatibility_matrix is not None and not compatibility.get("ready"):
        authority_blockers.append("compatibility_matrix_invalid")

    return {
        "ready": not authority_blockers,
        "exit_code": 2 if authority_blockers else 0,
        "output_dir": str(output_path),
        "blockers": authority_blockers,
    }


def _valid_facility_product(payload: Mapping[str, Any]) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("schema") != "uwm.traditional_livability.facility_product.v1":
        return False
    facilities = payload.get("facilities")
    if not isinstance(facilities, list) or any(
        not isinstance(row, Mapping) for row in facilities
    ):
        return False
    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, Mapping):
        return False
    if source_manifest.get("schema") != "uwm.traditional_livability.source_manifest.v1":
        return False
    sources = source_manifest.get("sources")
    return (
        isinstance(sources, list)
        and all(isinstance(row, Mapping) for row in sources)
        and isinstance(source_manifest.get("complete_inventory"), bool)
    )


def _dictionary_contract(
    payload: Mapping[str, Any] | None, error: str | None
) -> dict[str, Any]:
    if error is None:
        return (
            validate_facility_dictionary(payload)
            if payload is not None
            else unavailable_facility_dictionary()
        )
    contract = unavailable_facility_dictionary()
    contract["status"] = "dictionary_input_" + error.removeprefix(
        "facility_dictionary_"
    )
    contract["validation_errors"] = [error]
    return contract


def _compatibility_contract(
    payload: Mapping[str, Any] | None, error: str | None
) -> dict[str, Any]:
    if error is None:
        return (
            validate_compatibility_matrix(payload)
            if payload is not None
            else unavailable_compatibility_matrix()
        )
    contract = unavailable_compatibility_matrix()
    contract["status"] = "compatibility_matrix_input_" + error.removeprefix(
        "compatibility_matrix_"
    )
    contract["validation_errors"] = [error]
    return contract


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


def _resource_content_digest(payload: Mapping[str, Any]) -> str:
    digest_payload = {
        key: value for key, value in payload.items() if key != "content_digest"
    }
    serialized = json.dumps(
        digest_payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


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


def _write_snapshots_atomic(
    output_dir: Path, snapshots: Mapping[str, Mapping[str, Any]]
) -> None:
    serialized = {
        filename: json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
        for filename, payload in snapshots.items()
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths = []
    try:
        for filename, contents in serialized.items():
            temporary = (output_dir / filename).with_suffix(".json.tmp")
            temporary.write_text(contents, encoding="utf-8")
            temporary_paths.append(temporary)
        for temporary in temporary_paths:
            os.replace(temporary, temporary.with_suffix(""))
    finally:
        for temporary in temporary_paths:
            if temporary.exists():
                temporary.unlink()


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
    return payload


def _load_optional_json(
    path: Path | None, *, prefix: str
) -> tuple[Mapping[str, Any] | None, str | None]:
    if path is None:
        return None, None
    if not path.is_file():
        return None, f"{prefix}_missing"
    try:
        return _load_json(path), None
    except OSError:
        return None, f"{prefix}_unreadable"
    except (json.JSONDecodeError, ValueError):
        return None, f"{prefix}_malformed_json"


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
        try:
            facility_product = _load_json(args.facility_product)
        except (OSError, json.JSONDecodeError, ValueError):
            facility_product = None
        if facility_product is None:
            result = {
                "ready": False,
                "exit_code": 2,
                "blockers": ["facility_product_invalid"],
            }
            print(json.dumps(result, ensure_ascii=False))
            return 2
        facility_dictionary, facility_dictionary_error = _load_optional_json(
            args.facility_dictionary,
            prefix="facility_dictionary",
        )
        compatibility_matrix, compatibility_matrix_error = _load_optional_json(
            args.compatibility_matrix,
            prefix="compatibility_matrix",
        )
        result = build_s6_fulu(
            source_root=args.source_root,
            facility_product=facility_product,
            output_dir=args.output,
            facility_dictionary=facility_dictionary,
            compatibility_matrix=compatibility_matrix,
            facility_dictionary_error=facility_dictionary_error,
            compatibility_matrix_error=compatibility_matrix_error,
        )
    print(json.dumps(result, ensure_ascii=False))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
