from __future__ import annotations

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
        bundle = SyntheticDataBundle()
        for idx in range(1, self.config.project_count + 1):
            project = self._project(idx)
            bundle.projects.append(project)
            self._append_project_graph(bundle, project)
            self._append_lifecycle_records(bundle, project, idx)
            self._append_parcels_and_spatial_relations(bundle, project, idx)
        return bundle

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
                "target_table": "mp_project_parcel",
                "target_id": target_id,
                "relation_type": relation_type,
                "match_method": match_method,
                "confidence": confidence,
                "evidence": self._json_properties(evidence),
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
                "properties": self._json_properties({"project_id": project["project_id"], "missing_stage": stage}),
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
                "properties": self._json_properties({"project_id": project["project_id"], "risk_type": risk_type}),
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
