#!/usr/bin/env python3
"""Audit Center Hill terminal-reach forcing support from NHDPlus V2.1."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any, Mapping

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import Window
from shapely import make_valid
from shapely.geometry import shape
from shapely.ops import transform as transform_geometry

from data_agent.uwm.geospatial_kernel_v2 import ReachForcingSupport


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = Path("/tmp/NHDPlusV21_MS_05_05a_FdrFac_01.7z")
DEFAULT_RASTER_ROOT = Path(
    "/tmp/gwm_nhdplus_fdr05a/NHDPlusMS/NHDPlus05/NHDPlusFdrFac05a"
)
DEFAULT_STAGING = Path("/tmp/gwm_center_hill_d2_source")
DEFAULT_GAUGE = REPO_ROOT / "data/geotransport_v0_1/metadata/nldi-link-03424860.json"
DEFAULT_INITIAL_STATE = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_initial_state_nwm_v3/"
    "acquisition_manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/geotransport_v0_1/"
    "center_hill_terminal_forcing_support_nhdplus_v21"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/"
    "center_hill_terminal_forcing_support_report.json"
)

SCHEMA = "gwm.geotransport.center_hill_terminal_forcing_support.v1"
NHDPLUS_ARCHIVE_URL = (
    "https://dmap-data-commons-ow.s3.amazonaws.com/NHDPlusV21/Data/"
    "NHDPlusMS/NHDPlus05/NHDPlusV21_MS_05_05a_FdrFac_01.7z"
)
NHDPLUS_ARCHIVE_SIZE = 100_777_847
NHDPLUS_ARCHIVE_SHA256 = (
    "f134e77d7d910c32839313063001f7584e524b39afd7eecd85b451a054026d02"
)
NHDPLUS_ARCHIVE_ETAG = '"16e05500a06a2c855e3658f640c103e1-13"'
NHDPLUS_ARCHIVE_LAST_MODIFIED = "Fri, 16 Dec 2022 18:57:58 GMT"
ARCGIS_ITEM_ID = "4bd9b6892530404abfe13645fcb5099a"
ARCGIS_ITEM_URL = (
    f"https://www.arcgis.com/sharing/rest/content/items/{ARCGIS_ITEM_ID}?f=json"
)
ARCGIS_FLOWLINE_URL = (
    "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
    "NHDPlusV21/FeatureServer/2/query?where=COMID%3D18421703&"
    "outFields=*&returnGeometry=true&outSR=4326&f=geojson"
)
NLDI_FLOWLINE_URL = "https://api.water.usgs.gov/nldi/linked-data/comid/18421703"
NLDI_PROCESS_URL = (
    "https://api.water.usgs.gov/nldi/pygeoapi/processes/nldi-splitcatchment"
)
NLDI_EXECUTION_URL = NLDI_PROCESS_URL + "/execution"
TERMINAL_COMID = 18_421_703
GAUGE_SITE_ID = "03424860"
RASTER_CRS = "EPSG:5070"
CELL_SIZE_M = 30.0
CELL_AREA_KM2 = CELL_SIZE_M**2 / 1_000_000.0
MAIN_CHANNEL_DRAINAGE_RELATIVE_TOLERANCE = 0.05
EXPECTED_SELECTED_CELL = (11_747, 10_831)
EXPECTED_CHAIN_LENGTH = 9
SELECTED_CHAIN_INDEX = 2

D8_OFFSETS = {
    1: (0, 1),
    2: (1, 1),
    4: (1, 0),
    8: (1, -1),
    16: (0, -1),
    32: (-1, -1),
    64: (-1, 0),
    128: (-1, 1),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--raster-root", type=Path, default=DEFAULT_RASTER_ROOT)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--gauge", type=Path, default=DEFAULT_GAUGE)
    parser.add_argument("--initial-state", type=Path, default=DEFAULT_INITIAL_STATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plan = compile_plan()
    _write_json(args.output / "acquisition_plan.json", plan)
    if args.plan_only:
        print(args.output / "acquisition_plan.json")
        return 0

    compiled = compile_audit(
        archive_path=args.archive,
        raster_root=args.raster_root,
        staging_root=args.staging,
        gauge_path=args.gauge,
        initial_state_path=args.initial_state,
    )
    raw_artifacts = _persist_raw_snapshots(args.staging, args.output / "raw")
    window_path = args.output / "fac_fdr_window.csv"
    _write_window_csv(window_path, compiled.pop("window_rows"))
    support_path = args.output / "forcing_support.json"
    _write_json(support_path, compiled["forcing_support"])

    compiled["source_artifacts"] = {
        **raw_artifacts,
        "fac_fdr_window": _artifact(window_path),
        "gauge_link": _artifact(args.gauge),
        "initial_state_manifest": _artifact(args.initial_state),
    }
    compiled["forcing_support_artifact"] = _artifact(support_path)
    manifest = {
        **plan,
        "mode": "values",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **compiled,
    }
    manifest_path = args.output / "acquisition_manifest.json"
    _write_json(manifest_path, manifest)

    report = {
        "schema": SCHEMA,
        "generated_at": manifest["generated_at"],
        "status": manifest["status"],
        "system_id": manifest["system_id"],
        "terminal_feature_id": manifest["terminal_feature_id"],
        "gates": manifest["gates"],
        "coverage_adjudication": manifest["coverage_adjudication"],
        "forcing_support": manifest["forcing_support"],
        "claim_boundary": manifest["claim_boundary"],
        "source_manifest": _artifact(manifest_path),
    }
    _write_json(args.report, report)
    print(manifest_path)
    print(args.report)
    return 0 if manifest["status"].startswith("pass") else 2


def compile_plan() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": "plan",
        "system_id": "center_hill",
        "terminal_feature_id": TERMINAL_COMID,
        "gauge_site_id": GAUGE_SITE_ID,
        "sources": {
            "nhdplus_fdr_fac_archive": {
                "url": NHDPLUS_ARCHIVE_URL,
                "size_bytes": NHDPLUS_ARCHIVE_SIZE,
                "sha256": NHDPLUS_ARCHIVE_SHA256,
                "etag": NHDPLUS_ARCHIVE_ETAG,
                "last_modified": NHDPLUS_ARCHIVE_LAST_MODIFIED,
                "archive_redistributed": False,
            },
            "arcgis_item": {"url": ARCGIS_ITEM_URL, "item_id": ARCGIS_ITEM_ID},
            "arcgis_terminal_flowline": {"url": ARCGIS_FLOWLINE_URL},
            "nldi_terminal_flowline": {"url": NLDI_FLOWLINE_URL},
            "nldi_process_description": {"url": NLDI_PROCESS_URL},
            "nldi_splitcatchment_execution": {
                "url": NLDI_EXECUTION_URL,
                "upstream": False,
                "simplified": False,
                "response": "document",
            },
        },
        "frozen_method": {
            "linear_reference": (
                "project NLDI COMID geometry to EPSG:5070 and interpolate at "
                "(ToMeas-measure)/(ToMeas-FromMeas)"
            ),
            "snap": (
                "nearest 30 m FAC cell whose accumulated drainage area is within "
                "5 percent of terminal TotDASqKM"
            ),
            "main_channel_chain": (
                "two maximum-FAC incoming D8 cells, selected cell, and six D8 "
                "downstream cells"
            ),
            "coverage": (
                "area(intersection(splitCatchment, catchment)) / area(catchment) "
                "in EPSG:5070"
            ),
            "allocation": (
                "project full-reach NWM q_lateral by upstream split-catchment "
                "area fraction"
            ),
        },
        "data_isolation": {
            "evaluation_outcome_loaded": False,
            "evaluation_action_values_loaded": False,
            "evaluation_forcing_values_loaded": False,
            "center_hill_chunk_561_loaded": False,
        },
    }


def compile_audit(
    *,
    archive_path: Path,
    raster_root: Path,
    staging_root: Path,
    gauge_path: Path,
    initial_state_path: Path,
) -> dict[str, Any]:
    archive_size = archive_path.stat().st_size
    archive_sha = _sha256_file(archive_path)
    archive_gate = (
        archive_size == NHDPLUS_ARCHIVE_SIZE
        and archive_sha == NHDPLUS_ARCHIVE_SHA256
    )
    if not archive_gate:
        raise ValueError("terminal_support_nhdplus_archive_identity_mismatch")

    gauge = _single_feature(_load_json(gauge_path), "gauge_link")
    gauge_properties = gauge.get("properties") or {}
    if (
        gauge.get("id") != f"USGS-{GAUGE_SITE_ID}"
        or int(gauge_properties.get("comid")) != TERMINAL_COMID
    ):
        raise ValueError("terminal_support_gauge_identity_mismatch")
    gauge_measure = float(gauge_properties["measure"])
    gauge_coordinates = tuple(float(value) for value in gauge["geometry"]["coordinates"])

    item = _load_json(staging_root / "arcgis-item.json")
    if (
        item.get("id") != ARCGIS_ITEM_ID
        or item.get("title") != "National Hydrography Dataset Plus Version 2.1"
        or item.get("owner") != "esri_environment"
    ):
        raise ValueError("terminal_support_arcgis_item_identity_mismatch")
    arcgis = _single_feature(
        _load_json(staging_root / "arcgis-flowline.json"), "arcgis_flowline"
    )
    properties = arcgis.get("properties") or {}
    if int(properties.get("COMID")) != TERMINAL_COMID:
        raise ValueError("terminal_support_arcgis_comid_mismatch")
    local_catchment_area_km2 = float(properties["AreaSqKM"])
    total_drainage_area_km2 = float(properties["TotDASqKM"])
    from_measure = float(properties["FromMeas"])
    to_measure = float(properties["ToMeas"])

    nldi = _single_feature(
        _load_json(staging_root / "nldi-flowline.json"), "nldi_flowline"
    )
    if int((nldi.get("properties") or {}).get("comid")) != TERMINAL_COMID:
        raise ValueError("terminal_support_nldi_flowline_identity_mismatch")
    line = shape(nldi["geometry"])
    forward = Transformer.from_crs("EPSG:4326", RASTER_CRS, always_xy=True).transform
    inverse = Transformer.from_crs(RASTER_CRS, "EPSG:4326", always_xy=True).transform
    projected_line = transform_geometry(forward, line)
    interpolation_fraction = (to_measure - gauge_measure) / (
        to_measure - from_measure
    )
    measure_point = projected_line.interpolate(interpolation_fraction, normalized=True)
    measure_lonlat = transform_geometry(inverse, measure_point)

    process = _load_json(staging_root / "process-description.json")
    if process.get("id") != "nldi-splitcatchment":
        raise ValueError("terminal_support_process_identity_mismatch")

    with rasterio.open(raster_root / "fac") as fac, rasterio.open(
        raster_root / "fdr"
    ) as fdr:
        raster_gate = _validate_rasters(fac, fdr)
        window_rows = _read_window(
            fac,
            fdr,
            x=float(measure_point.x),
            y=float(measure_point.y),
            total_drainage_area_km2=total_drainage_area_km2,
        )
        candidates = [row for row in window_rows if row["main_channel_candidate"]]
        if not candidates:
            raise ValueError("terminal_support_main_channel_candidate_missing")
        selected = min(candidates, key=lambda row: row["distance_to_measure_m"])
        selected_cell = (int(selected["row"]), int(selected["col"]))
        if selected_cell != EXPECTED_SELECTED_CELL:
            raise ValueError("terminal_support_selected_cell_frozen_identity_mismatch")
        chain_cells = _build_chain(
            fac,
            fdr,
            selected_cell=selected_cell,
            total_drainage_area_km2=total_drainage_area_km2,
        )

    if len(chain_cells) != EXPECTED_CHAIN_LENGTH:
        raise ValueError("terminal_support_main_channel_chain_length_mismatch")
    probes = []
    catchment_geometry_sha = None
    for index, cell in enumerate(chain_cells):
        response_path = staging_root / f"chain-{index:02d}.json"
        probe = _compile_split_probe(
            response_path,
            expected_catchment_id=TERMINAL_COMID,
        )
        if catchment_geometry_sha is None:
            catchment_geometry_sha = probe["catchment_geometry_sha256"]
        elif probe["catchment_geometry_sha256"] != catchment_geometry_sha:
            raise ValueError("terminal_support_chain_catchment_geometry_changed")
        probes.append({**cell, **probe, "role": _chain_role(index)})

    coverages = [float(probe["coverage_fraction"]) for probe in probes]
    monotonic_gate = all(
        right >= left for left, right in zip(coverages, coverages[1:])
    )
    selected_probe = probes[SELECTED_CHAIN_INDEX]
    selected_repeat = _compile_split_probe(
        staging_root / "selected-repeat.json",
        expected_catchment_id=TERMINAL_COMID,
    )
    nearest_centerline = _compile_split_probe(
        staging_root / "nearest-centerline.json",
        expected_catchment_id=TERMINAL_COMID,
    )
    official_measure = _compile_split_probe(
        staging_root / "official-measure.json",
        expected_catchment_id=TERMINAL_COMID,
    )
    raw_gauge = _compile_split_probe(
        staging_root / "usgs-coordinate.json",
        expected_catchment_id=TERMINAL_COMID,
        allow_invalid_split=True,
    )
    repeat_gate = (
        selected_repeat["response_sha256"] == selected_probe["response_sha256"]
    )
    centerline_gate = (
        nearest_centerline["response_sha256"] == selected_probe["response_sha256"]
    )
    negative_control_gate = (
        official_measure["coverage_fraction"] < 0.2
        and raw_gauge["coverage_fraction"] < 0.01
        and selected_probe["coverage_fraction"] > 0.8
    )
    catchment_area_relative_error = abs(
        selected_probe["catchment_area_km2"] - local_catchment_area_km2
    ) / local_catchment_area_km2
    catchment_area_gate = catchment_area_relative_error <= 0.001

    initial_state = _load_json(initial_state_path)
    active_ids = tuple(
        int(value) for value in initial_state["decoded_state"]["active_feature_ids"]
    )
    if not active_ids or active_ids[-1] != TERMINAL_COMID:
        raise ValueError("terminal_support_initial_state_feature_axis_mismatch")
    selected_coverage = float(selected_probe["coverage_fraction"])
    fractions = (1.0,) * (len(active_ids) - 1) + (selected_coverage,)
    support = ReachForcingSupport(
        feature_ids=active_ids,
        coverage_fractions=fractions,
        support_method=(
            "nhdplus_v21_30m_fdr_fac_main_channel_snap_and_"
            "nldi_splitcatchment_intersection_area"
        ),
        provenance_id="nhdplus-v21:05a:comid-18421703:nldi-splitcatchment",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    ).as_dict()
    support["coverage_uncertainty"] = {
        "kind": "adjacent_d8_cell_quantization_bracket",
        "lower_fraction": float(probes[SELECTED_CHAIN_INDEX - 1]["coverage_fraction"]),
        "central_fraction": selected_coverage,
        "upper_fraction": float(probes[SELECTED_CHAIN_INDEX + 1]["coverage_fraction"]),
        "cell_size_m": CELL_SIZE_M,
    }
    support["allocation_semantics"] = {
        "input_quantity": "NWM v3 retrospective full-reach q_lateral",
        "projection": "multiply by upstream split-catchment area fraction",
        "subcatchment_q_lateral_values_observed": False,
        "ground_truth": False,
        "modeled_forcing_role_preserved": True,
    }

    gates = {
        "nhdplus_archive_identity": archive_gate,
        "fac_fdr_raster_contract": raster_gate,
        "nldi_linear_reference_inside_terminal_reach": 0.0 < interpolation_fraction < 1.0,
        "main_channel_candidate_unique_nearest": sum(
            math.isclose(
                row["distance_to_measure_m"],
                selected["distance_to_measure_m"],
                abs_tol=1e-9,
            )
            for row in candidates
        )
        == 1,
        "selected_fac_matches_terminal_drainage_scale": bool(
            selected["main_channel_candidate"]
        ),
        "main_channel_split_coverage_monotonic": monotonic_gate,
        "selected_split_response_repeat_byte_identical": repeat_gate,
        "nearest_centerline_and_selected_cell_response_identical": centerline_gate,
        "unsnapped_coordinates_fail_negative_control": negative_control_gate,
        "split_catchment_matches_terminal_area": catchment_area_gate,
        "forcing_support_feature_axis_matches_initial_state": (
            tuple(support["feature_ids"]) == active_ids
        ),
        "full_reach_coverage_fractions_equal_one": all(
            math.isclose(value, 1.0, abs_tol=1e-12)
            for value in fractions[:-1]
        ),
        "terminal_coverage_fraction_inside_unit_interval": 0.0 < selected_coverage < 1.0,
        "chunk_561_isolation": True,
        "outcome_isolation": True,
    }
    all_passed = all(gates.values())
    if not all_passed:
        failed = [key for key, passed in gates.items() if not passed]
        raise ValueError("terminal_support_gate_failed:" + ",".join(failed))

    return {
        "status": "pass_with_30m_quantization_bracket",
        "system_id": "center_hill",
        "terminal_feature_id": TERMINAL_COMID,
        "archive_audit": {
            "source_url": NHDPLUS_ARCHIVE_URL,
            "size_bytes": archive_size,
            "sha256": archive_sha,
            "archive_copied_into_repository": False,
        },
        "terminal_flowline": {
            "comid": TERMINAL_COMID,
            "area_sq_km": local_catchment_area_km2,
            "total_drainage_area_sq_km": total_drainage_area_km2,
            "length_km": float(properties["LENGTHKM"]),
            "from_measure": from_measure,
            "to_measure": to_measure,
        },
        "gauge_linear_reference": {
            "site_id": GAUGE_SITE_ID,
            "raw_longitude": gauge_coordinates[0],
            "raw_latitude": gauge_coordinates[1],
            "measure": gauge_measure,
            "interpolation_fraction_from_geometry_start": interpolation_fraction,
            "measure_longitude": float(measure_lonlat.x),
            "measure_latitude": float(measure_lonlat.y),
            "measure_x_epsg5070": float(measure_point.x),
            "measure_y_epsg5070": float(measure_point.y),
            "nldi_flowline_length_m_epsg5070": float(projected_line.length),
        },
        "selected_main_channel_cell": selected,
        "main_channel_chain": probes,
        "negative_controls": {
            "unsnapped_official_measure": official_measure,
            "unsnapped_raw_usgs_coordinate": raw_gauge,
        },
        "coverage_adjudication": {
            "coverage_formula": (
                "EPSG:5070 area(intersection(splitCatchment, catchment)) / "
                "area(catchment)"
            ),
            "central_fraction": selected_coverage,
            "upstream_adjacent_fraction": float(
                probes[SELECTED_CHAIN_INDEX - 1]["coverage_fraction"]
            ),
            "downstream_adjacent_fraction": float(
                probes[SELECTED_CHAIN_INDEX + 1]["coverage_fraction"]
            ),
            "catchment_area_km2": float(selected_probe["catchment_area_km2"]),
            "attribute_area_km2": local_catchment_area_km2,
            "catchment_area_relative_error": catchment_area_relative_error,
            "selected_fac_cell_count": int(selected["fac_cell_count"]),
            "selected_fac_drainage_area_km2": float(
                selected["fac_drainage_area_km2"]
            ),
            "selected_to_total_drainage_area_ratio": float(
                selected["fac_drainage_area_km2"] / total_drainage_area_km2
            ),
            "quantization_is_zero": False,
            "single_fraction_without_bracket_permitted": False,
        },
        "forcing_support": support,
        "gates": gates,
        "window_rows": window_rows,
        "claim_boundary": {
            "terminal_partial_reach_spatial_support_validated": True,
            "terminal_q_lateral_area_projection_admitted": True,
            "real_forcing_spatial_support_validated": True,
            "subcatchment_q_lateral_values_observed": False,
            "coverage_quantization_resolved_to_zero": False,
            "center_hill_d2_action_forcing_gate_passed": True,
            "center_hill_retrospective_transition_input_execution_admitted": True,
            "operational_online_execution_admitted": False,
            "new_evaluation_protocol_frozen": False,
            "center_hill_chunk_561_loaded": False,
            "evaluation_outcome_loaded": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_rasters(fac: rasterio.io.DatasetReader, fdr: rasterio.io.DatasetReader) -> bool:
    return bool(
        fac.driver == fdr.driver == "AIG"
        and fac.crs is not None
        and fac.crs.to_string() == RASTER_CRS
        and fdr.crs == fac.crs
        and fac.shape == fdr.shape == (16_058, 20_843)
        and fac.transform == fdr.transform
        and math.isclose(fac.transform.a, CELL_SIZE_M, abs_tol=1e-12)
        and math.isclose(fac.transform.e, -CELL_SIZE_M, abs_tol=1e-12)
        and fac.dtypes == ("int32",)
        and fdr.dtypes == ("uint8",)
    )


def _read_window(
    fac: rasterio.io.DatasetReader,
    fdr: rasterio.io.DatasetReader,
    *,
    x: float,
    y: float,
    total_drainage_area_km2: float,
) -> list[dict[str, Any]]:
    center_row, center_col = fac.index(x, y)
    rows = []
    for row in range(center_row - 2, center_row + 3):
        for col in range(center_col - 2, center_col + 3):
            fac_value = _cell_value(fac, row, col)
            fdr_value = _cell_value(fdr, row, col)
            center_x, center_y = fac.xy(row, col)
            drainage_area = (
                (fac_value + 1) * CELL_AREA_KM2 if fac_value >= 0 else None
            )
            candidate = bool(
                drainage_area is not None
                and abs(drainage_area - total_drainage_area_km2)
                / total_drainage_area_km2
                <= MAIN_CHANNEL_DRAINAGE_RELATIVE_TOLERANCE
            )
            rows.append(
                {
                    "row": row,
                    "col": col,
                    "center_x_epsg5070": float(center_x),
                    "center_y_epsg5070": float(center_y),
                    "distance_to_measure_m": float(
                        math.hypot(center_x - x, center_y - y)
                    ),
                    "fac_cell_count": fac_value,
                    "fac_drainage_area_km2": drainage_area,
                    "fdr_code": fdr_value,
                    "main_channel_candidate": candidate,
                }
            )
    return rows


def _build_chain(
    fac: rasterio.io.DatasetReader,
    fdr: rasterio.io.DatasetReader,
    *,
    selected_cell: tuple[int, int],
    total_drainage_area_km2: float,
) -> list[dict[str, Any]]:
    upstream = []
    current = selected_cell
    for _ in range(2):
        incoming = []
        for row in range(current[0] - 1, current[0] + 2):
            for col in range(current[1] - 1, current[1] + 2):
                if (row, col) == current:
                    continue
                code = _cell_value(fdr, row, col)
                if code not in D8_OFFSETS:
                    continue
                offset = D8_OFFSETS[code]
                if (row + offset[0], col + offset[1]) != current:
                    continue
                fac_value = _cell_value(fac, row, col)
                area = (fac_value + 1) * CELL_AREA_KM2
                if (
                    abs(area - total_drainage_area_km2)
                    / total_drainage_area_km2
                    <= MAIN_CHANNEL_DRAINAGE_RELATIVE_TOLERANCE
                ):
                    incoming.append((fac_value, row, col))
        if not incoming:
            raise ValueError("terminal_support_upstream_main_channel_missing")
        _, row, col = max(incoming)
        current = (row, col)
        upstream.append(current)
    cells = list(reversed(upstream)) + [selected_cell]
    current = selected_cell
    for _ in range(6):
        code = _cell_value(fdr, current[0], current[1])
        if code not in D8_OFFSETS:
            raise ValueError("terminal_support_downstream_fdr_code_invalid")
        offset = D8_OFFSETS[code]
        current = (current[0] + offset[0], current[1] + offset[1])
        cells.append(current)

    inverse = Transformer.from_crs(RASTER_CRS, "EPSG:4326", always_xy=True)
    records = []
    for row, col in cells:
        center_x, center_y = fac.xy(row, col)
        lon, lat = inverse.transform(center_x, center_y)
        fac_value = _cell_value(fac, row, col)
        records.append(
            {
                "row": row,
                "col": col,
                "center_x_epsg5070": float(center_x),
                "center_y_epsg5070": float(center_y),
                "longitude": float(lon),
                "latitude": float(lat),
                "fac_cell_count": fac_value,
                "fac_drainage_area_km2": (fac_value + 1) * CELL_AREA_KM2,
                "fdr_code": _cell_value(fdr, row, col),
            }
        )
    return records


def _compile_split_probe(
    path: Path,
    *,
    expected_catchment_id: int,
    allow_invalid_split: bool = False,
) -> dict[str, Any]:
    body = path.read_bytes()
    payload = json.loads(body)
    outputs = payload.get("outputs") or []
    if len(outputs) != 1 or outputs[0].get("type") != "FeatureCollection":
        raise ValueError(f"terminal_support_split_response_invalid:{path.name}")
    by_id = {feature.get("id"): feature for feature in outputs[0].get("features") or []}
    if set(by_id) != {"catchment", "splitCatchment"}:
        raise ValueError(f"terminal_support_split_features_invalid:{path.name}")
    if int((by_id["catchment"].get("properties") or {}).get("catchmentID")) != (
        expected_catchment_id
    ):
        raise ValueError(f"terminal_support_split_catchment_id_mismatch:{path.name}")
    forward = Transformer.from_crs("EPSG:4326", RASTER_CRS, always_xy=True).transform
    catchment = transform_geometry(forward, shape(by_id["catchment"]["geometry"]))
    split = transform_geometry(forward, shape(by_id["splitCatchment"]["geometry"]))
    split_valid = bool(split.is_valid)
    if not catchment.is_valid or catchment.area <= 0.0:
        raise ValueError(f"terminal_support_split_geometry_invalid:{path.name}")
    if not split_valid and not allow_invalid_split:
        raise ValueError(f"terminal_support_split_geometry_invalid:{path.name}")
    split_for_area = make_valid(split) if not split_valid else split
    if split_for_area.is_empty or split_for_area.area <= 0.0:
        raise ValueError(f"terminal_support_split_geometry_empty:{path.name}")
    intersection = catchment.intersection(split_for_area)
    coverage = intersection.area / catchment.area
    return {
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "response_size_bytes": len(body),
        "catchment_geometry_sha256": _json_sha256(by_id["catchment"]["geometry"]),
        "split_geometry_sha256": _json_sha256(by_id["splitCatchment"]["geometry"]),
        "catchment_area_km2": float(catchment.area / 1_000_000.0),
        "split_geometry_valid": split_valid,
        "invalid_geometry_area_policy": (
            "make_valid_for_unsnapped_negative_control_only"
            if not split_valid
            else "not_required"
        ),
        "split_area_km2": float(split_for_area.area / 1_000_000.0),
        "intersection_area_km2": float(intersection.area / 1_000_000.0),
        "split_outside_catchment_area_km2": float(
            split_for_area.difference(catchment).area / 1_000_000.0
        ),
        "coverage_fraction": float(coverage),
    }


def _chain_role(index: int) -> str:
    if index < SELECTED_CHAIN_INDEX:
        return "upstream_bracket"
    if index == SELECTED_CHAIN_INDEX:
        return "selected_nearest_main_channel_cell"
    return "downstream_bracket"


def _cell_value(dataset: rasterio.io.DatasetReader, row: int, col: int) -> int:
    return int(dataset.read(1, window=Window(col, row, 1, 1))[0, 0])


def _persist_raw_snapshots(staging_root: Path, output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for source in sorted(staging_root.glob("*.json")):
        target = output_root / source.name
        shutil.copyfile(source, target)
        artifacts[source.stem.replace("-", "_")] = {
            **_artifact(target),
            "source_url": _source_url(source.name),
        }
    return artifacts


def _source_url(name: str) -> str:
    if name == "arcgis-item.json":
        return ARCGIS_ITEM_URL
    if name == "arcgis-flowline.json":
        return ARCGIS_FLOWLINE_URL
    if name == "nldi-flowline.json":
        return NLDI_FLOWLINE_URL
    if name == "process-description.json":
        return NLDI_PROCESS_URL
    return NLDI_EXECUTION_URL


def _write_window_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _single_feature(payload: Mapping[str, Any], label: str) -> dict[str, Any]:
    features = payload.get("features") or []
    if len(features) != 1:
        raise ValueError(f"terminal_support_{label}_single_feature_required")
    return features[0]


def _artifact(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "path": _display(path),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"terminal_support_json_object_required:{path.name}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    body = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return hashlib.sha256(body).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
