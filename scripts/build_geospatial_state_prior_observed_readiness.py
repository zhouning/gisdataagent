"""Build the Chongqing observed-candidate readiness artifact for P2-D2a."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.state_prior_observed_readiness import (
    build_state_prior_observed_candidate_readiness,
)
from data_agent.uwm.geospatial_kernel.station_admin_crosswalk import (
    station_admin_assignment_map,
)
from data_agent.uwm.geospatial_state_prior_chongqing import (
    build_chongqing_pm25_state_prior_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_state_prior_observed_readiness_2026_08_04"
    / "uwm_geospatial_state_prior_observed_readiness.json"
)
DEFAULT_OPENAQ_DIRECTORY = DATA_ROOT / "openaq_station_observations"
DEFAULT_CROSSWALK = (
    DATA_ROOT
    / "geospatial_station_admin_crosswalk_2026_08_04"
    / "uwm_geospatial_station_admin_crosswalk.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--openaq-directory", type=Path, default=DEFAULT_OPENAQ_DIRECTORY)
    parser.add_argument("--station-admin-crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--multi-geometry-dataset", type=Path)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    openaq_paths = _openaq_source_paths(args.openaq_directory)
    if args.multi_geometry_dataset is not None:
        dataset = _read_json(args.multi_geometry_dataset)
        source_paths = {
            **openaq_paths,
            "multi_geometry_dataset": args.multi_geometry_dataset,
        }
    else:
        geometry_paths = _geometry_source_paths()
        source_paths = {**geometry_paths, **openaq_paths}
        dataset = build_chongqing_pm25_state_prior_dataset(
            scene_aligned_holdout=_read_json(geometry_paths["scene"]),
            admin_livability_panel=_read_json(geometry_paths["panel"]),
            admin_spatial_graph=_read_json(geometry_paths["graph"]),
            dataset_id="chongqing-three-geometry-pm25-observed-candidate-readiness",
            created_at=args.created_at,
            evidence_refs=[_relative(path) for path in source_paths.values()],
            openmeteo_weather_payload=_read_json(geometry_paths["weather"]),
            openmeteo_air_quality_payload=_read_json(geometry_paths["air_quality"]),
        )
    crosswalk_artifact = _read_json(args.station_admin_crosswalk)
    crosswalk = station_admin_assignment_map(crosswalk_artifact)
    evidence_paths = {**source_paths, "station_admin_crosswalk": args.station_admin_crosswalk}
    assessment = build_state_prior_observed_candidate_readiness(
        assessment_id="chongqing-openaq-state-prior-observed-readiness-2026-08-04",
        created_at=args.created_at,
        target_parameter="pm25",
        locations_payload=_read_json(source_paths["locations"]),
        sensor_measurement_payloads=_read_json(source_paths["measurements"]),
        multi_geometry_dataset=dataset,
        normalized_station_proxy=_read_json(source_paths["proxy"]),
        station_admin_crosswalk=crosswalk,
        evidence_refs=[_relative(path) for path in evidence_paths.values()],
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "p1_benchmark_input_ready": assessment["p1_benchmark_input_ready"],
                "p2_admission_permitted": assessment["p2_admission_permitted"],
                "remaining_gates": assessment["remaining_gates"],
                "readiness_sha256": assessment["readiness_sha256"],
            },
            ensure_ascii=False,
        )
    )


def _geometry_source_paths() -> dict[str, Path]:
    return {
        "scene": DATA_ROOT
        / "scene_aligned_gridded_air_quality_holdout_2026_07_06"
        / "uwm_scene_aligned_gridded_air_quality_holdout.json",
        "panel": DATA_ROOT
        / "admin_livability_target_2024_07_2026_07_05"
        / "uwm_admin_livability_target_panel.json",
        "graph": DATA_ROOT
        / "admin_spatial_graph_2026_07_05"
        / "uwm_admin_spatial_adjacency_graph.json",
        "weather": DATA_ROOT
        / "openmeteo_history_2024_07_01_07"
        / "openmeteo_historical_weather_raw.json",
        "air_quality": DATA_ROOT
        / "openmeteo_history_2024_07_01_07"
        / "openmeteo_historical_air_quality_raw.json",
    }


def _openaq_source_paths(openaq_directory: Path) -> dict[str, Path]:
    return {
        "locations": openaq_directory / "openaq_locations_raw.json",
        "measurements": openaq_directory / "openaq_sensor_measurements_raw.json",
        "proxy": openaq_directory / "openaq_station_observation_proxy.json",
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


if __name__ == "__main__":
    main()
