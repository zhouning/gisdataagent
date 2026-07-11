"""Versioned product assembly for UWM livability S2."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


PRODUCT_FILENAMES = {
    "parcels": "uwm_livability_s2_parcels.geojson",
    "planning_resources": "uwm_livability_s2_planning_resources.geojson",
    "facilities": "uwm_livability_s2_facilities.geojson",
    "graph_nodes": "uwm_livability_s2_graph_nodes.json",
    "graph_edges": "uwm_livability_s2_graph_edges.json",
    "land_use_dictionary": "uwm_livability_s2_land_use_dictionary.json",
    "transition_matrix": "uwm_livability_s2_transition_matrix.json",
    "evidence_manifest": "uwm_livability_s2_evidence_manifest.json",
    "build_report": "uwm_livability_s2_build_report.json",
}


def build_s2_product_payloads(
    *,
    inputs: Mapping[str, Any],
    graph_product: Mapping[str, Any],
    land_use_dictionary: Mapping[str, Any],
    transition_matrix: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build public JSON payloads from validated inputs and a state graph."""

    graph = graph_product["state_graph"]
    payloads = {
        PRODUCT_FILENAMES["parcels"]: _feature_collection(
            "uwm.livability_s2.parcels.v1",
            inputs.get("parcels") or [],
            geometry_field="display_geometry_wgs84",
            id_field="parcel_id",
        ),
        PRODUCT_FILENAMES["planning_resources"]: _feature_collection(
            "uwm.livability_s2.planning_resources.v1",
            inputs.get("planning_resources") or [],
            geometry_field="display_geometry_wgs84",
            id_field="resource_id",
        ),
        PRODUCT_FILENAMES["facilities"]: _feature_collection(
            "uwm.livability_s2.facilities.v1",
            inputs.get("current_facilities") or [],
            geometry_field="display_geometry_wgs84",
            id_field="facility_id",
        ),
        PRODUCT_FILENAMES["graph_nodes"]: {
            "schema": "uwm.livability_s2.graph_nodes.v1",
            "kernel_version": graph.get("kernel_version"),
            "state_graph_snapshot_digest": graph.get("snapshot_digest"),
            "nodes": _public_rows(graph.get("nodes") or []),
        },
        PRODUCT_FILENAMES["graph_edges"]: {
            "schema": "uwm.livability_s2.graph_edges.v1",
            "kernel_version": graph.get("kernel_version"),
            "state_graph_snapshot_digest": graph.get("snapshot_digest"),
            "edges": _public_rows(graph.get("edges") or []),
        },
        PRODUCT_FILENAMES["land_use_dictionary"]: deepcopy(dict(land_use_dictionary)),
        PRODUCT_FILENAMES["transition_matrix"]: deepcopy(dict(transition_matrix)),
        PRODUCT_FILENAMES["evidence_manifest"]: {
            "schema": "uwm.livability_s2.evidence_manifest.v1",
            "scope": inputs.get("scope"),
            "source_content_digest": inputs.get("content_digest"),
            "state_graph_snapshot_digest": graph.get("snapshot_digest"),
            "source_manifest": _public_value(inputs.get("source_manifest") or {}),
            "facility_inventory_complete": bool(
                (inputs.get("facility_inventory") or {}).get("complete_inventory")
            ),
            "synthetic_parcels_created": False,
            "claim_boundary": {
                "max_claim_level": "bounded_action_conditioned_spatial_scenario"
            },
        },
        PRODUCT_FILENAMES["build_report"]: {
            "schema": "uwm.livability_s2.build_report.v1",
            "scope": inputs.get("scope"),
            "planning_area_count": len(inputs.get("planning_areas") or []),
            **deepcopy(dict(graph_product.get("build_report") or {})),
            "planning_resource_unresolved_count": sum(
                row.get("resource_domain") == "unresolved"
                for row in inputs.get("planning_resources") or []
            ),
            "facility_inventory_complete": bool(
                (inputs.get("facility_inventory") or {}).get("complete_inventory")
            ),
            "distance_bands_m": [[0, 50], [50, 150], [150, 300]],
            "synthetic_parcels_created": False,
            "blockers": [],
        },
    }
    return {filename: attach_content_digest(payload) for filename, payload in payloads.items()}


def attach_content_digest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with a canonical public content digest."""

    public = _public_value(deepcopy(dict(payload)))
    public["content_digest"] = _content_digest(public)
    return public


def _feature_collection(
    schema: str,
    rows: list[dict[str, Any]],
    *,
    geometry_field: str,
    id_field: str,
) -> dict[str, Any]:
    features = []
    for row in sorted(rows, key=lambda value: str(value.get(id_field) or "")):
        geometry = deepcopy(row.get(geometry_field))
        properties = {
            key: _public_value(value)
            for key, value in row.items()
            if key not in {geometry_field, "metric_geometry"}
        }
        features.append(
            {
                "type": "Feature",
                "id": row.get(id_field),
                "geometry": geometry,
                "properties": properties,
            }
        )
    return {"schema": schema, "type": "FeatureCollection", "features": features}


def _public_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_public_value(row) for row in rows]


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _public_value(item)
            for key, item in value.items()
            if key not in {"absolute_path", "source_root", "metric_geometry"}
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    return value


def _content_digest(payload: Mapping[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "content_digest"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()

