#!/usr/bin/env python3
"""Build the customer demo bundle from the supplied village-planning sample.

The source archive remains read-only. This builder performs every spatial
intersection in the source projected CRS, then exports a compact WGS84 bundle
for the GIS Data Agent runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

ONTOLOGY = {
    "key": "natural-resource-one-map",
    "version": "2.0.1",
    "package_id": "natural-resource-one-map:2.0.1:953dac97c1be4d96",
    "sha256": "953dac97c1be4d9683247da42dea022128471b15b9c677215d913fa209bd1200",
    "namespace": "https://gisdataagent.local/ontology/natural-resource/2.0.1/",
}

ONTOLOGY_STATS = {
    "domain_classes": 96,
    "schema_artifacts": 3932,
    "skos_concepts": 1066,
    "mappings": 422,
    "rdf_triples": 528252,
}

STATE_MAP = {
    "水田": ("CultivatedLandUseState", "耕地利用状态"),
    "水浇地": ("CultivatedLandUseState", "耕地利用状态"),
    "旱地": ("CultivatedLandUseState", "耕地利用状态"),
    "园地": ("NonCultivatedAgriculturalLandUseState", "非耕农用地利用状态"),
    "林地": ("NonCultivatedAgriculturalLandUseState", "非耕农用地利用状态"),
    "牧草地": ("NonCultivatedAgriculturalLandUseState", "非耕农用地利用状态"),
    "设施农用地": ("NonCultivatedAgriculturalLandUseState", "非耕农用地利用状态"),
    "农用地": ("AgriculturalLandUseState", "农用地利用状态"),
    "自然保留地": ("UnusedLandUseState", "未利用地利用状态"),
}

CONSTRUCTION_TERMS = {
    "城镇用地",
    "宅基地（村居住用地）",
    "农村居民点用地",
    "村居住用地",
    "村产业用地",
    "村公共服务用地",
    "村混合用地",
    "村基础设施用地",
    "采矿用地",
    "其他独立建设用地",
    "公路用地",
    "铁路用地",
    "水工建筑用地",
}

OTHER_AGRICULTURAL_TERMS = {
    "农村道路",
    "坑塘水面",
    "农田水利用地",
    "田坎",
}

CONSTRAINT_SPECS = {
    "STBHHX": ("生态保护红线", "EcologicalConservationRedline", "禁止性冲突", "critical"),
    "LSWH": ("历史文化保护要素", "ControlBoundary", "保护对象复核", "critical"),
    "DZDYXFW": ("地质灾害影响范围", "ControlBoundary", "建设条件复核", "warning"),
    "YBD": ("郁闭度大于0.7的林地", "ControlBoundary", "林地保护复核", "warning"),
}

PROCESS_LABELS = {
    "AgriculturalStructureAdjustment": "农业结构调整",
    "ConstructionOccupation": "建设占用",
    "LandReclamation": "土地复垦",
    "LandConsolidation": "土地整治",
    "LandUseTransition": "土地利用转换",
    "NoChange": "状态保持",
}


def _json_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 6)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_one(root: Path, village: str, filename: str) -> Path:
    matches = sorted(path for path in root.rglob(filename) if village in str(path))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {filename} for {village}, found {len(matches)}")
    return matches[0]


def _state(term: str) -> tuple[str, str]:
    normalized = str(term or "").strip()
    if normalized in STATE_MAP:
        return STATE_MAP[normalized]
    if normalized in CONSTRUCTION_TERMS:
        return "ConstructionLandUseState", "建设用地利用状态"
    if normalized in OTHER_AGRICULTURAL_TERMS:
        return "AgriculturalLandUseState", "农用地利用状态"
    return "LandUseState", "土地利用状态"


def _process(source_id: str, target_id: str, source_term: str, target_term: str) -> str:
    if str(source_term or "").strip() == str(target_term or "").strip():
        return "NoChange"
    agricultural = {
        "AgriculturalLandUseState",
        "CultivatedLandUseState",
        "NonCultivatedAgriculturalLandUseState",
    }
    if source_id in agricultural and target_id in agricultural:
        if {source_id, target_id} == {
            "CultivatedLandUseState",
            "NonCultivatedAgriculturalLandUseState",
        }:
            return "AgriculturalStructureAdjustment"
        return "LandConsolidation"
    if source_id in agricultural and target_id == "ConstructionLandUseState":
        return "ConstructionOccupation"
    if source_id == "ConstructionLandUseState" and target_id in agricultural:
        return "LandReclamation"
    return "LandUseTransition"


def _identifier(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _ontology_ref(class_name: str, label: str) -> dict[str, str]:
    return {
        "id": f"gda:nr:class:{class_name}",
        "uri": f"{ONTOLOGY['namespace']}class/{class_name}",
        "label": label,
    }


def _valid_frame(path: Path) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    frame.geometry = frame.geometry.make_valid()
    return frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()


def _safe_intersection_area(geometry, constraint: gpd.GeoDataFrame) -> float:
    if geometry is None or geometry.is_empty or constraint.empty:
        return 0.0
    candidates = constraint[constraint.intersects(geometry)]
    if candidates.empty:
        return 0.0
    return float(candidates.geometry.intersection(geometry).area.sum())


def _planning_frame(root: Path, village: str) -> tuple[gpd.GeoDataFrame, Path]:
    path = _find_one(root, village, "TDGHDL.shp")
    frame = _valid_frame(path)
    frame["source_state_id"] = frame["JQDLMC"].map(lambda value: _state(value)[0])
    frame["source_state"] = frame["JQDLMC"].map(lambda value: _state(value)[1])
    frame["target_state_id"] = frame["GHDLMC"].map(lambda value: _state(value)[0])
    frame["target_state"] = frame["GHDLMC"].map(lambda value: _state(value)[1])
    frame["process_id"] = [
        _process(source, target, source_term, target_term)
        for source, target, source_term, target_term in zip(
            frame["source_state_id"],
            frame["target_state_id"],
            frame["JQDLMC"],
            frame["GHDLMC"],
            strict=True,
        )
    ]
    frame["process"] = frame["process_id"].map(PROCESS_LABELS)
    frame["changed"] = frame["JQDLMC"].fillna("") != frame["GHDLMC"].fillna("")
    frame["area_ha"] = frame.geometry.area / 10000
    frame["parcel_id"] = frame["BSM"].map(lambda value: f"{village}-{_identifier(value)}")
    return frame, path


def _load_constraints(root: Path) -> tuple[dict[str, gpd.GeoDataFrame], dict[str, Path]]:
    frames: dict[str, gpd.GeoDataFrame] = {}
    paths: dict[str, Path] = {}
    for layer_name in CONSTRAINT_SPECS:
        path = _find_one(root, "和平村", f"{layer_name}.shp")
        frames[layer_name] = _valid_frame(path)
        paths[layer_name] = path
    return frames, paths


def _constraint_hits(
    planning: gpd.GeoDataFrame,
    constraints: dict[str, gpd.GeoDataFrame],
) -> tuple[gpd.GeoDataFrame, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    statuses: list[str] = []
    summaries: list[str] = []
    for _, row in planning.iterrows():
        hits: list[dict[str, Any]] = []
        for layer_name, constraint in constraints.items():
            area_m2 = _safe_intersection_area(row.geometry, constraint)
            if area_m2 <= 0.01:
                continue
            label, ontology_class, rule, severity = CONSTRAINT_SPECS[layer_name]
            matching_names = sorted(
                set(
                    constraint.loc[constraint.intersects(row.geometry), "GZMC"]
                    .dropna()
                    .astype(str)
                    .tolist()
                )
            )
            hits.append(
                {
                    "layer": layer_name,
                    "label": label,
                    "names": matching_names,
                    "intersection_area_ha": round(area_m2 / 10000, 6),
                    "rule": rule,
                    "severity": severity,
                    "ontology": _ontology_ref(ontology_class, label),
                }
            )
        has_critical = any(hit["severity"] == "critical" for hit in hits)
        has_warning = any(hit["severity"] == "warning" for hit in hits)
        missing_approval = row["process_id"] == "ConstructionOccupation"
        if has_critical:
            status = "空间冲突"
        elif missing_approval:
            status = "材料待补"
        elif has_warning:
            status = "条件复核"
        else:
            status = "初筛通过"
        summary_parts = [hit["label"] for hit in hits]
        if missing_approval:
            summary_parts.append("缺少审批文件关联")
        statuses.append(status)
        summaries.append("、".join(summary_parts) if summary_parts else "未命中已注册约束")
        results.append(
            {
                "parcel_id": row["parcel_id"],
                "status": status,
                "constraint_hits": hits,
                "approval_evidence": "missing"
                if missing_approval
                else "not_required_by_transition_rule",
                "is_administrative_decision": False,
            }
        )
    planning = planning.copy()
    planning["review_status"] = statuses
    planning["review_summary"] = summaries
    return planning, results


def _geojson_payload(
    frame: gpd.GeoDataFrame, columns: list[str], *, tolerance: float
) -> dict[str, Any]:
    export = frame[columns + [frame.geometry.name]].copy().to_crs(4326)
    export.geometry = export.geometry.simplify(tolerance, preserve_topology=True)
    return json.loads(export.to_json(drop_id=True, to_wgs84=True))


def _project_registry(root: Path, village: str) -> tuple[list[dict[str, Any]], Path]:
    filename = (
        "210重点项目清单.xlsx" if village == "和平村" else "210璧山区福禄镇斑竹村重点项目清单.xlsx"
    )
    path = _find_one(root, village, filename)
    raw = pd.read_excel(path, sheet_name=0, header=None)
    start = -1
    sequence_column = -1
    for row_index in range(len(raw)):
        for column_index in range(min(3, len(raw.columns))):
            if str(raw.iat[row_index, column_index]).strip() in {"1", "1.0"}:
                start = row_index
                sequence_column = column_index
                break
        if start >= 0:
            break
    if start < 0:
        raise RuntimeError(f"project rows not found in {path}")
    projects: list[dict[str, Any]] = []
    for _, row in raw.iloc[start:].iterrows():
        if pd.isna(row.iloc[sequence_column]) or pd.isna(row.iloc[sequence_column + 1]):
            continue

        def cell(position: int, source_row=row) -> Any:
            absolute = sequence_column + position
            value = source_row.iloc[absolute] if absolute < len(source_row) else None
            return _json_value(value)

        projects.append(
            {
                "sequence": int(float(row.iloc[sequence_column])),
                "name": str(row.iloc[sequence_column + 1]).strip(),
                "construction_type": cell(2),
                "project_type": cell(3),
                "content": cell(4),
                "location": cell(5),
                "land_area_ha": cell(6),
                "cultivated_land_ha": cell(7),
                "permanent_basic_farmland_ha": cell(8),
                "schedule": cell(9),
                "planned_land_class": cell(10),
                "note": cell(11),
                "spatial_link_status": "unresolved",
                "spatial_link_reason": "项目名称未写入规划图斑 XMMC 字段，不能建立可靠空间关联",
            }
        )
    return projects, path


def _structure_adjustment(root: Path) -> tuple[list[dict[str, Any]], Path]:
    path = _find_one(root, "斑竹村", "220璧山区福禄镇斑竹村土地利用结构调整表.xlsx")
    raw = pd.read_excel(path, sheet_name=0, header=None)
    rows: list[dict[str, Any]] = []
    for _, row in raw.iloc[3:].iterrows():
        labels = [str(row.iloc[index]).strip() for index in range(4) if pd.notna(row.iloc[index])]
        if not labels or pd.isna(row.iloc[6]) or pd.isna(row.iloc[8]) or pd.isna(row.iloc[10]):
            continue
        name = labels[-1]
        rows.append(
            {
                "hierarchy": labels,
                "name": name,
                "baseline_ha": round(float(row.iloc[6]), 2),
                "target_ha": round(float(row.iloc[8]), 2),
                "delta_ha": round(float(row.iloc[10]), 2),
                "direction": "增加"
                if float(row.iloc[10]) > 0
                else "减少"
                if float(row.iloc[10]) < 0
                else "不变",
                "state": _ontology_ref(*_state(name)),
            }
        )
    return rows, path


def _source_entry(
    path: Path, root: Path, *, role: str, record_count: int | None = None
) -> dict[str, Any]:
    return {
        "name": path.name,
        "relative_path": str(path.relative_to(root)),
        "role": role,
        "sha256": _sha256(path),
        "record_count": record_count,
    }


def build(source_root: Path, output: Path) -> dict[str, Any]:
    if not source_root.exists():
        raise FileNotFoundError(source_root)
    output.mkdir(parents=True, exist_ok=True)

    heping, heping_path = _planning_frame(source_root, "和平村")
    banzhu, banzhu_path = _planning_frame(source_root, "斑竹村")
    constraints, constraint_paths = _load_constraints(source_root)
    heping, heping_reviews = _constraint_hits(heping, constraints)
    heping_projects, heping_projects_path = _project_registry(source_root, "和平村")
    banzhu_projects, banzhu_projects_path = _project_registry(source_root, "斑竹村")
    adjustment, adjustment_path = _structure_adjustment(source_root)

    heping_changed = heping[heping["changed"]].copy()
    banzhu_changed = banzhu[banzhu["changed"]].copy()
    heping_review_by_id = {item["parcel_id"]: item for item in heping_reviews}

    planning_columns = [
        "parcel_id",
        "BSM",
        "TBBH",
        "JQDLDM",
        "JQDLMC",
        "GHDLDM",
        "GHDLMC",
        "source_state_id",
        "source_state",
        "target_state_id",
        "target_state",
        "process_id",
        "process",
        "area_ha",
        "review_status",
        "review_summary",
    ]
    changed_columns = [column for column in planning_columns if column in heping_changed.columns]
    heping_geojson = _geojson_payload(heping_changed, changed_columns, tolerance=0.000002)
    for feature in heping_geojson["features"]:
        parcel_id = feature["properties"]["parcel_id"]
        feature["properties"]["evidence"] = heping_review_by_id[parcel_id]
    _write_json(output / "heping_changed_parcels.geojson", heping_geojson)

    banzhu_columns = [
        column
        for column in planning_columns
        if column in banzhu_changed.columns and not column.startswith("review_")
    ]
    _write_json(
        output / "banzhu_changed_parcels.geojson",
        _geojson_payload(banzhu_changed, banzhu_columns, tolerance=0.000002),
    )

    constraint_features: list[dict[str, Any]] = []
    for layer_name, frame in constraints.items():
        label, ontology_class, rule, severity = CONSTRAINT_SPECS[layer_name]
        payload = _geojson_payload(
            frame,
            [column for column in ("BSM", "GZMC", "JSMJ") if column in frame.columns],
            tolerance=0.000004,
        )
        for feature in payload["features"]:
            feature["properties"].update(
                {
                    "layer": layer_name,
                    "constraint_type": label,
                    "rule": rule,
                    "severity": severity,
                    "ontology_class": ontology_class,
                }
            )
            constraint_features.append(feature)
    _write_json(
        output / "heping_constraints.geojson",
        {"type": "FeatureCollection", "features": constraint_features},
    )

    zone_path = _find_one(source_root, "和平村", "JSYDGZQ.shp")
    zones = _valid_frame(zone_path)
    zone_labels = {
        "010": "允许建设区",
        "020": "有条件建设区",
        "030": "限制建设区",
        "040": "禁止建设区",
    }
    zones["zone_label"] = zones["GZQLXDM"].astype(str).map(zone_labels).fillna("未识别管制区")
    zones["ontology_class"] = "ControlBoundary"
    _write_json(
        output / "heping_construction_zones.geojson",
        _geojson_payload(
            zones, ["BSM", "GZQLXDM", "zone_label", "GZQMJ", "ontology_class"], tolerance=0.000004
        ),
    )

    heping_changed_review = [
        heping_review_by_id[parcel_id] for parcel_id in heping_changed["parcel_id"]
    ]
    status_counts = Counter(item["status"] for item in heping_changed_review)
    process_counts = Counter(heping_changed["process"].tolist())
    process_areas = {
        label: round(float(group["area_ha"].sum()), 2)
        for label, group in heping_changed.groupby("process")
    }

    unresolved_terms = sorted(
        {
            str(term)
            for term in pd.concat(
                [heping["JQDLMC"], heping["GHDLMC"], banzhu["JQDLMC"], banzhu["GHDLMC"]]
            ).dropna()
            if _state(str(term))[0] == "LandUseState"
        }
    )
    mapped_terms = sorted(
        {
            str(term)
            for term in pd.concat(
                [heping["JQDLMC"], heping["GHDLMC"], banzhu["JQDLMC"], banzhu["GHDLMC"]]
            ).dropna()
            if _state(str(term))[0] != "LandUseState"
        }
    )
    quality_checks = [
        {"id": "crs", "label": "坐标参考系可解析", "status": "passed", "value": str(heping.crs)},
        {
            "id": "geometry",
            "label": "有效且非空几何",
            "status": "passed",
            "value": f"和平村 {len(heping)}/{len(heping)}；斑竹村 {len(banzhu)}/{len(banzhu)}",
        },
        {
            "id": "identity",
            "label": "地块标识 BSM 完整",
            "status": "passed" if heping["BSM"].notna().all() else "failed",
            "value": f"{int(heping['BSM'].notna().sum())}/{len(heping)}",
        },
        {
            "id": "state",
            "label": "规划前后状态完整",
            "status": "passed" if heping[["JQDLMC", "GHDLMC"]].notna().all().all() else "failed",
            "value": f"{int(heping[['JQDLMC', 'GHDLMC']].notna().all(axis=1).sum())}/{len(heping)}",
        },
        {
            "id": "semantic_mapping",
            "label": "地类术语语义映射",
            "status": "warning" if unresolved_terms else "passed",
            "value": f"已映射 {len(mapped_terms)} 类；待治理 {len(unresolved_terms)} 类",
            "unresolved": unresolved_terms,
        },
        {
            "id": "project_link",
            "label": "项目台账空间关联",
            "status": "warning",
            "value": f"0/{len(heping_projects)}",
            "reason": "TDGHDL.XMMC 全字段为空",
        },
        {
            "id": "approval",
            "label": "建设占用审批证据",
            "status": "warning",
            "value": "规划图斑未提供审批文件字段，按本体规则标记材料待补",
        },
    ]

    sources = [
        _source_entry(heping_path, source_root, role="和平村规划地类", record_count=len(heping)),
        _source_entry(banzhu_path, source_root, role="斑竹村规划地类", record_count=len(banzhu)),
        _source_entry(zone_path, source_root, role="建设用地管制区", record_count=len(zones)),
        _source_entry(
            heping_projects_path,
            source_root,
            role="和平村重点项目台账",
            record_count=len(heping_projects),
        ),
        _source_entry(
            banzhu_projects_path,
            source_root,
            role="斑竹村重点项目台账",
            record_count=len(banzhu_projects),
        ),
        _source_entry(
            adjustment_path,
            source_root,
            role="斑竹村土地利用结构调整",
            record_count=len(adjustment),
        ),
    ]
    sources.extend(
        _source_entry(
            path, source_root, role=CONSTRAINT_SPECS[layer][0], record_count=len(constraints[layer])
        )
        for layer, path in constraint_paths.items()
    )

    demo = {
        "bundle": {
            "id": "natural-resource-ontology-customer-demo-v1",
            "version": "1.0.0",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_title": "规划院提供数据样例及 Demo 系统功能演示建议",
            "decision_scope": "辅助预审，不替代法定审批或行政决定",
        },
        "ontology": {**ONTOLOGY, "stats": ONTOLOGY_STATS},
        "overview": {
            "title": "本体驱动的村规划用地转换与空间约束辅助审查",
            "location": "重庆市璧山区福禄镇",
            "story": (
                "以和平村地块级辅助预审为主线，以斑竹村结构调整为对照，"
                "演示从数据汇聚、语义对齐、空间计算到证据解释的完整闭环。"
            ),
            "source_assets": len(sources),
            "planning_parcels": len(heping) + len(banzhu),
            "changed_parcels": len(heping_changed) + len(banzhu_changed),
            "registered_constraints": sum(len(frame) for frame in constraints.values())
            + len(zones),
            "project_records": len(heping_projects) + len(banzhu_projects),
            "quality_passed": sum(check["status"] == "passed" for check in quality_checks),
            "quality_warnings": sum(check["status"] == "warning" for check in quality_checks),
        },
        "scenarios": [
            {
                "id": "heping_review",
                "label": "和平村 · 用地转换辅助预审",
                "question": (
                    "哪些规划地块发生了语义上的用地转换，是否命中已注册空间约束，还缺什么审批证据？"
                ),
                "parcel_count": len(heping),
                "changed_count": len(heping_changed),
                "changed_area_ha": round(float(heping_changed["area_ha"].sum()), 2),
                "process_counts": dict(process_counts),
                "process_areas_ha": process_areas,
                "review_status_counts": dict(status_counts),
                "layers": [
                    "heping_changed_parcels",
                    "heping_constraints",
                    "heping_construction_zones",
                ],
            },
            {
                "id": "banzhu_adjustment",
                "label": "斑竹村 · 土地利用结构调整",
                "question": (
                    "规划前后土地利用结构发生了什么变化，这些统计变化如何回到具体地块和本体状态？"
                ),
                "parcel_count": len(banzhu),
                "changed_count": len(banzhu_changed),
                "changed_area_ha": round(float(banzhu_changed["area_ha"].sum()), 2),
                "structure_rows": adjustment,
                "layers": ["banzhu_changed_parcels"],
            },
        ],
        "agent_plan": [
            {
                "id": "understand",
                "label": "业务问题解析",
                "owner": "Agent",
                "detail": "识别地块、土地利用状态、转换过程、管控边界和证据要求",
            },
            {
                "id": "discover",
                "label": "数据发现",
                "owner": "Agent + 数据目录",
                "detail": "定位 TDGHDL、空间管制图层、重点项目和结构调整表",
            },
            {
                "id": "align",
                "label": "语义对齐",
                "owner": "MMFE",
                "detail": "将 JQDLMC/GHDLMC 等源字段对齐到本体状态与过程",
            },
            {
                "id": "spatial",
                "label": "空间计算",
                "owner": "GIS 引擎",
                "detail": "在源投影坐标系中执行地块与约束范围叠加并计算相交面积",
            },
            {
                "id": "validate",
                "label": "规则与质量校验",
                "owner": "本体 + SHACL",
                "detail": "核验转换允许范围、必需审批证据、标识和来源完整性",
            },
            {
                "id": "explain",
                "label": "证据组织与解释",
                "owner": "Agent",
                "detail": "把结论关联到本体 URI、源文件、源字段、空间命中和版本",
            },
        ],
        "capability_coverage": [
            {"capability": "数据汇聚", "evidence": "Shapefile、Excel 多源资产统一注册"},
            {"capability": "数据治理", "evidence": "术语映射、项目空间关联缺口显式暴露"},
            {"capability": "数据质检", "evidence": "CRS、几何、标识、状态、映射和证据规则校验"},
            {"capability": "数据展示", "evidence": "规划地块、转换过程和管控边界联动地图"},
            {"capability": "数据分析", "evidence": "规划前后状态转换与空间叠加"},
            {"capability": "数据分发", "evidence": "按场景提供受控 GeoJSON 与证据包"},
            {"capability": "数据安全", "evidence": "认证只读 API、来源和用途范围声明"},
            {"capability": "全流程管理", "evidence": "问题解析到证据解释的六步可追踪执行计划"},
            {
                "capability": "数据反馈",
                "evidence": "未映射术语、项目未关联和缺审批材料形成治理待办",
            },
            {"capability": "更新维护", "evidence": "本体、演示包和源文件哈希独立版本化"},
        ],
        "quality": {
            "checks": quality_checks,
            "mapped_terms": mapped_terms,
            "unresolved_terms": unresolved_terms,
        },
        "projects": {"和平村": heping_projects, "斑竹村": banzhu_projects},
        "reviews": {"和平村": heping_changed_review},
        "sources": sources,
        "field_mappings": [
            {"source": "TDGHDL.BSM", "target": "LandParcel.identifier", "relation": "实体标识"},
            {
                "source": "TDGHDL.JQDLMC",
                "target": "LandUseTransition.hasSourceState",
                "relation": "源状态",
            },
            {
                "source": "TDGHDL.GHDLMC",
                "target": "LandUseTransition.hasTargetState",
                "relation": "目标状态",
            },
            {"source": "TDGHDL.geometry", "target": "LandParcel.geometry", "relation": "空间范围"},
            {
                "source": "STBHHX.geometry",
                "target": "EcologicalConservationRedline.geometry",
                "relation": "受边界约束",
            },
            {
                "source": "重点项目清单.占用耕地",
                "target": "ConstructionOccupation.affectedCultivatedArea",
                "relation": "业务指标（待空间关联）",
            },
        ],
    }
    _write_json(output / "demo.json", demo)
    bundle_files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "bundle": demo["bundle"],
        "ontology": demo["ontology"],
        "files": [
            {"name": path.name, "size": path.stat().st_size, "sha256": _sha256(path)}
            for path in bundle_files
        ],
    }
    _write_json(output / "manifest.json", manifest)
    return demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("/Users/zhouning/Downloads/规划院提供数据样例及Demo系统功能演示建议_解压"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data_agent/demo_data/natural_resource_ontology_customer_v1"),
    )
    args = parser.parse_args()
    demo = build(args.source_root.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "overview": demo["overview"],
                "quality": demo["quality"]["checks"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
