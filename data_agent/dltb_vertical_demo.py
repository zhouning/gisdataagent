"""DLTB vertical demo for an air-gapped GIS Data Agent installation.

The module is intentionally file-first.  It treats the GeoParquet produced by
``OfflineIngestStore`` as the governed data product and creates a small,
deterministic semantic projection on top of it.  The projection is a control
plane manifest; feature records stay in the lake and are never copied into the
ontology store.

This is the offline/demo path used on a plain Windows host. It does not need
ArcPy or a container. The governed GeoParquet can be queried in-place and can
also be published to the bundled PostGIS service for the production-default
NL2Semantic2SQL route. Production promotion is closed unless the upstream
quality and standard-contract gates are accepted.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .offline_ingest import OfflineIngestStore, _atomic_json, _utc_now, sha256_tree


SEMANTIC_SOURCE = "land_parcel_current"
ONTOLOGY_VERSION = "2.3.0"
_SAFE_IDENTIFIER = re.compile(r"[^0-9A-Za-z_]+")

# The physical source fields are retained as-is.  These are the semantic
# properties exposed to the query layer and to the ontology binding.
FIELD_SPECS: dict[str, dict[str, Any]] = {
    "BSM": {
        "semantic_field": "feature_identifier",
        "property": "featureIdentifier",
        "domain": "LandParcel",
        "label": "图斑标识",
        "aliases": ["标识码", "图斑标识", "唯一标识", "BSM"],
    },
    "YSDM": {
        "semantic_field": "feature_code",
        "property": "featureTypeCode",
        "domain": "LandParcel",
        "label": "要素代码",
        "aliases": ["要素代码", "YSDM"],
    },
    "DLBM": {
        "semantic_field": "land_use_code",
        "property": "currentLandUseCode",
        "domain": "LandParcel",
        "label": "地类编码",
        "aliases": ["地类编码", "土地利用类型编码", "DLBM", "地类"],
    },
    "DLMC": {
        "semantic_field": "land_use_name",
        "property": "currentLandUseName",
        "domain": "LandParcel",
        "label": "地类名称",
        "aliases": ["地类名称", "土地利用类型", "DLMC"],
    },
    "QSDWDM": {
        "semantic_field": "owner_admin_code",
        "property": "administrativeDivisionCode",
        "domain": "AdministrativeUnit",
        "label": "权属单位代码",
        "aliases": ["权属单位代码", "QSDWDM"],
    },
    "QSDWMC": {
        "semantic_field": "owner_admin_name",
        "property": "administrativeDivisionName",
        "domain": "AdministrativeUnit",
        "label": "权属单位名称",
        "aliases": ["权属单位名称", "QSDWMC"],
    },
    "ZLDWDM": {
        "semantic_field": "located_admin_code",
        "property": "administrativeDivisionCode",
        "domain": "AdministrativeUnit",
        "label": "坐落单位代码",
        "aliases": ["坐落单位代码", "ZLDWDM"],
    },
    "ZLDWMC": {
        "semantic_field": "located_admin_name",
        "property": "administrativeDivisionName",
        "domain": "AdministrativeUnit",
        "label": "坐落单位名称",
        "aliases": ["坐落单位名称", "行政区", "ZLDWMC"],
    },
    "TBMJ": {
        "semantic_field": "parcel_area_sqm",
        "property": "parcelArea",
        "domain": "LandParcel",
        "label": "图斑面积",
        "unit": "m²",
        "aliases": ["图斑面积", "面积", "TBMJ", "地类面积"],
    },
}


def _json_value(value: Any) -> Any:
    """Convert pandas/numpy values to strict JSON values."""

    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _safe_name(value: str) -> str:
    name = _SAFE_IDENTIFIER.sub("_", value).strip("_") or "dltb"
    return name[:100]


def _norm_text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _column_for(mapping: dict[str, Any], canonical: str, columns: list[str]) -> str | None:
    """Resolve a standard field through the durable mapping, then aliases."""

    for item in mapping.get("field_mappings") or []:
        if str(item.get("canonical_field")) == canonical:
            candidate = str(item.get("source_field") or "")
            if candidate in columns:
                return candidate
    aliases = {canonical.casefold(), *(str(a).casefold() for a in FIELD_SPECS.get(canonical, {}).get("aliases", []))}
    for column in columns:
        if str(column).casefold() in aliases:
            return str(column)
    return None


def _geometry_area_sqm(frame):
    """Return an area series in square metres without assuming a CRS."""

    import pandas as pd

    geometry = frame.geometry
    crs = frame.crs
    if crs is None:
        return pd.Series([None] * len(frame), index=frame.index, dtype="float64")
    try:
        from pyproj import CRS

        parsed = CRS.from_user_input(crs)
        if parsed.is_geographic:
            projected_crs = frame.estimate_utm_crs()
            if projected_crs:
                return frame.to_crs(projected_crs).geometry.area
        return geometry.area
    except Exception:
        return geometry.area


def _feature_properties(row: Any, columns: list[str]) -> dict[str, Any]:
    return {column: _json_value(row[column]) for column in columns if column in row.index}


class DLTBVerticalDemo:
    """Build, register and query the DLTB semantic product."""

    def __init__(self, store: OfflineIngestStore):
        self.store = store

    def _read_materialization(self, plan_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        path = self.store.root / "materialized" / plan_id / "materialization.json"
        if not path.exists():
            raise FileNotFoundError(f"materialization not found: {plan_id}")
        materialization = json.loads(path.read_text(encoding="utf-8"))
        if materialization.get("status") != "succeeded":
            raise ValueError("semantic projection requires successful materialization")
        plan_path = self.store.root / "standardized" / plan_id / "standardization_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
        parent_run_id = plan.get("parent_run_id")
        if parent_run_id:
            try:
                parent_run = self.store.get_run(parent_run_id)
                plan["quality"] = parent_run.get("deep_quality") or {"items": parent_run.get("quality") or []}
            except (FileNotFoundError, ValueError):
                plan["quality"] = {"items": []}
        return plan, materialization

    @staticmethod
    def _select_dltb(materialization: dict[str, Any]) -> dict[str, Any]:
        candidates = []
        for output in materialization.get("outputs") or []:
            if output.get("target_kind") != "postgis_or_geoparquet":
                continue
            mapping = output.get("mapping") or {}
            if mapping.get("ea_model_candidate") == "DLTB" or str(output.get("source_layer", "")).casefold() in {
                "dltb",
                "jqdltb",
                "地类图斑",
            }:
                candidates.append(output)
        if not candidates:
            raise ValueError("no DLTB GeoParquet output found in materialization")
        succeeded = [item for item in candidates if item.get("execution_status") == "succeeded"]
        if not succeeded:
            raise ValueError("DLTB output was not materialized")
        return succeeded[0]

    @staticmethod
    def _quality_evidence(plan: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
        # The plan carries source IDs; deep quality is attached to the parent
        # scan run.  Missing evidence is deliberately treated as review.
        source_asset_id = output.get("source_asset_id")
        parent_quality = plan.get("quality") or {}
        items = parent_quality.get("items") or []
        item = next((row for row in items if row.get("asset_id") == source_asset_id and (not output.get("source_layer") or row.get("layer") == output.get("source_layer"))), None)
        if item:
            return item
        return {"status": "review", "reason": "deep_quality_evidence_not_attached"}

    def build_projection(
        self,
        plan_id: str,
        *,
        actor: str = "system",
        mode: str = "rehearsal",
        preview_limit: int = 500,
        publish_postgis: bool = False,
        postgis_table_name: str = SEMANTIC_SOURCE,
        postgis_schema: str | None = None,
        postgis_engine=None,
    ) -> dict[str, Any]:
        """Create semantic projection and deterministic DLTB metrics."""

        if mode not in {"rehearsal", "production"}:
            raise ValueError("mode must be rehearsal or production")
        plan, materialization = self._read_materialization(plan_id)
        output = self._select_dltb(materialization)
        mapping = output.get("mapping") or {}
        quality = self._quality_evidence(plan, output)
        mapping_status = mapping.get("status") or "manual_review"
        if mode == "production" and (mapping_status != "accepted" or quality.get("status") != "pass"):
            raise ValueError("production semantic registration requires accepted mapping and passed quality")

        target = Path(str(output.get("target_path"))).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(str(target))
        try:
            import geopandas as gpd
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - deployment packaging gate
            raise RuntimeError("geopandas and pandas are required for DLTB semantic projection") from exc
        frame = gpd.read_parquet(target)
        columns = [str(column) for column in frame.columns]
        geometry_name = str(frame.geometry.name) if hasattr(frame, "geometry") else "geometry"
        field_map: dict[str, str | None] = {
            canonical: _column_for(mapping, canonical, columns) for canonical in FIELD_SPECS
        }
        canonical_fields = {
            spec["semantic_field"]: {
                "source_field": field_map[canonical],
                "property": spec["property"],
                "domain": spec["domain"],
                "label": spec["label"],
                "unit": spec.get("unit"),
                "aliases": spec["aliases"],
                "required": canonical in {"DLBM", "TBMJ"},
            }
            for canonical, spec in FIELD_SPECS.items()
        }
        for canonical, source_field in field_map.items():
            semantic_field = FIELD_SPECS[canonical]["semantic_field"]
            if source_field and source_field in frame.columns:
                canonical_fields[semantic_field]["data_type"] = str(frame[source_field].dtype)
        canonical_fields["land_use_code"]["value_semantics"] = {
            "groups": {"耕地": {"prefixes": ["01"]}},
        }
        canonical_fields.update(
            {
                "geometry_area_sqm": {
                    "source_field": "_gda_geometry_area_sqm",
                    "property": "geometryArea",
                    "domain": "LandParcel",
                    "label": "几何面积（预计算）",
                    "unit": "m²",
                    "aliases": ["几何面积", "空间面积", "geometry area"],
                    "required": False,
                    "data_type": "float64",
                    "description": "已在治理阶段预计算，查询时不需要调用 ST_Area。",
                },
                "area_delta_sqm": {
                    "source_field": "_gda_area_delta_sqm",
                    "property": "areaDifference",
                    "domain": "LandParcel",
                    "label": "属性面积与几何面积差值",
                    "unit": "m²",
                    "aliases": ["面积差值", "面积差异", "属性面积与几何面积差异"],
                    "required": False,
                    "data_type": "float64",
                    "description": "TBMJ 减去预计算几何面积；可直接排序或过滤。",
                },
                "area_delta_ratio": {
                    "source_field": "_gda_area_delta_ratio",
                    "property": "areaDifferenceRatio",
                    "domain": "LandParcel",
                    "label": "属性面积与几何面积差异率",
                    "unit": "ratio",
                    "aliases": ["面积差异率", "面积偏差率", "面积误差率"],
                    "required": False,
                    "data_type": "float64",
                    "description": "面积差值绝对值除以几何面积；可直接排序或过滤。",
                },
            }
        )

        numeric_area = None
        area_column = field_map.get("TBMJ")
        if area_column:
            numeric_area = pd.to_numeric(frame[area_column], errors="coerce")
        geometry_area = _geometry_area_sqm(frame)
        frame["_gda_geometry_area_sqm"] = geometry_area
        if numeric_area is not None:
            frame["_gda_area_delta_sqm"] = numeric_area - geometry_area
            frame["_gda_area_delta_ratio"] = (
                (numeric_area - geometry_area).abs() / geometry_area.replace(0, pd.NA)
            )
        else:
            frame["_gda_area_delta_sqm"] = pd.Series(
                [None] * len(frame), index=frame.index, dtype="float64"
            )
            frame["_gda_area_delta_ratio"] = pd.Series(
                [None] * len(frame), index=frame.index, dtype="float64"
            )

        quality_checks = {
            "feature_count": int(len(frame)),
            "geometry_column": geometry_name,
            "crs": frame.crs.to_string() if frame.crs else None,
            "null_geometry_count": int(frame.geometry.isna().sum()),
            "empty_geometry_count": int(frame.geometry[~frame.geometry.isna()].is_empty.sum()),
            "invalid_geometry_count": int((~frame.geometry[~frame.geometry.isna()].is_valid).sum()),
            "missing_semantic_fields": [canonical for canonical, source in field_map.items() if source is None],
            "duplicate_feature_identifier_count": 0,
        }
        identifier = field_map.get("BSM")
        if identifier:
            quality_checks["duplicate_feature_identifier_count"] = int(frame[identifier].duplicated(keep=False).sum())
        consistency = {
            "compared": int(numeric_area.notna().sum()) if numeric_area is not None else 0,
            "mean_abs_delta_sqm": None,
            "p95_abs_delta_sqm": None,
            "large_delta_count": 0,
            "threshold_pct": 0.05,
        }
        if numeric_area is not None:
            valid = frame["_gda_area_delta_ratio"].dropna()
            if len(valid):
                consistency.update({
                    "mean_abs_delta_sqm": float(frame.loc[valid.index, "_gda_area_delta_sqm"].abs().mean()),
                    "p95_abs_delta_sqm": float(frame.loc[valid.index, "_gda_area_delta_sqm"].abs().quantile(0.95)),
                    "large_delta_count": int((valid > consistency["threshold_pct"]).sum()),
                })

        projection_quality_status = "pass"
        projection_quality_reasons: list[str] = []
        if quality_checks["missing_semantic_fields"]:
            projection_quality_reasons.append("missing_semantic_fields")
        if quality_checks["null_geometry_count"] or quality_checks["empty_geometry_count"] or quality_checks["invalid_geometry_count"]:
            projection_quality_reasons.append("geometry_validity")
        if quality_checks["duplicate_feature_identifier_count"]:
            projection_quality_reasons.append("duplicate_feature_identifier")
        if consistency["large_delta_count"]:
            projection_quality_reasons.append("geometry_area_consistency")
        if projection_quality_reasons:
            projection_quality_status = "review"
        if mode == "production" and (mapping_status != "accepted" or quality.get("status") != "pass" or projection_quality_status != "pass"):
            raise ValueError(
                "production semantic registration requires accepted mapping, passed deep quality, and passed DLTB product checks"
            )

        def summary(group_column: str | None) -> list[dict[str, Any]]:
            if not group_column or group_column not in frame.columns:
                return []
            work = frame.assign(_area=numeric_area if numeric_area is not None else geometry_area)
            grouped = work.groupby(group_column, dropna=False, as_index=False).agg(
                feature_count=(group_column, "size"),
                area_sqm=("_area", "sum"),
            )
            total = float(grouped["area_sqm"].sum()) if len(grouped) else 0.0
            grouped["area_pct"] = grouped["area_sqm"].apply(lambda value: float(value / total * 100) if total else 0.0)
            grouped = grouped.sort_values(["area_sqm", "feature_count"], ascending=False)
            return [_json_value(row) for row in grouped.to_dict(orient="records")]

        land_use_code = field_map.get("DLBM")
        land_use_name = field_map.get("DLMC")
        admin_name = field_map.get("ZLDWMC") or field_map.get("QSDWMC")
        metrics = {
            "feature_count": int(len(frame)),
            "total_area_sqm": float((numeric_area if numeric_area is not None else geometry_area).sum()),
            "by_land_use": summary(land_use_code),
            "by_admin": summary(admin_name),
            "area_consistency": consistency,
            "quality_checks": quality_checks,
            "status": projection_quality_status,
            "reasons": projection_quality_reasons,
        }
        projection_id = str(uuid.uuid4())
        product_root = self.store.root / "semantic_products" / projection_id
        product_root.mkdir(parents=True, exist_ok=True)
        query_target = product_root / "land_parcel_current.parquet"
        frame.to_parquet(query_target, index=False)
        preview_columns = [column for column in columns if column != geometry_name][:12]
        preview = frame.loc[:, preview_columns + [geometry_name]].head(max(1, min(int(preview_limit), 2000))).copy()
        try:
            if preview.crs:
                preview = preview.to_crs("EPSG:4326")
            (product_root / "dltb_preview.geojson").write_text(preview.to_json(drop_id=True), encoding="utf-8")
        except Exception:
            # A projection without a map preview is still useful for tabular
            # questions, but is marked in the manifest for operators.
            pass
        with (product_root / "dltb_metrics.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["metric", "value"])
            writer.writerow(["feature_count", metrics["feature_count"]])
            writer.writerow(["total_area_sqm", metrics["total_area_sqm"]])
            writer.writerow(["large_area_delta_count", consistency["large_delta_count"]])
        _atomic_json(product_root / "dltb_metrics.json", _json_value(metrics))
        lake_binding = {
            "engine": "lake",
            "table_name": SEMANTIC_SOURCE,
            "projection_id": projection_id,
            "projection_path": str(query_target),
            "projection_sha256": sha256_tree(query_target),
            "governed_source_path": str(target),
            "governed_source_sha256": sha256_tree(target),
            "row_count": int(len(frame)),
        }
        execution_bindings: dict[str, dict[str, Any]] = {"lake": lake_binding}
        if publish_postgis:
            from .postgis_projection_publisher import publish_geoparquet_to_postgis

            execution_bindings["postgis"] = publish_geoparquet_to_postgis(
                query_target,
                projection_id=projection_id,
                table_name=postgis_table_name,
                schema=postgis_schema
                or os.environ.get("GDA_DLTB_POSTGIS_SCHEMA", "public"),
                engine=postgis_engine,
                chunksize=int(os.environ.get("GDA_POSTGIS_PUBLISH_CHUNKSIZE", "5000")),
            )
        projection = {
            "schema": "gda.dltb-semantic-projection.v1",
            "projection_id": projection_id,
            "semantic_source": SEMANTIC_SOURCE,
            "display_name": "现状地类图斑（治理产品）",
            "description": "DLTB 标准化 GeoParquet 的语义投影；PostGIS 与数据湖执行器绑定同一治理版本。",
            "geometry_type": "Polygon",
            "srid": int(frame.crs.to_epsg()) if frame.crs and frame.crs.to_epsg() else None,
            "target_path": str(target),
            "target_sha256": lake_binding["governed_source_sha256"],
            "semantic_query_projection_path": str(query_target),
            "semantic_query_projection_sha256": lake_binding["projection_sha256"],
            "postgis_table_name": (
                execution_bindings.get("postgis", {}).get("table_name")
            ),
            "execution_bindings": execution_bindings,
            "default_execution_engine": "postgis",
            "publication_status": (
                "dual_published" if "postgis" in execution_bindings else "lake_only"
            ),
            "source_asset_id": output.get("source_asset_id"),
            "source_layer": output.get("source_layer"),
            "canonical_dataset": "DLTB",
            "ontology_version": ONTOLOGY_VERSION,
            "ontology_classes": ["LandParcel", "SpatialUnit", "LandUseType", "AdministrativeUnit"],
            "ontology_relations": ["hasLandUseState", "locatedIn", "derivedFrom"],
            "mapping_status": mapping_status,
            "quality_status": projection_quality_status,
            "mode": mode,
            "production_eligible": mode == "production" and mapping_status == "accepted" and quality.get("status") == "pass" and projection_quality_status == "pass",
            "instance_policy": "reference_only_no_raw_record_copy",
            "fields": canonical_fields,
            "metrics_path": str(product_root / "dltb_metrics.json"),
            "preview_path": str(product_root / "dltb_preview.geojson") if (product_root / "dltb_preview.geojson").exists() else None,
            "created_at": _utc_now(),
            "actor": actor,
        }
        _atomic_json(product_root / "semantic_projection.json", projection)
        catalog_path = self.store.root / "semantic_products" / "catalog.json"
        existing = []
        if catalog_path.exists():
            try:
                existing = json.loads(catalog_path.read_text(encoding="utf-8")).get("sources") or []
            except (OSError, ValueError, TypeError):
                existing = []
        existing = [item for item in existing if item.get("projection_id") != projection_id and item.get("table_name") != SEMANTIC_SOURCE]
        existing.append(projection_catalog_entry(projection))
        _atomic_json(catalog_path, {"schema": "gda.offline-semantic-catalog.v1", "sources": existing, "updated_at": _utc_now()})
        _atomic_json(product_root / "lineage.json", {
            "edges": [
                {"from": output.get("source_asset_id"), "to": str(target), "type": "raw_to_standardized", "sha256": projection["target_sha256"]},
                {"from": str(target), "to": f"semantic:{SEMANTIC_SOURCE}", "type": "standardized_to_semantic_projection", "projection_id": projection_id},
                *(
                    [{
                        "from": str(target),
                        "to": execution_bindings["postgis"]["table_name"],
                        "type": "governed_projection_to_postgis",
                        "projection_id": projection_id,
                        "row_count": execution_bindings["postgis"]["row_count"],
                    }]
                    if "postgis" in execution_bindings
                    else []
                ),
                {"from": f"semantic:{SEMANTIC_SOURCE}", "to": "ontology:gda:nr:class:LandParcel", "type": "semantic_to_ontology_reference", "ontology_version": ONTOLOGY_VERSION},
            ]
        })
        return {"status": "succeeded", "projection": projection, "metrics": metrics}

    @staticmethod
    def load_projection(path: str | Path) -> dict[str, Any]:
        candidate = Path(path).expanduser().resolve()
        if candidate.is_dir():
            candidate = candidate / "semantic_projection.json"
        if not candidate.exists():
            raise FileNotFoundError(str(candidate))
        return json.loads(candidate.read_text(encoding="utf-8"))

    @staticmethod
    def execute_semantic_ast(
        projection_path: str | Path,
        ast: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a previously validated DLTB semantic AST."""

        projection = DLTBVerticalDemo.load_projection(projection_path)
        target = Path(projection["target_path"])
        if not target.exists():
            raise FileNotFoundError(str(target))
        import geopandas as gpd
        import pandas as pd

        frame = gpd.read_parquet(target)
        fields = projection.get("fields") or {}

        def col(semantic_field: str, fallback: str) -> str | None:
            spec = fields.get(semantic_field) or {}
            physical = spec.get("source_field")
            if physical in frame.columns:
                return physical
            return fallback if fallback in frame.columns else None

        semantic_columns = {
            "feature_identifier": col("feature_identifier", "BSM"),
            "land_use_code": col("land_use_code", "DLBM"),
            "land_use_name": col("land_use_name", "DLMC"),
            "located_admin_name": col("located_admin_name", "ZLDWMC"),
            "owner_admin_name": col("owner_admin_name", "QSDWMC"),
            "parcel_area_sqm": col("parcel_area_sqm", "TBMJ"),
        }
        filtered = frame
        for item in ast.get("filters") or []:
            physical = semantic_columns.get(item["field"])
            if not physical:
                raise ValueError(
                    f"semantic field is unavailable in this projection: {item['field']}"
                )
            values = filtered[physical].astype(str)
            expected = str(item["value"])
            if item["operator"] == "eq":
                normalized_values = values.str.replace(r"\.0$", "", regex=True)
                normalized_expected = re.sub(r"\.0$", "", expected)
                mask = normalized_values.str.casefold() == normalized_expected.casefold()
            elif item["operator"] == "prefix":
                mask = values.str.startswith(expected, na=False)
            elif item["operator"] == "contains":
                mask = values.str.contains(expected, case=False, regex=False, na=False)
            else:  # validated by dltb_llm_query; kept fail-closed for direct callers
                raise ValueError(f"unsupported semantic filter operator: {item['operator']}")
            filtered = filtered[mask]

        intent = ast.get("intent")
        limit = max(1, min(int(ast.get("limit") or 100), 1000))
        code_col = semantic_columns["land_use_code"]
        name_col = semantic_columns["land_use_name"]
        area_col = semantic_columns["parcel_area_sqm"]
        id_col = semantic_columns["feature_identifier"]
        if intent == "area_consistency":
            work = filtered.copy()
            work["_gda_geometry_area_sqm"] = _geometry_area_sqm(work)
            area = (
                pd.to_numeric(work[area_col], errors="coerce")
                if area_col
                else work["_gda_geometry_area_sqm"]
            )
            work["_gda_area_delta_sqm"] = area - work["_gda_geometry_area_sqm"]
            work["_gda_area_delta_ratio"] = (
                work["_gda_area_delta_sqm"].abs()
                / work["_gda_geometry_area_sqm"].replace(0, pd.NA)
            )
            work["_gda_area_delta_pct"] = work["_gda_area_delta_ratio"] * 100.0
            result = work.sort_values(
                "_gda_area_delta_ratio", ascending=False, na_position="last"
            ).head(limit)
            columns = [
                column
                for column in (
                    id_col,
                    code_col,
                    name_col,
                    area_col,
                    "_gda_geometry_area_sqm",
                    "_gda_area_delta_sqm",
                    "_gda_area_delta_pct",
                )
                if column
            ]
            rows = [_feature_properties(row, columns) for _, row in result.iterrows()]
            answer = f"已找到面积差异最大的 {len(rows)} 个图斑。"
        elif intent == "parcel_lookup":
            columns = [
                column
                for column in (
                    id_col,
                    code_col,
                    name_col,
                    semantic_columns["located_admin_name"],
                    semantic_columns["owner_admin_name"],
                    area_col,
                )
                if column
            ]
            result = filtered.head(limit)
            rows = [_feature_properties(row, columns) for _, row in result.iterrows()]
            answer = f"定位到 {len(rows)} 个图斑。"
        elif intent == "group_summary":
            group_semantic = ast.get("group_by")
            group_col = semantic_columns.get(group_semantic) if group_semantic else None
            area = (
                pd.to_numeric(filtered[area_col], errors="coerce")
                if area_col
                else _geometry_area_sqm(filtered)
            )
            work = filtered.assign(_semantic_area_sqm=area)
            if group_col:
                grouped = work.groupby(group_col, dropna=False, as_index=False).agg(
                    feature_count=(group_col, "size"),
                    area_sqm=("_semantic_area_sqm", "sum"),
                )
                if name_col and group_semantic == "land_use_code":
                    names = (
                        filtered.groupby(group_col, dropna=False)[name_col]
                        .first()
                        .rename("land_use_name")
                    )
                    grouped = grouped.join(names, on=group_col)
            else:
                grouped = pd.DataFrame(
                    [{"feature_count": len(work), "area_sqm": float(area.sum())}]
                )
            total = float(grouped["area_sqm"].sum()) if len(grouped) else 0.0
            grouped["area_pct"] = grouped["area_sqm"].apply(
                lambda value: float(value / total * 100) if total else 0.0
            )
            grouped = grouped.sort_values("area_sqm", ascending=False).head(limit)
            rows = [_json_value(row) for row in grouped.to_dict(orient="records")]
            label = {
                "land_use_code": "地类",
                "located_admin_name": "坐落行政区",
                "owner_admin_name": "权属行政区",
                None: "全部图斑",
            }.get(group_semantic, str(group_semantic))
            answer = f"按{label}汇总了 {len(rows)} 个结果，面积单位为平方米。"
        elif intent == "dataset_summary":
            area = (
                pd.to_numeric(filtered[area_col], errors="coerce")
                if area_col
                else _geometry_area_sqm(filtered)
            )
            rows = [{"feature_count": len(filtered), "area_sqm": _json_value(area.sum())}]
            answer = "已汇总当前现状地类图斑治理产品。"
        else:
            raise ValueError(f"unsupported semantic intent: {intent}")

        return {
            "status": "succeeded",
            "query_type": intent,
            "semantic_source": SEMANTIC_SOURCE,
            "answer": answer,
            "rows": rows,
            "production_eligible": bool(projection.get("production_eligible")),
        }

    @staticmethod
    def query(projection_path: str | Path, question: str, *, limit: int = 100) -> dict[str, Any]:
        """Answer a bounded set of DLTB questions from the semantic product."""

        projection = DLTBVerticalDemo.load_projection(projection_path)
        target = Path(projection["target_path"])
        if not target.exists():
            raise FileNotFoundError(str(target))
        import geopandas as gpd
        import pandas as pd

        frame = gpd.read_parquet(target)
        fields = projection.get("fields") or {}
        source = {item.get("source_field"): name for name, item in fields.items() if item.get("source_field")}
        logical = {name: field for field, name in source.items()}
        # A projection stores physical fields; fall back to common codes for
        # legacy outputs generated before the projection contract existed.
        def col(semantic_field: str, fallback: str) -> str | None:
            for name, spec in fields.items():
                if name == semantic_field and spec.get("source_field") in frame.columns:
                    return spec["source_field"]
            return fallback if fallback in frame.columns else None

        code_col = col("land_use_code", "DLBM")
        name_col = col("land_use_name", "DLMC")
        area_col = col("parcel_area_sqm", "TBMJ")
        admin_col = col("located_admin_name", "ZLDWMC") or col("owner_admin_name", "QSDWMC")
        id_col = col("feature_identifier", "BSM")
        text = _norm_text(question)
        limit = max(1, min(int(limit), 1000))

        if any(token in text for token in ("差异", "不一致", "几何面积", "面积核对")):
            if "_gda_area_delta_ratio" not in frame.columns:
                frame["_gda_geometry_area_sqm"] = _geometry_area_sqm(frame)
                if area_col:
                    area = pd.to_numeric(frame[area_col], errors="coerce")
                    frame["_gda_area_delta_sqm"] = area - frame["_gda_geometry_area_sqm"]
                    frame["_gda_area_delta_ratio"] = (
                        (area - frame["_gda_geometry_area_sqm"]).abs()
                        / frame["_gda_geometry_area_sqm"].replace(0, pd.NA)
                    )
            frame["_gda_area_delta_pct"] = frame["_gda_area_delta_ratio"] * 100.0
            result = frame.sort_values(
                "_gda_area_delta_ratio", ascending=False, na_position="last"
            ).head(limit)
            cols = [column for column in (id_col, code_col, name_col, area_col, "_gda_geometry_area_sqm", "_gda_area_delta_sqm", "_gda_area_delta_pct") if column]
            return {"status": "succeeded", "query_type": "area_consistency", "semantic_source": SEMANTIC_SOURCE, "answer": f"已找到面积差异最大的 {len(result)} 个图斑。", "rows": [_feature_properties(row, cols) for _, row in result.iterrows()], "production_eligible": bool(projection.get("production_eligible"))}

        # Identify a parcel by its stable identifier.  This deliberately
        # requires an explicit identifier token rather than fuzzy matching a
        # random number in the question.
        if id_col and any(token in text for token in ("图斑", "地块", "bsm", "标识")):
            match = re.search(r"bsm\s*[:：]\s*([a-z0-9_-]{3,})", text, re.I)
            if not match:
                match = re.search(
                    r"(?:标识(?:码)?|图斑(?:编号)?)\s*[:：]?\s*([a-z0-9_-]{3,})",
                    text,
                    re.I,
                )
            if match:
                value = match.group(1)
                normalized_ids = (
                    frame[id_col]
                    .astype(str)
                    .str.replace(r"\.0$", "", regex=True)
                    .str.casefold()
                )
                result = frame[normalized_ids == value.casefold()].head(limit)
                cols = [column for column in (id_col, code_col, name_col, admin_col, area_col) if column]
                return {"status": "succeeded", "query_type": "parcel_lookup", "semantic_source": SEMANTIC_SOURCE, "answer": f"定位到 {len(result)} 个图斑。", "rows": [_feature_properties(row, cols) for _, row in result.iterrows()], "production_eligible": bool(projection.get("production_eligible"))}

        filtered = frame
        if "耕地" in text:
            mask = pd.Series(False, index=frame.index)
            if code_col:
                mask = mask | frame[code_col].astype(str).str.startswith("01", na=False)
            if name_col:
                mask = mask | frame[name_col].astype(str).str.contains("耕地", na=False)
            filtered = frame[mask]

        if any(token in text for token in ("行政区", "地区", "各区", "各县", "各乡", "地类", "面积", "数量", "多少", "占比")):
            group_col = code_col if any(token in text for token in ("地类", "土地利用")) else admin_col
            if group_col:
                area = pd.to_numeric(filtered[area_col], errors="coerce") if area_col else _geometry_area_sqm(filtered)
                work = filtered.assign(_semantic_area_sqm=area)
                group = work.groupby(group_col, dropna=False, as_index=False).agg(feature_count=(group_col, "size"), area_sqm=("_semantic_area_sqm", "sum"))
                if name_col and group_col == code_col:
                    names = filtered.groupby(code_col, dropna=False)[name_col].first().rename("land_use_name")
                    group = group.join(names, on=group_col)
                total = float(group.area_sqm.sum()) if len(group) else 0.0
                group["area_pct"] = group.area_sqm.apply(lambda value: float(value / total * 100) if total else 0.0)
                group = group.sort_values("area_sqm", ascending=False).head(limit)
                rows = [_json_value(row) for row in group.to_dict(orient="records")]
                label = "地类" if group_col == code_col else "行政区"
                return {"status": "succeeded", "query_type": "group_summary", "semantic_source": SEMANTIC_SOURCE, "answer": f"按{label}汇总了 {len(rows)} 个分组，面积单位为平方米。", "rows": rows, "production_eligible": bool(projection.get("production_eligible"))}

        return {"status": "succeeded", "query_type": "dataset_summary", "semantic_source": SEMANTIC_SOURCE, "answer": "这是现状地类图斑治理产品，可按地类、行政区、面积一致性和图斑标识继续查询。", "rows": [projection.get("metrics") or {}], "production_eligible": bool(projection.get("production_eligible"))}


def projection_catalog_entry(projection: dict[str, Any]) -> dict[str, Any]:
    """Return the source shape consumed by the semantic resolver."""

    fields = {
        name: dict(spec)
        for name, spec in (projection.get("fields") or {}).items()
    }
    if "land_use_code" in fields:
        fields["land_use_code"]["value_semantics"] = {
            "groups": {"耕地": {"prefixes": ["01"]}},
        }
    return {
        "table_name": SEMANTIC_SOURCE,
        "display_name": projection.get("display_name", "现状地类图斑（治理产品）"),
        "description": projection.get("description", ""),
        "geometry_type": projection.get("geometry_type"),
        "srid": projection.get("srid"),
        "synonyms": ["地类图斑", "现状用地", "土地利用现状", "DLTB", "图斑"],
        "suggested_analyses": ["按地类统计面积", "按行政区统计面积", "图斑面积一致性检查", "空间展示"],
        "projection_path": projection.get("target_path"),
        "projection_id": projection.get("projection_id"),
        "postgis_table_name": projection.get("postgis_table_name"),
        "execution_bindings": projection.get("execution_bindings") or {},
        "default_execution_engine": projection.get(
            "default_execution_engine", "postgis"
        ),
        "publication_status": projection.get("publication_status", "lake_only"),
        "quality_status": projection.get("quality_status"),
        "production_eligible": projection.get("production_eligible", False),
        "canonical_dataset": projection.get("canonical_dataset"),
        "fields": fields,
    }
