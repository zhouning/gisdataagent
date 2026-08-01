#!/usr/bin/env python3
"""Acquire the Stage 33 public source-to-target NLDI path."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import acquire_geotransport_stage29_blind_transfer_events as stage29


DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/stage33_center_hill_temporal_support_path"
)
SCHEMA = "gwm.geotransport.stage33_temporal_support_path_acquisition.v1"
OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/geospatial_temporal_support.py"
)
SOURCE_BOUNDARY_ID = "CETT1-CENTER_HILL"
SOURCE_COMID = 18421761
SOURCE_COORDINATE = (-85.8261235, 36.0975966)
TARGET_SITE_ID = "USGS-03424860"
TARGET_COMID = 18421703
TARGET_COORDINATE = (-85.9044444, 36.1861111)
NLDI_HOST = "api.water.usgs.gov"
MAXIMUM_DISTANCE_KM = 50.0
MAXIMUM_DOWNLOAD_BYTES = 2_000_000
PATH_URL = (
    "https://api.water.usgs.gov/nldi/linked-data/comid/18421761/"
    "navigation/DM/flowlines?distance=50.0"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("plan", "acquire"), required=True
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": "path_values" if values_mode else "plan",
        "purpose": (
            "bind the operational tailwater source to the Stonewall target "
            "on an independently acquired NLDI downstream path before "
            "reconciling empirical and physics temporal support"
        ),
        "frozen_operator_artifact": stage29._artifact(OPERATOR_PATH),
        "relation": {
            "relation_id": "center-hill-tailwater-to-stonewall",
            "source": {
                "boundary_id": SOURCE_BOUNDARY_ID,
                "comid": SOURCE_COMID,
                "coordinate_wgs84": list(SOURCE_COORDINATE),
                "spatial_role": "operational_tailwater_zone",
            },
            "target": {
                "site_id": TARGET_SITE_ID,
                "comid": TARGET_COMID,
                "coordinate_wgs84": list(TARGET_COORDINATE),
                "spatial_role": "observed_outlet_node",
            },
            "navigation": "downstream_main",
            "maximum_distance_km": MAXIMUM_DISTANCE_KM,
        },
        "predeclared_reconciliation": {
            "empirical_quantity": "empirical_downstream_response_lag",
            "physics_quantities": [
                "gravity_wave_time",
                "manning_kinematic_centroid_time",
                "advective_residence_time",
            ],
            "same_spatial_path_required": True,
            "all_event_common_empirical_support_required": True,
            "physics_quantity_admission_required": True,
            "numerical_overlap_required": True,
            "runtime_promotion_allowed": False,
        },
        "request_boundary": {
            "allowed_hosts": [NLDI_HOST],
            "maximum_request_count": 1,
            "maximum_total_download_bytes": MAXIMUM_DOWNLOAD_BYTES,
            "workspace_or_private_data_sent": False,
            "release_or_downstream_outcome_values_requested": False,
        },
        "sources": [
            {
                "source_id": "nldi_tailwater_downstream_flowlines_50km",
                "source": "usgs_nldi",
                "role": "source_to_target_spatial_path",
                "url": PATH_URL,
                "output_name": (
                    "raw/nldi_tailwater_downstream_flowlines_50km.json"
                ),
                "maximum_bytes": MAXIMUM_DOWNLOAD_BYTES,
                "license": "USGS public-domain data",
                "license_url": (
                    "https://www.usgs.gov/information-policies-and-"
                    "instructions/copyrights-and-credits"
                ),
            }
        ],
        "claim_boundary": {
            "path_values_acquired": values_mode,
            "spatial_path_identity_admitted": False,
            "physics_time_admitted": False,
            "empirical_physics_consistency_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage33_positive_request_limits_required")
    output = stage29._validate_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.phase == "plan":
        path = output / "acquisition_plan.json"
        stage29._write_json(path, compile_plan())
    else:
        path = _acquire(args, output)
    print(path)
    return 0


def _acquire(args: argparse.Namespace, output: Path) -> Path:
    plan_path = output / "acquisition_plan.json"
    frozen_plan = _load_exact_plan(plan_path, compile_plan())
    values_plan = compile_plan(values_mode=True)
    source = values_plan["sources"][0]
    _validate_url(str(source["url"]))
    body, retrieval = stage29._fetch(
        str(source["url"]),
        opener=stage29._opener(args.proxy),
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        maximum_bytes=int(source["maximum_bytes"]),
    )
    payload = stage29._json_object(body)
    path_features = _validate_path_payload(payload)
    raw_path = output / str(source["output_name"])
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(body)
    artifact = stage29._artifact_record(
        raw_path, source=source, retrieval=retrieval
    )
    manifest = {
        **values_plan,
        "status": "source_to_target_path_acquired",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "frozen_acquisition_plan": stage29._artifact(plan_path),
        "frozen_acquisition_plan_content": frozen_plan,
        "path_feature_ids": [
            int(value["properties"]["nhdplus_comid"])
            for value in path_features
        ],
        "path_feature_count": len(path_features),
        "source_is_first_path_feature": True,
        "target_reached": True,
        "features_after_target_excluded": (
            len(payload["features"]) - len(path_features)
        ),
        "artifacts": [artifact],
        "artifact_count": 1,
        "actual_request_count": 1,
        "total_downloaded_bytes": len(body),
        "claim_boundary_after_acquisition": {
            "operator_frozen_before_path_values": True,
            "source_to_target_path_acquired": True,
            "temporal_support_reconciliation_compiled": False,
            "physics_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }
    path = output / "acquisition_manifest.json"
    stage29._write_json(path, manifest)
    print(f"path_features={len(path_features)}")
    print(f"downloaded_bytes={len(body)}")
    return path


def _validate_path_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if payload.get("type") != "FeatureCollection":
        raise ValueError("stage33_nldi_feature_collection_required")
    features = payload.get("features") or []
    ids = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        if (
            feature.get("type") != "Feature"
            or geometry.get("type") != "LineString"
            or len(geometry.get("coordinates") or []) < 2
            or "nhdplus_comid" not in properties
        ):
            raise ValueError("stage33_nldi_flowline_invalid")
        ids.append(int(properties["nhdplus_comid"]))
    if len(ids) != len(set(ids)) or not ids or ids[0] != SOURCE_COMID:
        raise ValueError("stage33_nldi_source_path_invalid")
    if ids.count(TARGET_COMID) != 1:
        raise ValueError("stage33_nldi_target_not_unique")
    target_index = ids.index(TARGET_COMID)
    return list(features[: target_index + 1])


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != NLDI_HOST:
        raise ValueError("stage33_temporal_path_url_outside_allowlist")


def _load_exact_plan(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("stage33_plan_must_be_frozen_before_path_values")
    value = json.loads(path.read_bytes())
    if value != expected:
        raise ValueError("stage33_frozen_plan_mismatch")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
