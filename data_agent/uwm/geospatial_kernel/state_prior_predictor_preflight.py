"""Data-side preflight for the frozen observed-station P1 replication."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..geospatial_state_prior_observed_station import _load_tap_support
from .state_prior_p1_prospective_protocol import (
    validate_state_prior_p1_prospective_protocol,
)
from .station_admin_crosswalk import validate_station_admin_crosswalk

STATE_PRIOR_PREDICTOR_PREFLIGHT_SCHEMA = "uwm.geospatial_kernel.state_prior_predictor_preflight.v1"

PREDICTOR_PREFLIGHT_GATES = (
    "prospective_protocol_contract_valid",
    "acquisition_plan_contract_valid",
    "plan_window_matches_frozen_holdout",
    "one_pm25_sensor_per_station",
    "bindings_match_prior_audited_catalog",
    "station_crosswalk_complete",
    "station_sets_aligned",
    "admin_geometry_support_complete",
    "graph_support_complete",
    "tap_required_file_inventory_complete",
    "tap_lag_station_day_support_complete",
    "prior_attempt_contains_no_target_measurements",
)

ACTIVATION_BLOCKERS = (
    "target_measurements_acquired",
    "admin_boundary_vintage_verified",
    "admin_source_license_verified",
    "external_registration_receipt_verified",
)

_CLAIM_BOUNDARY = {
    "max_claim_level": "not_for_claim",
    "scope": "pre_acquisition_predictor_input_audit_only",
    "observed_target_claim": False,
    "p1_result_claim": False,
    "p2_admission_permitted": False,
    "scientific_result_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}


def build_state_prior_predictor_preflight(
    *,
    assessment_id: str,
    created_at: str,
    protocol: Mapping[str, Any],
    acquisition_plan: Mapping[str, Any],
    reference_acquisition_audit: Mapping[str, Any],
    prior_attempt_manifest: Mapping[str, Any],
    station_admin_crosswalk: Mapping[str, Any],
    admin_feature_collection: Mapping[str, Any],
    admin_snapshot_manifest: Mapping[str, Any],
    admin_spatial_graph: Mapping[str, Any],
    admin_source_metadata_xml: str | Path,
    tap_downloaded_dir: str | Path,
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    """Audit real predictor availability before any final target is acquired."""

    if not _nonempty_string(assessment_id):
        raise ValueError("state_prior_predictor_preflight_assessment_id_required")
    _require_aware_timestamp(created_at)
    protocol_payload = copy.deepcopy(dict(protocol))
    plan = copy.deepcopy(dict(acquisition_plan))
    reference_audit = copy.deepcopy(dict(reference_acquisition_audit))
    attempt_manifest = copy.deepcopy(dict(prior_attempt_manifest))
    crosswalk = copy.deepcopy(dict(station_admin_crosswalk))
    admin_units = copy.deepcopy(dict(admin_feature_collection))
    admin_manifest = copy.deepcopy(dict(admin_snapshot_manifest))
    admin_graph = copy.deepcopy(dict(admin_spatial_graph))
    refs = _unique_nonempty_strings(evidence_refs)
    if not refs:
        raise ValueError("state_prior_predictor_preflight_evidence_refs_required")

    protocol_validation = validate_state_prior_p1_prospective_protocol(protocol_payload)
    plan_valid = _valid_acquisition_plan(plan)
    crosswalk_validation = validate_station_admin_crosswalk(crosswalk)
    bindings = list(plan.get("planned_bindings") or [])
    plan_station_ids = [str(row.get("station_id")) for row in bindings]
    plan_sensor_ids = [str(row.get("sensor_id")) for row in bindings]
    reference_bindings = list(reference_audit.get("selected_bindings") or [])
    reference_pairs = sorted(
        (str(row.get("station_id")), str(row.get("sensor_id"))) for row in reference_bindings
    )
    plan_pairs = sorted(zip(plan_station_ids, plan_sensor_ids, strict=True))

    crosswalk_assignments = list(crosswalk.get("assignments") or [])
    crosswalk_station_ids = sorted(
        str(row.get("station_id"))
        for row in crosswalk_assignments
        if row.get("status") == "matched"
    )
    assigned_admin_ids = sorted(
        {
            str((row.get("assignment") or {}).get("admin_id"))
            for row in crosswalk_assignments
            if row.get("status") == "matched"
        }
    )
    assigned_graph_keys = sorted(
        {
            (
                str((row.get("assignment") or {}).get("county")),
                str((row.get("assignment") or {}).get("township")),
            )
            for row in crosswalk_assignments
            if row.get("status") == "matched"
        }
    )
    admin_ids = _admin_ids(admin_units)
    graph_keys = _graph_keys(admin_graph)

    final_window = (protocol_payload.get("window_design") or {}).get("final_holdout_window") or {}
    target_start = _require_date(final_window.get("start_date"), "target_start_date")
    target_end = _require_date(final_window.get("end_date"), "target_end_date")
    target_dates = _date_range(target_start, target_end)
    lag_dates = [target_date - timedelta(days=1) for target_date in target_dates]
    expected_plan_range = {
        "datetime_from": f"{target_start.isoformat()}T00:00:00Z",
        "datetime_to": f"{(target_end + timedelta(days=1)).isoformat()}T00:00:00Z",
    }

    tap_dir = Path(tap_downloaded_dir)
    tap_support = _load_tap_support(tap_dir, bindings)
    expected_station_days = [
        (station_id, lag_date) for station_id in plan_station_ids for lag_date in lag_dates
    ]
    missing_station_days = [
        f"{station_id}|{lag_date.isoformat()}"
        for station_id, lag_date in expected_station_days
        if (station_id, lag_date) not in tap_support["values"]
    ]
    tap_inventory = _tap_inventory(tap_dir, required_dates=set(lag_dates))
    admin_provenance = _admin_provenance(
        manifest=admin_manifest,
        metadata_xml=Path(admin_source_metadata_xml),
    )

    gates = {
        "prospective_protocol_contract_valid": protocol_validation["valid"],
        "acquisition_plan_contract_valid": plan_valid,
        "plan_window_matches_frozen_holdout": (
            plan.get("measurement_time_range") == expected_plan_range
        ),
        "one_pm25_sensor_per_station": bool(bindings)
        and len(plan_station_ids) == len(set(plan_station_ids))
        and len(plan_sensor_ids) == len(set(plan_sensor_ids))
        and all(row.get("parameter") == "pm25" for row in bindings),
        "bindings_match_prior_audited_catalog": plan_pairs == reference_pairs,
        "station_crosswalk_complete": crosswalk_validation["valid"]
        and crosswalk.get("crosswalk_complete") is True,
        "station_sets_aligned": sorted(plan_station_ids) == crosswalk_station_ids,
        "admin_geometry_support_complete": bool(assigned_admin_ids)
        and set(assigned_admin_ids).issubset(admin_ids),
        "graph_support_complete": bool(assigned_graph_keys)
        and set(assigned_graph_keys).issubset(graph_keys),
        "tap_required_file_inventory_complete": tap_inventory["required_file_inventory_complete"],
        "tap_lag_station_day_support_complete": bool(expected_station_days)
        and not missing_station_days,
        "prior_attempt_contains_no_target_measurements": (
            (attempt_manifest.get("record_counts") or {}).get("measurements") == 0
            and (attempt_manifest.get("observed_time_range") or {}).get("start") is None
            and (attempt_manifest.get("observed_time_range") or {}).get("end") is None
        ),
    }
    predictor_ready = all(gates.values())
    blockers = {
        "target_measurements_acquired": False,
        "admin_boundary_vintage_verified": admin_provenance["official_boundary_vintage_verified"],
        "admin_source_license_verified": admin_provenance["source_license_verified"],
        "external_registration_receipt_verified": False,
    }
    artifact = {
        "schema": STATE_PRIOR_PREDICTOR_PREFLIGHT_SCHEMA,
        "version": "0.1",
        "assessment_id": str(assessment_id),
        "created_at": str(created_at),
        "protocol_id": protocol_payload.get("protocol_id"),
        "protocol_sha256": protocol_payload.get("protocol_sha256"),
        "input_artifact_sha256": {
            "acquisition_plan_sha256": plan.get("plan_sha256"),
            "reference_acquisition_audit_sha256": _canonical_sha256(reference_audit),
            "prior_attempt_manifest_sha256": _canonical_sha256(attempt_manifest),
            "station_admin_crosswalk_sha256": crosswalk.get("crosswalk_sha256"),
            "admin_feature_collection_sha256": _canonical_sha256(admin_units),
            "admin_snapshot_manifest_sha256": _canonical_sha256(admin_manifest),
            "admin_spatial_graph_sha256": _canonical_sha256(admin_graph),
            "tap_file_inventory_sha256": tap_inventory["file_inventory_sha256"],
        },
        "frozen_window": {
            "target_start_date": target_start.isoformat(),
            "target_end_date": target_end.isoformat(),
            "required_lag_start_date": lag_dates[0].isoformat(),
            "required_lag_end_date": lag_dates[-1].isoformat(),
        },
        "binding_summary": {
            "planned_station_count": len(plan_station_ids),
            "planned_sensor_count": len(plan_sensor_ids),
            "bindings_match_prior_audited_catalog": plan_pairs == reference_pairs,
            "matched_crosswalk_station_count": len(crosswalk_station_ids),
            "assigned_admin_group_count": len(assigned_admin_ids),
            "planned_bindings": copy.deepcopy(bindings),
        },
        "tap_support_summary": {
            "required_station_day_count": len(expected_station_days),
            "available_station_day_count": len(expected_station_days) - len(missing_station_days),
            "missing_station_day_ids": missing_station_days,
            "station_grid_assignments": tap_support["stations"],
            "maximum_grid_distance_degrees": max(
                row["distance_degrees"] for row in tap_support["stations"].values()
            ),
            "file_inventory": tap_inventory,
        },
        "admin_provenance_audit": admin_provenance,
        "gate_results": gates,
        "remaining_predictor_gates": [
            gate for gate in PREDICTOR_PREFLIGHT_GATES if not gates[gate]
        ],
        "activation_blockers": blockers,
        "remaining_activation_blockers": [
            blocker for blocker in ACTIVATION_BLOCKERS if not blockers[blocker]
        ],
        "evidence_refs": refs,
        "pre_acquisition_predictor_inputs_ready": predictor_ready,
        "p1_execution_permitted": False,
        "p2_admission_permitted": False,
        "supported_claim": "pre_acquisition_predictor_input_audit_only",
        "claim_boundary": copy.deepcopy(_CLAIM_BOUNDARY),
    }
    artifact["preflight_sha256"] = compute_state_prior_predictor_preflight_sha256(artifact)
    validation = validate_state_prior_predictor_preflight(artifact)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_predictor_preflight:" + ";".join(validation["errors"])
        )
    return artifact


def validate_state_prior_predictor_preflight(payload: Any) -> dict[str, Any]:
    """Validate predictor readiness while prohibiting P1/P2 self-activation."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["predictor_preflight_must_be_dictionary"]}
    errors: list[str] = []
    if payload.get("schema") != STATE_PRIOR_PREDICTOR_PREFLIGHT_SCHEMA:
        errors.append("predictor_preflight_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("predictor_preflight_version_mismatch")
    gates = payload.get("gate_results")
    if not isinstance(gates, dict) or tuple(gates) != PREDICTOR_PREFLIGHT_GATES:
        errors.append("predictor_preflight_gate_set_mismatch")
        expected_remaining: list[str] = []
        all_predictors_ready = False
    else:
        if any(value not in {True, False} for value in gates.values()):
            errors.append("predictor_preflight_gate_values_invalid")
        expected_remaining = [
            gate for gate in PREDICTOR_PREFLIGHT_GATES if gates.get(gate) is not True
        ]
        all_predictors_ready = not expected_remaining
    if payload.get("remaining_predictor_gates") != expected_remaining:
        errors.append("predictor_preflight_remaining_gates_mismatch")
    if payload.get("pre_acquisition_predictor_inputs_ready") is not all_predictors_ready:
        errors.append("predictor_preflight_ready_mismatch")
    blockers = payload.get("activation_blockers")
    if not isinstance(blockers, dict) or tuple(blockers) != ACTIVATION_BLOCKERS:
        errors.append("predictor_preflight_activation_blockers_invalid")
        expected_blockers: list[str] = []
    else:
        expected_blockers = [
            blocker for blocker in ACTIVATION_BLOCKERS if blockers.get(blocker) is not True
        ]
    if payload.get("remaining_activation_blockers") != expected_blockers:
        errors.append("predictor_preflight_remaining_activation_blockers_mismatch")
    if payload.get("p1_execution_permitted") is not False:
        errors.append("predictor_preflight_cannot_permit_p1_execution")
    if payload.get("p2_admission_permitted") is not False:
        errors.append("predictor_preflight_cannot_permit_p2_admission")
    if payload.get("supported_claim") != "pre_acquisition_predictor_input_audit_only":
        errors.append("predictor_preflight_supported_claim_invalid")
    if payload.get("claim_boundary") != _CLAIM_BOUNDARY:
        errors.append("predictor_preflight_claim_boundary_invalid")
    digest = payload.get("preflight_sha256")
    if not _valid_sha256(digest):
        errors.append("predictor_preflight_sha256_invalid")
    elif digest != compute_state_prior_predictor_preflight_sha256(payload):
        errors.append("predictor_preflight_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_predictor_preflight_sha256(
    payload: Mapping[str, Any],
) -> str:
    values = copy.deepcopy(dict(payload))
    values.pop("preflight_sha256", None)
    return _canonical_sha256(values)


def _valid_acquisition_plan(plan: Mapping[str, Any]) -> bool:
    if plan.get("schema") != "uwm.openaq_multi_station_acquisition_plan.v1":
        return False
    digest = plan.get("plan_sha256")
    values = copy.deepcopy(dict(plan))
    values.pop("plan_sha256", None)
    return _valid_sha256(digest) and digest == _canonical_sha256(values)


def _admin_ids(payload: Mapping[str, Any]) -> set[str]:
    result = set()
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        values = [
            str(properties.get(field) or "").strip() for field in ("province", "county", "township")
        ]
        if all(values):
            result.add("|".join(values))
    return result


def _graph_keys(payload: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(row.get("county") or "").strip(), str(row.get("township") or "").strip())
        for row in payload.get("nodes") or []
        if row.get("county") and row.get("township")
    }


def _tap_inventory(downloaded: Path, *, required_dates: set[date]) -> dict[str, Any]:
    coordinate_files = sorted(downloaded.glob("Tile_*_lonlat.csv.zip"))
    tile_ids = {
        match.group(1)
        for path in coordinate_files
        if (match := re.search(r"Tile_(\d{3})_lonlat", path.name))
    }
    raster_files: dict[tuple[date, str], Path] = {}
    for path in sorted(downloaded.glob("China_PM25_1km_*.csv.zip")):
        match = re.search(r"China_PM25_1km_(\d{4})_(\d{3})_(\d{3})", path.name)
        if not match:
            continue
        year, day_of_year, tile_id = match.groups()
        value_date = datetime.strptime(f"{year} {day_of_year}", "%Y %j").date()
        raster_files[(value_date, tile_id)] = path
    required_pairs = {
        (required_date, tile_id) for required_date in required_dates for tile_id in tile_ids
    }
    missing_pairs = sorted(required_pairs - set(raster_files))
    file_rows = [
        {
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        for path in sorted((*coordinate_files, *raster_files.values()))
    ]
    return {
        "coordinate_tile_count": len(coordinate_files),
        "tile_ids": sorted(tile_ids),
        "available_raster_date_count": len({key[0] for key in raster_files}),
        "available_raster_file_count": len(raster_files),
        "required_raster_file_count": len(required_pairs),
        "missing_required_raster_files": [
            f"{value_date.isoformat()}|{tile_id}" for value_date, tile_id in missing_pairs
        ],
        "required_file_inventory_complete": bool(tile_ids) and not missing_pairs,
        "files": file_rows,
        "file_inventory_sha256": _canonical_sha256(file_rows),
    }


def _admin_provenance(*, manifest: Mapping[str, Any], metadata_xml: Path) -> dict[str, Any]:
    process_dates: list[str] = []
    metadata_created_date = None
    if metadata_xml.is_file():
        root = ElementTree.parse(metadata_xml).getroot()
        created = root.find(".//CreaDate")
        metadata_created_date = created.text if created is not None else None
        process_dates = sorted(
            {
                str(element.attrib["Date"])
                for element in root.findall(".//Process")
                if element.attrib.get("Date")
            }
        )
    return {
        "source_dataset_id": manifest.get("dataset_id"),
        "local_source_ref": manifest.get("source_ref"),
        "derived_at": manifest.get("derived_at"),
        "metadata_xml_sha256": (_file_sha256(metadata_xml) if metadata_xml.is_file() else None),
        "metadata_created_date": metadata_created_date,
        "metadata_process_dates": process_dates,
        "external_source_url_present": False,
        "license_document_present": False,
        "official_boundary_vintage_verified": False,
        "source_license_verified": False,
        "historical_name_warning_present": any(
            "historical county names" in str(value) for value in manifest.get("limitations") or []
        ),
        "limitations": list(manifest.get("limitations") or []),
    }


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _require_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"state_prior_predictor_preflight_{field}_invalid") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _unique_nonempty_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_aware_timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("state_prior_predictor_preflight_created_at_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("state_prior_predictor_preflight_created_at_invalid")
    return parsed
