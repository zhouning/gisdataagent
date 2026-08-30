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
ABU_DHABI_FLOOD_FIXTURE_PATH = SAMPLE_DATA_ROOT / "abu_dhabi_flood_public_proxy_fixture.csv"
ABU_DHABI_LIVABILITY_FIXTURE_PATH = SAMPLE_DATA_ROOT / "abu_dhabi_livability_causal_readiness_fixture.csv"
# This file is generated locally by the Abu Dhabi SWMM prototype and is
# intentionally ignored by git.  It is preferred when available so the demo
# can show the real public-proxy node results without placing customer-derived
# geometry in the repository.
ABU_DHABI_FLOOD_PUBLIC_PROXY_PATH = PACKAGE_ROOT / "uploads" / "admin" / "abu_dhabi_swmm_public_proxy_pilot_nodes.geojson"


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
    workflow_kind: str = "scca"
    evidence_mode: str = "observational"


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
    "abu_dhabi_flood": SCCACaseDefinition(
        case_id="abu_dhabi_flood",
        label="阿布扎比城市内涝（物理反事实）",
        description=(
            "以 SWMM 节点级结果展示排水治理问题：当前可运行公共代理诊断和因果问题模板，"
            "尚未对真实治理措施估计统计因果效应。"
        ),
        input_path=ABU_DHABI_FLOOD_FIXTURE_PATH,
        variables={
            "unit_id": "node_id",
            "exposure": "排水设施治理（能力/堵塞/泵站动作）",
            "outcome": "max_water_depth_m",
            "confounders": [
                "rainfall_depth_mm",
                "max_total_inflow_m3s",
                "degree",
                "component_node_count",
            ],
        },
        context_columns=("longitude", "latitude", "partition_id"),
        coordinates={"lon": "longitude", "lat": "latitude"},
        preprocessing={},
        robustness={},
        targets=(),
        default_row_limit=None,
        map_kind="abu_dhabi_flood",
        spatial_source_path=ABU_DHABI_FLOOD_PUBLIC_PROXY_PATH,
        workflow_kind="physical_counterfactual",
        evidence_mode="diagnostic_only",
    ),
    "abu_dhabi_livability": SCCACaseDefinition(
        case_id="abu_dhabi_livability",
        label="阿布扎比宜居设施改造（因果设计预检）",
        description=(
            "以地区 QoL 和设施改造候选字段设计“设施改造是否改善宜居性”的因果问题；"
            "当前为脱敏聚合示例，未估计真实 ATT/ATE/DiD。"
        ),
        input_path=ABU_DHABI_LIVABILITY_FIXTURE_PATH,
        variables={
            "unit_id": "district_id",
            "exposure": "refurbishment_completed",
            "outcome": "qol_2025_score",
            "confounders": [
                "qol_2023_score",
                "facility_count_before",
                "population_proxy",
                "qol_change_2023_2025",
            ],
        },
        context_columns=("longitude", "latitude", "district_id"),
        coordinates={"lon": "longitude", "lat": "latitude"},
        preprocessing={},
        robustness={},
        targets=(),
        default_row_limit=None,
        map_kind="abu_dhabi_livability",
        spatial_source_path=None,
        workflow_kind="causal_readiness",
        evidence_mode="design_only",
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
                "workflow_kind": case.workflow_kind,
                "evidence_mode": case.evidence_mode,
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
    if case.workflow_kind == "physical_counterfactual":
        return _run_abu_dhabi_flood_case(case, output_root=output_root, user_id=user_id)
    if case.workflow_kind == "causal_readiness":
        return _run_abu_dhabi_livability_case(case, output_root=output_root, user_id=user_id)
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


def _run_abu_dhabi_flood_case(
    case: SCCACaseDefinition,
    *,
    output_root: str | Path | None,
    user_id: str | None,
) -> dict[str, Any]:
    """Build the Abu Dhabi flood case without pretending proxy output is causal.

    The causal tab is also a workflow catalogue.  Abu Dhabi currently has
    hydraulic diagnostic results, but not the intervention/event panel needed
    for an observational SCCA estimate.  We therefore expose the real public
    proxy SWMM node layer (or a tiny public fixture) and return an explicit
    evidence boundary instead of fabricating coefficients or p-values.
    """
    output_base = Path(output_root).resolve() if output_root is not None else DEFAULT_OUTPUT_ROOT
    output_dir = output_base / case.case_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, _source_meta = _load_abu_dhabi_flood_rows(case)
    if rows.empty:
        raise FileNotFoundError("阿布扎比内涝公共代理节点结果不可用")

    # Keep the analysis input auditable while retaining only public proxy
    # fields.  Customer GDB and private SWMM runs are never copied here.
    input_path = output_dir / "abu_dhabi_flood_public_proxy_nodes.csv"
    rows.to_csv(input_path, index=False, encoding="utf-8-sig")
    map_update: dict[str, Any] = {}
    spatial_manifest: dict[str, Any] = {}
    try:
        gpd = _require_geopandas()
        frame = gpd.GeoDataFrame(
            rows.copy(),
            geometry=gpd.points_from_xy(rows["longitude"], rows["latitude"]),
            crs="EPSG:4326",
        )
        spatial = _write_frontend_map(
            case=case,
            frame=_prepare_geojson_properties(frame),
            map_field="max_water_depth_m",
            output_dir=output_dir,
            user_id=user_id,
            layer_type="bubble",
            layer_name="阿布扎比内涝 · SWMM 节点最大水深（公共代理诊断）",
            zoom=11,
            manifest={"evidence_grade": "D（物理模型诊断）"},
        )
        map_update = spatial.get("map_update") or {}
        spatial_manifest = spatial.get("spatial_outputs") or {}
    except Exception as exc:
        spatial_manifest = {"error": str(exc)}

    feature_count = int(len(rows))
    max_depth = _finite_or_none(pd.to_numeric(rows["max_water_depth_m"], errors="coerce").max())
    max_overflow = _finite_or_none(pd.to_numeric(rows["max_overflow_or_flooding_m3s"], errors="coerce").max())
    return {
        "algorithm": "SWMM physical counterfactual case",
        "case_id": case.case_id,
        "case_label": case.label,
        "description": case.description,
        "workflow_kind": case.workflow_kind,
        "evidence_mode": case.evidence_mode,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "row_limit": None,
        "raw_input_count": feature_count,
        "row_count": feature_count,
        "column_count": int(len(rows.columns)),
        "input_path": str(input_path),
        "config_path": None,
        "output_dir": str(output_dir),
        "exposure": case.variables["exposure"],
        "outcome": case.variables["outcome"],
        "confounders": case.variables["confounders"],
        "context_columns": list(case.context_columns),
        "credibility_decision": "仅用于物理模型反事实设计；未估计真实治理因果效应",
        "robustness_interpretation": "等待客户权威事件、措施和观测面板",
        "evidence_grade": "D（物理模型诊断）",
        "evidence_grade_reasons": [
            "节点结果来自 EPA SWMM 公共代理降雨诊断，不是客户实测事件观测。",
            "当前没有治理措施时间、治理前后事件和对照区，不能运行 DiD/SCCA 真实效应估计。",
            "地图显示的是节点最大水深，不是工程治理的统计因果效应。",
        ],
        "result_summary": {
            "source": "Open-Meteo public proxy SWMM diagnostic",
            "node_count": feature_count,
            "max_water_depth_m": max_depth,
            "max_overflow_or_flooding_m3s": max_overflow,
        },
        "effect_estimates": [],
        "balance_summary": [],
        "robustness": {"status": "not_applicable_until_observed_panel_arrives"},
        "spatial_diagnostics": {"status": "public_proxy_node_layer_only"},
        "data_profile": {"source_authority": "public_proxy", "customer_data_included": False},
        "files": {"public_proxy_nodes_csv": str(input_path)},
        "spatial_outputs": spatial_manifest,
        "map_update": map_update,
        "user_summary": {
            "headline": "阿布扎比城市内涝因果案例已加载（物理反事实准备态）",
            "plain_effect": "当前可用 SWMM 节点结果定义治理问题和反事实比较，尚未给出真实工程治理的因果效应估计。",
            "map_plain": "地图按节点最大水深着色；它用于定位内涝响应和设计干预，不表示某项工程已经产生了多少实际改善。",
            "map_field": "max_water_depth_m",
            "map_field_label": "节点最大水深（m）· 公共代理诊断",
            "coverage": {
                "raw_input_units": feature_count,
                "analysis_units": feature_count,
                "mapped_features": int(map_update.get("summary", {}).get("feature_count", feature_count)),
                "ratio": 1.0,
                "unit_label": "SWMM 节点",
                "is_full": True,
            },
            "effect": {"coef": None, "p_value": None, "estimator": "physical_counterfactual_design", "direction": "尚未估计"},
            "credibility": {
                "grade": "D（物理模型诊断）",
                "decision": "不支持真实治理因果声明",
                "robustness": "等待客户观测面板",
                "reasons": ["当前结果是公共代理降雨下的 SWMM 诊断节点层。"],
            },
            "caveats": [
                "降雨为 Open-Meteo 公共代理，未替代客户权威历史时序。",
                "当前没有治理措施、前后事件和对照组，因此没有统计因果系数或 P 值。",
                "下一步可将本案例与基准/干预 SWMM 成对运行，输出节点水深和溢流差值。",
            ],
            "next_action": "客户提供治理时间、历史暴雨和积水观测后，再启用 DiD/空间 SCCA 的真实效应估计。",
        },
    }


def _load_abu_dhabi_flood_rows(case: SCCACaseDefinition) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load public proxy nodes, with a small deterministic fallback fixture."""
    source = case.spatial_source_path
    features: list[dict[str, Any]] = []
    if source and source.is_file():
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            features = payload.get("features", []) if isinstance(payload, dict) else []
        except (OSError, json.JSONDecodeError):
            features = []
    if not features:
        if case.input_path.is_file() and case.input_path.suffix.lower() == ".csv":
            try:
                fixture_frame = pd.read_csv(case.input_path, encoding="utf-8-sig")
                return fixture_frame, {"source": str(case.input_path)}
            except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
                pass
    if not features:
        # Abu Dhabi public-proxy fixture: representative public diagnostic
        # values only, not customer geometry or customer observations.
        fixture = [
            (54.3773, 24.4539, 0.048, 0.0000, 0.0060, 1, 67),
            (54.3921, 24.4612, 0.081, 0.0012, 0.0095, 2, 84),
            (54.4070, 24.4724, 0.116, 0.0040, 0.0130, 3, 112),
            (54.4236, 24.4455, 0.064, 0.0000, 0.0072, 2, 73),
            (54.3444, 24.4338, 0.097, 0.0021, 0.0106, 1, 51),
            (54.3298, 24.4692, 0.137, 0.0074, 0.0152, 3, 96),
            (54.3650, 24.4925, 0.073, 0.0000, 0.0084, 2, 62),
            (54.4512, 24.4810, 0.154, 0.0101, 0.0187, 4, 141),
        ]
        features = [
            {
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "node_id": f"public_fixture_{idx:02d}",
                    "partition_id": idx % 4,
                    "max_water_depth_m": depth,
                    "max_overflow_or_flooding_m3s": overflow,
                    "max_total_inflow_m3s": inflow,
                    "degree": degree,
                    "component_node_count": component_count,
                    "forcing_source": "Open-Meteo public proxy rainfall fixture",
                    "calibration_status": "not_calibrated",
                },
            }
            for idx, (lon, lat, depth, overflow, inflow, degree, component_count) in enumerate(fixture, start=1)
        ]
    rows: list[dict[str, Any]] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2 or not props.get("node_id"):
            continue
        props["longitude"] = float(coords[0])
        props["latitude"] = float(coords[1])
        props.setdefault("rainfall_depth_mm", 120.0)
        props.setdefault("degree", 0)
        props.setdefault("component_node_count", 0)
        props.setdefault("max_water_depth_m", 0.0)
        props.setdefault("max_overflow_or_flooding_m3s", 0.0)
        props.setdefault("max_total_inflow_m3s", 0.0)
        rows.append(props)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {}
    numeric = ["longitude", "latitude", "rainfall_depth_mm", "max_water_depth_m", "max_overflow_or_flooding_m3s", "max_total_inflow_m3s", "degree", "component_node_count"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    return frame.dropna(subset=["longitude", "latitude", "node_id"]), {"source": str(source) if source else "fixture"}


def _run_abu_dhabi_livability_case(
    case: SCCACaseDefinition,
    *,
    output_root: str | Path | None,
    user_id: str | None,
) -> dict[str, Any]:
    """Expose the liveability causal design without fabricating an effect.

    The live PostgreSQL audit proved that the action and QoL tables exist, but
    did not prove completed/commissioned dates, comparable score versions or
    an entity-level action-to-outcome join.  This case therefore reports the
    design gates and maps a clearly labelled de-identified aggregate fixture.
    """
    output_base = Path(output_root).resolve() if output_root is not None else DEFAULT_OUTPUT_ROOT
    output_dir = output_base / case.case_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.read_csv(case.input_path, encoding="utf-8-sig")
    if rows.empty:
        raise FileNotFoundError("阿布扎比宜居因果设计示例数据不可用")
    input_path = output_dir / "abu_dhabi_livability_causal_readiness_fixture.csv"
    rows.to_csv(input_path, index=False, encoding="utf-8-sig")

    map_update: dict[str, Any] = {}
    spatial_manifest: dict[str, Any] = {}
    try:
        gpd = _require_geopandas()
        frame = gpd.GeoDataFrame(
            rows.copy(),
            geometry=gpd.points_from_xy(rows["longitude"], rows["latitude"]),
            crs="EPSG:4326",
        )
        spatial = _write_frontend_map(
            case=case,
            frame=_prepare_geojson_properties(frame),
            map_field="qol_change_2023_2025",
            output_dir=output_dir,
            user_id=user_id,
            layer_type="bubble",
            layer_name="阿布扎比宜居 · QoL 变化示例（因果设计预检）",
            zoom=11,
            manifest={"evidence_grade": "设计预检（未估计）"},
        )
        map_update = spatial.get("map_update") or {}
        spatial_manifest = spatial.get("spatial_outputs") or {}
    except Exception as exc:
        spatial_manifest = {"error": str(exc)}

    treatment_count = int(pd.to_numeric(rows["refurbishment_completed"], errors="coerce").fillna(0).sum())
    candidate_count = int(pd.to_numeric(rows["refurbishment_candidate"], errors="coerce").fillna(0).sum())
    return {
        "algorithm": "Liveability causal design preflight",
        "case_id": case.case_id,
        "case_label": case.label,
        "description": case.description,
        "workflow_kind": case.workflow_kind,
        "evidence_mode": case.evidence_mode,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "row_limit": None,
        "raw_input_count": int(len(rows)),
        "row_count": int(len(rows)),
        "column_count": int(len(rows.columns)),
        "input_path": str(input_path),
        "config_path": None,
        "output_dir": str(output_dir),
        "exposure": "设施改造完成（当前示例字段）",
        "outcome": "QoL 2025 总分",
        "confounders": ["QoL 2023 总分", "改造前设施数量", "人口代理", "2023→2025 QoL 变化"],
        "context_columns": list(case.context_columns),
        "credibility_decision": "仅完成因果设计预检；未估计真实治理因果效应",
        "robustness_interpretation": "等待真实投运日期、可比版本和多期 QoL 面板",
        "evidence_grade": "设计预检（未估计）",
        "evidence_grade_reasons": [
            "示例数据是脱敏聚合结构，用于演示页面闭环，不是客户设施明细。",
            "整治审批/候选记录尚未证明实际完成或投入运营。",
            "当前只有 2023 与 2025 结果轴，无法检验平行趋势。",
            "同一年存在多个 calc_version_id，跨年可比版本仍需锁定。",
        ],
        "result_summary": {
            "source": "liveability_data_20260730 schema audit + de-identified aggregate fixture",
            "candidate_district_count": candidate_count,
            "completed_treatment_count_in_fixture": treatment_count,
            "qol_years": [2023, 2025],
            "observational_effect_estimated": False,
        },
        "effect_estimates": [],
        "balance_summary": [],
        "robustness": {"status": "blocked_missing_pre_periods_and_commissioning_dates"},
        "spatial_diagnostics": {"status": "aggregate_design_preview_only"},
        "data_profile": {
            "source_authority": "deidentified_aggregate_fixture",
            "customer_data_included": False,
            "audit_reference": "abu-dhabi-liveability-research/causal_readiness/pg_live_schema_audit_20260820",
        },
        "files": {"causal_readiness_fixture_csv": str(input_path)},
        "spatial_outputs": spatial_manifest,
        "map_update": map_update,
        "readiness_gates": [
            {"name": "设施实际完成/投运日期", "status": "blocked", "detail": "当前审计未确认可用的 completion/commissioning date。"},
            {"name": "QoL 前后结果周期", "status": "partial", "detail": "已发现 2023、2025 结果轴，但前期周期不足以检验平行趋势。"},
            {"name": "评分版本一致性", "status": "blocked", "detail": "同一年存在多个 calc_version_id，需要客户锁定可比版本。"},
            {"name": "动作—设施—地区—结果关联", "status": "blocked", "detail": "候选表、设施历史和评分表的实体链尚未完成业务确认。"},
            {"name": "真实因果估计", "status": "waiting", "detail": "完成上述数据闸门后运行 DiD / 事件研究 / 空间 SCCA。"},
        ],
        "user_summary": {
            "headline": "阿布扎比宜居设施改造因果案例已加载（设计预检）",
            "plain_effect": "当前定义的是“设施改造完成是否改善 QoL”的因果问题；页面暂不输出真实 ATT、ATE 或 DiD 系数。",
            "map_plain": "地图显示脱敏聚合示例中的 2023→2025 QoL 变化，用于查看空间设计和候选处理组，不表示改造已经造成该变化。",
            "map_field": "qol_change_2023_2025",
            "map_field_label": "QoL 2023→2025 变化（脱敏示例）",
            "coverage": {
                "raw_input_units": int(len(rows)),
                "analysis_units": int(len(rows)),
                "mapped_features": int(map_update.get("summary", {}).get("feature_count", len(rows))),
                "ratio": 1.0,
                "unit_label": "地区示例",
                "is_full": True,
            },
            "effect": {"coef": None, "p_value": None, "estimator": "causal_design_preflight", "direction": "尚未估计"},
            "credibility": {
                "grade": "设计预检（未估计）",
                "decision": "不支持真实宜居治理因果声明",
                "robustness": "等待客户数据闸门",
                "reasons": ["当前案例只完成动作—结果设计和数据就绪度展示。"],
            },
            "caveats": [
                "地图使用仓库内脱敏聚合示例，不是客户设施或居民明细。",
                "审批/候选不等于设施实际完成或投入运营。",
                "2023 与 2025 两个结果年份不足以检验平行趋势。",
                "下一步需锁定 calc_version_id，并补齐投运日期、多个前期周期和对照区。",
            ],
            "next_action": "客户确认设施投运事件和版本后，运行地区级 DiD/事件研究，并进一步估计设施类型异质性。",
        },
    }


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
        "abu_dhabi_flood": {
            "max_water_depth_m": "节点最大水深（m）· 公共代理诊断",
            "max_overflow_or_flooding_m3s": "节点最大溢流/积水（m³/s）· 公共代理诊断",
            "physical_counterfactual_depth_delta_m": "物理反事实水深差值（m）",
        },
        "abu_dhabi_livability": {
            "qol_change_2023_2025": "QoL 2023→2025 变化（脱敏示例）",
            "qol_2023_score": "QoL 2023 总分（示例）",
            "qol_2025_score": "QoL 2025 总分（示例）",
            "refurbishment_candidate": "整治候选（示例）",
            "refurbishment_completed": "改造完成（待客户确认）",
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
    if case.case_id == "abu_dhabi_flood":
        return [
            "node_id",
            map_field,
            "max_overflow_or_flooding_m3s",
            "max_total_inflow_m3s",
            "partition_id",
            "forcing_source",
            "calibration_status",
        ]
    if case.case_id == "abu_dhabi_livability":
        return [
            "district_id",
            map_field,
            "qol_2023_score",
            "qol_2025_score",
            "refurbishment_candidate",
            "refurbishment_completed",
            "calc_version_2023",
            "calc_version_2025",
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
    elif case.case_id == "abu_dhabi_flood":
        common.update(
            {
                "node_id": "节点 ID",
                "max_water_depth_m": "节点最大水深（m）",
                "max_overflow_or_flooding_m3s": "节点最大溢流/积水（m³/s）",
                "max_total_inflow_m3s": "最大总入流（m³/s）",
                "partition_id": "SWMM 分区",
                "forcing_source": "降雨来源",
                "calibration_status": "校准状态",
            }
        )
    elif case.case_id == "abu_dhabi_livability":
        common.update(
            {
                "district_id": "地区 ID（示例）",
                "qol_change_2023_2025": "QoL 2023→2025 变化（脱敏示例）",
                "qol_2023_score": "QoL 2023 总分（示例）",
                "qol_2025_score": "QoL 2025 总分（示例）",
                "refurbishment_candidate": "整治候选（示例）",
                "refurbishment_completed": "改造完成（待客户确认）",
                "calc_version_2023": "2023 评分版本（示例）",
                "calc_version_2025": "2025 评分版本（示例）",
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
