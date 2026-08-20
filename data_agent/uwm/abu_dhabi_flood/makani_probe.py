"""Governed aggregate evidence for registered Makani stormwater assets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .smartmakani_acquisition import canonical_json_bytes

MAKANI_PROBE_SCHEMA = "gwm.abu_dhabi_flood.makani_relationship_probe.v1"
EXPECTED_SOURCE_BINDING = {
    "source_id": 13,
    "source_name": "abu-dhabi-makani-dev",
    "database_name": "makani",
    "authorized_schemas": ["layer"],
    "discovery_fingerprint": (
        "a9eb35e889383ba7d12c2c23e46aa89c39898ca9905b94a0b271faeae9db5812"
    ),
    "profile_fingerprint": (
        "b69b4935adff73d5ebcf4c2ca2010bd0549d48445eef835fd8ff076a8f96c399"
    ),
}

INVENTORY_RESOURCE_NAMES = (
    "layer.st_pipeline",
    "layer.st_inlet",
    "layer.st_catchbasin",
    "layer.st_sw_node",
    "layer.st_sw_junction",
    "layer.st_outfall",
    "layer.st_ps_pump",
    "layer.st_sw_pumpingstationstructure",
    "layer.st_sw_reservoirstructure",
    "layer.st_soakaway",
)

RELATIONSHIP_RESOURCE_NAMES = (
    *INVENTORY_RESOURCE_NAMES,
    "layer.st_chamber",
    "layer.st_collectivetank",
    "layer.st_dischargechamber",
    "layer.st_gratedchanneldrainage",
    "layer.st_petrolinterceptor",
    "layer.st_pond",
    "layer.st_ps_wet_well_area",
    "layer.st_sw_cappedend",
    "layer.st_sw_valve",
)

TARGET_RESOURCE_NAMES = RELATIONSHIP_RESOURCE_NAMES


@dataclass(frozen=True)
class MakaniProbeSpec:
    probe_id: str
    sql_filename: str
    expected_columns: tuple[str, ...]
    maximum_rows: int


PROBE_SPECS = (
    MakaniProbeSpec(
        probe_id="target_inventory",
        sql_filename="target_inventory.sql",
        expected_columns=(
            "asset_role",
            "total_count",
            "target_count",
            "target_geom_count",
            "target_empty_geom_count",
            "target_wrong_srid_count",
            "target_unitid_present_count",
            "target_unitid_distinct_count",
            "target_uid_present_count",
            "target_uid_distinct_count",
        ),
        maximum_rows=len(INVENTORY_RESOURCE_NAMES),
    ),
    MakaniProbeSpec(
        probe_id="pipeline_field_quality",
        sql_filename="pipeline_field_quality.sql",
        expected_columns=(
            "target_pipeline_count",
            "unitid_present_count",
            "unitid_distinct_count",
            "unitid2_present_count",
            "unitid2_distinct_count",
            "asset_before_present_count",
            "asset_before_valid_reference_count",
            "asset_before_sentinel_count",
            "asset_after_present_count",
            "asset_after_valid_reference_count",
            "asset_after_sentinel_count",
            "outfallid_valid_reference_count",
            "positive_diameter_count",
            "diameter_median_source_value",
            "both_inverts_present_count",
            "both_inverts_candidate_plausible_count",
        ),
        maximum_rows=1,
    ),
    MakaniProbeSpec(
        probe_id="pipeline_endpoint_identifier_matches",
        sql_filename="pipeline_endpoint_identifier_matches.sql",
        expected_columns=(
            "endpoint_role",
            "facility_role",
            "identifier_kind",
            "valid_reference_count",
            "matched_reference_count",
            "matched_percent",
            "matched_any_identifier_count",
            "matched_any_identifier_percent",
        ),
        maximum_rows=72,
    ),
    MakaniProbeSpec(
        probe_id="outfall_identifier_matches",
        sql_filename="outfall_identifier_matches.sql",
        expected_columns=(
            "asset_role",
            "identifier_kind",
            "valid_reference_count",
            "matched_reference_count",
            "matched_percent",
            "matched_any_identifier_count",
            "matched_any_identifier_percent",
        ),
        maximum_rows=16,
    ),
    MakaniProbeSpec(
        probe_id="pump_station_identifier_matches",
        sql_filename="pump_station_identifier_matches.sql",
        expected_columns=(
            "identifier_kind",
            "valid_reference_count",
            "matched_reference_count",
            "matched_percent",
            "matched_any_identifier_count",
            "matched_any_identifier_percent",
        ),
        maximum_rows=5,
    ),
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_discovery_export(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the persisted metadata-only discovery and return its scoped slice."""

    snapshot = payload.get("discovery_snapshot") or {}
    observed = {
        "source_id": payload.get("source_id"),
        "source_name": payload.get("source_name"),
        "database_name": snapshot.get("database_name"),
        "authorized_schemas": snapshot.get("authorized_schemas"),
        "discovery_fingerprint": payload.get("discovery_fingerprint"),
        "profile_fingerprint": payload.get("profile_fingerprint"),
    }
    if payload.get("status") != "ok" or payload.get("discovery_status") != "succeeded":
        raise ValueError("makani_discovery_not_succeeded")
    if observed != EXPECTED_SOURCE_BINDING:
        raise ValueError("makani_discovery_binding_drift")
    if snapshot.get("contains_source_rows") is not False:
        raise ValueError("makani_discovery_contains_source_rows")
    if snapshot.get("truncated") is not False:
        raise ValueError("makani_discovery_is_truncated")

    resources = {
        str(resource.get("name")): resource
        for resource in snapshot.get("resources") or []
        if resource.get("name") in TARGET_RESOURCE_NAMES
    }
    missing = sorted(set(TARGET_RESOURCE_NAMES) - resources.keys())
    if missing:
        raise ValueError(f"makani_discovery_missing_resources:{','.join(missing)}")
    return {
        "binding": observed,
        "last_discovery_at": payload.get("last_discovery_at"),
        "contains_source_rows": False,
        "resources": [resources[name] for name in TARGET_RESOURCE_NAMES],
    }


def validate_aggregate_result(
    spec: MakaniProbeSpec,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed unless an operator result has the exact aggregate contract."""

    if payload.get("status") != "ok":
        raise ValueError(f"makani_probe_failed:{spec.probe_id}")
    columns = tuple(str(value) for value in payload.get("columns") or [])
    if columns != spec.expected_columns:
        raise ValueError(f"makani_probe_columns_changed:{spec.probe_id}")
    row_count = int(payload.get("row_count", -1))
    rows = payload.get("rows")
    if row_count < 0 or row_count > spec.maximum_rows:
        raise ValueError(f"makani_probe_row_bound_exceeded:{spec.probe_id}")
    if not isinstance(rows, list) or len(rows) != row_count:
        raise ValueError(f"makani_probe_rows_missing:{spec.probe_id}")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError(f"makani_probe_row_shape_changed:{spec.probe_id}")
    if int(payload.get("bounded_limit", -1)) > spec.maximum_rows:
        raise ValueError(f"makani_probe_operator_limit_too_large:{spec.probe_id}")
    fingerprint = str(payload.get("result_fingerprint") or "")
    if len(fingerprint) != 64:
        raise ValueError(f"makani_probe_fingerprint_missing:{spec.probe_id}")
    return {
        "probe_id": spec.probe_id,
        "columns": list(columns),
        "row_count": row_count,
        "rows": rows,
        "result_fingerprint": fingerprint,
        "equivalence_fingerprints": payload.get("equivalence_fingerprints") or {},
        "bounded_limit": int(payload["bounded_limit"]),
        "aggregate_rows_only": True,
        "source_feature_rows_persisted": False,
    }


def build_probe_artifact(
    discovery: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    sql_contracts: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    if [item.get("probe_id") for item in results] != [
        spec.probe_id for spec in PROBE_SPECS
    ]:
        raise ValueError("makani_probe_result_set_incomplete")
    return {
        "schema": MAKANI_PROBE_SCHEMA,
        "generated_at": generated_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": discovery,
        "target_bbox_wgs84": [54.2971553, 24.2810331, 54.7659108, 24.601854],
        "target_crs": "EPSG:32640",
        "query_contracts": sql_contracts,
        "results": results,
        "privacy": {
            "aggregate_rows_persisted": True,
            "source_feature_rows_persisted": False,
            "raw_identifiers_persisted": False,
            "geometry_persisted": False,
        },
        "admission": {
            "admitted": False,
            "operator_admitted": False,
            "calibration_admitted": False,
            "relationship_evidence_class": "aggregate_diagnostic_candidate",
        },
        "claim_boundary": [
            "identifier_matches_do_not_by_themselves_establish_hydraulic_connectivity",
            "registered_asset_metadata_does_not_supply_event_operations_or_observations",
            "no_source_feature_rows_or_raw_identifiers_are_persisted_by_this_probe",
            "spatial_attachment_and_engineering_validation_remain_separate_gates",
        ],
    }


def atomic_write_probe(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def load_json_object(text: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}_is_not_json") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}_must_be_object")
    return value
