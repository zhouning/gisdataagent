"""Build the 2018 multi-station observed-target state-prior dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_state_prior_observed_station import (
    build_observed_station_pm25_state_prior_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_OPENAQ_DIRECTORY = DATA_ROOT / "openaq_station_observations_multi_station_2018_10_17_23"
DEFAULT_CROSSWALK = (
    DATA_ROOT
    / "geospatial_station_admin_crosswalk_multi_station_2018_10_17_23"
    / "uwm_geospatial_station_admin_crosswalk.json"
)
DEFAULT_ADMIN_UNITS = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
DEFAULT_ADMIN_GRAPH = (
    DATA_ROOT / "admin_spatial_graph_2026_07_05" / "uwm_admin_spatial_adjacency_graph.json"
)
DEFAULT_TAP_DOWNLOADED = (
    Path("/Users/zhouning/Downloads/tap_uwm") / "chongqing_pm25_2018_10_17_23" / "downloaded"
)
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_dataset_2018_10_18_23"
    / "uwm_geospatial_state_prior_dataset.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--openaq-directory", type=Path, default=DEFAULT_OPENAQ_DIRECTORY)
    parser.add_argument("--station-admin-crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--admin-units", type=Path, default=DEFAULT_ADMIN_UNITS)
    parser.add_argument("--admin-graph", type=Path, default=DEFAULT_ADMIN_GRAPH)
    parser.add_argument("--tap-downloaded", type=Path, default=DEFAULT_TAP_DOWNLOADED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    locations = args.openaq_directory / "openaq_locations_raw.json"
    measurements = args.openaq_directory / "openaq_sensor_measurements_raw.json"
    evidence_paths = [
        locations,
        measurements,
        args.station_admin_crosswalk,
        args.admin_units,
        args.admin_graph,
    ]
    dataset = build_observed_station_pm25_state_prior_dataset(
        locations_payload=_read_json(locations),
        sensor_measurement_payloads=_read_json(measurements),
        station_admin_crosswalk=_read_json(args.station_admin_crosswalk),
        admin_feature_collection=_read_json(args.admin_units),
        admin_spatial_graph=_read_json(args.admin_graph),
        tap_downloaded_dir=args.tap_downloaded,
        dataset_id="chongqing-openaq-observed-station-state-prior-2018-10-18-23",
        created_at=args.created_at,
        evidence_refs=[_relative(path) for path in evidence_paths]
        + [str(args.tap_downloaded.resolve())],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "row_count": len(dataset["rows"]),
                "measured_station_count": dataset["adapter_audit"]["measured_station_count"],
                "time_group_count": dataset["adapter_audit"]["time_group_count"],
                "admin_group_count": dataset["adapter_audit"]["admin_group_count"],
                "dropped_missing_lag_sample_count": dataset["adapter_audit"][
                    "dropped_missing_lag_sample_count"
                ],
            },
            ensure_ascii=False,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    main()
