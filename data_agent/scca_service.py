"""Service layer for SCCA demo workflows used by the causal reasoning tab."""

from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / ".tmp" / "scca_runs"
UPLOADS_ROOT = PACKAGE_ROOT / "uploads"
SAMPLE_DATA_ROOT = PACKAGE_ROOT / "scca_samples" / "data"
SAMPLE_SPATIAL_ROOT = PACKAGE_ROOT / "scca_samples" / "spatial"
COUNTY_BOUNDARY_PATH = SAMPLE_SPATIAL_ROOT / "county_data" / "CountyData.shp"
CHONGQING_POINTS_PATH = SAMPLE_SPATIAL_ROOT / "chongqing_uhi_points" / "chongqing_uhi_points.geojson"
CHONGQING_BUILDINGS_PATH = SAMPLE_SPATIAL_ROOT / "chongqing_buildings" / "中心城区建筑数据带层高.shp"


@dataclass(frozen=True)
class SCCACaseDefinition:
    case_id: str
    label: str
    description: str
    input_path: Path
    variables: dict[str, Any]
    context_columns: tuple[str, ...]
    preprocessing: dict[str, Any]
    robustness: dict[str, Any]
    targets: tuple[dict[str, Any], ...]
    coordinates: dict[str, str] | None = None
    default_row_limit: int | None = None
    map_kind: str | None = None
    spatial_source_path: Path | None = None


SCCA_CASES: dict[str, SCCACaseDefinition] = {
    "chongqing_uhi": SCCACaseDefinition(
        case_id="chongqing_uhi",
        label="重庆 UHI 建筑高度热环境",
        description="以重庆建筑样点为输入，评估高层建筑暴露对地表温度的空间上下文校准效应。",
        input_path=SAMPLE_DATA_ROOT / "chongqing_uhi_points.csv",
        variables={
            "unit_id": "_gc_unit_id",
            "exposure": "floor",
            "outcome": "LST",
            "confounders": [
                "area_m2",
                "rs_NDVI",
                "rs_NDBI",
                "rs_MNDWI",
                "rs_BSI",
                "rs_elevation",
                "rs_slope",
            ],
        },
        context_columns=("centroid_x", "centroid_y"),
        coordinates={"lon": "centroid_x", "lat": "centroid_y"},
        preprocessing={
            "exposure_trim": {
                "lower_quantile": 0.01,
                "upper_quantile": 0.99,
            }
        },
        robustness={
            "bootstrap": {"n_replicates": 12},
            "placebo_exposures": [
                {
                    "name": "rs_NDVI",
                    "column": "rs_NDVI",
                    "role": "placebo_context",
                    "expected_relation": "weaker_than_main",
                },
                {
                    "name": "rs_MNDWI",
                    "column": "rs_MNDWI",
                    "role": "placebo_context",
                    "expected_relation": "weaker_than_main",
                },
            ],
        },
        targets=({"name": "cooler_35C", "value": 35.0},),
        default_row_limit=None,
        map_kind="building",
        spatial_source_path=CHONGQING_BUILDINGS_PATH,
    ),
    "county_social_capital": SCCACaseDefinition(
        case_id="county_social_capital",
        label="美国 CountyData 社会资本长寿",
        description="以 CountyData 派生表为输入，评估社会资本与平均死亡年龄的空间上下文校准关系。",
        input_path=SAMPLE_DATA_ROOT / "county_social_capital.csv",
        variables={
            "unit_id": "FIPS",
            "exposure": "SocialAssoc",
            "outcome": "AveAgeDeath",
            "confounders": [
                "UnemployRate",
                "pHHinPoverty",
                "pNoHealthInsur",
                "MentalHealth",
                "pAdultSmoking",
                "pAdultObesity",
                "FastFood",
                "pInsufficientSleep",
                "pAlcohol",
                "pSuicideDeaths",
                "AirPollution",
            ],
        },
        context_columns=("Shape_Length", "Shape_Area"),
        preprocessing={
            "exposure_trim": {
                "lower_quantile": 0.01,
                "upper_quantile": 0.99,
            }
        },
        robustness={
            "bootstrap": {"group_column": "STATE_NAME", "n_replicates": 12},
            "placebo_exposures": [
                {
                    "name": "Shape_Length",
                    "column": "Shape_Length",
                    "role": "placebo",
                    "expected_relation": "weaker_than_main",
                },
                {
                    "name": "Shape_Area",
                    "column": "Shape_Area",
                    "role": "placebo",
                    "expected_relation": "weaker_than_main",
                },
            ],
        },
        targets=({"name": "target_70", "value": 70.0},),
        default_row_limit=None,
        map_kind="county",
        spatial_source_path=COUNTY_BOUNDARY_PATH,
    ),
}


def list_scca_cases() -> dict[str, Any]:
    """Return the built-in SCCA workflows exposed to the UI."""

    cases = []
    for case in SCCA_CASES.values():
        cases.append(
            {
                "case_id": case.case_id,
                "label": case.label,
                "description": case.description,
                "default_row_limit": case.default_row_limit,
                "input_path": str(case.input_path),
                "exposure": case.variables["exposure"],
                "outcome": case.variables["outcome"],
                "confounder_count": len(case.variables.get("confounders", [])),
                "context_columns": list(case.context_columns),
                "map_kind": case.map_kind,
                "spatial_source_path": str(case.spatial_source_path) if case.spatial_source_path else None,
            }
        )
    return {
        "algorithm": "SCCA",
        "algorithm_label": "Spatial Contextual Causal Adjustment",
        "cases": cases,
    }


def run_scca_case(
    case_id: str,
    *,
    row_limit: int | None = None,
    output_root: str | Path | None = None,
    user_id: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Run one built-in SCCA workflow and return a UI-friendly summary."""

    try:
        case = SCCA_CASES[case_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported SCCA case: {case_id}") from exc
    if not case.input_path.exists():
        raise FileNotFoundError(f"SCCA sample data is missing: {case.input_path}")

    limit = row_limit
    if limit is not None and limit <= 0:
        limit = None

    output_base = Path(output_root).resolve() if output_root is not None else DEFAULT_OUTPUT_ROOT
    output_dir = output_base / case.case_id
    if overwrite and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    analysis_input = _prepare_case_input(case, output_dir, limit)
    config_path = _write_case_config(case, analysis_input, output_dir)

    from geocausal.config import load_config
    from geocausal.pipeline import run_analysis

    manifest = run_analysis(load_config(config_path))
    spatial_output = _build_spatial_map_output(
        case=case,
        analysis_input=analysis_input,
        output_dir=output_dir,
        manifest=manifest,
        user_id=user_id,
    )
    return _summarize_run(case, config_path, analysis_input, output_dir, manifest, limit, spatial_output)


def _prepare_case_input(case: SCCACaseDefinition, output_dir: Path, row_limit: int | None) -> Path:
    if row_limit is None:
        return case.input_path
    frame = pd.read_csv(case.input_path, encoding="utf-8-sig")
    sampled = frame.head(int(row_limit)).copy()
    target = output_dir / f"{case.case_id}_input.csv"
    sampled.to_csv(target, index=False)
    return target


def _write_case_config(case: SCCACaseDefinition, analysis_input: Path, output_dir: Path) -> Path:
    input_block: dict[str, Any] = {
        "path": str(analysis_input.resolve()),
        "format": "csv",
    }
    if case.coordinates:
        input_block.update(case.coordinates)

    config = {
        "case_name": f"gisdataagent_{case.case_id}",
        "input": input_block,
        "variables": case.variables,
        "context": {"columns": list(case.context_columns)},
        "preprocessing": case.preprocessing,
        "robustness": case.robustness,
        "targets": {"outcome_values": list(case.targets)},
        "output": {"directory": str(output_dir.resolve())},
    }
    config_path = output_dir / "analysis.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return config_path


def _summarize_run(
    case: SCCACaseDefinition,
    config_path: Path,
    analysis_input: Path,
    output_dir: Path,
    manifest: dict[str, Any],
    row_limit: int | None,
    spatial_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    effect_estimates = _read_csv_records(output_dir / "effect_estimates.csv", limit=12)
    balance_rows = _read_csv_records(output_dir / "balance_summary.csv", limit=12)
    robustness = _read_json(output_dir / "robustness_manifest.json")
    spatial_diagnostics = _read_json(output_dir / "spatial_diagnostics.json")
    data_profile = _read_json(output_dir / "data_profile.json")

    result = {
        "algorithm": "SCCA",
        "case_id": case.case_id,
        "case_label": case.label,
        "description": case.description,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "row_limit": row_limit,
        "raw_input_count": _count_csv_rows(analysis_input),
        "row_count": manifest.get("row_count"),
        "column_count": manifest.get("column_count"),
        "input_path": manifest.get("input_path"),
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "exposure": manifest.get("exposure"),
        "outcome": manifest.get("outcome"),
        "confounders": manifest.get("confounders", []),
        "context_columns": manifest.get("context_columns", []),
        "credibility_decision": manifest.get("credibility_decision"),
        "robustness_interpretation": manifest.get("robustness_interpretation"),
        "evidence_grade": manifest.get("evidence_grade"),
        "evidence_grade_reasons": manifest.get("evidence_grade_reasons", []),
        "result_summary": manifest.get("result_summary", {}),
        "effect_estimates": effect_estimates,
        "balance_summary": balance_rows,
        "robustness": robustness,
        "spatial_diagnostics": spatial_diagnostics,
        "data_profile": data_profile,
        "files": {
            name: str(output_dir / rel_path)
            for name, rel_path in files.items()
            if isinstance(rel_path, str)
        },
    }
    if spatial_output:
        result["spatial_outputs"] = spatial_output.get("spatial_outputs", {})
        result["map_update"] = spatial_output.get("map_update")
        if spatial_output.get("error"):
            result["spatial_map_error"] = spatial_output["error"]
    result["user_summary"] = _build_user_summary(case, result, output_dir)
    return result


def _build_spatial_map_output(
    *,
    case: SCCACaseDefinition,
    analysis_input: Path,
    output_dir: Path,
    manifest: dict[str, Any],
    user_id: str | None,
) -> dict[str, Any]:
    if not case.map_kind:
        return {}
    try:
        if case.map_kind == "point":
            return _build_point_map_output(
                case=case,
                analysis_input=analysis_input,
                output_dir=output_dir,
                manifest=manifest,
                user_id=user_id,
            )
        if case.map_kind == "building":
            return _build_chongqing_building_map_output(
                case=case,
                analysis_input=analysis_input,
                output_dir=output_dir,
                manifest=manifest,
                user_id=user_id,
            )
        if case.map_kind == "county":
            return _build_county_map_output(
                case=case,
                output_dir=output_dir,
                manifest=manifest,
                user_id=user_id,
            )
        return {}
    except Exception as exc:
        return {"error": str(exc)}


def _build_chongqing_building_map_output(
    *,
    case: SCCACaseDefinition,
    analysis_input: Path,
    output_dir: Path,
    manifest: dict[str, Any],
    user_id: str | None,
) -> dict[str, Any]:
    """Join SCCA results back to the original Chongqing building polygons."""

    if not case.coordinates:
        return {}
    if not case.spatial_source_path or not case.spatial_source_path.exists():
        fallback = _build_point_map_output(
            case=case,
            analysis_input=analysis_input,
            output_dir=output_dir,
            manifest=manifest,
            user_id=user_id,
        )
        if fallback:
            fallback["error"] = f"SCCA Chongqing building boundary data is missing: {case.spatial_source_path}"
        return fallback

    gpd = _require_geopandas()
    lon_col = case.coordinates["lon"]
    lat_col = case.coordinates["lat"]
    unit_id = str(case.variables["unit_id"])
    source = pd.read_csv(analysis_input, encoding="utf-8-sig")
    source = _ensure_unit_id(source, unit_id)
    enriched = _merge_analysis_metrics(source, output_dir, unit_id=unit_id)
    enriched = enriched.dropna(subset=[lon_col, lat_col]).copy()
    if enriched.empty:
        return {}

    enriched["_scca_sample_key"] = _normalize_join_key(enriched[unit_id])
    points = gpd.GeoDataFrame(
        enriched,
        geometry=gpd.points_from_xy(
            pd.to_numeric(enriched[lon_col], errors="coerce"),
            pd.to_numeric(enriched[lat_col], errors="coerce"),
        ),
        crs="EPSG:4326",
    )
    points = points.loc[points.geometry.notna() & ~points.geometry.is_empty].copy()
    if points.empty:
        return {}

    buildings = gpd.read_file(case.spatial_source_path)
    buildings = buildings.loc[buildings.geometry.notna() & ~buildings.geometry.is_empty].copy()
    if buildings.empty:
        return {"error": f"SCCA Chongqing building boundary data is empty: {case.spatial_source_path}"}

    buildings = buildings.reset_index(drop=False).rename(columns={"index": "_scca_building_idx"})
    matched = _match_points_to_buildings(points, buildings)
    if matched.empty:
        fallback = _build_point_map_output(
            case=case,
            analysis_input=analysis_input,
            output_dir=output_dir,
            manifest=manifest,
            user_id=user_id,
        )
        if fallback:
            fallback["error"] = "SCCA Chongqing building join produced no polygon matches; fell back to point output."
        return fallback

    keep_cols = [column for column in matched.columns if column != "geometry"]
    building_cols = [
        column
        for column in ["_scca_building_idx", "Id", "Floor", "geometry"]
        if column in buildings.columns
    ]
    frame = buildings[building_cols].merge(
        matched[keep_cols],
        on="_scca_building_idx",
        how="inner",
        suffixes=("_building", ""),
    )
    frame = _prepare_geojson_properties(frame)
    map_field = _preferred_map_field(frame, preferred=("gc_cooler_35c_exposure_change", "LST"))
    spatial_output = _write_frontend_map(
        case=case,
        frame=frame,
        map_field=map_field,
        output_dir=output_dir,
        user_id=user_id,
        layer_type="choropleth",
        layer_name=f"SCCA 重庆建筑面: {map_field}",
        zoom=11,
        manifest=manifest,
    )
    if spatial_output:
        spatial_output["spatial_outputs"]["source_geometry"] = "chongqing_buildings_shp"
        spatial_output["spatial_outputs"]["match_summary"] = _building_match_summary(matched, len(points))
        if spatial_output.get("map_update"):
            spatial_output["map_update"]["summary"]["source_geometry"] = "chongqing_buildings_shp"
            spatial_output["map_update"]["summary"]["match_summary"] = spatial_output["spatial_outputs"]["match_summary"]
    return spatial_output


def _build_point_map_output(
    *,
    case: SCCACaseDefinition,
    analysis_input: Path,
    output_dir: Path,
    manifest: dict[str, Any],
    user_id: str | None,
) -> dict[str, Any]:
    if not case.coordinates:
        return {}
    lon_col = case.coordinates["lon"]
    lat_col = case.coordinates["lat"]
    source = pd.read_csv(analysis_input, encoding="utf-8-sig")
    unit_id = str(case.variables["unit_id"])
    source = _ensure_unit_id(source, unit_id)
    enriched = _merge_analysis_metrics(source, output_dir, unit_id=unit_id)
    enriched = enriched.dropna(subset=[lon_col, lat_col]).copy()
    if enriched.empty:
        return {}

    gpd = _require_geopandas()
    geometry = gpd.points_from_xy(
        pd.to_numeric(enriched[lon_col], errors="coerce"),
        pd.to_numeric(enriched[lat_col], errors="coerce"),
    )
    frame = gpd.GeoDataFrame(_prepare_geojson_properties(enriched), geometry=geometry, crs="EPSG:4326")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()

    map_field = _preferred_map_field(frame, preferred=("gc_cooler_35c_exposure_change", "LST"))
    return _write_frontend_map(
        case=case,
        frame=frame,
        map_field=map_field,
        output_dir=output_dir,
        user_id=user_id,
        layer_type="point",
        layer_name=f"SCCA 重庆样点: {map_field}",
        zoom=11,
        manifest=manifest,
    )


def _build_county_map_output(
    *,
    case: SCCACaseDefinition,
    output_dir: Path,
    manifest: dict[str, Any],
    user_id: str | None,
) -> dict[str, Any]:
    if not case.spatial_source_path or not case.spatial_source_path.exists():
        return {"error": f"SCCA county boundary data is missing: {case.spatial_source_path}"}

    gpd = _require_geopandas()
    from geocausal.spatial_outputs import COUNTY_SHAPEFILE_FIELD_MAP

    counties = gpd.read_file(case.spatial_source_path)
    counties = counties.rename(
        columns={key: value for key, value in COUNTY_SHAPEFILE_FIELD_MAP.items() if key in counties.columns}
    )
    unit_id = str(case.variables["unit_id"])
    if unit_id not in counties.columns:
        return {"error": f"SCCA county boundary key is missing: {unit_id}"}

    context = _read_csv_frame(output_dir / "context_features.csv", dtype={unit_id: "string"})
    if context.empty or unit_id not in context.columns:
        return {}
    enriched = _merge_analysis_metrics(context, output_dir, unit_id=unit_id)

    counties = counties.copy()
    counties["_scca_join_key"] = _normalize_join_key(counties[unit_id], width=5)
    enriched["_scca_join_key"] = _normalize_join_key(enriched[unit_id], width=5)
    enriched = enriched.drop_duplicates(subset=["_scca_join_key"], keep="first")
    keep_cols = [column for column in enriched.columns if column != "geometry"]
    frame = counties.merge(enriched[keep_cols], on="_scca_join_key", how="inner", suffixes=("", "_scca"))
    frame = frame.drop(columns=["_scca_join_key"], errors="ignore")
    if frame.empty:
        return {}

    map_field = _preferred_map_field(frame, preferred=("gc_target_70_exposure_change", "SocialAssoc"))
    frame = _prepare_geojson_properties(frame)
    return _write_frontend_map(
        case=case,
        frame=frame,
        map_field=map_field,
        output_dir=output_dir,
        user_id=user_id,
        layer_type="choropleth",
        layer_name=f"SCCA CountyData: {map_field}",
        zoom=4,
        manifest=manifest,
    )


def _match_points_to_buildings(points: Any, buildings: Any, *, max_nearest_distance_m: float = 20.0) -> pd.DataFrame:
    building_attrs = [
        column
        for column in ["_scca_building_idx", "Id", "Floor", "geometry"]
        if column in buildings.columns
    ]
    within = points.sjoin(buildings[building_attrs], predicate="within", how="left")
    within["_scca_match_method"] = "within"
    within["_scca_match_distance_m"] = 0.0
    within = _rank_building_matches(within)

    matched_keys = set(within.loc[within["_scca_building_idx"].notna(), "_scca_sample_key"].astype(str))
    unmatched = points.loc[~points["_scca_sample_key"].astype(str).isin(matched_keys)].copy()
    if unmatched.empty:
        return within.loc[within["_scca_building_idx"].notna()].copy()

    nearest = unmatched.to_crs(epsg=3857).sjoin_nearest(
        buildings[building_attrs].to_crs(epsg=3857),
        how="left",
        max_distance=max_nearest_distance_m,
        distance_col="_scca_match_distance_m",
    )
    nearest = nearest.to_crs(points.crs)
    nearest["_scca_match_method"] = "nearest"
    nearest = _rank_building_matches(nearest)

    matched = pd.concat(
        [
            within.loc[within["_scca_building_idx"].notna()],
            nearest.loc[nearest["_scca_building_idx"].notna()],
        ],
        ignore_index=True,
    )
    matched = _rank_building_matches(matched)
    return matched


def _rank_building_matches(matches: pd.DataFrame) -> pd.DataFrame:
    if matches.empty or "_scca_sample_key" not in matches.columns:
        return matches
    ranked = matches.copy()
    ranked["_scca_floor_match"] = False
    if "floor" in ranked.columns and "Floor" in ranked.columns:
        left_floor = pd.to_numeric(ranked["floor"], errors="coerce").round()
        right_floor = pd.to_numeric(ranked["Floor"], errors="coerce").round()
        ranked["_scca_floor_match"] = left_floor.eq(right_floor).fillna(False)
    if "_scca_match_distance_m" not in ranked.columns:
        ranked["_scca_match_distance_m"] = 0.0
    ranked["_scca_match_distance_m"] = pd.to_numeric(
        ranked["_scca_match_distance_m"],
        errors="coerce",
    ).fillna(float("inf"))
    ranked = ranked.sort_values(
        by=["_scca_sample_key", "_scca_floor_match", "_scca_match_distance_m"],
        ascending=[True, False, True],
    )
    ranked = ranked.drop_duplicates(subset=["_scca_sample_key"], keep="first")
    ranked["_scca_match_distance_m"] = ranked["_scca_match_distance_m"].replace([np.inf, -np.inf], np.nan)
    return ranked


def _building_match_summary(matched: pd.DataFrame, source_count: int) -> dict[str, Any]:
    distances = pd.to_numeric(matched.get("_scca_match_distance_m", pd.Series(dtype=float)), errors="coerce")
    floor_matches = matched.get("_scca_floor_match", pd.Series(dtype=bool)).fillna(False)
    methods = matched.get("_scca_match_method", pd.Series(dtype=str)).fillna("unknown").astype(str)
    return {
        "source_count": int(source_count),
        "matched_count": int(len(matched)),
        "matched_ratio": float(len(matched) / source_count) if source_count else None,
        "floor_match_count": int(floor_matches.sum()),
        "within_count": int((methods == "within").sum()),
        "nearest_count": int((methods == "nearest").sum()),
        "max_distance_m": _finite_or_none(distances.max()) if not distances.empty else None,
        "mean_distance_m": _finite_or_none(distances.mean()) if not distances.empty else None,
    }


def _build_user_summary(case: SCCACaseDefinition, result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    effect = _main_effect_summary(output_dir / "effect_estimates.csv")
    map_update = result.get("map_update") if isinstance(result.get("map_update"), dict) else {}
    map_summary = map_update.get("summary") if isinstance(map_update.get("summary"), dict) else {}
    spatial = result.get("spatial_outputs") if isinstance(result.get("spatial_outputs"), dict) else {}
    map_field = str(map_summary.get("map_field") or spatial.get("map_field") or "")
    row_count = int(result.get("row_count") or 0)
    raw_input_count = int(result.get("raw_input_count") or row_count)
    feature_count = int(map_summary.get("feature_count") or spatial.get("feature_count") or 0)
    coverage = float(feature_count / row_count) if row_count else None
    field_label = _map_field_label(case, map_field)
    coef = effect.get("gc_effect_coef")
    p_value = effect.get("gc_effect_p_value")

    if case.case_id == "chongqing_uhi":
        direction = _effect_direction(coef, positive="楼层越高，模型估计 LST 越高", negative="楼层越高，模型估计 LST 越低")
        headline = "建筑高度与地表温度的关系未达到强因果证据" if (p_value is None or p_value >= 0.05) else direction
        plain_effect = (
            f"在控制建筑面积、植被/建设指数、水体指数、裸地指数、海拔和坡度后，"
            f"楼层每增加 1 层，LST 的估计变化约为 {_signed_number(coef, '°C')}。"
        )
        map_plain = (
            f"地图按“{field_label}”给建筑面着色：正值表示模型认为要达到 35°C 目标需要提高楼层暴露，"
            "负值表示需要降低楼层暴露；数值绝对值越大，代表该建筑离目标情景越远。"
        )
        unit_label = "建筑"
    elif case.case_id == "county_social_capital":
        direction = _effect_direction(coef, positive="社会资本越高，模型估计平均死亡年龄越高", negative="社会资本越高，模型估计平均死亡年龄越低")
        headline = "社会资本与平均死亡年龄的关系未达到强因果证据" if (p_value is None or p_value >= 0.05) else direction
        plain_effect = (
            f"在控制失业、贫困、健康保险、心理健康、吸烟、肥胖、快餐、睡眠、饮酒、自杀死亡和空气污染后，"
            f"社会资本每增加 1 个单位，平均死亡年龄的估计变化约为 {_signed_number(coef, '岁')}。"
        )
        map_plain = (
            f"地图按“{field_label}”给县域着色：正值表示要达到 70 岁目标需要提高社会资本，"
            "负值表示当前社会资本相对目标情景偏高或模型建议降低；颜色越深，调整幅度越大。"
        )
        unit_label = "县域"
    else:
        headline = "SCCA 分析完成"
        plain_effect = f"主效应估计值为 {_signed_number(coef, '')}。"
        map_plain = f"地图按“{field_label}”显示分析结果。"
        unit_label = "空间单元"

    caveats = []
    if p_value is None:
        caveats.append("主效应显著性未能计算，结论应按探索性结果理解。")
    elif p_value >= 0.05:
        caveats.append(f"P 值为 {_format_number(p_value, 3)}，未达到 0.05 显著性阈值，不应解读为已经证明的强因果关系。")
    else:
        caveats.append(f"P 值为 {_format_number(p_value, 3)}，通过常用 0.05 显著性阈值。")
    if coverage is not None and coverage < 0.995:
        caveats.append(f"地图展示 {feature_count}/{row_count} 个{unit_label}，其余记录未成功匹配到空间几何。")
    else:
        caveats.append(f"地图展示 {feature_count} 个{unit_label}，覆盖本次分析输入。")
    if raw_input_count > row_count:
        caveats.append(f"原始输入 {raw_input_count} 条记录，SCCA 预处理后有效分析样本为 {row_count} 条；地图只显示有有效 SCCA 指标的空间单元。")

    match_summary = map_summary.get("match_summary") if isinstance(map_summary.get("match_summary"), dict) else spatial.get("match_summary")
    if isinstance(match_summary, dict) and match_summary:
        matched = match_summary.get("matched_count")
        source = match_summary.get("source_count")
        floor_match = match_summary.get("floor_match_count")
        caveats.append(f"重庆建筑面回连: {matched}/{source} 个样本匹配到原始建筑面，其中 {floor_match} 个楼层一致。")

    return {
        "headline": headline,
        "plain_effect": plain_effect,
        "map_plain": map_plain,
        "map_field": map_field,
        "map_field_label": field_label,
        "coverage": {
            "raw_input_units": raw_input_count,
            "analysis_units": row_count,
            "mapped_features": feature_count,
            "ratio": coverage,
            "unit_label": unit_label,
            "is_full": bool(coverage is None or coverage >= 0.995),
        },
        "effect": {
            "coef": coef,
            "p_value": p_value,
            "estimator": effect.get("gc_effect_estimator"),
            "direction": direction,
        },
        "credibility": {
            "grade": result.get("evidence_grade"),
            "decision": result.get("credibility_decision"),
            "robustness": result.get("robustness_interpretation"),
            "reasons": result.get("evidence_grade_reasons", []),
        },
        "caveats": caveats,
        "next_action": "先看地图中颜色最深的空间单元，再结合弹窗字段判断哪些区域对目标情景最敏感。",
    }


def _map_field_label(case: SCCACaseDefinition, field: str) -> str:
    labels = {
        "chongqing_uhi": {
            "gc_cooler_35c_exposure_change": "达到 35°C 目标所需楼层调整量",
            "LST": "地表温度",
            "floor": "楼层",
            "gc_spatial_total_effect": "空间总效应",
        },
        "county_social_capital": {
            "gc_target_70_exposure_change": "达到 70 岁目标所需社会资本变化量",
            "SocialAssoc": "社会资本",
            "AveAgeDeath": "平均死亡年龄",
            "gc_spatial_total_effect": "空间总效应",
        },
    }
    return labels.get(case.case_id, {}).get(field, field or "地图指标")


def _effect_direction(value: Any, *, positive: str, negative: str) -> str:
    numeric = _finite_or_none(value)
    if numeric is None:
        return "方向不明确"
    if numeric > 0:
        return positive
    if numeric < 0:
        return negative
    return "模型估计接近 0"


def _signed_number(value: Any, unit: str) -> str:
    numeric = _finite_or_none(value)
    if numeric is None:
        return "无法计算"
    sign = "+" if numeric > 0 else ""
    return f"{sign}{_format_number(numeric, 3)}{unit}"


def _format_number(value: Any, digits: int = 3) -> str:
    numeric = _finite_or_none(value)
    if numeric is None:
        return "—"
    if numeric != 0 and abs(numeric) < 0.001:
        return f"{numeric:.2e}"
    return f"{numeric:.{digits}f}"


def _require_geopandas() -> Any:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise RuntimeError("GeoPandas is required to generate SCCA map outputs.") from exc
    return gpd


def _ensure_unit_id(frame: pd.DataFrame, unit_id: str) -> pd.DataFrame:
    prepared = frame.copy()
    if unit_id in prepared.columns:
        prepared[unit_id] = prepared[unit_id].astype("string").fillna("").str.strip()
        return prepared
    if unit_id == "_gc_unit_id":
        prepared.insert(0, unit_id, [str(index) for index in range(1, len(prepared) + 1)])
        return prepared
    raise ValueError(f"SCCA input is missing configured unit ID column: {unit_id}")


def _merge_analysis_metrics(frame: pd.DataFrame, output_dir: Path, *, unit_id: str) -> pd.DataFrame:
    result = _ensure_unit_id(frame, unit_id)
    result["_scca_unit_key"] = _normalize_join_key(result[unit_id])

    target_metrics = _target_exposure_wide(output_dir / "target_exposures.csv")
    result = _left_join_metrics(result, target_metrics, left_key="_scca_unit_key", right_key="unit_id")

    spatial_metrics = _read_csv_frame(output_dir / "spatial_exposure_mapping.csv", dtype={"unit_id": "string"})
    spatial_rename = {
        "direct_effect": "gc_spatial_direct_effect",
        "indirect_effect": "gc_spatial_indirect_effect",
        "total_effect": "gc_spatial_total_effect",
        "out_neighbor_count": "gc_spatial_out_neighbor_count",
        "incoming_weight_sum": "gc_spatial_incoming_weight_sum",
    }
    if not spatial_metrics.empty:
        spatial_metrics = spatial_metrics.rename(columns=spatial_rename)
        result = _left_join_metrics(result, spatial_metrics, left_key="_scca_unit_key", right_key="unit_id")

    effect = _main_effect_summary(output_dir / "effect_estimates.csv")
    for key, value in effect.items():
        result[key] = value
    result["scca_included"] = True
    return result.drop(columns=["_scca_unit_key"], errors="ignore")


def _target_exposure_wide(path: Path, *, method: str = "erf_delta_anchor") -> pd.DataFrame:
    targets = _read_csv_frame(path, dtype={"unit_id": "string"})
    if targets.empty or not {"unit_id", "method", "target_name"}.issubset(targets.columns):
        return pd.DataFrame()
    selected = targets.loc[targets["method"].astype(str) == method].copy()
    if selected.empty:
        selected = targets.copy()
    selected["unit_id"] = _normalize_join_key(selected["unit_id"])
    metric_columns = [
        column
        for column in selected.columns
        if column not in {"unit_id", "method", "target_name", "warning"}
    ]
    wide: pd.DataFrame | None = None
    for target_name in selected["target_name"].dropna().astype(str).drop_duplicates():
        token = _safe_field_token(target_name)
        block = selected.loc[selected["target_name"].astype(str) == target_name, ["unit_id", *metric_columns]]
        block = block.drop_duplicates(subset=["unit_id"], keep="first")
        block = block.rename(columns={column: f"gc_{token}_{_safe_field_token(column)}" for column in metric_columns})
        wide = block if wide is None else wide.merge(block, on="unit_id", how="outer")
    return wide if wide is not None else pd.DataFrame()


def _left_join_metrics(
    result: pd.DataFrame,
    metrics: pd.DataFrame,
    *,
    left_key: str,
    right_key: str,
) -> pd.DataFrame:
    if metrics.empty or right_key not in metrics.columns:
        return result
    prepared = metrics.copy()
    prepared["_scca_metric_key"] = _normalize_join_key(prepared[right_key])
    prepared = prepared.drop_duplicates(subset=["_scca_metric_key"], keep="first")
    prepared = prepared.drop(columns=[right_key], errors="ignore")
    joined = result.merge(
        prepared,
        left_on=left_key,
        right_on="_scca_metric_key",
        how="left",
    )
    return joined.drop(columns=["_scca_metric_key"], errors="ignore")


def _main_effect_summary(path: Path) -> dict[str, Any]:
    estimates = _read_csv_frame(path)
    if estimates.empty or "coef" not in estimates.columns:
        return {}
    baseline = estimates.loc[estimates.get("estimator", "").astype(str) == "baseline_adjusted_ols"]
    row = baseline.iloc[0] if not baseline.empty else estimates.iloc[0]
    return {
        "gc_effect_estimator": row.get("estimator"),
        "gc_effect_coef": _finite_or_none(row.get("coef")),
        "gc_effect_p_value": _finite_or_none(row.get("p_value")),
    }


def _write_frontend_map(
    *,
    case: SCCACaseDefinition,
    frame: Any,
    map_field: str,
    output_dir: Path,
    user_id: str | None,
    layer_type: str,
    layer_name: str,
    zoom: int,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if frame.empty:
        return {}
    if map_field in frame.columns:
        frame = frame.loc[pd.to_numeric(frame[map_field], errors="coerce").notna()].copy()
        if frame.empty:
            return {}
    map_dir, relative_dir = _map_output_dir(case.case_id, user_id=user_id, output_dir=output_dir)
    map_path = map_dir / f"{case.case_id}_scca_map.geojson"
    map_frame = frame.to_crs(epsg=4326) if getattr(frame, "crs", None) else frame
    map_frame.to_file(map_path, driver="GeoJSON")

    center = _frame_center(map_frame)
    layer: dict[str, Any] = {
        "name": layer_name,
        "type": layer_type,
        "geojson": f"{relative_dir}/{map_path.name}" if relative_dir else map_path.name,
        "value_column": map_field,
        "style": _layer_style(layer_type),
        "visible": True,
        "legend_title": _map_field_label(case, map_field),
        "tooltip_fields": _tooltip_fields(case, map_field),
        "tooltip_labels": _tooltip_labels(case, map_field),
    }
    if layer_type == "choropleth":
        layer.update(
            {
                "breaks": _numeric_breaks(map_frame[map_field]) if map_field in map_frame.columns else [],
                "color_scheme": "RdYlGn",
            }
        )
    if layer_type == "bubble":
        layer["style"].update({"min_radius": 4, "max_radius": 24})

    map_update = {
        "layers": [layer],
        "center": center,
        "zoom": zoom,
        "summary": {
            "case_id": case.case_id,
            "case_label": case.label,
            "feature_count": int(len(map_frame)),
            "map_field": map_field,
            "map_field_label": _map_field_label(case, map_field),
            "effect": _main_effect_summary(output_dir / "effect_estimates.csv"),
            "evidence_grade": manifest.get("evidence_grade"),
        },
    }
    spatial_manifest = {
        "geojson": str(map_path),
        "geojson_relative": layer["geojson"],
        "feature_count": int(len(map_frame)),
        "map_field": map_field,
        "map_field_label": _map_field_label(case, map_field),
        "map_kind": case.map_kind,
    }
    (output_dir / "frontend_map_manifest.json").write_text(
        json.dumps(spatial_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"spatial_outputs": spatial_manifest, "map_update": map_update}


def _map_output_dir(case_id: str, *, user_id: str | None, output_dir: Path) -> tuple[Path, str]:
    if user_id:
        relative_dir = f"scca/{case_id}"
        target = UPLOADS_ROOT / user_id / relative_dir
        target.mkdir(parents=True, exist_ok=True)
        return target, relative_dir
    target = output_dir / "frontend_map"
    target.mkdir(parents=True, exist_ok=True)
    return target, ""


def _count_csv_rows(path: Path) -> int | None:
    try:
        return int(sum(1 for _ in path.open("r", encoding="utf-8-sig")) - 1)
    except Exception:
        return None


def _prepare_geojson_properties(frame: Any) -> Any:
    prepared = frame.copy()
    geometry_name = getattr(prepared, "geometry", None).name if hasattr(prepared, "geometry") else "geometry"
    for column in list(prepared.columns):
        if column == geometry_name:
            continue
        if pd.api.types.is_object_dtype(prepared[column]):
            prepared[column] = prepared[column].map(_json_property_value)
    return prepared


def _json_property_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _normalize_join_key(series: pd.Series, *, width: int | None = None) -> pd.Series:
    values = series.astype("string").fillna("").str.strip()
    values = values.str.replace(r"\.0$", "", regex=True)
    if width:
        values = values.str.zfill(width)
    return values


def _safe_field_token(value: object) -> str:
    import re

    token = re.sub(r"[^0-9A-Za-z_]+", "_", str(value).strip()).strip("_").lower()
    if not token:
        token = "field"
    if token[0].isdigit():
        token = f"f_{token}"
    return token


def _preferred_map_field(frame: Any, *, preferred: tuple[str, ...]) -> str:
    for column in preferred:
        if column in frame.columns and pd.to_numeric(frame[column], errors="coerce").notna().any():
            return column
    for column in frame.columns:
        if column == getattr(frame, "geometry", None).name:
            continue
        if pd.to_numeric(frame[column], errors="coerce").notna().any():
            return column
    return preferred[-1]


def _numeric_breaks(series: pd.Series, *, bins: int = 5) -> list[float]:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return []
    quantiles = np.quantile(numeric.to_numpy(dtype=float), np.linspace(0.2, 1.0, bins))
    breaks = [float(value) for value in quantiles if math.isfinite(float(value))]
    unique: list[float] = []
    for value in breaks:
        if not unique or abs(value - unique[-1]) > 1e-12:
            unique.append(value)
    return unique


def _frame_center(frame: Any) -> list[float]:
    try:
        bounds = frame.total_bounds
        if len(bounds) == 4 and all(math.isfinite(float(value)) for value in bounds):
            minx, miny, maxx, maxy = (float(value) for value in bounds)
            return [(miny + maxy) / 2.0, (minx + maxx) / 2.0]
    except Exception:
        pass
    return [30.5, 114.3]


def _layer_style(layer_type: str) -> dict[str, Any]:
    if layer_type == "bubble":
        return {
            "fillColor": "#e11d48",
            "color": "#ffffff",
            "weight": 1,
            "fillOpacity": 0.68,
            "opacity": 0.9,
        }
    return {
        "fillColor": "#2f80ed",
        "color": "#f8fafc",
        "weight": 0.8,
        "fillOpacity": 0.74,
        "opacity": 0.9,
    }


def _tooltip_fields(case: SCCACaseDefinition, map_field: str) -> list[str]:
    if case.case_id == "chongqing_uhi":
        return [
            map_field,
            "LST",
            "floor",
            "area_m2",
            "_scca_match_method",
            "_scca_floor_match",
        ]
    if case.case_id == "county_social_capital":
        return [
            "County",
            map_field,
            "SocialAssoc",
            "AveAgeDeath",
            "STATE_NAME",
        ]
    return [map_field]


def _tooltip_labels(case: SCCACaseDefinition, map_field: str) -> dict[str, str]:
    common = {
        map_field: _map_field_label(case, map_field),
        "gc_spatial_total_effect": "空间总效应",
    }
    if case.case_id == "chongqing_uhi":
        common.update(
            {
                "LST": "地表温度",
                "floor": "楼层",
                "area_m2": "建筑面积",
                "_scca_match_method": "建筑匹配方式",
                "_scca_floor_match": "楼层是否一致",
            }
        )
    elif case.case_id == "county_social_capital":
        common.update(
            {
                "County": "县",
                "STATE_NAME": "州",
                "SocialAssoc": "社会资本",
                "AveAgeDeath": "平均死亡年龄",
            }
        )
    return common


def _finite_or_none(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    try:
        return float(numeric) if math.isfinite(float(numeric)) else None
    except (TypeError, ValueError):
        return None


def _read_csv_frame(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig", **kwargs)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _read_csv_records(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return []
    return json.loads(frame.head(limit).to_json(orient="records"))
