from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any


LIFECYCLE_STAGES = [
    "project_list",
    "land_plan",
    "pre_review",
    "site_selection",
    "conversion_expropriation",
    "approval_project",
    "approval_supply",
    "land_supply",
    "land_use_permit",
    "construction_permit",
    "verification",
]

GENERATOR_VERSION = "major_project_synthetic_core_v1"

_STAGE_DEFS = [
    ("land_plan", "land_plans", "LandPlan", "HAS_LAND_PLAN", "PLAN", "plan_id"),
    ("pre_review", "pre_reviews", "PreReview", "HAS_PRE_REVIEW", "PRE", "pre_review_id"),
    ("site_selection", "site_selections", "SiteSelection", "HAS_SITE_SELECTION", "SITE", "site_selection_id"),
    (
        "conversion_expropriation",
        "conversions",
        "ConversionExpropriation",
        "HAS_CONVERSION",
        "CONV",
        "conversion_id",
    ),
    (
        "approval_project",
        "approval_projects",
        "ApprovalProject",
        "HAS_APPROVAL_PROJECT",
        "APPR",
        "approval_project_id",
    ),
    (
        "approval_supply",
        "approval_supplies",
        "ApprovalSupply",
        "HAS_APPROVAL_SUPPLY",
        "APPS",
        "approval_supply_id",
    ),
    ("land_supply", "land_supplies", "LandSupply", "HAS_LAND_SUPPLY", "SUP", "land_supply_id"),
    (
        "land_use_permit",
        "land_use_permits",
        "LandUsePermit",
        "HAS_LAND_USE_PERMIT",
        "LUP",
        "land_use_permit_id",
    ),
    (
        "construction_permit",
        "construction_permits",
        "ConstructionPermit",
        "HAS_CONSTRUCTION_PERMIT",
        "CP",
        "construction_permit_id",
    ),
    ("verification", "verifications", "Verification", "HAS_VERIFICATION", "VER", "verification_id"),
]

_STAGE_NAMES = {
    "land_plan": "用地计划配置",
    "pre_review": "建设项目用地预审",
    "site_selection": "规划选址",
    "conversion_expropriation": "农用地转用和土地征收",
    "approval_project": "建设用地审批项目",
    "approval_supply": "批供关联",
    "land_supply": "土地供应",
    "land_use_permit": "建设用地规划许可",
    "construction_permit": "建设工程规划许可",
    "verification": "规划核实",
}

ARTIFACT_NAMES = [
    "schema_postgis.sql",
    "seed_small.sql",
    "kg_nodes_small.csv",
    "kg_edges_small.csv",
    "neo4j_nodes_small.csv",
    "neo4j_edges_small.csv",
    "neo4j_import.cypher",
    "semantic_sources.json",
    "semantic_registry.json",
    "semantic_models.yaml",
    "semantic_relation_map.json",
    "nl2sql_benchmark_questions.jsonl",
]

KG_NODE_COLUMNS = ["node_id", "label", "biz_id", "name", "properties"]
KG_EDGE_COLUMNS = [
    "edge_id",
    "source_node_id",
    "target_node_id",
    "edge_type",
    "confidence",
    "match_method",
    "evidence",
]

_PROJECT_SQL_COLUMNS = [
    "project_id",
    "zdxmbh",
    "zdxm_sec",
    "project_name",
    "project_type",
    "province",
    "city",
    "county",
    "construction_unit",
    "total_investment_million",
    "planned_land_area_mu",
    "list_year",
    "status",
    "geom",
    "synthetic_seed",
    "profile",
    "generator_version",
]

_STAGE_COMMON_COLUMNS = [
    "project_id",
    "zdxmbh",
    "zdxm_sec",
    "project_name",
    "stage",
    "stage_name",
    "flowsn",
    "dzjgh",
    "approval_date",
    "status",
    "area_mu",
    "synthetic_seed",
    "profile",
    "generator_version",
]

_STAGE_EXTRA_COLUMNS = {
    "pre_review": ["xs_dzjgh"],
    "approval_project": ["bp_guid"],
    "approval_supply": ["bp_guid", "gd_guid"],
    "land_supply": ["gd_guid"],
    "land_use_permit": ["ygdzjgh"],
    "construction_permit": ["ggdzjgh"],
    "verification": ["verification_no"],
}

_STAGE_TABLE_SPECS = [
    {
        "stage": stage,
        "attr": attr,
        "table": f"mp_{stage}",
        "id_field": key_field,
        "columns": [key_field, *_STAGE_COMMON_COLUMNS, *_STAGE_EXTRA_COLUMNS.get(stage, [])],
    }
    for stage, attr, _label, _edge_type, _prefix, key_field in _STAGE_DEFS
]

_PARCEL_SQL_COLUMNS = [
    "parcel_id",
    "project_id",
    "land_use_type",
    "area_mu",
    "geom",
    "synthetic_seed",
    "profile",
    "generator_version",
]

_SPATIAL_OVERLAP_SQL_COLUMNS = [
    "overlap_id",
    "project_id",
    "parcel_id",
    "overlap_ratio",
    "overlap_area_mu",
    "geometry_source",
    "synthetic_seed",
    "profile",
    "generator_version",
]

_RELATION_CONFIDENCE_SQL_COLUMNS = [
    "relation_id",
    "project_id",
    "source_table",
    "source_id",
    "target_table",
    "target_id",
    "relation_type",
    "match_method",
    "confidence",
    "evidence",
    "synthetic_seed",
    "profile",
    "generator_version",
]

_SEED_RESET_TABLE_ORDER = [
    "kg_query_result",
    "kg_edges",
    "kg_nodes",
    "mp_relation_confidence",
    "mp_spatial_overlap",
    "mp_parcel",
    "mp_verification",
    "mp_construction_permit",
    "mp_land_use_permit",
    "mp_land_supply",
    "mp_approval_supply",
    "mp_approval_project",
    "mp_conversion_expropriation",
    "mp_site_selection",
    "mp_pre_review",
    "mp_land_plan",
    "mp_project_list",
]


@dataclass(frozen=True)
class GenerationConfig:
    profile: str = "small_dev"
    project_count: int = 200
    seed: int = 20260604
    output_dir: Path = Path("data_agent/synthetic/major_projects")


@dataclass
class SyntheticDataBundle:
    projects: list[dict[str, Any]] = field(default_factory=list)
    land_plans: list[dict[str, Any]] = field(default_factory=list)
    pre_reviews: list[dict[str, Any]] = field(default_factory=list)
    site_selections: list[dict[str, Any]] = field(default_factory=list)
    conversions: list[dict[str, Any]] = field(default_factory=list)
    approval_projects: list[dict[str, Any]] = field(default_factory=list)
    approval_supplies: list[dict[str, Any]] = field(default_factory=list)
    land_supplies: list[dict[str, Any]] = field(default_factory=list)
    land_use_permits: list[dict[str, Any]] = field(default_factory=list)
    construction_permits: list[dict[str, Any]] = field(default_factory=list)
    verifications: list[dict[str, Any]] = field(default_factory=list)
    parcels: list[dict[str, Any]] = field(default_factory=list)
    spatial_overlaps: list[dict[str, Any]] = field(default_factory=list)
    relation_confidence: list[dict[str, Any]] = field(default_factory=list)
    kg_nodes: list[dict[str, Any]] = field(default_factory=list)
    kg_edges: list[dict[str, Any]] = field(default_factory=list)


class SyntheticMajorProjectGenerator:
    def __init__(self, config: GenerationConfig):
        self.config = config
        self.rng = random.Random(config.seed)

    def build(self) -> SyntheticDataBundle:
        self.rng = random.Random(self.config.seed)
        bundle = SyntheticDataBundle()
        for idx in range(1, self.config.project_count + 1):
            project = self._project(idx)
            bundle.projects.append(project)
            self._append_project_graph(bundle, project)
            self._append_lifecycle_records(bundle, project, idx)
            self._append_parcels_and_spatial_relations(bundle, project, idx)
        return bundle

    def write_all(self, bundle: SyntheticDataBundle) -> list[Path]:
        return _write_all_artifacts(self.config, bundle)

    def _project(self, idx: int) -> dict[str, Any]:
        province = self.rng.choice(["示范省A", "示范省B", "示范省C"])
        city_no = idx % 6 + 1
        county_no = idx % 12 + 1
        return {
            "project_id": f"MP{idx:06d}",
            "zdxmbh": f"ZDXM-{idx:06d}",
            "zdxm_sec": f"SEC-{self.config.seed % 10000:04d}-{idx:08d}",
            "project_name": self._project_name(idx),
            "project_type": self.rng.choice(["交通", "能源", "水利", "产业园区", "民生"]),
            "province": province,
            "city": f"{province}示范市{city_no}",
            "county": f"示范县{county_no}",
            "construction_unit": f"示范建设单位-{idx % 37 + 1:03d}",
            "total_investment_million": round(self.rng.uniform(80, 5000), 2),
            "planned_land_area_mu": round(self.rng.uniform(10, 1200), 2),
            "list_year": 2022 + idx % 5,
            "status": self.rng.choice(["储备", "审批中", "已供地", "建设中", "已核实"]),
            "geom_wkt": self._square_wkt(idx),
            "synthetic_seed": self.config.seed,
            "profile": self.config.profile,
            "generator_version": GENERATOR_VERSION,
        }

    def _project_name(self, idx: int) -> str:
        if idx % 13 == 0:
            return f"示范重大项目重复名称-{idx % 5:02d}"
        letter = chr(65 + (idx - 1) % 26)
        return f"示范重大项目{letter}-{idx:04d}"

    def _square_wkt(self, idx: int) -> str:
        base_x = 118.0 + (idx % 50) * 0.02
        base_y = 31.0 + (idx % 40) * 0.02
        size = 0.005 + (idx % 5) * 0.001
        return (
            f"POLYGON(({base_x:.6f} {base_y:.6f}, {base_x + size:.6f} {base_y:.6f}, "
            f"{base_x + size:.6f} {base_y + size:.6f}, {base_x:.6f} {base_y + size:.6f}, "
            f"{base_x:.6f} {base_y:.6f}))"
        )

    def _append_project_graph(self, bundle: SyntheticDataBundle, project: dict[str, Any]) -> None:
        bundle.kg_nodes.append(
            {
                "node_id": f"project:{project['project_id']}",
                "label": "MajorProject",
                "biz_id": project["project_id"],
                "name": project["project_name"],
                "properties": self._json_properties(project),
            }
        )

    def _append_lifecycle_records(self, bundle: SyntheticDataBundle, project: dict[str, Any], idx: int) -> None:
        previous_node_id = f"project:{project['project_id']}"
        for stage_order, (stage, attr, label, edge_type, prefix, key_field) in enumerate(_STAGE_DEFS, start=1):
            if idx % 7 == 0 and stage == "pre_review":
                self._add_missing_stage(bundle, project, stage)
                previous_node_id = f"stage:{project['project_id']}:{stage}:missing"
                continue

            record = self._stage_record(project, idx, stage_order, stage, prefix, key_field)
            getattr(bundle, attr).append(record)
            node_id = self._add_node_edge(
                bundle=bundle,
                project=project,
                label=label,
                target_id=record[key_field],
                edge_type=edge_type,
                confidence=round(0.99 - stage_order * 0.005, 3),
                match_method="exact_key",
                evidence={"source": "synthetic_lifecycle", "stage": stage},
                properties=record,
            )
            if previous_node_id != f"project:{project['project_id']}":
                self._add_edge(
                    bundle=bundle,
                    source_node_id=previous_node_id,
                    target_node_id=node_id,
                    edge_type="NEXT_STAGE",
                    confidence=0.97,
                    match_method="workflow_order",
                    evidence={"from_stage_order": stage_order - 1, "to_stage_order": stage_order},
                )
            previous_node_id = node_id

        if idx % 9 == 0:
            self._add_risk(bundle, project, "overdue_approval")

    def _stage_record(
        self,
        project: dict[str, Any],
        idx: int,
        stage_order: int,
        stage: str,
        prefix: str,
        key_field: str,
    ) -> dict[str, Any]:
        record_id = f"{prefix}{idx:06d}"
        row = {
            key_field: record_id,
            "project_id": project["project_id"],
            "zdxmbh": project["zdxmbh"],
            "zdxm_sec": project["zdxm_sec"],
            "project_name": project["project_name"],
            "stage": stage,
            "stage_name": _STAGE_NAMES[stage],
            "flowsn": f"FLOW-{stage_order:02d}-{idx:08d}",
            "dzjgh": f"DZJGH-{stage_order:02d}-{idx:08d}",
            "approval_date": self._stage_date(idx, stage_order),
            "status": "已办结" if stage != "verification" else self.rng.choice(["已核实", "待整改"]),
            "area_mu": round(project["planned_land_area_mu"] * self.rng.uniform(0.65, 1.05), 2),
            "synthetic_seed": self.config.seed,
            "profile": self.config.profile,
            "generator_version": GENERATOR_VERSION,
        }
        row.update(self._stage_specific_keys(idx, stage_order, stage))
        return row

    def _stage_specific_keys(self, idx: int, stage_order: int, stage: str) -> dict[str, Any]:
        dzjgh = f"DZJGH-{stage_order:02d}-{idx:08d}"
        if stage == "pre_review":
            return {"xs_dzjgh": dzjgh}
        if stage == "approval_project":
            return {"bp_guid": f"BP-{idx:08d}"}
        if stage == "approval_supply":
            return {"bp_guid": f"BP-{idx:08d}", "gd_guid": f"GD-{idx:08d}"}
        if stage == "land_supply":
            return {"gd_guid": f"GD-{idx:08d}"}
        if stage == "land_use_permit":
            return {"ygdzjgh": dzjgh}
        if stage == "construction_permit":
            return {"ggdzjgh": dzjgh}
        if stage == "verification":
            return {"verification_no": f"VER-NO-{idx:08d}"}
        return {}

    def _stage_date(self, idx: int, stage_order: int) -> str:
        start = date(2022, 1, 1)
        return (start + timedelta(days=idx * 11 + stage_order * 23)).isoformat()

    def _append_parcels_and_spatial_relations(
        self, bundle: SyntheticDataBundle, project: dict[str, Any], idx: int
    ) -> None:
        parcel = {
            "parcel_id": f"PARCEL{idx:06d}",
            "project_id": project["project_id"],
            "land_use_type": self.rng.choice(["耕地", "建设用地", "林地", "未利用地"]),
            "area_mu": round(project["planned_land_area_mu"] * self.rng.uniform(0.5, 1.2), 2),
            "geom_wkt": project["geom_wkt"],
            "synthetic_seed": self.config.seed,
            "profile": self.config.profile,
            "generator_version": GENERATOR_VERSION,
        }
        bundle.parcels.append(parcel)
        parcel_node_id = self._add_node_edge(
            bundle=bundle,
            project=project,
            label="Parcel",
            target_id=parcel["parcel_id"],
            edge_type="OCCUPIES_PARCEL",
            confidence=0.99,
            match_method="exact_key",
            evidence={"source": "synthetic_project_parcel", "matched_fields": ["project_id"]},
            properties=parcel,
        )
        self._append_relation_confidence(
            bundle=bundle,
            project=project,
            target_id=parcel["parcel_id"],
            relation_type="OCCUPIES_PARCEL",
            match_method="exact_key",
            confidence=0.99,
            evidence={"matched_fields": ["project_id"]},
        )

        if idx % 8 == 0:
            self._append_spatial_overlay(bundle, project, parcel, parcel_node_id, idx)
        if idx % 10 == 0:
            self._append_fuzzy_relation(bundle, project, parcel, parcel_node_id, idx)

    def _append_spatial_overlay(
        self,
        bundle: SyntheticDataBundle,
        project: dict[str, Any],
        parcel: dict[str, Any],
        parcel_node_id: str,
        idx: int,
    ) -> None:
        overlap_ratio = round(0.31 + (idx % 5) * 0.07, 2)
        overlap = {
            "overlap_id": f"OVL{idx:06d}",
            "project_id": project["project_id"],
            "parcel_id": parcel["parcel_id"],
            "overlap_ratio": overlap_ratio,
            "overlap_area_mu": round(parcel["area_mu"] * overlap_ratio, 2),
            "geometry_source": "synthetic_demo_extent",
            "synthetic_seed": self.config.seed,
            "profile": self.config.profile,
            "generator_version": GENERATOR_VERSION,
        }
        bundle.spatial_overlaps.append(overlap)
        self._append_relation_confidence(
            bundle=bundle,
            project=project,
            target_id=parcel["parcel_id"],
            relation_type="SPATIALLY_OVERLAPS",
            match_method="spatial_overlay",
            confidence=0.72,
            evidence={"overlap_ratio": overlap_ratio, "geometry_source": overlap["geometry_source"]},
        )
        self._add_edge(
            bundle=bundle,
            source_node_id=f"project:{project['project_id']}",
            target_node_id=parcel_node_id,
            edge_type="SPATIALLY_OVERLAPS",
            confidence=0.72,
            match_method="spatial_overlay",
            evidence={"overlap_ratio": overlap_ratio, "geometry_source": overlap["geometry_source"]},
        )

    def _append_fuzzy_relation(
        self,
        bundle: SyntheticDataBundle,
        project: dict[str, Any],
        parcel: dict[str, Any],
        parcel_node_id: str,
        idx: int,
    ) -> None:
        fuzzy_name = project["project_name"].replace("-", "")
        self._append_relation_confidence(
            bundle=bundle,
            project=project,
            target_id=parcel["parcel_id"],
            relation_type="FUZZY_PROJECT_PARCEL_MATCH",
            match_method="fuzzy_name",
            confidence=0.81,
            evidence={"source_name": project["project_name"], "matched_name": fuzzy_name},
        )
        self._add_edge(
            bundle=bundle,
            source_node_id=f"project:{project['project_id']}",
            target_node_id=parcel_node_id,
            edge_type="FUZZY_PROJECT_PARCEL_MATCH",
            confidence=0.81,
            match_method="fuzzy_name",
            evidence={"source_name": project["project_name"], "matched_name": fuzzy_name, "case_idx": idx},
        )

    def _append_relation_confidence(
        self,
        bundle: SyntheticDataBundle,
        project: dict[str, Any],
        target_id: str,
        relation_type: str,
        match_method: str,
        confidence: float,
        evidence: dict[str, Any],
    ) -> None:
        bundle.relation_confidence.append(
            {
                "relation_id": f"REL-{project['project_id']}:{relation_type}:{match_method}:{target_id}",
                "project_id": project["project_id"],
                "source_table": "mp_project_list",
                "source_id": project["project_id"],
                "target_table": "mp_parcel",
                "target_id": target_id,
                "relation_type": relation_type,
                "match_method": match_method,
                "confidence": confidence,
                "evidence": self._json_properties(evidence),
                "synthetic_seed": self.config.seed,
                "profile": self.config.profile,
                "generator_version": GENERATOR_VERSION,
            }
        )

    def _add_node_edge(
        self,
        bundle: SyntheticDataBundle,
        project: dict[str, Any],
        label: str,
        target_id: str,
        edge_type: str,
        confidence: float,
        match_method: str,
        evidence: dict[str, Any],
        properties: dict[str, Any],
    ) -> str:
        node_id = f"{label.lower()}:{target_id}"
        bundle.kg_nodes.append(
            {
                "node_id": node_id,
                "label": label,
                "biz_id": target_id,
                "name": f"{label}-{target_id}",
                "properties": self._json_properties(properties),
            }
        )
        self._add_edge(
            bundle=bundle,
            source_node_id=f"project:{project['project_id']}",
            target_node_id=node_id,
            edge_type=edge_type,
            confidence=confidence,
            match_method=match_method,
            evidence=evidence,
        )
        return node_id

    def _add_edge(
        self,
        bundle: SyntheticDataBundle,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        confidence: float,
        match_method: str,
        evidence: dict[str, Any],
    ) -> None:
        bundle.kg_edges.append(
            {
                "edge_id": f"edge:{len(bundle.kg_edges) + 1:08d}:{edge_type}",
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "edge_type": edge_type,
                "confidence": confidence,
                "match_method": match_method,
                "evidence": self._json_properties(evidence),
            }
        )

    def _add_missing_stage(self, bundle: SyntheticDataBundle, project: dict[str, Any], stage: str) -> None:
        missing_node_id = f"stage:{project['project_id']}:{stage}:missing"
        bundle.kg_nodes.append(
            {
                "node_id": missing_node_id,
                "label": "LifecycleAnomaly",
                "biz_id": f"{project['project_id']}:{stage}",
                "name": f"缺失阶段:{_STAGE_NAMES[stage]}",
                "properties": self._json_properties(
                    {
                        "project_id": project["project_id"],
                        "missing_stage": stage,
                        "synthetic_seed": self.config.seed,
                        "profile": self.config.profile,
                        "generator_version": GENERATOR_VERSION,
                    }
                ),
            }
        )
        self._add_edge(
            bundle=bundle,
            source_node_id=f"project:{project['project_id']}",
            target_node_id=missing_node_id,
            edge_type="MISSING_STAGE",
            confidence=1.0,
            match_method="rule",
            evidence={"missing_stage": stage, "rule": "idx % 7 == 0"},
        )

    def _add_risk(self, bundle: SyntheticDataBundle, project: dict[str, Any], risk_type: str) -> None:
        risk_id = f"risk:{project['project_id']}:{risk_type}"
        bundle.kg_nodes.append(
            {
                "node_id": risk_id,
                "label": "RiskEvent",
                "biz_id": risk_id,
                "name": risk_type,
                "properties": self._json_properties(
                    {
                        "project_id": project["project_id"],
                        "risk_type": risk_type,
                        "synthetic_seed": self.config.seed,
                        "profile": self.config.profile,
                        "generator_version": GENERATOR_VERSION,
                    }
                ),
            }
        )
        self._add_edge(
            bundle=bundle,
            source_node_id=f"project:{project['project_id']}",
            target_node_id=risk_id,
            edge_type="HAS_RISK",
            confidence=0.88,
            match_method="rule",
            evidence={"source": "synthetic_rule", "rule": "idx % 9 == 0"},
        )

    def _json_properties(self, value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _write_all_artifacts(config: GenerationConfig, bundle: SyntheticDataBundle) -> list[Path]:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    written = [
        _write_text(output_dir / "schema_postgis.sql", _schema_postgis_sql()),
        _write_text(output_dir / "seed_small.sql", _seed_sql(config, bundle)),
        _write_csv(output_dir / "kg_nodes_small.csv", KG_NODE_COLUMNS, bundle.kg_nodes),
        _write_csv(output_dir / "kg_edges_small.csv", KG_EDGE_COLUMNS, bundle.kg_edges),
        _write_csv(output_dir / "neo4j_nodes_small.csv", KG_NODE_COLUMNS, bundle.kg_nodes),
        _write_csv(output_dir / "neo4j_edges_small.csv", KG_EDGE_COLUMNS, bundle.kg_edges),
        _write_text(output_dir / "neo4j_import.cypher", _neo4j_import_cypher()),
        _write_json(output_dir / "semantic_sources.json", _semantic_sources(config)),
        _write_json(output_dir / "semantic_registry.json", _semantic_registry(config)),
        _write_text(output_dir / "semantic_models.yaml", _semantic_models_yaml(config)),
        _write_json(output_dir / "semantic_relation_map.json", _semantic_relation_map(config)),
        _write_jsonl(output_dir / "nl2sql_benchmark_questions.jsonl", _benchmark_questions()),
    ]
    return written


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text = f"{text}\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return _write_text(path, text)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return _write_text(path, text)


def _schema_postgis_sql() -> str:
    blocks = [
        "-- Synthetic major-project PostGIS schema",
        "-- Synthetic-only demonstration structure; contains no production records.",
        "CREATE EXTENSION IF NOT EXISTS postgis;",
        """CREATE TABLE IF NOT EXISTS mp_project_list (
    project_id TEXT PRIMARY KEY,
    zdxmbh TEXT NOT NULL,
    zdxm_sec TEXT NOT NULL,
    project_name TEXT NOT NULL,
    project_type TEXT,
    province TEXT,
    city TEXT,
    county TEXT,
    construction_unit TEXT,
    total_investment_million NUMERIC,
    planned_land_area_mu NUMERIC,
    list_year INTEGER,
    status TEXT,
    geom geometry(Polygon, 4326),
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);""",
    ]

    blocks.extend(_stage_schema_sql(spec) for spec in _STAGE_TABLE_SPECS)
    blocks.extend(
        [
            """CREATE TABLE IF NOT EXISTS mp_parcel (
    parcel_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES mp_project_list(project_id),
    land_use_type TEXT,
    area_mu NUMERIC,
    geom geometry(Polygon, 4326),
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);""",
            """CREATE TABLE IF NOT EXISTS mp_spatial_overlap (
    overlap_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES mp_project_list(project_id),
    parcel_id TEXT NOT NULL REFERENCES mp_parcel(parcel_id),
    overlap_ratio NUMERIC,
    overlap_area_mu NUMERIC,
    geometry_source TEXT,
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);""",
            """CREATE TABLE IF NOT EXISTS mp_relation_confidence (
    relation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES mp_project_list(project_id),
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    match_method TEXT NOT NULL,
    confidence NUMERIC NOT NULL,
    evidence JSONB,
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);""",
            """CREATE TABLE IF NOT EXISTS kg_nodes (
    node_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    biz_id TEXT NOT NULL,
    name TEXT,
    properties JSONB
);""",
            """CREATE TABLE IF NOT EXISTS kg_edges (
    edge_id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL REFERENCES kg_nodes(node_id),
    target_node_id TEXT NOT NULL REFERENCES kg_nodes(node_id),
    edge_type TEXT NOT NULL,
    confidence NUMERIC,
    match_method TEXT,
    evidence JSONB
);""",
            """CREATE TABLE IF NOT EXISTS kg_query_result (
    result_id BIGSERIAL PRIMARY KEY,
    benchmark_id TEXT,
    question TEXT NOT NULL,
    route_class TEXT,
    sql_text TEXT,
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);""",
            "CREATE INDEX IF NOT EXISTS idx_mp_project_list_geom ON mp_project_list USING GIST (geom);",
            "CREATE INDEX IF NOT EXISTS idx_mp_parcel_geom ON mp_parcel USING GIST (geom);",
            "CREATE INDEX IF NOT EXISTS idx_mp_relation_confidence_type ON mp_relation_confidence (relation_type);",
            "CREATE INDEX IF NOT EXISTS idx_kg_edges_edge_type ON kg_edges (edge_type);",
        ]
    )
    return "\n\n".join(blocks)


def _stage_schema_sql(spec: dict[str, Any]) -> str:
    id_field = spec["id_field"]
    lines = [f"CREATE TABLE IF NOT EXISTS {spec['table']} (", f"    {id_field} TEXT PRIMARY KEY"]
    for column in spec["columns"][1:]:
        lines.append(f"    ,{column} {_sql_column_type(column)}")
    lines.append("    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)")
    lines.append(");")
    return "\n".join(lines)


def _sql_column_type(column: str) -> str:
    if column in {"synthetic_seed"}:
        return "INTEGER NOT NULL"
    if column in {"area_mu", "overlap_ratio", "overlap_area_mu", "confidence"}:
        return "NUMERIC"
    if column == "approval_date":
        return "DATE"
    return "TEXT"


def _seed_sql(config: GenerationConfig, bundle: SyntheticDataBundle) -> str:
    blocks = [
        "-- Synthetic major-project seed data",
        "-- Synthetic-only demonstration records; contains no production records.",
        f"-- profile={config.profile}; project_count={config.project_count}; seed={config.seed}",
        "BEGIN;",
        _seed_reset_sql(),
        _sql_insert_block(
            "mp_project_list",
            bundle.projects,
            _PROJECT_SQL_COLUMNS,
            source_columns={"geom": "geom_wkt"},
            geometry_columns={"geom"},
        ),
    ]

    for spec in _STAGE_TABLE_SPECS:
        blocks.append(_sql_insert_block(spec["table"], getattr(bundle, spec["attr"]), spec["columns"]))

    blocks.extend(
        [
            _sql_insert_block(
                "mp_parcel",
                bundle.parcels,
                _PARCEL_SQL_COLUMNS,
                source_columns={"geom": "geom_wkt"},
                geometry_columns={"geom"},
            ),
            _sql_insert_block("mp_spatial_overlap", bundle.spatial_overlaps, _SPATIAL_OVERLAP_SQL_COLUMNS),
            _sql_insert_block(
                "mp_relation_confidence",
                bundle.relation_confidence,
                _RELATION_CONFIDENCE_SQL_COLUMNS,
                jsonb_columns={"evidence"},
            ),
            _sql_insert_block("kg_nodes", bundle.kg_nodes, KG_NODE_COLUMNS, jsonb_columns={"properties"}),
            _sql_insert_block("kg_edges", bundle.kg_edges, KG_EDGE_COLUMNS, jsonb_columns={"evidence"}),
            "COMMIT;",
        ]
    )
    return "\n\n".join(blocks)


def _seed_reset_sql() -> str:
    table_lines = ",\n".join(f"    {table_name}" for table_name in _SEED_RESET_TABLE_ORDER)
    return (
        "-- Reset synthetic major-project tables before loading this seed/profile.\n"
        "-- This keeps repeated demo loads deterministic across seeds and profiles.\n"
        f"TRUNCATE TABLE\n{table_lines}\nRESTART IDENTITY;"
    )


def _sql_insert_block(
    table: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    source_columns: dict[str, str] | None = None,
    geometry_columns: set[str] | None = None,
    jsonb_columns: set[str] | None = None,
) -> str:
    if not rows:
        return f"-- No synthetic rows generated for {table}."

    source_columns = source_columns or {}
    geometry_columns = geometry_columns or set()
    jsonb_columns = jsonb_columns or set()
    rendered_rows = []
    for row in rows:
        values = []
        for column in columns:
            source_column = source_columns.get(column, column)
            values.append(
                _sql_value(
                    row.get(source_column),
                    is_geometry=column in geometry_columns,
                    is_jsonb=column in jsonb_columns,
                )
            )
        rendered_rows.append(f"    ({', '.join(values)})")

    joined_rows = ",\n".join(rendered_rows)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n{joined_rows}\nON CONFLICT DO NOTHING;"


def _sql_value(value: Any, *, is_geometry: bool = False, is_jsonb: bool = False) -> str:
    if value is None:
        return "NULL"
    if is_geometry:
        return f"ST_GeomFromText({_sql_literal(value)}, 4326)"
    if is_jsonb:
        if isinstance(value, str):
            payload = value
        else:
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return f"{_sql_literal(payload)}::jsonb"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    return _sql_literal(value)


def _sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _neo4j_import_cypher() -> str:
    return """// Synthetic major-project Neo4j import
// Synthetic-only demonstration graph; contains no production records.
// Copy neo4j_nodes_small.csv and neo4j_edges_small.csv into Neo4j's import directory before running.

CREATE CONSTRAINT synthetic_major_project_node_id IF NOT EXISTS
FOR (n:SyntheticMajorProjectNode)
REQUIRE n.node_id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///neo4j_nodes_small.csv' AS row
CREATE (n:SyntheticMajorProjectNode)
SET n.node_id = row.node_id,
    n.label = row.label,
    n.biz_id = row.biz_id,
    n.name = row.name,
    n.properties_json = row.properties,
    n.synthetic_notice = 'Synthetic major-project demo only; no production records';

LOAD CSV WITH HEADERS FROM 'file:///neo4j_edges_small.csv' AS row
MATCH (source:SyntheticMajorProjectNode {node_id: row.source_node_id})
MATCH (target:SyntheticMajorProjectNode {node_id: row.target_node_id})
CREATE (source)-[r:SYNTHETIC_KG_EDGE]->(target)
SET r.edge_id = row.edge_id,
    r.edge_type = row.edge_type,
    r.confidence = toFloat(row.confidence),
    r.match_method = row.match_method,
    r.evidence_json = row.evidence,
    r.synthetic_notice = 'Synthetic major-project demo only; no production records';
"""


def _semantic_sources(config: GenerationConfig) -> dict[str, Any]:
    stage_synonyms = {
        "land_plan": ["用地计划", "计划配置", "土地计划"],
        "pre_review": ["用地预审", "预审", "预审意见", "建设项目预审"],
        "site_selection": ["规划选址", "选址意见", "项目选址", "选址阶段"],
        "conversion_expropriation": ["农转用", "土地征收", "转用征收", "农用地转用"],
        "approval_project": ["建设用地审批", "审批项目", "用地审批", "项目审批"],
        "approval_supply": ["批供关联", "审批供地关联", "批供", "批供关系"],
        "land_supply": ["供地", "土地供应", "供地结果", "供应地块"],
        "land_use_permit": ["用地规划许可", "建设用地规划许可证", "用地许可", "规划许可"],
        "construction_permit": ["工程规划许可", "建设工程规划许可证", "工程许可", "建设许可"],
        "verification": ["规划核实", "核实", "竣工核实", "规划核验"],
    }
    sources: dict[str, Any] = {
        "mp_project_list": {
            "display_name": "重大项目清单（合成）",
            "description": "重大项目主表，保留项目编号、名称、行政区、投资、计划用地面积和空间范围等业务结构。",
            "primary_key": "project_id",
            "synonyms": ["重大项目", "重点项目", "项目清单", "省级重大项目", "重大项目列表"],
            "default_grain": "one row per major project",
            "geometry_column": "geom",
        },
    }
    for spec in _STAGE_TABLE_SPECS:
        stage = spec["stage"]
        sources[spec["table"]] = {
            "display_name": f"{_STAGE_NAMES[stage]}（合成）",
            "description": f"重大项目生命周期中的{_STAGE_NAMES[stage]}阶段记录，可通过 project_id 或 zdxmbh 关联项目清单。",
            "primary_key": spec["id_field"],
            "synonyms": stage_synonyms[stage],
            "default_grain": "one row per project lifecycle stage record",
        }
    sources.update(
        {
            "mp_parcel": {
                "display_name": "项目占用地块（合成）",
                "description": "项目关联地块，包含地类、面积和 PostGIS 几何。",
                "primary_key": "parcel_id",
                "synonyms": ["地块", "项目地块", "占用地块", "宗地", "图斑"],
                "geometry_column": "geom",
            },
            "mp_spatial_overlap": {
                "display_name": "项目地块空间叠加（合成）",
                "description": "项目范围与地块范围的空间叠加比例和面积。",
                "primary_key": "overlap_id",
                "synonyms": ["空间叠加", "空间重叠", "叠加分析", "重叠地块"],
            },
            "mp_relation_confidence": {
                "display_name": "关系置信度（合成）",
                "description": "项目、地块和流程节点之间的关系推断证据及置信度。",
                "primary_key": "relation_id",
                "synonyms": ["关系置信度", "匹配置信度", "关系证据", "图谱关系"],
            },
            "kg_nodes": {
                "display_name": "知识图谱节点（合成）",
                "description": "重大项目、生命周期节点、地块、异常和风险事件的图谱节点投影。",
                "primary_key": "node_id",
                "synonyms": ["图谱节点", "KG节点", "知识图谱节点", "节点表"],
            },
            "kg_edges": {
                "display_name": "知识图谱边（合成）",
                "description": "生命周期、占地、空间叠加、缺失阶段和风险事件的图谱边投影。",
                "primary_key": "edge_id",
                "synonyms": ["图谱边", "KG边", "知识图谱关系", "边表"],
            },
            "kg_query_result": {
                "display_name": "知识图谱查询结果（合成）",
                "description": "用于记录合成 benchmark 问题、路由类别、SQL 和结果 JSON 的结果表。",
                "primary_key": "result_id",
                "synonyms": ["查询结果", "图谱查询结果", "Benchmark结果", "问答结果"],
            },
        }
    )
    return {
        "metadata": {
            "profile": config.profile,
            "seed": config.seed,
            "generator_version": GENERATOR_VERSION,
            "synthetic_only": True,
            "notice": "Synthetic major-project semantic sources; no production records.",
        },
        "sources": sources,
    }


def _semantic_registry(config: GenerationConfig) -> dict[str, Any]:
    return {
        "metadata": {
            "profile": config.profile,
            "seed": config.seed,
            "generator_version": GENERATOR_VERSION,
            "synthetic_only": True,
            "notice": "Chinese NL2SQL grounding registry for synthetic major-project data only.",
        },
        "columns": {
            "project_id": {
                "display_name": "项目内部ID",
                "aliases": ["项目ID", "项目编号", "内部项目编号", "major project id"],
                "domain": "major_project_identifier",
                "tables": ["mp_project_list", "mp_relation_confidence", "mp_parcel"],
                "value_example": "MP000001",
            },
            "zdxmbh": {
                "display_name": "重大项目编号",
                "aliases": ["重大项目编号", "重点项目编号", "zdxmbh", "业务编号"],
                "domain": "business_project_identifier",
                "tables": ["mp_project_list", "mp_land_plan", "mp_pre_review", "mp_conversion_expropriation"],
                "value_example": "ZDXM-000001",
            },
            "project_name": {
                "display_name": "项目名称",
                "aliases": ["项目名称", "重大项目名称", "工程名称", "建设项目名称"],
                "domain": "project_text",
                "tables": ["mp_project_list", "mp_land_plan", "mp_pre_review", "mp_land_supply"],
            },
            "planned_land_area_mu": {
                "display_name": "计划用地面积",
                "aliases": ["计划用地面积", "拟用地面积", "规划用地面积", "用地规模", "用地面积"],
                "domain": "land_area",
                "unit": "亩",
                "tables": ["mp_project_list"],
            },
            "area_mu": {
                "display_name": "阶段或地块面积",
                "aliases": ["面积", "阶段面积", "地块面积", "供地面积", "预审面积"],
                "domain": "land_area",
                "unit": "亩",
                "tables": ["mp_pre_review", "mp_land_supply", "mp_parcel"],
            },
            "geom": {
                "display_name": "空间几何",
                "aliases": ["空间范围", "几何", "geometry", "geom", "坐标范围", "图形"],
                "domain": "postgis_geometry",
                "tables": ["mp_project_list", "mp_parcel"],
                "operators": ["ST_Intersects", "ST_Contains", "ST_Area", "ST_GeomFromText"],
            },
            "land_use_type": {
                "display_name": "地类",
                "aliases": ["地类", "土地用途", "用地类型", "土地利用类型", "现状地类"],
                "domain": "land_use_category",
                "tables": ["mp_parcel"],
                "value_examples": ["耕地", "建设用地", "林地", "未利用地"],
            },
            "relation_type": {
                "display_name": "图谱关系类型",
                "aliases": ["关系类型", "边类型", "图谱边", "关联类型"],
                "domain": "kg_relation",
                "tables": ["mp_relation_confidence", "kg_edges"],
            },
            "confidence": {
                "display_name": "关系置信度",
                "aliases": ["置信度", "匹配分数", "可信度", "关系分值"],
                "domain": "confidence_score",
                "tables": ["mp_relation_confidence", "kg_edges"],
                "range": [0, 1],
            },
        },
    }


def _semantic_models_yaml(config: GenerationConfig) -> str:
    return f"""semantic_models:
  - name: mp_project_lifecycle
    description: "重大项目从清单、用地计划、预审、农转用、供地到许可核实的合成生命周期模型。"
    source_table: mp_project_list
    srid: 4326
    geometry_type: Polygon
    metadata:
      profile: {config.profile}
      seed: {config.seed}
      generator_version: {GENERATOR_VERSION}
      synthetic_only: true
      notice: "Synthetic major-project semantic model; no production records."
    entities:
      - name: major_project
        type: primary
        column: project_id
      - name: parcel
        type: foreign
        column: parcel_id
    joins:
      - name: project_to_pre_review
        left_table: mp_project_list
        right_table: mp_pre_review
        left_key: project_id
        right_key: project_id
        relationship: one_to_many
      - name: project_to_conversion
        left_table: mp_project_list
        right_table: mp_conversion_expropriation
        left_key: project_id
        right_key: project_id
        relationship: one_to_many
      - name: project_to_parcel_confidence
        left_table: mp_project_list
        right_table: mp_relation_confidence
        left_key: project_id
        right_key: project_id
        relationship: one_to_many
        filter: "relation_type = 'OCCUPIES_PARCEL'"
      - name: parcel_confidence_to_parcel
        left_table: mp_relation_confidence
        right_table: mp_parcel
        left_key: target_id
        right_key: parcel_id
        relationship: many_to_one
    dimensions:
      - name: project_name
        type: categorical
        column: project_name
      - name: zdxmbh
        type: categorical
        column: zdxmbh
      - name: province
        type: categorical
        column: province
      - name: city
        type: categorical
        column: city
      - name: county
        type: categorical
        column: county
      - name: project_type
        type: categorical
        column: project_type
      - name: status
        type: categorical
        column: status
      - name: list_year
        type: time
        column: list_year
      - name: geom
        type: spatial
        column: geom
        srid: 4326
        geometry_type: Polygon
    measures:
      - name: project_count
        agg: count_distinct
        column: project_id
      - name: planned_land_area_mu
        agg: sum
        column: planned_land_area_mu
      - name: occupied_parcel_area_mu
        agg: sum
        column: area_mu
    metrics:
      - name: total_planned_land_area_mu
        type: simple
        measure: planned_land_area_mu
      - name: total_occupied_parcel_area_mu
        type: simple
        measure: occupied_parcel_area_mu
"""


def _semantic_relation_map(config: GenerationConfig) -> dict[str, Any]:
    edge_types: dict[str, Any] = {
        edge_type: {
            "sql_table": f"mp_{stage}",
            "source_table": "mp_project_list",
            "source_key": "project_id",
            "target_key": "project_id",
            "semantic": f"项目具有{_STAGE_NAMES[stage]}阶段记录",
            "route_hint": "sql_join",
        }
        for stage, _attr, _label, edge_type, _prefix, _key_field in _STAGE_DEFS
    }
    edge_types.update(
        {
            "OCCUPIES_PARCEL": {
                "sql_table": "mp_relation_confidence",
                "source_table": "mp_project_list",
                "target_table": "mp_parcel",
                "relation_filter": "relation_type = 'OCCUPIES_PARCEL'",
                "source_key": "project_id",
                "target_key": "target_id",
                "target_join_key": "parcel_id",
                "relation_source_key": "project_id",
                "relation_target_key": "target_id",
                "semantic": "项目占用或关联地块",
                "route_hint": "hybrid_sql_graph",
            },
            "SPATIALLY_OVERLAPS": {
                "sql_table": "mp_relation_confidence",
                "source_table": "mp_project_list",
                "target_table": "mp_parcel",
                "relation_filter": "relation_type = 'SPATIALLY_OVERLAPS'",
                "source_key": "project_id",
                "target_key": "target_id",
                "target_join_key": "parcel_id",
                "relation_source_key": "project_id",
                "relation_target_key": "target_id",
                "semantic": "项目空间范围与地块有叠加关系",
                "route_hint": "hybrid_spatial",
            },
            "FUZZY_PROJECT_PARCEL_MATCH": {
                "sql_table": "mp_relation_confidence",
                "source_table": "mp_project_list",
                "target_table": "mp_parcel",
                "relation_filter": "relation_type = 'FUZZY_PROJECT_PARCEL_MATCH'",
                "source_key": "project_id",
                "target_key": "target_id",
                "target_join_key": "parcel_id",
                "relation_source_key": "project_id",
                "relation_target_key": "target_id",
                "semantic": "项目和地块通过名称或弱键模糊匹配",
                "route_hint": "graph_evidence",
            },
            "MISSING_STAGE": {
                "sql_table": "kg_edges",
                "semantic": "生命周期缺失阶段告警",
                "route_hint": "graph",
            },
            "NEXT_STAGE": {
                "sql_table": "kg_edges",
                "semantic": "生命周期阶段顺序边",
                "route_hint": "graph",
            },
            "HAS_RISK": {
                "sql_table": "kg_edges",
                "semantic": "项目风险事件",
                "route_hint": "graph",
            },
        }
    )
    return {
        "metadata": {
            "profile": config.profile,
            "seed": config.seed,
            "generator_version": GENERATOR_VERSION,
            "synthetic_only": True,
            "notice": "KG-to-SQL relation map for synthetic major-project data only.",
        },
        "kg_edge_types": edge_types,
    }


def _benchmark_row(
    question_id: str,
    query_class: str,
    coverage_category: str,
    question: str,
    expected_sql_tables: list[str],
    expected_route: str,
    notes: str,
    expected_kg_edge_types: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": question_id,
        "class": query_class,
        "query_class": query_class,
        "coverage_category": coverage_category,
        "question": question,
        "expected_sql_tables": expected_sql_tables,
        "expected_kg_edge_types": expected_kg_edge_types or [],
        "expected_route": expected_route,
        "notes": notes,
    }


def _benchmark_questions() -> list[dict[str, Any]]:
    return [
        _benchmark_row(
            "mp_bench_sql_type_001",
            "sql_only",
            "sql_project_count_by_type",
            "按项目类型统计重大项目数量，并按数量降序排列。",
            ["mp_project_list"],
            "sql",
            "验证 project_type 分组和项目计数。",
        ),
        _benchmark_row(
            "mp_bench_sql_type_002",
            "sql_only",
            "sql_project_count_by_type",
            "统计2024年清单中各项目类型的重大项目数量。",
            ["mp_project_list"],
            "sql",
            "验证 list_year 过滤、project_type 分组和 count。",
        ),
        _benchmark_row(
            "mp_bench_sql_type_003",
            "sql_only",
            "sql_project_count_by_type",
            "列出每个城市内各项目类型的重大项目数量。",
            ["mp_project_list"],
            "sql",
            "验证 city 与 project_type 的组合分组。",
        ),
        _benchmark_row(
            "mp_bench_sql_area_city_001",
            "sql_only",
            "sql_planned_land_area_by_city",
            "按城市汇总重大项目计划用地面积，并按面积从高到低排序。",
            ["mp_project_list"],
            "sql",
            "验证 planned_land_area_mu、city 和聚合排序。",
        ),
        _benchmark_row(
            "mp_bench_sql_area_city_002",
            "sql_only",
            "sql_planned_land_area_by_city",
            "统计2025年各城市重大项目计划用地总面积。",
            ["mp_project_list"],
            "sql",
            "验证年份过滤后的计划用地面积汇总。",
        ),
        _benchmark_row(
            "mp_bench_sql_area_city_003",
            "sql_only",
            "sql_planned_land_area_by_city",
            "列出各城市各项目类型的计划用地面积合计。",
            ["mp_project_list"],
            "sql",
            "验证城市和项目类型双维度面积聚合。",
        ),
        _benchmark_row(
            "mp_bench_sql_supply_count_001",
            "sql_only",
            "sql_supplied_project_count",
            "统计已经形成供地记录的重大项目数量。",
            ["mp_project_list", "mp_land_supply"],
            "sql",
            "验证清单表和供地阶段表的 SQL 连接计数。",
        ),
        _benchmark_row(
            "mp_bench_sql_supply_count_002",
            "sql_only",
            "sql_supplied_project_count",
            "按城市统计已供地重大项目数量。",
            ["mp_project_list", "mp_land_supply"],
            "sql",
            "验证供地记录与城市维度的聚合。",
        ),
        _benchmark_row(
            "mp_bench_sql_supply_count_003",
            "sql_only",
            "sql_supplied_project_count",
            "统计2024年有土地供应记录的重大项目数量。",
            ["mp_project_list", "mp_land_supply"],
            "sql",
            "验证年份过滤和供地阶段存在性。",
        ),
        _benchmark_row(
            "mp_bench_graph_missing_001",
            "graph",
            "graph_missing_stage",
            "找出知识图谱中缺少用地预审阶段的重大项目。",
            ["kg_nodes", "kg_edges"],
            "graph",
            "验证生命周期异常边。",
            ["MISSING_STAGE"],
        ),
        _benchmark_row(
            "mp_bench_graph_missing_002",
            "graph",
            "graph_missing_stage",
            "列出知识图谱中存在 MISSING_STAGE 边的项目编号和缺失阶段。",
            ["kg_nodes", "kg_edges"],
            "graph",
            "验证缺失阶段异常节点和边的解析。",
            ["MISSING_STAGE"],
        ),
        _benchmark_row(
            "mp_bench_graph_missing_003",
            "graph",
            "graph_missing_stage",
            "统计缺少用地预审阶段的重大项目数量。",
            ["kg_nodes", "kg_edges"],
            "graph",
            "验证图谱异常边的聚合计数。",
            ["MISSING_STAGE"],
        ),
        _benchmark_row(
            "mp_bench_graph_path_001",
            "graph",
            "graph_lifecycle_path",
            "查询重大项目从清单到规划核实的生命周期路径。",
            ["kg_nodes", "kg_edges"],
            "graph",
            "验证 NEXT_STAGE 生命周期路径边。",
            ["NEXT_STAGE"],
        ),
        _benchmark_row(
            "mp_bench_graph_path_002",
            "graph",
            "graph_lifecycle_path",
            "列出项目的相邻生命周期阶段顺序关系。",
            ["kg_nodes", "kg_edges"],
            "graph",
            "验证阶段节点之间的顺序边。",
            ["NEXT_STAGE"],
        ),
        _benchmark_row(
            "mp_bench_graph_path_003",
            "graph",
            "graph_lifecycle_path",
            "找出包含用地预审到规划选址路径的重大项目。",
            ["kg_nodes", "kg_edges"],
            "graph",
            "验证 HAS_PRE_REVIEW、HAS_SITE_SELECTION 和 NEXT_STAGE 组合路径。",
            ["HAS_PRE_REVIEW", "HAS_SITE_SELECTION", "NEXT_STAGE"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_pre_no_conv_001",
            "hybrid",
            "hybrid_pre_review_without_conversion",
            "找出已有用地预审记录但没有农转用和征收记录的重大项目。",
            ["mp_project_list", "mp_pre_review", "mp_conversion_expropriation", "kg_edges"],
            "semantic_graph_sql",
            "验证预审阶段 SQL 存在性和转换征收图谱关系缺口。",
            ["HAS_PRE_REVIEW", "HAS_CONVERSION"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_pre_no_conv_002",
            "hybrid",
            "hybrid_pre_review_without_conversion",
            "列出预审已办结但转换征收阶段缺失的项目名称。",
            ["mp_project_list", "mp_pre_review", "mp_conversion_expropriation", "kg_edges"],
            "semantic_graph_sql",
            "验证阶段状态过滤和缺失关系判断。",
            ["HAS_PRE_REVIEW", "HAS_CONVERSION"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_pre_no_conv_003",
            "hybrid",
            "hybrid_pre_review_without_conversion",
            "按城市统计有用地预审但无农转用征收记录的重大项目数量。",
            ["mp_project_list", "mp_pre_review", "mp_conversion_expropriation", "kg_edges"],
            "semantic_graph_sql",
            "验证城市聚合、SQL 反连接和图谱阶段证据。",
            ["HAS_PRE_REVIEW", "HAS_CONVERSION"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_supply_no_ver_001",
            "hybrid",
            "hybrid_supply_without_verification",
            "找出已有土地供应记录但没有规划核实记录的重大项目。",
            ["mp_project_list", "mp_land_supply", "mp_verification", "kg_edges"],
            "semantic_graph_sql",
            "验证供地阶段存在和核实阶段缺失的混合判断。",
            ["HAS_LAND_SUPPLY", "HAS_VERIFICATION"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_supply_no_ver_002",
            "hybrid",
            "hybrid_supply_without_verification",
            "列出供地面积大于100亩但尚未规划核实的项目名称。",
            ["mp_project_list", "mp_land_supply", "mp_verification", "kg_edges"],
            "semantic_graph_sql",
            "验证供地面积过滤和核实阶段缺口。",
            ["HAS_LAND_SUPPLY", "HAS_VERIFICATION"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_supply_no_ver_003",
            "hybrid",
            "hybrid_supply_without_verification",
            "按项目类型统计已供地但未完成规划核实的重大项目数量。",
            ["mp_project_list", "mp_land_supply", "mp_verification", "kg_edges"],
            "semantic_graph_sql",
            "验证供地、核实和项目类型维度的混合聚合。",
            ["HAS_LAND_SUPPLY", "HAS_VERIFICATION"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_spatial_001",
            "hybrid",
            "hybrid_spatial_overlay",
            "列出与地块存在空间叠加关系的重大项目名称、叠加比例和叠加面积。",
            ["mp_project_list", "mp_spatial_overlap", "mp_relation_confidence", "mp_parcel"],
            "semantic_graph_sql",
            "验证 SPATIALLY_OVERLAPS 关系和叠加结果表。",
            ["SPATIALLY_OVERLAPS"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_spatial_002",
            "hybrid",
            "hybrid_spatial_overlay",
            "找出空间叠加比例大于0.5的项目和地块。",
            ["mp_project_list", "mp_spatial_overlap", "mp_relation_confidence", "mp_parcel"],
            "semantic_graph_sql",
            "验证空间叠加比例过滤和关系证据。",
            ["SPATIALLY_OVERLAPS"],
        ),
        _benchmark_row(
            "mp_bench_hybrid_spatial_003",
            "hybrid",
            "hybrid_spatial_overlay",
            "按城市汇总重大项目与地块的空间叠加面积。",
            ["mp_project_list", "mp_spatial_overlap", "mp_relation_confidence", "mp_parcel"],
            "semantic_graph_sql",
            "验证空间叠加面积、城市维度和混合路由。",
            ["SPATIALLY_OVERLAPS"],
        ),
        _benchmark_row(
            "mp_bench_fuzzy_001",
            "hybrid",
            "fuzzy_match",
            "列出通过项目名称模糊匹配关联到地块的重大项目和匹配置信度。",
            ["mp_project_list", "mp_relation_confidence", "mp_parcel", "kg_edges"],
            "semantic_graph_sql",
            "验证 FUZZY_PROJECT_PARCEL_MATCH 关系。",
            ["FUZZY_PROJECT_PARCEL_MATCH"],
        ),
        _benchmark_row(
            "mp_bench_fuzzy_002",
            "hybrid",
            "fuzzy_match",
            "找出模糊匹配置信度大于0.8的项目地块关联。",
            ["mp_project_list", "mp_relation_confidence", "mp_parcel", "kg_edges"],
            "semantic_graph_sql",
            "验证 match_method=fuzzy_name 和置信度过滤。",
            ["FUZZY_PROJECT_PARCEL_MATCH"],
        ),
        _benchmark_row(
            "mp_bench_fuzzy_003",
            "hybrid",
            "fuzzy_match",
            "按城市统计通过模糊名称匹配得到地块关联的重大项目数量。",
            ["mp_project_list", "mp_relation_confidence", "mp_parcel", "kg_edges"],
            "semantic_graph_sql",
            "验证模糊匹配关系和城市聚合。",
            ["FUZZY_PROJECT_PARCEL_MATCH"],
        ),
        _benchmark_row(
            "mp_bench_farmland_001",
            "hybrid",
            "farmland_occupation",
            "列出占用耕地且关系置信度大于0.9的重大项目名称和地块面积。",
            ["mp_project_list", "mp_relation_confidence", "mp_parcel"],
            "semantic_graph_sql",
            "验证 OCCUPIES_PARCEL 关系到 mp_parcel 的混合接地。",
            ["OCCUPIES_PARCEL"],
        ),
        _benchmark_row(
            "mp_bench_farmland_002",
            "hybrid",
            "farmland_occupation",
            "统计各城市占用耕地的重大项目数量。",
            ["mp_project_list", "mp_relation_confidence", "mp_parcel"],
            "semantic_graph_sql",
            "验证地类过滤、项目地块关系和城市聚合。",
            ["OCCUPIES_PARCEL"],
        ),
        _benchmark_row(
            "mp_bench_farmland_003",
            "hybrid",
            "farmland_occupation",
            "汇总每类项目占用耕地的地块面积。",
            ["mp_project_list", "mp_relation_confidence", "mp_parcel"],
            "semantic_graph_sql",
            "验证项目类型维度、耕地过滤和占地面积聚合。",
            ["OCCUPIES_PARCEL"],
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic major-project KG and NL2SQL artifacts.")
    parser.add_argument("--profile", default="small_dev")
    parser.add_argument("--project-count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260604)
    parser.add_argument("--output-dir", type=Path, default=Path("data_agent/synthetic/major_projects"))
    args = parser.parse_args(argv)

    config = GenerationConfig(
        profile=args.profile,
        project_count=args.project_count,
        seed=args.seed,
        output_dir=args.output_dir,
    )
    generator = SyntheticMajorProjectGenerator(config)
    bundle = generator.build()
    written_paths = generator.write_all(bundle)
    print(
        json.dumps(
            {
                "status": "success",
                "profile": config.profile,
                "project_count": config.project_count,
                "seed": config.seed,
                "written_paths": [str(path) for path in written_paths],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
