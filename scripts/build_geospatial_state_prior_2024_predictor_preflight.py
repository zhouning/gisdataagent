"""Build the real-data predictor preflight for the frozen 2024 P1 window."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.state_prior_predictor_preflight import (
    build_state_prior_predictor_preflight,
    validate_state_prior_predictor_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_PROTOCOL = (
    DATA_ROOT
    / "geospatial_state_prior_next_p1_protocol_2024_07_02_07"
    / "uwm_geospatial_state_prior_p1_prospective_protocol.json"
)
DEFAULT_PLAN = (
    DATA_ROOT
    / "openaq_multi_station_acquisition_plan_2024_07_02_07"
    / "uwm_openaq_multi_station_acquisition_plan.json"
)
DEFAULT_REFERENCE_AUDIT = (
    DATA_ROOT
    / "openaq_station_observations_multi_station_2018_10_17_23"
    / "openaq_acquisition_audit.json"
)
DEFAULT_ATTEMPT_MANIFEST = (
    DATA_ROOT / "openaq_station_observations_2024_07_attempt/snapshot_manifest.json"
)
DEFAULT_CROSSWALK = (
    DATA_ROOT
    / "geospatial_station_admin_crosswalk_2024_07_attempt_locations"
    / "uwm_geospatial_station_admin_crosswalk.json"
)
DEFAULT_ADMIN_UNITS = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
DEFAULT_ADMIN_MANIFEST = DATA_ROOT / "admin_units/snapshot_manifest.json"
DEFAULT_ADMIN_GRAPH = (
    DATA_ROOT / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
DEFAULT_ADMIN_METADATA_XML = Path("/Users/zhouning/Downloads/shp/xiangzhen.shp.xml")
DEFAULT_TAP_DOWNLOADED = (
    Path("/Users/zhouning/Downloads/tap_uwm") / "chongqing_pm25_2024_07_01_07" / "downloaded"
)
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_state_prior_2024_predictor_preflight"
    / "uwm_geospatial_state_prior_predictor_preflight.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--acquisition-plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--reference-acquisition-audit", type=Path, default=DEFAULT_REFERENCE_AUDIT)
    parser.add_argument("--prior-attempt-manifest", type=Path, default=DEFAULT_ATTEMPT_MANIFEST)
    parser.add_argument("--station-admin-crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--admin-units", type=Path, default=DEFAULT_ADMIN_UNITS)
    parser.add_argument("--admin-manifest", type=Path, default=DEFAULT_ADMIN_MANIFEST)
    parser.add_argument("--admin-graph", type=Path, default=DEFAULT_ADMIN_GRAPH)
    parser.add_argument(
        "--admin-source-metadata-xml", type=Path, default=DEFAULT_ADMIN_METADATA_XML
    )
    parser.add_argument("--tap-downloaded", type=Path, default=DEFAULT_TAP_DOWNLOADED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    evidence_paths = [
        args.protocol,
        args.acquisition_plan,
        args.reference_acquisition_audit,
        args.prior_attempt_manifest,
        args.station_admin_crosswalk,
        args.admin_units,
        args.admin_manifest,
        args.admin_graph,
        args.admin_source_metadata_xml,
    ]
    artifact = build_state_prior_predictor_preflight(
        assessment_id="chongqing-observed-station-p1-2024-predictor-preflight",
        created_at=args.created_at,
        protocol=_read_json(args.protocol),
        acquisition_plan=_read_json(args.acquisition_plan),
        reference_acquisition_audit=_read_json(args.reference_acquisition_audit),
        prior_attempt_manifest=_read_json(args.prior_attempt_manifest),
        station_admin_crosswalk=_read_json(args.station_admin_crosswalk),
        admin_feature_collection=_read_json(args.admin_units),
        admin_snapshot_manifest=_read_json(args.admin_manifest),
        admin_spatial_graph=_read_json(args.admin_graph),
        admin_source_metadata_xml=args.admin_source_metadata_xml,
        tap_downloaded_dir=args.tap_downloaded,
        evidence_refs=[_relative_or_absolute(path) for path in evidence_paths]
        + [str(args.tap_downloaded.resolve())],
    )
    validation = validate_state_prior_predictor_preflight(artifact)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_predictor_preflight:" + ";".join(validation["errors"])
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "preflight_sha256": artifact["preflight_sha256"],
                "pre_acquisition_predictor_inputs_ready": artifact[
                    "pre_acquisition_predictor_inputs_ready"
                ],
                "tap_support_summary": {
                    key: artifact["tap_support_summary"][key]
                    for key in (
                        "required_station_day_count",
                        "available_station_day_count",
                        "maximum_grid_distance_degrees",
                    )
                },
                "remaining_activation_blockers": artifact["remaining_activation_blockers"],
                "p1_execution_permitted": artifact["p1_execution_permitted"],
            },
            ensure_ascii=False,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    main()
