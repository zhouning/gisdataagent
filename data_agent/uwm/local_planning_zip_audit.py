"""Audit and normalize UWM-relevant assets in the local planning-institute zip."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import pyogrio
import rasterio


LOCAL_PLANNING_ZIP_AUDIT_SCHEMA = "uwm.local_planning_zip_audit.v1"
UNICOM_COMMUTING_DATASET_ID = "chongqing_unicom_commuting_2023_local"
BAIDU_SEARCH_INDEX_DATASET_ID = "baidu_search_index_2023_local"


KNOWN_VECTOR_ASSETS = [
    {
        "asset_id": "chongqing_osm_roads_2021",
        "relative_path": "02重庆市OSM道路数据2021年/OSM_roads.shp",
        "status": "already_manifested_now_profiled",
        "roles": "mobility_graph;mobility_activity;renderer;baseline",
    },
    {
        "asset_id": "chongqing_central_buildings_2021",
        "relative_path": "04重庆市中心城区建筑物轮廓数据2021年/中心城区建筑数据带层高.shp",
        "status": "already_manifested_now_profiled",
        "roles": "urban_form;renderer;baseline",
    },
    {
        "asset_id": "chongqing_historic_districts_local",
        "relative_path": "05重庆市中心城区历史文化街区数据/中心城区历史文化街区数据.shp",
        "status": "newly_recognized",
        "roles": "urban_form;cultural_heritage;service_accessibility;livability_context;renderer;planner_targeting",
    },
    {
        "asset_id": "bishan_land_use_dltb_local",
        "relative_path": "07规划编制相关数据/区县/现状用地数据/GDB.gdb",
        "layer": "DLTB",
        "status": "newly_recognized",
        "roles": "land_use_context;urban_form;planning_constraints;simulator_context;baseline",
    },
    {
        "asset_id": "gaode_poi_2024",
        "relative_path": "09高德地图POI数据/高德地图POI数据2024年.gdb",
        "layer": "高德地图POI数据2024年",
        "status": "already_manifested_now_profiled",
        "roles": "service_accessibility;baseline;planner_targeting",
    },
    {
        "asset_id": "baidu_aoi_2024",
        "relative_path": "10百度地图AOI数据/百度地图AOI数据.gdb",
        "layer": "重庆市百度地图AOI数据_2024年",
        "status": "already_manifested_now_profiled",
        "roles": "service_accessibility;urban_form;baseline;planner_targeting",
    },
    {
        "asset_id": BAIDU_SEARCH_INDEX_DATASET_ID,
        "relative_path": "12成渝环渝百度搜索指数/成渝环渝百度搜索指数.gdb",
        "layer": "成渝环渝百度搜索指数_2023",
        "status": "newly_recognized",
        "roles": "mobility_activity;urban_activity_proxy;simulator_context;planner_targeting;mmfe_alignment",
    },
]


KNOWN_RASTER_ASSETS = [
    {
        "asset_id": "chongqing_dem_80m",
        "relative_path": "01重庆市DEM数据2020年/Chongqing_aster_gdem_80m.tif",
        "status": "already_manifested_now_profiled",
        "roles": "renderer;heat_exposure",
    },
    {
        "asset_id": "chongqing_clcd_2020",
        "relative_path": "03重庆市遥感影像解译数据2020年/CLCD_v01_2020_chongqing.tif",
        "status": "already_manifested_now_profiled",
        "roles": "remote_sensing_state;urban_form;baseline",
    },
]


def build_unicom_commuting_proxy(
    *,
    records: list[dict[str, Any]],
    source_ref: str,
    created_at: str,
) -> dict[str, Any]:
    """Normalize China Unicom work-home commuting rows into a UWM activity asset."""

    rows = [_normalise_unicom_row(row) for row in records]
    expanded_sum = sum(row["expanded_population"] for row in rows)
    raw_sum = sum(row["raw_population"] for row in rows)
    same_count = sum(1 for row in rows if row["home_work_same"] == 1)
    work_zero_count = sum(1 for row in rows if row["work_grid_id"] == "0")
    return {
        "schema": "uwm.unicom_commuting_proxy.v1",
        "dataset_id": UNICOM_COMMUTING_DATASET_ID,
        "source": "local planning-institute sample; China Unicom mobile signaling commuting table",
        "source_ref": source_ref,
        "created_at": created_at,
        "temporal_extent": "2023-05",
        "record_counts": {
            "rows": len(rows),
            "unique_home_grids": len({row["home_grid_id"] for row in rows}),
            "unique_work_grids": len({row["work_grid_id"] for row in rows}),
            "same_home_work_rows": same_count,
            "work_grid_zero_rows": work_zero_count,
        },
        "summary": {
            "raw_population_sum": round(raw_sum, 6),
            "expanded_population_sum": round(expanded_sum, 6),
            "same_home_work_expanded_population_sum": round(
                sum(row["expanded_population"] for row in rows if row["home_work_same"] == 1),
                6,
            ),
            "unknown_or_external_work_grid_expanded_population_sum": round(
                sum(row["expanded_population"] for row in rows if row["work_grid_id"] == "0"),
                6,
            ),
            "sex_code_counts": _count_values(row["sex_code"] for row in rows),
            "age_code_counts": _count_values(row["age_code"] for row in rows),
            "top_home_grids": _top_weighted_groups(rows, ["home_grid_id"], "expanded_population"),
            "top_work_grids": _top_weighted_groups(rows, ["work_grid_id"], "expanded_population"),
            "top_od_pairs": _top_weighted_groups(rows, ["home_grid_id", "work_grid_id"], "expanded_population"),
        },
        "od_rows": rows,
        "mmfe_target_roles": [
            "mobility_activity",
            "commuting_od",
            "population_vulnerability",
            "simulator_context",
            "planner_targeting",
            "mmfe_alignment",
        ],
        "synthetic_flags": [{"dataset_id": UNICOM_COMMUTING_DATASET_ID, "status": "real"}],
        "claim_boundary": {
            "max_claim_level": "fragile",
            "reason": "Real local commuting table is usable as activity context, but the zip does not include a grid geometry dictionary.",
        },
        "limitations": [
            "grid_geometry_dictionary_missing",
            "work_grid_zero_meaning_unverified_unknown_or_external",
            "mobile_signaling_expansion_method_not_audited",
            "not_travel_time_or_traffic_flow",
            "not_observed_policy_outcome",
            "source_license_and_redistribution_terms_pending",
        ],
        "empirical_superiority_claim": False,
    }


def build_baidu_search_index_proxy(
    *,
    records: list[dict[str, Any]],
    source_ref: str,
    created_at: str,
) -> dict[str, Any]:
    """Normalize Baidu inter-city search-index flows into a UWM activity asset."""

    rows = [_normalise_baidu_search_row(row) for row in records]
    return {
        "schema": "uwm.baidu_search_index_proxy.v1",
        "dataset_id": BAIDU_SEARCH_INDEX_DATASET_ID,
        "source": "local planning-institute sample; Baidu Chengdu-Chongqing search-index FileGDB",
        "source_ref": source_ref,
        "created_at": created_at,
        "temporal_extent": "2023",
        "record_counts": {
            "flows": len(rows),
            "origin_cities": len({row["origin"] for row in rows if row["origin"]}),
            "destination_cities": len({row["destination"] for row in rows if row["destination"]}),
        },
        "summary": {
            "total_pc_search_count": round(sum(row["pc_search_count"] for row in rows), 6),
            "total_mobile_search_count": round(sum(row["mobile_search_count"] for row in rows), 6),
            "total_search_index": round(sum(row["search_index"] for row in rows), 6),
            "top_total_flows": _top_search_flows(rows),
            "top_chongqing_inbound_flows": _top_search_flows(
                [row for row in rows if "重庆" in row["destination"]]
            ),
            "top_chongqing_outbound_flows": _top_search_flows(
                [row for row in rows if "重庆" in row["origin"]]
            ),
        },
        "flow_rows": rows,
        "mmfe_target_roles": [
            "mobility_activity",
            "urban_activity_proxy",
            "simulator_context",
            "planner_targeting",
            "mmfe_alignment",
        ],
        "synthetic_flags": [{"dataset_id": BAIDU_SEARCH_INDEX_DATASET_ID, "status": "real"}],
        "claim_boundary": {
            "max_claim_level": "fragile",
            "reason": "Search interest is a real local activity signal but not observed trips, traffic volume, or policy outcome.",
        },
        "limitations": [
            "search_interest_not_observed_trip_or_policy_outcome",
            "city_pair_activity_signal_not_intraurban_accessibility",
            "source_license_and_redistribution_terms_pending",
        ],
        "empirical_superiority_claim": False,
    }


def build_local_planning_zip_audit_report(
    *,
    created_at: str,
    source_zip: str,
    source_root: str,
    file_inventory: dict[str, int],
    vector_profiles: list[dict[str, Any]],
    tabular_profiles: list[dict[str, Any]],
    raster_profiles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a source-grounded audit report for the local planning zip."""

    profiles = vector_profiles + tabular_profiles + raster_profiles
    newly = sorted(
        {
            str(profile["asset_id"])
            for profile in profiles
            if profile.get("status") == "newly_recognized"
        }
    )
    profiled = sorted(
        {
            str(profile["asset_id"])
            for profile in profiles
            if profile.get("status") == "already_manifested_now_profiled"
        }
    )
    return {
        "schema": LOCAL_PLANNING_ZIP_AUDIT_SCHEMA,
        "created_at": created_at,
        "source_zip": source_zip,
        "source_root": source_root,
        "root_cause": {
            "missed_population_data": "coarse_directory_level_audit_without_table_or_layer_profiling",
            "corrective_action": "enumerate_and_read_tables_vectors_rasters_before_manifest_classification",
        },
        "inventory_counts": dict(sorted(file_inventory.items())),
        "vector_profiles": vector_profiles,
        "tabular_profiles": tabular_profiles,
        "raster_profiles": raster_profiles,
        "newly_recognized_asset_ids": newly,
        "already_manifested_but_now_profiled_asset_ids": profiled,
        "honesty_policy": {
            "real_local_data": "Only assets read from the supplied zip or extracted root are marked real.",
            "proxies": "Public proxies remain explicitly marked public_proxy in the main manifest.",
            "synthetic": "No synthetic replacement is introduced by this audit.",
            "claim_boundary": "Assets without geometry dictionaries, full lineage, or redistribution terms stay fragile.",
        },
        "remaining_gaps": [
            "unicom_grid_geometry_dictionary_missing",
            "tap_pm25_access_still_pending_user_account_approval",
            "observed_scene_aligned_air_pollution_policy_outcome_missing",
            "authoritative_township_or_grid_population_for_2024_scene_missing",
            "traffic_speed_or_travel_time_observations_missing",
            "source_license_and_redistribution_terms_pending_for_restricted_local_assets",
        ],
    }


def scan_local_planning_zip_assets(
    *,
    source_root: str | Path,
    source_zip: str | Path,
    created_at: str,
) -> dict[str, Any]:
    """Scan the extracted zip and return vector, tabular, and raster profiles."""

    root = Path(source_root)
    file_inventory = _file_inventory(root)
    vector_profiles = [_vector_profile(root, spec) for spec in KNOWN_VECTOR_ASSETS]
    vector_profiles.extend(_admin_boundary_profiles(root))
    vector_profiles.append(_village_planning_profile(root))
    tabular_profiles = _tabular_profiles(root)
    raster_profiles = [_raster_profile(root, spec) for spec in KNOWN_RASTER_ASSETS]
    return build_local_planning_zip_audit_report(
        created_at=created_at,
        source_zip=str(source_zip),
        source_root=str(root),
        file_inventory=file_inventory,
        vector_profiles=vector_profiles,
        tabular_profiles=tabular_profiles,
        raster_profiles=raster_profiles,
    )


def write_local_planning_zip_audit_snapshot(
    *,
    source_root: str | Path,
    source_zip: str | Path,
    output_dir: str | Path,
    created_at: str,
) -> dict[str, Any]:
    """Persist audit report, inventory CSV, and normalized small activity assets."""

    root = Path(source_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = scan_local_planning_zip_assets(source_root=root, source_zip=source_zip, created_at=created_at)

    unicom_path = root / "11中国联通手机信令数据/现状职住通勤数据_202305.csv"
    unicom_records = json.loads(pd.read_csv(unicom_path).to_json(orient="records", force_ascii=False))
    unicom_proxy = build_unicom_commuting_proxy(
        records=unicom_records,
        source_ref=str(unicom_path),
        created_at=created_at,
    )
    _write_json(out / "chongqing_unicom_commuting_proxy.json", unicom_proxy)
    _write_rows_csv(out / "chongqing_unicom_commuting_od_rows.csv", unicom_proxy["od_rows"])

    search_path = root / "12成渝环渝百度搜索指数/成渝环渝百度搜索指数.gdb"
    search_layer = "成渝环渝百度搜索指数_2023"
    search_df = pyogrio.read_dataframe(search_path, layer=search_layer)
    search_records = json.loads(
        search_df.drop(columns=search_df.geometry.name, errors="ignore").to_json(orient="records", force_ascii=False)
    )
    search_proxy = build_baidu_search_index_proxy(
        records=search_records,
        source_ref=f"{search_path}:{search_layer}",
        created_at=created_at,
    )
    _write_json(out / "baidu_search_index_proxy.json", search_proxy)
    _write_rows_csv(out / "baidu_search_index_flows.csv", search_proxy["flow_rows"])

    _write_json(out / "uwm_local_planning_zip_audit.json", report)
    _write_inventory_csv(out / "uwm_local_planning_zip_inventory.csv", report)
    manifest = {
        "schema": "uwm.local_planning_zip_audit_snapshot_manifest.v1",
        "dataset_id": "uwm_local_planning_zip_audit_2026_07_05_snapshot",
        "created_at": created_at,
        "source_zip": str(source_zip),
        "source_root": str(root),
        "files": {
            "audit_report": "uwm_local_planning_zip_audit.json",
            "inventory_csv": "uwm_local_planning_zip_inventory.csv",
            "unicom_commuting_proxy": "chongqing_unicom_commuting_proxy.json",
            "unicom_commuting_rows": "chongqing_unicom_commuting_od_rows.csv",
            "baidu_search_index_proxy": "baidu_search_index_proxy.json",
            "baidu_search_index_flows": "baidu_search_index_flows.csv",
        },
        "newly_recognized_asset_ids": report["newly_recognized_asset_ids"],
        "already_manifested_but_now_profiled_asset_ids": report[
            "already_manifested_but_now_profiled_asset_ids"
        ],
        "limitations": report["remaining_gaps"],
    }
    _write_json(out / "snapshot_manifest.json", manifest)
    return manifest


def _normalise_unicom_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "home_grid_id": _id_text(record.get("居住格网")),
        "work_grid_id": _id_text(record.get("工作格网")),
        "home_work_same": _int(record.get("职住格网是否重合")),
        "sex_code": _id_text(record.get("性别")),
        "age_code": _id_text(record.get("年龄")),
        "raw_population": _float(record.get("扩样前人口")),
        "expanded_population": _float(record.get("扩样后人口")),
    }


def _normalise_baidu_search_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "origin": str(record.get("ODJSMC") or record.get("odjsmc") or "").strip(),
        "destination": str(record.get("DDJSMC") or record.get("ddjsmc") or "").strip(),
        "pc_search_count": _float(record.get("PCSSCS") or record.get("pcsscs")),
        "mobile_search_count": _float(record.get("YDSSCS") or record.get("ydsscs")),
        "search_index": _float(record.get("SSZS") or record.get("sszs")),
    }


def _top_weighted_groups(
    rows: list[dict[str, Any]],
    keys: list[str],
    weight_key: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    totals: dict[tuple[str, ...], float] = defaultdict(float)
    for row in rows:
        key = tuple(str(row.get(name, "")) for name in keys)
        totals[key] += _float(row.get(weight_key))
    output = []
    for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]:
        if len(keys) == 1 and keys[0] in {"home_grid_id", "work_grid_id"}:
            item = {"grid_id": key[0]}
        else:
            item = {name: part for name, part in zip(keys, key)}
        item["expanded_population"] = round(value, 6)
        output.append(item)
    return output


def _top_search_flows(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    return [
        {
            "origin": row["origin"],
            "destination": row["destination"],
            "search_index": round(row["search_index"], 6),
        }
        for row in sorted(rows, key=lambda item: item["search_index"], reverse=True)[:limit]
    ]


def _count_values(values: Any) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _file_inventory(root: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower().lstrip(".") or "[no_ext]"
        counts[suffix] += 1
    return dict(counts)


def _vector_profile(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = root / spec["relative_path"]
    info = pyogrio.read_info(path, layer=spec.get("layer")) if spec.get("layer") else pyogrio.read_info(path)
    bounds = info.get("total_bounds")
    fields = info.get("fields")
    return {
        "asset_id": spec["asset_id"],
        "asset_kind": "vector",
        "status": spec["status"],
        "source_path": str(path),
        "layer": spec.get("layer", ""),
        "feature_count": int(info.get("features") or 0),
        "geometry_type": str(info.get("geometry_type") or ""),
        "crs": str(info.get("crs") or ""),
        "bounds": [float(value) for value in bounds.tolist()] if hasattr(bounds, "tolist") else list(bounds or []),
        "fields": [str(value) for value in fields.tolist()] if hasattr(fields, "tolist") else list(fields or []),
        "uwm_roles": spec.get("roles", ""),
    }


def _admin_boundary_profiles(root: Path) -> list[dict[str, Any]]:
    gdb = root / "07规划编制相关数据/区县/其他资料/境界与政区.gdb/境界与政区.gdb"
    profiles = []
    for layer in ["CJDCQ", "XZQ"]:
        profile = _vector_profile(
            root,
            {
                "asset_id": f"bishan_admin_boundary_{layer.lower()}_local",
                "relative_path": str(gdb.relative_to(root)),
                "layer": layer,
                "status": "newly_recognized",
                "roles": "administrative_units;land_use_context;planning_constraints;baseline",
            },
        )
        profile["asset_group_id"] = "bishan_admin_cadastral_boundary_local"
        profiles.append(profile)
    return profiles


def _village_planning_profile(root: Path) -> dict[str, Any]:
    village_root = root / "07规划编制相关数据/村规划"
    shapefiles = list(village_root.rglob("*.shp"))
    feature_count = 0
    nonempty_layers = 0
    for shp in shapefiles:
        info = pyogrio.read_info(shp)
        count = int(info.get("features") or 0)
        feature_count += count
        if count:
            nonempty_layers += 1
    return {
        "asset_id": "fulu_village_planning_database_local",
        "asset_kind": "vector_collection",
        "status": "newly_recognized",
        "source_path": str(village_root),
        "feature_count": feature_count,
        "layer_count": len(shapefiles),
        "nonempty_layer_count": nonempty_layers,
        "geometry_type": "mixed",
        "crs": "mixed_CGCS2000_GK_zone_35_EPSG4523",
        "fields": [],
        "uwm_roles": "planning_constraints;land_use_context;village_livability_context;simulator_context",
    }


def _tabular_profiles(root: Path) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    population = root / "08重庆市各区县人口规模表格数据/重庆市各区县人口规模数据.xlsx"
    profiles.append(_excel_profile("chongqing_district_population_stats_2021_local", population, "already_manifested_now_profiled", "population_vulnerability;equity_evaluation"))
    unicom = root / "11中国联通手机信令数据/现状职住通勤数据_202305.csv"
    df = pd.read_csv(unicom)
    profiles.append(
        {
            "asset_id": UNICOM_COMMUTING_DATASET_ID,
            "asset_kind": "table",
            "status": "newly_recognized",
            "source_path": str(unicom),
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": list(df.columns),
            "uwm_roles": "mobility_activity;commuting_od;population_vulnerability;simulator_context;planner_targeting",
            "limitations": "grid_geometry_dictionary_missing;work_grid_zero_meaning_unverified",
        }
    )
    clcd_dict = root / "03重庆市遥感影像解译数据2020年/CLCD_Classification System_学研录.xlsx"
    profiles.append(
        _excel_profile(
            "clcd_classification_dictionary_local",
            clcd_dict,
            "newly_recognized",
            "remote_sensing_state;renderer;baseline_context",
        )
    )
    profiles.append(_land_development_ledger_profile(root))
    return profiles


def _excel_profile(asset_id: str, path: Path, status: str, roles: str) -> dict[str, Any]:
    workbook = pd.ExcelFile(path)
    rows = 0
    sheets = []
    for sheet in workbook.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet, header=None)
        nonempty = frame.dropna(how="all").dropna(how="all", axis=1)
        rows += int(nonempty.shape[0])
        sheets.append({"sheet": sheet, "rows": int(nonempty.shape[0]), "columns": int(nonempty.shape[1])})
    return {
        "asset_id": asset_id,
        "asset_kind": "workbook",
        "status": status,
        "source_path": str(path),
        "row_count": rows,
        "sheet_count": len(sheets),
        "sheets": sheets,
        "uwm_roles": roles,
    }


def _land_development_ledger_profile(root: Path) -> dict[str, Any]:
    paths = [
        root / "07规划编制相关数据/区县/用地态势数据/附件/2019年璧山建设用地规划许可证台账.xls",
        root / "07规划编制相关数据/区县/用地态势数据/附件/2019年璧山征地台账.xls",
        root / "07规划编制相关数据/区县/用地态势数据/附件/2019年璧山账建设用地出让划拨台账.xls",
    ]
    row_count = 0
    sheet_count = 0
    files = []
    for path in paths:
        profile = _excel_profile("tmp", path, "tmp", "")
        row_count += int(profile["row_count"])
        sheet_count += int(profile["sheet_count"])
        files.append({"file": str(path), "row_count": profile["row_count"], "sheet_count": profile["sheet_count"]})
    return {
        "asset_id": "bishan_land_development_ledger_2019_local",
        "asset_kind": "workbook_collection",
        "status": "newly_recognized",
        "source_path": str(root / "07规划编制相关数据/区县/用地态势数据/附件"),
        "row_count": row_count,
        "sheet_count": sheet_count,
        "files": files,
        "uwm_roles": "land_development_pressure;planning_context;planner_constraints;simulator_context",
    }


def _raster_profile(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = root / spec["relative_path"]
    with rasterio.open(path) as src:
        return {
            "asset_id": spec["asset_id"],
            "asset_kind": "raster",
            "status": spec["status"],
            "source_path": str(path),
            "width": int(src.width),
            "height": int(src.height),
            "band_count": int(src.count),
            "pixel_count": int(src.width * src.height),
            "crs": str(src.crs),
            "bounds": [src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top],
            "dtype": list(src.dtypes),
            "nodata": src.nodata,
            "uwm_roles": spec.get("roles", ""),
        }


def _write_inventory_csv(path: Path, report: dict[str, Any]) -> None:
    rows = []
    for section in ["vector_profiles", "tabular_profiles", "raster_profiles"]:
        rows.extend(report.get(section) or [])
    fieldnames = [
        "asset_id",
        "asset_kind",
        "status",
        "source_path",
        "layer",
        "feature_count",
        "row_count",
        "pixel_count",
        "geometry_type",
        "crs",
        "uwm_roles",
        "limitations",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _id_text(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0
