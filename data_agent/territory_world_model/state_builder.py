from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

try:
    import geopandas as gpd
except Exception:  # pragma: no cover - geospatial deps are optional in some runtimes
    gpd = None  # type: ignore[assignment]

from shapely.geometry.base import BaseGeometry

from .models import (
    StateBuildResult,
    TwmLayerBinding,
    TwmProject,
    TwmRelationSpec,
    TwmStateObject,
    TwmStateRelation,
    TwmStateVersion,
    jsonable,
    now_utc_iso,
)
from .semantic_loader import load_semantic_bundle
from .utils import compact_text, read_csv, read_json, safe_float, safe_int, truthy


DEFAULT_AUXILIARY_TABLES = {
    "approval_records.csv": {
        "role": "approval_records",
        "canonical_role": "approval_record",
        "object_type": "approval_record",
        "code_fields": ("approval_id", "record_id", "id", "AJBH", "approval_no", "approval_code"),
    },
    "enforcement_events.csv": {
        "role": "enforcement_events",
        "canonical_role": "enforcement_event",
        "object_type": "enforcement_event",
        "code_fields": ("event_id", "record_id", "id", "ENF_ID", "enforcement_id"),
    },
    "multimodal_evidence_index.csv": {
        "role": "multimodal_evidence_index",
        "canonical_role": "multimodal_evidence_index",
        "object_type": "multimodal_evidence_index",
        "code_fields": ("evidence_id", "id", "EVIDENCE_ID"),
    },
    "rule_evaluation.csv": {
        "role": "rule_evaluation",
        "canonical_role": "rule_evaluation",
        "object_type": "rule_evaluation",
        "code_fields": ("rule_eval_id", "id", "RULE_EVAL_ID"),
    },
    "review_tasks.csv": {
        "role": "review_tasks",
        "canonical_role": "review_task",
        "object_type": "review_task",
        "code_fields": ("review_task_id", "id", "task_id"),
    },
}


DEFAULT_RELATION_SPECS: list[TwmRelationSpec] = [
    TwmRelationSpec(
        relation_type="project_overlaps_parcel",
        subject_roles=["project"],
        target_roles=["parcel_current", "parcel"],
        predicate="intersects",
        twm_usage="state_builder_project_parcel_impact",
        objective_id="farmland_loss_m2",
        rule_id="TWM-PARCEL-001",
        evidence_type="spatial_overlay",
        severity="medium",
        review_policy="review_required",
        min_overlap_area_m2=1.0,
    ),
    TwmRelationSpec(
        relation_type="project_overlaps_permanent_basic_farmland",
        subject_roles=["project"],
        target_roles=["pbf"],
        predicate="intersects",
        twm_usage="hard_constraint_pbf_overlap",
        objective_id="pbf_overlap_m2",
        rule_id="TWM-FARM-001",
        evidence_type="spatial_overlay",
        severity="high",
        review_policy="review_required",
        min_overlap_area_m2=1.0,
    ),
    TwmRelationSpec(
        relation_type="project_overlaps_ecological_redline",
        subject_roles=["project"],
        target_roles=["eco_redline"],
        predicate="intersects",
        twm_usage="hard_constraint_eco_overlap",
        objective_id="eco_overlap_m2",
        rule_id="TWM-ECO-001",
        evidence_type="spatial_overlay",
        severity="critical",
        review_policy="always_review",
        min_overlap_area_m2=1.0,
    ),
    TwmRelationSpec(
        relation_type="project_overlaps_planning_zone",
        subject_roles=["project"],
        target_roles=["planning_zone"],
        predicate="intersects",
        twm_usage="planning_consistency_assessment",
        objective_id="planning_conflict_m2",
        rule_id="TWM-PLAN-001",
        evidence_type="spatial_overlay",
        severity="medium",
        review_policy="review_required",
        min_overlap_area_m2=1.0,
    ),
    TwmRelationSpec(
        relation_type="project_overlaps_urban_development_boundary",
        subject_roles=["project"],
        target_roles=["urban_boundary"],
        predicate="intersects",
        twm_usage="urban_boundary_consistency",
        objective_id="planning_conflict_m2",
        rule_id="TWM-URBAN-001",
        evidence_type="spatial_overlay",
        severity="medium",
        review_policy="review_required",
        min_overlap_area_m2=1.0,
    ),
    TwmRelationSpec(
        relation_type="project_observed_by_remote_sensing_tile",
        subject_roles=["project"],
        target_roles=["remote_sensing_evidence", "remote_sensing_tile"],
        predicate="intersects",
        twm_usage="multimodal_observation_evidence",
        objective_id="review_load_count",
        rule_id="TWM-EVD-001",
        evidence_type="remote_sensing_coverage",
        severity="medium",
        review_policy="review_required",
        min_overlap_area_m2=1.0,
    ),
    TwmRelationSpec(
        relation_type="annual_change_of_parcel",
        subject_roles=["parcel_current", "parcel"],
        target_roles=["parcel_current", "parcel"],
        predicate="identifier_link",
        twm_usage="dynamic_state_transition",
        objective_id="farmland_gain_m2",
        rule_id=None,
        evidence_type="identifier_link",
        severity="medium",
        review_policy="review_required",
    ),
    TwmRelationSpec(
        relation_type="project_within_admin_unit",
        subject_roles=["project", "parcel_current", "parcel"],
        target_roles=["admin_unit"],
        predicate="within",
        twm_usage="regional_context",
        objective_id="admin_fairness_cv",
        rule_id=None,
        evidence_type="spatial_overlay",
        severity="info",
        review_policy="auto_pass",
        min_overlap_area_m2=1.0,
    ),
]


def load_state_source(source_path: str | Path) -> dict[str, Any]:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"state source not found: {path}")
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return {
            "kind": "table",
            "path": str(path),
            "records": read_csv(path),
        }
    if gpd is None:
        raise RuntimeError("geopandas is required to load geospatial sources")
    gdf = gpd.read_file(path)
    return {
        "kind": "geospatial",
        "path": str(path),
        "crs": str(gdf.crs) if gdf.crs else "",
        "records": gdf,
    }


class StateBuilder:
    def __init__(self, *, metric_crs: str | None = None, max_features_per_layer: int | None = None):
        self.metric_crs = metric_crs
        self.max_features_per_layer = max_features_per_layer

    def build_from_bundle(
        self,
        bundle_dir: str | Path,
        *,
        project: TwmProject | None = None,
        label: str | None = None,
        state_time: str | None = None,
        rule_set_id: str | None = None,
        include_auxiliary_tables: bool = True,
    ) -> StateBuildResult:
        bundle = load_semantic_bundle(bundle_dir)
        project = project or self._default_project(bundle)
        bindings = list(bundle.layer_bindings)
        contract = self._load_contract(bundle)
        if not bindings and isinstance(contract.get("role_bindings"), list):
            bindings = [
                self._binding_from_contract_row(row, bundle.root_dir)
                for row in contract.get("role_bindings") or []
                if isinstance(row, dict)
            ]
        return self.build_from_bindings(
            project,
            bindings,
            bundle_root=bundle.root_dir,
            bundle_manifest=bundle.manifest,
            bundle_contract=contract,
            bundle_state_input=self._load_state_input(bundle),
            bundle_warnings=list(bundle.warnings),
            label=label,
            state_time=state_time,
            rule_set_id=rule_set_id,
            include_auxiliary_tables=include_auxiliary_tables,
        )

    def build_from_bindings(
        self,
        project: TwmProject,
        layer_bindings: Iterable[TwmLayerBinding],
        *,
        bundle_root: str | Path | None = None,
        bundle_manifest: dict[str, Any] | None = None,
        bundle_contract: dict[str, Any] | None = None,
        bundle_state_input: dict[str, Any] | None = None,
        bundle_warnings: list[str] | None = None,
        label: str | None = None,
        state_time: str | None = None,
        rule_set_id: str | None = None,
        include_auxiliary_tables: bool = True,
    ) -> StateBuildResult:
        bundle_root = Path(bundle_root) if bundle_root is not None else None
        layer_bindings = list(layer_bindings)
        warnings: list[str] = list(bundle_warnings or [])
        manifest = bundle_manifest or {}
        contract = bundle_contract or {}
        state_input = bundle_state_input or {}

        state_version = TwmStateVersion(
            project_id=project.id,
            state_time=state_time or now_utc_iso(),
            label=label or compact_text(manifest.get("product_id") or project.name or "twm_state"),
            source_manifest={
                "bundle_dir": str(bundle_root) if bundle_root else "",
                "semantic_product": jsonable(manifest),
                "state_input_contract": jsonable(contract),
                "state_input": jsonable(state_input),
            },
            rule_set_id=rule_set_id,
            created_by=project.owner_username or "",
        )

        objects, object_records = self._build_objects_from_bindings(
            state_version=state_version,
            layer_bindings=layer_bindings,
            bundle_root=bundle_root,
        )
        if include_auxiliary_tables and bundle_root is not None:
            aux_objects, aux_notes = self._build_auxiliary_objects(
                state_version=state_version,
                bundle_root=bundle_root,
            )
            objects.extend(aux_objects)
            warnings.extend(aux_notes)

        metric_crs = self._select_metric_crs(object_records)
        metric_geoms = self._metric_geometries(object_records, metric_crs)
        relations, relation_counts = self._build_relations(objects, object_records, metric_geoms)

        object_counts_by_role = Counter(obj.canonical_role or obj.source_role or obj.object_type for obj in objects)
        relation_counts_by_type = Counter(rel.relation_type or rel.predicate for rel in relations)
        quality_summary = self._build_quality_summary(
            objects=objects,
            layer_bindings=layer_bindings,
            bundle_manifest=manifest,
            bundle_contract=contract,
            bundle_state_input=state_input,
            bundle_warnings=warnings,
            metric_crs=metric_crs,
            relation_counts=relation_counts_by_type,
        )
        hierarchy_tokens = {
            "metric_crs": metric_crs,
            "source_layer_roles": [binding.role for binding in layer_bindings],
            "object_counts_by_role": dict(object_counts_by_role),
            "auxiliary_object_count": sum(
                1 for obj in objects if obj.object_type in {"approval_record", "enforcement_event", "multimodal_evidence_index", "rule_evaluation", "review_task"}
            ),
        }
        state_version.object_count = len(objects)
        state_version.relation_count = len(relations)
        state_version.build_status = "ready"
        state_version.quality_summary = quality_summary
        state_version.summary = {
            "label": state_version.label,
            "metric_crs": metric_crs,
            "object_counts_by_role": dict(object_counts_by_role),
            "relation_counts_by_type": dict(relation_counts_by_type),
        }
        state_version.build_log = {
            "layer_binding_count": len(layer_bindings),
            "auxiliary_tables_enabled": include_auxiliary_tables,
            "state_input_role_count": len(state_input.get("object_roles") or []),
            "state_input_semantic_relation_count": (state_input.get("state_builder_inputs") or {}).get("semantic_relation_count", 0),
        }

        return StateBuildResult(
            project=project,
            state_version=state_version,
            objects=objects,
            relations=relations,
            object_counts_by_role=dict(object_counts_by_role),
            relation_counts_by_type=dict(relation_counts_by_type),
            hierarchy_tokens=hierarchy_tokens,
            quality_summary=quality_summary,
            warnings=warnings,
            relation_specs=list(DEFAULT_RELATION_SPECS),
        )

    def _default_project(self, bundle) -> TwmProject:
        manifest = bundle.manifest or {}
        return TwmProject(
            name=compact_text(manifest.get("product_id") or bundle.root_dir.name),
            description=compact_text(manifest.get("product_type") or "Territorial world model state bundle"),
            region_code=compact_text((manifest.get("business_output") or {}).get("region_code")),
            business_scenario="planning_supervision",
            owner_username="",
            status="draft",
            metadata={
                "bundle_dir": str(bundle.root_dir),
                "manifest_path": str(bundle.manifest_path) if bundle.manifest_path else "",
                "contract_path": str(bundle.contract_path) if bundle.contract_path else "",
                "state_input_path": str(bundle.state_input_path) if bundle.state_input_path else "",
                "source_summary": bundle.source_summary,
            },
        )

    def _load_contract(self, bundle) -> dict[str, Any]:
        if bundle.contract_path and Path(bundle.contract_path).exists():
            try:
                return read_json(bundle.contract_path)
            except Exception:
                return {}
        return {}

    def _load_state_input(self, bundle) -> dict[str, Any]:
        if bundle.state_input_path and Path(bundle.state_input_path).exists():
            try:
                return read_json(bundle.state_input_path)
            except Exception:
                return {}
        if bundle.contract_path and Path(bundle.contract_path).name == "twm_state_input.json":
            try:
                return read_json(bundle.contract_path)
            except Exception:
                return {}
        return {}

    def _binding_from_contract_row(self, row: dict[str, Any], root_dir: Path) -> TwmLayerBinding:
        source_path = compact_text(row.get("source_path"))
        if source_path and not Path(source_path).is_absolute():
            candidate = root_dir / source_path
            if candidate.exists():
                source_path = str(candidate)
        return TwmLayerBinding(
            role=compact_text(row.get("role") or row.get("semantic_domain")),
            canonical_role=compact_text(row.get("standard_role") or row.get("role") or row.get("semantic_domain")),
            object_type=compact_text(row.get("object_type") or "feature"),
            layer_alias=compact_text(row.get("role_alias_zh") or row.get("alias_zh") or row.get("role")),
            source_path=source_path,
            semantic_product_path=str(root_dir),
            asset_id=safe_int(row.get("asset_id"), None) if row.get("asset_id") not in (None, "") else None,
            time_label=compact_text(row.get("time_label")),
            valid_from=compact_text(row.get("valid_from")) or None,
            valid_to=compact_text(row.get("valid_to")) or None,
            field_mapping=dict(row.get("twm_binding") or row.get("field_mapping") or {}),
            quality_snapshot={"quality_score": safe_float(row.get("quality_score"), None)} if row.get("quality_score") not in (None, "") else {},
            metadata={
                "business_role_zh": compact_text(row.get("business_role_zh")),
                "semantic_readiness": compact_text(row.get("semantic_readiness")),
            },
            synthetic=truthy(row.get("synthetic")),
            not_for_production=truthy(row.get("not_for_production")),
        )

    def _build_objects_from_bindings(
        self,
        *,
        state_version: TwmStateVersion,
        layer_bindings: list[TwmLayerBinding],
        bundle_root: Path | None,
    ) -> tuple[list[TwmStateObject], dict[str, dict[str, Any]]]:
        objects: list[TwmStateObject] = []
        record_lookup: dict[str, dict[str, Any]] = {}
        for binding in layer_bindings:
            source_path = self._resolve_source_path(binding, bundle_root)
            if not source_path.exists():
                record_lookup[binding.id] = {
                    "binding": binding,
                    "path": str(source_path),
                    "records": [],
                    "metric_crs": None,
                    "kind": "missing",
                }
                continue

            suffix = source_path.suffix.lower()
            if suffix in {".csv", ".tsv"}:
                records = read_csv(source_path)
                self._append_table_objects(objects, state_version, binding, source_path, records)
                record_lookup[binding.id] = {
                    "binding": binding,
                    "path": str(source_path),
                    "records": records,
                    "metric_crs": None,
                    "kind": "table",
                }
                continue

            if suffix in {".json", ".jsonl"}:
                record_lookup[binding.id] = {
                    "binding": binding,
                    "path": str(source_path),
                    "records": [],
                    "metric_crs": None,
                    "kind": "metadata",
                }
                continue

            if gpd is None:
                raise RuntimeError("geopandas is required to read geospatial state inputs")
            gdf = gpd.read_file(source_path)
            if len(gdf) == 0:
                record_lookup[binding.id] = {
                    "binding": binding,
                    "path": str(source_path),
                    "records": [],
                    "metric_crs": None,
                    "kind": "geospatial",
                }
                continue

            if self.max_features_per_layer is not None and len(gdf) > self.max_features_per_layer:
                gdf = gdf.head(self.max_features_per_layer).copy()

            gdf = self._ensure_4326(gdf)
            metric_crs = self.metric_crs or self._estimate_metric_crs(gdf)
            metric_gdf = gdf.to_crs(metric_crs) if metric_crs else gdf
            layer_records: list[dict[str, Any]] = []
            for idx, row in gdf.iterrows():
                row_dict = self._row_to_dict(row)
                geom = row.geometry
                metric_geom = metric_gdf.geometry.iloc[idx]
                object_code = self._object_code(binding, row_dict, idx)
                source_feature_id = self._source_feature_id(binding, row_dict, idx)
                attrs = self._object_attributes(binding, row_dict, source_path, idx)
                obj = TwmStateObject(
                    state_version_id=state_version.id,
                    object_type=binding.object_type or binding.canonical_role or "feature",
                    object_code=object_code,
                    source_role=binding.role or binding.canonical_role,
                    source_asset_id=binding.asset_id,
                    source_feature_id=source_feature_id,
                    source_path=str(source_path),
                    canonical_role=binding.canonical_role or binding.role or "feature",
                    attributes=attrs,
                    semantic_tags=self._semantic_tags(binding, row_dict),
                    quality_score=self._quality_score(binding, row_dict),
                    synthetic=self._row_synthetic(binding, row_dict),
                    not_for_production=self._row_not_for_production(binding, row_dict),
                    qa_use_for_rules=self._row_qa_use_for_rules(row_dict),
                    geometry_crs="EPSG:4326",
                    geom=geom,
                    bbox=list(geom.bounds) if geom is not None else None,
                )
                objects.append(obj)
                layer_records.append(
                    {
                        "object_id": obj.id,
                        "object_code": obj.object_code,
                        "object_type": obj.object_type,
                        "source_feature_id": obj.source_feature_id,
                        "geom_metric": metric_geom,
                        "attributes": attrs,
                        "binding": binding,
                        "source_path": str(source_path),
                    }
                )
            record_lookup[binding.id] = {
                "binding": binding,
                "path": str(source_path),
                "records": layer_records,
                "metric_crs": metric_crs,
                "kind": "geospatial",
            }
        return objects, record_lookup

    def _append_table_objects(
        self,
        objects: list[TwmStateObject],
        state_version: TwmStateVersion,
        binding: TwmLayerBinding,
        source_path: Path,
        records: list[dict[str, Any]],
    ) -> None:
        for idx, row in enumerate(records):
            row_dict = dict(row)
            object_code = self._object_code(binding, row_dict, idx)
            attrs = self._object_attributes(binding, row_dict, source_path, idx)
            obj = TwmStateObject(
                state_version_id=state_version.id,
                object_type=binding.object_type or binding.canonical_role or "feature",
                object_code=object_code,
                source_role=binding.role or binding.canonical_role,
                source_asset_id=binding.asset_id,
                source_feature_id=self._source_feature_id(binding, row_dict, idx),
                source_path=str(source_path),
                canonical_role=binding.canonical_role or binding.role or "feature",
                attributes=attrs,
                semantic_tags=self._semantic_tags(binding, row_dict),
                quality_score=self._quality_score(binding, row_dict),
                synthetic=self._row_synthetic(binding, row_dict),
                not_for_production=self._row_not_for_production(binding, row_dict),
                qa_use_for_rules=self._row_qa_use_for_rules(row_dict),
                geometry_crs="EPSG:4326",
                geom=None,
                bbox=None,
            )
            objects.append(obj)

    def _build_auxiliary_objects(
        self,
        *,
        state_version: TwmStateVersion,
        bundle_root: Path,
    ) -> tuple[list[TwmStateObject], list[str]]:
        objects: list[TwmStateObject] = []
        warnings: list[str] = []
        tables_dirs = []
        for candidate in (bundle_root / "tables", bundle_root.parent / "tables"):
            if candidate.exists() and candidate not in tables_dirs:
                tables_dirs.append(candidate)
        if not tables_dirs:
            return objects, warnings

        for table_name, spec in DEFAULT_AUXILIARY_TABLES.items():
            path = next((candidate / table_name for candidate in tables_dirs if (candidate / table_name).exists()), None)
            if path is None:
                continue
            try:
                rows = read_csv(path)
            except Exception as exc:
                warnings.append(f"failed to load auxiliary table {table_name}: {exc}")
                continue

            for idx, row in enumerate(rows):
                row_dict = dict(row)
                obj = TwmStateObject(
                    state_version_id=state_version.id,
                    object_type=spec["object_type"],
                    object_code=self._object_code_from_fields(row_dict, spec["code_fields"], fallback=f"{path.stem}:{idx}"),
                    source_role=spec["role"],
                    source_feature_id=self._source_feature_id_from_fields(row_dict, spec["code_fields"], fallback=f"{path.stem}:{idx}"),
                    source_path=str(path),
                    canonical_role=spec["canonical_role"],
                    attributes=row_dict,
                    semantic_tags=[spec["role"], spec["canonical_role"], spec["object_type"]],
                    quality_score=safe_float(row_dict.get("confidence"), None),
                    synthetic=truthy(row_dict.get("synthetic")),
                    not_for_production=truthy(row_dict.get("not_for_production")),
                    qa_use_for_rules=True,
                    geometry_crs="EPSG:4326",
                    geom=None,
                    bbox=None,
                )
                objects.append(obj)
        return objects, warnings

    def _build_relations(
        self,
        objects: list[TwmStateObject],
        object_records: dict[str, dict[str, Any]],
        metric_geoms: dict[str, BaseGeometry | None],
    ) -> tuple[list[TwmStateRelation], dict[str, int]]:
        relations: list[TwmStateRelation] = []
        relation_counts: Counter[str] = Counter()

        grouped_objects = self._group_objects(objects)
        for spec in DEFAULT_RELATION_SPECS:
            if spec.predicate == "identifier_link":
                built = self._build_identifier_relations(objects, spec)
            else:
                built = self._build_spatial_relations(objects, grouped_objects, metric_geoms, spec)
            relations.extend(built)
            relation_counts.update(rel.relation_type or rel.predicate for rel in built)

        return relations, dict(relation_counts)

    def _build_identifier_relations(self, objects: list[TwmStateObject], spec: TwmRelationSpec) -> list[TwmStateRelation]:
        relations: list[TwmStateRelation] = []
        subjects = [obj for obj in objects if self._role_matches(obj, spec.subject_roles)]
        targets = [obj for obj in objects if self._role_matches(obj, spec.target_roles)]
        target_index: dict[str, TwmStateObject] = {}
        for target in targets:
            target_index[target.object_code] = target
            target_index[target.source_feature_id or ""] = target

        for subject in subjects:
            subject_key_candidates = [
                compact_text(subject.object_code),
                compact_text(subject.source_feature_id),
                compact_text(subject.attributes.get("object_id")),
                compact_text(subject.attributes.get("BSM")),
                compact_text(subject.attributes.get("bsm_norm")),
            ]
            matched_target = None
            for key in subject_key_candidates:
                if key and key in target_index:
                    matched_target = target_index[key]
                    break
            if matched_target is None:
                continue

            evidence = {
                "binding_type": "identifier_link",
                "source_subject_role": subject.source_role,
                "source_target_role": matched_target.source_role,
                "matched_key": next((key for key in subject_key_candidates if key in target_index), ""),
            }
            relations.append(
                self._make_relation(
                    spec=spec,
                    subject=subject,
                    target=matched_target,
                    metrics={
                        "match_confidence": 1.0,
                        "overlap_area_m2": 0.0,
                        "overlap_ratio_left": 0.0,
                        "overlap_ratio_right": 0.0,
                        "distance_m": 0.0,
                    },
                    evidence=evidence,
                    confidence=1.0,
                )
            )
        return relations

    def _build_spatial_relations(
        self,
        objects: list[TwmStateObject],
        grouped_objects: dict[str, list[TwmStateObject]],
        metric_geoms: dict[str, BaseGeometry | None],
        spec: TwmRelationSpec,
    ) -> list[TwmStateRelation]:
        relations: list[TwmStateRelation] = []
        subject_objects = [obj for obj in objects if self._role_matches(obj, spec.subject_roles)]
        target_objects = [obj for obj in objects if self._role_matches(obj, spec.target_roles)]

        if not subject_objects or not target_objects:
            return relations

        for subject in subject_objects:
            subject_geom = metric_geoms.get(subject.id)
            if subject_geom is None or subject_geom.is_empty:
                continue
            subject_area = max(subject_geom.area, 1e-9)
            best_relation: TwmStateRelation | None = None
            for target in target_objects:
                target_geom = metric_geoms.get(target.id)
                if target_geom is None or target_geom.is_empty:
                    continue

                inter = subject_geom.intersection(target_geom)
                overlap_area = float(inter.area) if inter and not inter.is_empty else 0.0
                distance_m = float(subject_geom.distance(target_geom))
                if spec.predicate == "intersects" and overlap_area <= 0:
                    continue
                if spec.predicate == "within" and not subject_geom.within(target_geom):
                    continue
                if spec.predicate == "contains" and not subject_geom.contains(target_geom):
                    continue
                if spec.predicate == "distance_lt":
                    if spec.max_distance_m is None or distance_m >= spec.max_distance_m:
                        continue
                if spec.predicate == "overlap_area_gt":
                    if overlap_area <= max(spec.min_overlap_area_m2, 0.0):
                        continue

                target_area = max(target_geom.area, 1e-9)
                overlap_ratio_left = overlap_area / subject_area
                overlap_ratio_right = overlap_area / target_area
                metrics = {
                    "overlap_area_m2": round(overlap_area, 6),
                    "overlap_ratio_left": round(overlap_ratio_left, 6),
                    "overlap_ratio_right": round(overlap_ratio_right, 6),
                    "distance_m": round(distance_m, 6),
                    "subject_area_m2": round(subject_area, 6),
                    "target_area_m2": round(target_area, 6),
                }
                evidence = {
                    "binding_type": "spatial_overlay",
                    "metric_crs": self.metric_crs or "",
                    "subject_role": subject.source_role,
                    "target_role": target.source_role,
                    "subject_object_code": subject.object_code,
                    "target_object_code": target.object_code,
                }
                relation = self._make_relation(
                    spec=spec,
                    subject=subject,
                    target=target,
                    metrics=metrics,
                    evidence=evidence,
                    confidence=self._relation_confidence(subject, target, overlap_area, overlap_ratio_left, overlap_ratio_right),
                )
                if best_relation is None or relation.metrics.get("overlap_area_m2", 0.0) > best_relation.metrics.get("overlap_area_m2", 0.0):
                    best_relation = relation
                if spec.relation_type in {"project_overlaps_parcel", "project_overlaps_permanent_basic_farmland", "project_overlaps_ecological_redline", "project_overlaps_urban_development_boundary"}:
                    relations.append(relation)
                elif spec.relation_type == "project_overlaps_planning_zone":
                    relations.append(relation)
                elif spec.relation_type == "project_observed_by_remote_sensing_tile":
                    relations.append(relation)
                elif spec.relation_type == "project_within_admin_unit":
                    relations.append(relation)
                else:
                    relations.append(relation)

            if spec.relation_type == "project_overlaps_planning_zone" and best_relation is not None:
                # Keep only the dominant planning-zone relation for planning consistency logic.
                relations.append(
                    self._decorate_dominant_zone(best_relation, subject, target_objects, metric_geoms, spec)
                )
        return self._dedupe_relations(relations)

    def _decorate_dominant_zone(
        self,
        relation: TwmStateRelation,
        subject: TwmStateObject,
        target_objects: list[TwmStateObject],
        metric_geoms: dict[str, BaseGeometry | None],
        spec: TwmRelationSpec,
    ) -> TwmStateRelation:
        dominant = relation
        dominant_zone = ""
        dominant_area = 0.0
        for target in target_objects:
            target_geom = metric_geoms.get(target.id)
            subject_geom = metric_geoms.get(subject.id)
            if subject_geom is None or target_geom is None or subject_geom.is_empty or target_geom.is_empty:
                continue
            area = float(subject_geom.intersection(target_geom).area)
            if area > dominant_area:
                dominant_area = area
                dominant_zone = compact_text(target.attributes.get("plan_zone_type") or target.attributes.get("zone_type") or target.object_code)
        dominant.metrics = {**dominant.metrics, "dominant_zone_type": dominant_zone, "dominant_overlap_area_m2": round(dominant_area, 6)}
        dominant.evidence = {**dominant.evidence, "dominant_zone_type": dominant_zone}
        return dominant

    def _dedupe_relations(self, relations: list[TwmStateRelation]) -> list[TwmStateRelation]:
        seen: dict[tuple[str, str, str, str], TwmStateRelation] = {}
        deduped: list[TwmStateRelation] = []
        for rel in relations:
            key = (rel.subject_object_id, rel.object_object_id, rel.relation_type, rel.predicate)
            existing = seen.get(key)
            if existing is not None:
                existing.metrics = self._merge_relation_payload(existing.metrics, rel.metrics)
                existing.evidence = self._merge_relation_payload(existing.evidence, rel.evidence)
                existing.confidence = max(existing.confidence, rel.confidence)
                continue
            seen[key] = rel
            deduped.append(rel)
        return deduped

    def _merge_relation_payload(self, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in (incoming or {}).items():
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
                continue
            current = merged.get(key)
            if isinstance(current, (int, float)) and isinstance(value, (int, float)) and value > current:
                merged[key] = value
        return merged

    def _make_relation(
        self,
        *,
        spec: TwmRelationSpec,
        subject: TwmStateObject,
        target: TwmStateObject,
        metrics: dict[str, Any],
        evidence: dict[str, Any],
        confidence: float,
    ) -> TwmStateRelation:
        return TwmStateRelation(
            state_version_id=subject.state_version_id,
            subject_object_id=subject.id,
            predicate=spec.predicate,
            object_object_id=target.id,
            relation_type=spec.relation_type,
            metrics=metrics,
            confidence=confidence,
            evidence=evidence,
            geom=None,
            source_subject_role=subject.source_role,
            source_target_role=target.source_role,
            synthetic=subject.synthetic or target.synthetic,
            not_for_production=subject.not_for_production or target.not_for_production,
        )

    def _relation_confidence(self, subject, target, overlap_area, left_ratio, right_ratio) -> float:
        base = 0.65
        if overlap_area > 0:
            base += min(0.25, (left_ratio + right_ratio) / 4.0)
        if subject.synthetic or target.synthetic:
            base -= 0.05
        return round(max(0.0, min(1.0, base)), 4)

    def _group_objects(self, objects: list[TwmStateObject]) -> dict[str, list[TwmStateObject]]:
        grouped: dict[str, list[TwmStateObject]] = defaultdict(list)
        for obj in objects:
            keys = {
                compact_text(obj.canonical_role),
                compact_text(obj.source_role),
                compact_text(obj.object_type),
            }
            for key in keys:
                if key:
                    grouped[key].append(obj)
        return grouped

    def _role_matches(self, obj: TwmStateObject, roles: Iterable[str]) -> bool:
        values = {
            compact_text(obj.canonical_role),
            compact_text(obj.source_role),
            compact_text(obj.object_type),
        }
        return bool(values.intersection({compact_text(role) for role in roles if role}))

    def _resolve_source_path(self, binding: TwmLayerBinding, bundle_root: Path | None) -> Path:
        raw = Path(binding.source_path)
        if raw.is_absolute() and raw.exists():
            return raw
        candidates = []
        if bundle_root is not None:
            candidates.append(bundle_root / raw)
            candidates.append(bundle_root.parent / raw)
            candidates.append(bundle_root.parent.parent / raw)
        candidates.append(Path.cwd() / raw)
        candidates.append(Path(raw))
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return raw

    def _ensure_4326(self, gdf):
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326", allow_override=True)
        elif gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        return gdf

    def _estimate_metric_crs(self, gdf) -> str:
        try:
            estimate = gdf.estimate_utm_crs()
            if estimate:
                return estimate.to_string()
        except Exception:
            pass
        return "EPSG:3857"

    def _select_metric_crs(self, object_records: dict[str, dict[str, Any]]) -> str:
        if self.metric_crs:
            return self.metric_crs
        for info in object_records.values():
            metric_crs = info.get("metric_crs")
            if metric_crs:
                return str(metric_crs)
        return "EPSG:3857"

    def _metric_geometries(self, object_records: dict[str, dict[str, Any]], metric_crs: str) -> dict[str, BaseGeometry | None]:
        geoms: dict[str, BaseGeometry | None] = {}
        for record in object_records.values():
            if record.get("kind") != "geospatial":
                continue
            binding = record["binding"]
            metric_records = record.get("records") or []
            if not metric_records:
                continue
            for item in metric_records:
                geom = item.get("geom_metric")
                geoms[item["object_id"]] = geom
        return geoms

    def _row_to_dict(self, row) -> dict[str, Any]:
        payload = row.to_dict() if hasattr(row, "to_dict") else dict(row)
        return {k: v for k, v in payload.items() if k != "geometry"}

    def _object_code(self, binding: TwmLayerBinding, row: dict[str, Any], idx: int) -> str:
        field_candidates = [
            binding.field_mapping.get("object_id"),
            binding.field_mapping.get("id"),
            binding.field_mapping.get("parcel_id"),
            binding.field_mapping.get("project_id"),
            binding.field_mapping.get("boundary_id"),
            binding.field_mapping.get("control_id"),
            "object_id",
            "id",
            "BSM",
            "bsm_norm",
            "project_id",
            "boundary_id",
            "control_id",
            "plan_zone_id",
            "redline_id",
            "tile_id",
            "approval_id",
            "event_id",
            "enforcement_id",
            "evidence_id",
            "rule_eval_id",
            "review_task_id",
        ]
        for field_name in field_candidates:
            if not field_name:
                continue
            value = row.get(field_name)
            if value not in (None, ""):
                return compact_text(value)
        return f"{compact_text(binding.role or binding.canonical_role or binding.object_type)}:{idx}"

    def _source_feature_id(self, binding: TwmLayerBinding, row: dict[str, Any], idx: int) -> str:
        return self._source_feature_id_from_fields(
            row,
            (
                binding.field_mapping.get("object_id"),
                binding.field_mapping.get("id"),
                "object_id",
                "id",
                "BSM",
                "project_id",
                "boundary_id",
                "control_id",
                "approval_id",
                "event_id",
                "evidence_id",
                "rule_eval_id",
                "review_task_id",
            ),
            fallback=f"{compact_text(binding.role or binding.canonical_role)}:{idx}",
        )

    def _source_feature_id_from_fields(self, row: dict[str, Any], fields: Iterable[str], fallback: str) -> str:
        for field_name in fields:
            if not field_name:
                continue
            value = row.get(field_name)
            if value not in (None, ""):
                return compact_text(value)
        return fallback

    def _object_code_from_fields(self, row: dict[str, Any], fields: Iterable[str], fallback: str) -> str:
        return self._source_feature_id_from_fields(row, fields, fallback)

    def _object_attributes(self, binding: TwmLayerBinding, row: dict[str, Any], source_path: Path, idx: int) -> dict[str, Any]:
        canonical = dict(binding.field_mapping or {})
        canonical_values = {key: row.get(field) for key, field in canonical.items() if field in row}
        attrs = {
            "role": binding.role,
            "canonical_role": binding.canonical_role,
            "object_type": binding.object_type,
            "source_path": str(source_path),
            "row_index": idx,
            "canonical_fields": canonical_values,
            "raw_fields": {k: v for k, v in row.items() if k != "geometry"},
            "qa_use_for_rules": self._row_qa_use_for_rules(row),
            "synthetic": self._row_synthetic(binding, row),
            "not_for_production": self._row_not_for_production(binding, row),
        }
        if "quality_score" not in attrs:
            attrs["quality_score"] = self._quality_score(binding, row)
        if row.get("source_dataset"):
            attrs["source_dataset"] = row.get("source_dataset")
        if row.get("synthetic_method"):
            attrs["synthetic_method"] = row.get("synthetic_method")
        if row.get("approval_status"):
            attrs["approval_status"] = row.get("approval_status")
        if row.get("project_type"):
            attrs["project_type"] = row.get("project_type")
        if row.get("plan_zone_type"):
            attrs["plan_zone_type"] = row.get("plan_zone_type")
        for key in (
            "object_id",
            "project_id",
            "parcel_id",
            "boundary_id",
            "control_id",
            "approval_id",
            "event_id",
            "evidence_id",
            "rule_eval_id",
            "review_task_id",
            "area_m2",
            "planned_area_m2",
        ):
            if key in row and row.get(key) not in (None, ""):
                attrs[key] = row.get(key)
        return attrs

    def _semantic_tags(self, binding: TwmLayerBinding, row: dict[str, Any]) -> list[str]:
        tags = [binding.role, binding.canonical_role, binding.object_type]
        if row.get("project_type"):
            tags.append(str(row.get("project_type")))
        if row.get("plan_zone_type"):
            tags.append(str(row.get("plan_zone_type")))
        if row.get("approval_status"):
            tags.append(str(row.get("approval_status")))
        if row.get("evidence_type"):
            tags.append(str(row.get("evidence_type")))
        if self._row_synthetic(binding, row):
            tags.append("synthetic")
        if self._row_not_for_production(binding, row):
            tags.append("not_for_production")
        return [tag for tag in dict.fromkeys(compact_text(tag) for tag in tags if compact_text(tag))]

    def _quality_score(self, binding: TwmLayerBinding, row: dict[str, Any]) -> float | None:
        for candidate in (
            row.get("quality_score"),
            row.get("confidence"),
            binding.quality_snapshot.get("quality_score") if binding.quality_snapshot else None,
        ):
            value = safe_float(candidate, None)
            if value is not None:
                return value
        return None

    def _row_synthetic(self, binding: TwmLayerBinding, row: dict[str, Any]) -> bool:
        return truthy(row.get("synthetic")) or binding.synthetic

    def _row_not_for_production(self, binding: TwmLayerBinding, row: dict[str, Any]) -> bool:
        return truthy(row.get("not_for_production")) or binding.not_for_production

    def _row_qa_use_for_rules(self, row: dict[str, Any]) -> bool:
        if "qa_use_for_rules" in row:
            return truthy(row.get("qa_use_for_rules"))
        return True

    def _build_quality_summary(
        self,
        *,
        objects: list[TwmStateObject],
        layer_bindings: list[TwmLayerBinding],
        bundle_manifest: dict[str, Any],
        bundle_contract: dict[str, Any],
        bundle_state_input: dict[str, Any],
        bundle_warnings: list[str],
        metric_crs: str,
        relation_counts: Counter[str],
    ) -> dict[str, Any]:
        synthetic_count = sum(1 for obj in objects if obj.synthetic)
        not_for_production_count = sum(1 for obj in objects if obj.not_for_production)
        qa_disabled_count = sum(1 for obj in objects if not obj.qa_use_for_rules)
        return {
            "source_layer_count": len(layer_bindings),
            "object_count": len(objects),
            "synthetic_object_count": synthetic_count,
            "not_for_production_object_count": not_for_production_count,
            "qa_disabled_object_count": qa_disabled_count,
            "metric_crs": metric_crs,
            "bundle_warnings": list(bundle_warnings),
            "manifest_quality_score": safe_float((bundle_manifest.get("quality") or {}).get("score"), None),
            "contract_state_builder_policy": bundle_contract.get("state_builder_policy", ""),
            "state_input_role_count": len(bundle_state_input.get("object_roles") or []),
            "state_input_relation_count": safe_int((bundle_state_input.get("state_builder_inputs") or {}).get("semantic_relation_count"), 0),
            "relation_counts_by_type": dict(relation_counts),
            "role_count_by_canonical_role": dict(Counter(obj.canonical_role for obj in objects if obj.canonical_role)),
        }


def build_state_from_bundle(
    bundle_dir: str | Path,
    *,
    project: TwmProject | None = None,
    label: str | None = None,
    state_time: str | None = None,
    rule_set_id: str | None = None,
    include_auxiliary_tables: bool = True,
) -> StateBuildResult:
    return StateBuilder().build_from_bundle(
        bundle_dir,
        project=project,
        label=label,
        state_time=state_time,
        rule_set_id=rule_set_id,
        include_auxiliary_tables=include_auxiliary_tables,
    )
