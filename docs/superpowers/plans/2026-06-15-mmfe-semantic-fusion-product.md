# MMFE Semantic Fusion Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a semantic fusion product layer to MMFE so fusion runs can emit both normal GIS business output and an AI-ready semantic manifest.

**Architecture:** Add a focused `semantic_product.py` module that enriches fused GeoDataFrames with deterministic ontology derivations/inferences and builds a portable JSON manifest. Wire it into `execute_fusion()` through an optional `semantic_config`, expose ontology matching in compatibility assessment, and enable the tool layer to request semantic products by default.

**Tech Stack:** Python, GeoPandas, Pandas, existing MMFE modules, YAML ontology, pytest.

---

## File Structure

- Create `data_agent/fusion/semantic_product.py`
  - Owns semantic enrichment, feature summaries, AI chunks, and manifest writing.

- Modify `data_agent/fusion/models.py`
  - Add `FusionResult` fields: `semantic_product_path`, `semantic_summary`, `derived_fields`, `inferred_fields`.

- Modify `data_agent/fusion/compatibility.py`
  - Add `use_ontology` parameter and pass it to `_find_field_matches()`.

- Modify `data_agent/fusion/execution.py`
  - Add `semantic_config`, call semantic product builder, re-save enriched output, return new result fields.

- Modify `data_agent/fusion/__init__.py` and `data_agent/fusion_engine.py`
  - Re-export semantic product helpers for compatibility.

- Modify `data_agent/toolsets/fusion_tools.py`
  - Add `semantic_product` parameter to `fuse_datasets()` and include manifest summary in return text.

- Replace `data_agent/standards/gis_ontology.yaml`
  - Repair UTF-8 Chinese aliases and keep deterministic derivations/inference rules.

- Create `data_agent/test_fusion_semantic_product.py`
  - Unit tests for the new module.

- Modify `data_agent/test_fusion_v2_semantic.py`
  - Test `assess_compatibility(..., use_ontology=True)`.

- Modify `data_agent/test_fusion_v2_integration.py`
  - Test `execute_fusion(..., semantic_config={"enabled": True})`.

---

### Task 1: Add Semantic Product Unit Tests

**Files:**
- Create: `data_agent/test_fusion_semantic_product.py`
- No production code changes in this task.

- [ ] **Step 1: Write the failing test file**

Create `data_agent/test_fusion_semantic_product.py` with:

```python
"""Tests for MMFE semantic fusion product manifests."""

import json
import os
import tempfile
import unittest

import geopandas as gpd
from shapely.geometry import Point

from data_agent.fusion.models import FusionSource


def _semantic_test_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "parcel_id": ["P1", "P2"],
            "floors": [5, 18],
            "slope": [3.0, 28.0],
            "area": [1000.0, 2000.0],
        },
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
    )


def _semantic_sources() -> list[FusionSource]:
    return [
        FusionSource(
            file_path="/data/parcels.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=2,
            columns=[
                {"name": "parcel_id", "dtype": "object", "null_pct": 0},
                {"name": "floors", "dtype": "int64", "null_pct": 0},
                {"name": "slope", "dtype": "float64", "null_pct": 0},
                {"name": "area", "dtype": "float64", "null_pct": 0},
            ],
        )
    ]


class TestSemanticFusionProduct(unittest.TestCase):
    def test_build_manifest_has_stable_top_level_keys(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        enriched, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _semantic_sources(),
            strategy="spatial_join",
            field_matches=[
                {
                    "left": "DLBM",
                    "right": "land_use_code",
                    "confidence": 0.85,
                    "match_type": "ontology",
                }
            ],
            quality={"score": 0.91, "warnings": []},
            alignment_log=["Aligned CRS to EPSG:4326"],
            config={"enabled": True, "feature_sample_limit": 1},
        )

        self.assertIsInstance(enriched, gpd.GeoDataFrame)
        for key in [
            "product_type",
            "version",
            "business_output",
            "sources",
            "semantic_mappings",
            "derived_fields",
            "inferred_fields",
            "feature_semantics",
            "ai_metadata",
            "quality",
            "lineage",
        ]:
            self.assertIn(key, manifest)
        self.assertEqual(manifest["product_type"], "semantic_fusion_product")
        self.assertEqual(manifest["quality"]["score"], 0.91)

    def test_ontology_derivation_and_inference_enrich_output(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        enriched, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _semantic_sources(),
            strategy="spatial_join",
            config={"enabled": True, "derive_fields": True, "infer_fields": True},
        )

        self.assertIn("building_height", enriched.columns)
        self.assertEqual(enriched["building_height"].tolist(), [15.0, 54.0])
        self.assertIn("slope_class", enriched.columns)
        self.assertIn("building_height", [d["field"] for d in manifest["derived_fields"]])
        self.assertIn("slope_class", [d["field"] for d in manifest["inferred_fields"]])

    def test_ai_chunks_are_embedding_ready_and_capped(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _semantic_sources(),
            strategy="nearest_join",
            quality={"score": 0.8, "warnings": ["sample warning"]},
            config={"enabled": True, "feature_sample_limit": 1, "ai_chunks": True},
        )

        ai_metadata = manifest["ai_metadata"]
        self.assertTrue(ai_metadata["embedding_ready"])
        self.assertIn("lancedb", ai_metadata["recommended_vector_targets"])
        self.assertEqual(len(ai_metadata["chunks"]), 2)  # product chunk + one feature chunk
        self.assertIn("nearest_join", ai_metadata["chunks"][0]["text"])

    def test_write_manifest_next_to_output(self):
        from data_agent.fusion.semantic_product import write_semantic_product_manifest

        with tempfile.TemporaryDirectory() as tmp:
            output_path = os.path.join(tmp, "fused.geojson")
            manifest = {
                "product_type": "semantic_fusion_product",
                "version": "1.0",
                "business_output": {"path": output_path},
            }
            manifest_path = write_semantic_product_manifest(manifest, output_path)
            self.assertTrue(manifest_path.endswith(".semantic.json"))
            self.assertTrue(os.path.exists(manifest_path))
            with open(manifest_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["product_type"], "semantic_fusion_product")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_semantic_product.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'data_agent.fusion.semantic_product'`.

---

### Task 2: Implement Semantic Product Module

**Files:**
- Create: `data_agent/fusion/semantic_product.py`
- Test: `data_agent/test_fusion_semantic_product.py`

- [ ] **Step 1: Add minimal implementation**

Create `data_agent/fusion/semantic_product.py` with:

```python
"""Semantic fusion product builder for MMFE.

This module converts a physical fused GeoDataFrame into a portable semantic
product: enriched business columns plus an AI-ready JSON manifest.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import geopandas as gpd
import pandas as pd

from .explainability import COL_CONFIDENCE, COL_SOURCES, _classify_quality
from .models import FusionSource


DEFAULT_SEMANTIC_PRODUCT_CONFIG = {
    "enabled": True,
    "use_ontology": True,
    "derive_fields": True,
    "infer_fields": True,
    "feature_sample_limit": 25,
    "ai_chunks": True,
}


def build_semantic_fusion_product(
    output_gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    strategy: str,
    field_matches: list[dict] | None = None,
    quality: dict | None = None,
    alignment_log: list[str] | None = None,
    temporal_log: list[str] | None = None,
    conflict_summary: dict | None = None,
    config: dict | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Apply deterministic semantic enrichment and build a product manifest."""
    cfg = {**DEFAULT_SEMANTIC_PRODUCT_CONFIG, **(config or {})}
    enriched = output_gdf.copy()
    semantic_warnings: list[str] = []
    derived_fields: list[dict[str, Any]] = []
    inferred_fields: list[dict[str, Any]] = []

    if cfg.get("enabled", True) and cfg.get("use_ontology", True):
        try:
            from .ontology import OntologyReasoner

            reasoner = OntologyReasoner()
            if reasoner.is_loaded and cfg.get("derive_fields", True):
                enriched, derived = reasoner.derive_missing_fields(enriched)
                derived_fields = [
                    {
                        "field": field,
                        "method": "ontology_derivation",
                        "description": _derivation_description(reasoner, field),
                    }
                    for field in derived
                ]
            if reasoner.is_loaded and cfg.get("infer_fields", True):
                enriched, inferred = reasoner.apply_inference_rules(enriched)
                inferred_fields = [
                    {"field": field, "method": "ontology_inference"}
                    for field in inferred
                ]
        except Exception as exc:
            semantic_warnings.append(f"semantic enrichment failed: {exc}")

    quality = quality or {"score": None, "warnings": []}
    feature_semantics = _build_feature_semantics(
        enriched,
        sources,
        sample_limit=int(cfg.get("feature_sample_limit", 25)),
    )
    ai_metadata = _build_ai_metadata(
        enriched,
        sources,
        strategy,
        quality,
        feature_semantics,
        enabled=bool(cfg.get("ai_chunks", True)),
    )

    manifest = {
        "product_type": "semantic_fusion_product",
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "business_output": {
            "path": "",
            "format": "GeoJSON",
            "row_count": int(len(enriched)),
            "column_count": len([c for c in enriched.columns if c != "geometry"]),
            "crs": str(enriched.crs) if getattr(enriched, "crs", None) else None,
        },
        "sources": [_source_manifest(s) for s in sources],
        "semantic_mappings": _normalize_field_matches(field_matches or []),
        "derived_fields": derived_fields,
        "inferred_fields": inferred_fields,
        "feature_semantics": feature_semantics,
        "ai_metadata": ai_metadata,
        "quality": {
            "score": quality.get("score"),
            "warnings": list(quality.get("warnings", [])) + semantic_warnings,
        },
        "lineage": {
            "strategy": strategy,
            "alignment_steps": alignment_log or [],
            "temporal_alignment": temporal_log or [],
            "conflict_resolution": conflict_summary or {},
        },
    }
    return enriched, manifest


def write_semantic_product_manifest(manifest: dict, output_path: str) -> str:
    """Write manifest JSON next to the fused dataset and return its path."""
    root, _ = os.path.splitext(output_path)
    manifest_path = f"{root}.semantic.json"
    manifest = dict(manifest)
    business_output = dict(manifest.get("business_output", {}))
    business_output["path"] = output_path
    manifest["business_output"] = business_output
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=_json_default)
    return manifest_path


def _source_manifest(source: FusionSource) -> dict:
    return {
        "path": source.file_path,
        "data_type": source.data_type,
        "row_count": int(source.row_count or 0),
        "crs": source.crs,
        "semantic_domain": source.semantic_domain,
        "columns": [c.get("name") for c in source.columns],
    }


def _normalize_field_matches(matches: list[dict]) -> list[dict]:
    normalized = []
    for match in matches:
        normalized.append(
            {
                "source_field": match.get("left", ""),
                "target_field": match.get("right", ""),
                "confidence": match.get("confidence"),
                "match_type": match.get("match_type", "exact" if match.get("confidence") == 1.0 else "semantic"),
            }
        )
    return normalized


def _build_feature_semantics(
    gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    sample_limit: int,
) -> list[dict]:
    if gdf.empty or sample_limit <= 0:
        return []

    source_refs = [os.path.basename(s.file_path) for s in sources]
    semantic_cols = _pick_semantic_columns(gdf)
    rows = []
    for idx, row in gdf.head(sample_limit).iterrows():
        confidence = _safe_float(row.get(COL_CONFIDENCE), default=1.0)
        attrs = []
        for col in semantic_cols:
            value = row.get(col)
            if pd.notna(value):
                attrs.append(f"{col}={value}")
        summary = f"Feature {idx}: " + "; ".join(attrs[:12])
        rows.append(
            {
                "row_index": int(idx) if isinstance(idx, int) else str(idx),
                "summary": summary,
                "source_refs": source_refs,
                "quality": _classify_quality(confidence),
            }
        )
    return rows


def _build_ai_metadata(
    gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    strategy: str,
    quality: dict,
    feature_semantics: list[dict],
    enabled: bool,
) -> dict:
    source_names = [os.path.basename(s.file_path) for s in sources]
    retrieval_text = (
        f"Semantic fusion product generated with {strategy}. "
        f"Sources: {', '.join(source_names)}. "
        f"Rows: {len(gdf)}. Quality score: {quality.get('score')}."
    )
    chunks = []
    if enabled:
        chunks.append(
            {
                "chunk_id": "fusion:product",
                "text": retrieval_text,
                "metadata": {
                    "strategy": strategy,
                    "row_count": int(len(gdf)),
                    "quality_score": quality.get("score"),
                    "sources": source_names,
                },
            }
        )
        for i, feature in enumerate(feature_semantics):
            chunks.append(
                {
                    "chunk_id": f"fusion:feature:{i}",
                    "text": feature["summary"],
                    "metadata": {
                        "strategy": strategy,
                        "quality": feature["quality"],
                        "source_refs": feature["source_refs"],
                    },
                }
            )

    return {
        "retrieval_text": retrieval_text,
        "chunks": chunks,
        "embedding_ready": True,
        "recommended_vector_targets": ["pgvector", "lancedb"],
    }


def _pick_semantic_columns(gdf: gpd.GeoDataFrame) -> list[str]:
    priority = [
        "parcel_id",
        "name",
        "land_use_code",
        "land_use_name",
        "area",
        "area_mu",
        "population",
        "population_density",
        "floors",
        "building_height",
        "slope",
        "slope_class",
        "building_type",
        "district",
    ]
    existing = [c for c in priority if c in gdf.columns]
    if len(existing) >= 12:
        return existing
    extra = [
        c
        for c in gdf.columns
        if c != "geometry" and not c.startswith("_") and c not in existing
    ]
    return existing + extra[: 12 - len(existing)]


def _derivation_description(reasoner, field: str) -> str:
    rule = getattr(reasoner, "_derivation_index", {}).get(field, {})
    return rule.get("description") or f"Derived field {field}"


def _safe_float(value, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    return str(value)
```

- [ ] **Step 2: Run semantic product tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_semantic_product.py -q
```

Expected: PASS.

---

### Task 3: Repair Ontology YAML and Verify Existing Ontology Tests

**Files:**
- Modify: `data_agent/standards/gis_ontology.yaml`
- Test: `data_agent/test_fusion_v2_semantic.py`

- [ ] **Step 1: Replace ontology YAML with valid UTF-8**

Replace `data_agent/standards/gis_ontology.yaml` with:

```yaml
version: "1.0"

equivalences:
  - group_id: area
    fields: ["area", "面积", "mj", "zmj", "shape_area", "tbmj", "TBMJ", "AREA"]
  - group_id: perimeter
    fields: ["perimeter", "周长", "shape_length", "shape_len", "PERIMETER"]
  - group_id: land_use_code
    fields: ["dlbm", "DLBM", "land_use_code", "地类编码", "用地编码", "land_code"]
  - group_id: land_use_name
    fields: ["dlmc", "DLMC", "land_use_name", "地类名称", "用地名称", "land_name"]
  - group_id: elevation
    fields: ["elevation", "高程", "dem", "height", "altitude", "海拔", "gc"]
  - group_id: slope
    fields: ["slope", "坡度", "gradient", "pd"]
  - group_id: aspect
    fields: ["aspect", "坡向", "px"]
  - group_id: population
    fields: ["population", "人口", "pop", "rk", "pop_count"]
  - group_id: floors
    fields: ["floors", "层数", "cs", "floor_count", "building_floors"]
  - group_id: building_height
    fields: ["building_height", "建筑高度", "jzgd", "bldg_height", "height_m"]
  - group_id: building_area
    fields: ["building_area", "建筑面积", "jzmj", "bldg_area"]
  - group_id: green_area
    fields: ["green_area", "绿化面积", "lhmj"]
  - group_id: parcel_id
    fields: ["parcel_id", "地块编号", "dkbh", "DKBH", "parcel_no", "lot_id"]
  - group_id: name
    fields: ["name", "名称", "mc", "MC", "feature_name"]
  - group_id: address
    fields: ["address", "地址", "dz", "addr", "location_text"]
  - group_id: district
    fields: ["district", "区县", "qx", "county", "行政区"]
  - group_id: ndvi
    fields: ["ndvi", "NDVI", "植被指数", "vegetation_index"]

derivations:
  - target: building_height
    formula: "floors * 3.0"
    required_fields: ["floors"]
    unit: "m"
    description: "建筑高度 = 层数 * 默认层高3m"

  - target: population_density
    formula: "population / (area / 1000000)"
    required_fields: ["population", "area"]
    unit: "people/km2"
    description: "人口密度 = 人口 / 面积(km2)"

  - target: floor_area_ratio
    formula: "building_area * floors / area"
    required_fields: ["building_area", "floors", "area"]
    unit: ""
    description: "容积率 = 建筑面积 * 层数 / 用地面积"

  - target: building_density
    formula: "building_area / area"
    required_fields: ["building_area", "area"]
    unit: ""
    description: "建筑密度 = 建筑占地面积 / 用地面积"

  - target: green_ratio
    formula: "green_area / area"
    required_fields: ["green_area", "area"]
    unit: ""
    description: "绿化率 = 绿化面积 / 用地面积"

  - target: perimeter_area_ratio
    formula: "perimeter / (area ** 0.5)"
    required_fields: ["perimeter", "area"]
    unit: ""
    description: "形状指数 = 周长 / 面积^0.5"

  - target: compactness
    formula: "(4 * 3.14159 * area) / (perimeter ** 2)"
    required_fields: ["perimeter", "area"]
    unit: ""
    description: "紧凑度 = 4π * 面积 / 周长^2"

  - target: area_mu
    formula: "area / 666.67"
    required_fields: ["area"]
    unit: "mu"
    description: "面积(亩) = 面积(m2) / 666.67"

inference_rules:
  - rule_id: high_rise_residential
    conditions:
      - field: floors
        operator: ">="
        value: 18
      - field: land_use_code
        operator: "startswith"
        value: "07"
    conclusion:
      field: building_type
      value: "高层住宅"

  - rule_id: commercial_building
    conditions:
      - field: land_use_code
        operator: "startswith"
        value: "05"
    conclusion:
      field: building_type
      value: "商业建筑"

  - rule_id: high_vegetation
    conditions:
      - field: ndvi
        operator: ">="
        value: 0.6
    conclusion:
      field: vegetation_level
      value: "高植被覆盖"

  - rule_id: steep_slope
    conditions:
      - field: slope
        operator: ">="
        value: 25
    conclusion:
      field: slope_class
      value: "陡坡"

  - rule_id: flat_terrain
    conditions:
      - field: slope
        operator: "<"
        value: 5
    conclusion:
      field: slope_class
      value: "平地"

unit_conversions:
  area:
    - from: m2
      to: mu
      factor: 0.0015
    - from: m2
      to: ha
      factor: 0.0001
    - from: mu
      to: ha
      factor: 0.0667
  length:
    - from: m
      to: km
      factor: 0.001
```

- [ ] **Step 2: Run existing semantic v2 tests and inspect failures**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_semantic.py -q
```

Expected: Some existing assertions may fail because they currently assert mojibake strings. Update those assertions in the next step.

- [ ] **Step 3: Update ontology assertions to valid UTF-8**

In `data_agent/test_fusion_v2_semantic.py`, update assertions:

```python
self.assertIn("面积", equivs)
...
left = [{"name": "面积", "dtype": "float64"}]
...
self.assertEqual(result.loc[0, "slope_class"], "平地")
self.assertEqual(result.loc[1, "slope_class"], "陡坡")
...
mocked JSON values should use "面积", "m2", "地块面积", "同义"
```

Keep the same test intent and replace only corrupted string literals.

- [ ] **Step 4: Re-run semantic v2 tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_semantic.py -q
```

Expected: PASS.

---

### Task 4: Expose Ontology Matching in Compatibility Assessment

**Files:**
- Modify: `data_agent/fusion/compatibility.py`
- Modify: `data_agent/test_fusion_v2_semantic.py`

- [ ] **Step 1: Add failing compatibility test**

Append to `TestOntologyInMatching` in `data_agent/test_fusion_v2_semantic.py`:

```python
    def test_assess_compatibility_accepts_ontology_flag(self):
        from data_agent.fusion.compatibility import assess_compatibility
        from data_agent.fusion.models import FusionSource

        s1 = FusionSource(
            file_path="a.geojson",
            data_type="vector",
            columns=[{"name": "面积", "dtype": "float64"}],
        )
        s2 = FusionSource(
            file_path="b.geojson",
            data_type="vector",
            columns=[{"name": "AREA", "dtype": "float64"}],
        )

        report = assess_compatibility([s1, s2], use_ontology=True)
        ontology_matches = [
            m for m in report.field_matches if m.get("match_type") == "ontology"
        ]
        self.assertEqual(len(ontology_matches), 1)
        self.assertEqual(ontology_matches[0]["left"], "面积")
        self.assertEqual(ontology_matches[0]["right"], "AREA")
```

- [ ] **Step 2: Run targeted failing test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_semantic.py::TestOntologyInMatching::test_assess_compatibility_accepts_ontology_flag -q
```

Expected: FAIL with `TypeError: assess_compatibility() got an unexpected keyword argument 'use_ontology'`.

- [ ] **Step 3: Implement compatibility parameter**

Change `data_agent/fusion/compatibility.py`:

```python
def assess_compatibility(
    sources: list[FusionSource],
    use_embedding: bool = False,
    use_llm_schema: bool = False,
    use_ontology: bool = False,
) -> CompatibilityReport:
```

Change `_find_field_matches` call:

```python
field_matches = _find_field_matches(
    sources,
    use_embedding=use_embedding,
    use_llm_schema=use_llm_schema,
    use_ontology=use_ontology,
)
```

- [ ] **Step 4: Run targeted test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_semantic.py::TestOntologyInMatching::test_assess_compatibility_accepts_ontology_flag -q
```

Expected: PASS.

---

### Task 5: Extend FusionResult and Re-Exports

**Files:**
- Modify: `data_agent/fusion/models.py`
- Modify: `data_agent/fusion/__init__.py`
- Modify: `data_agent/fusion_engine.py`
- Modify: `data_agent/test_fusion_v2_integration.py`

- [ ] **Step 1: Add failing model export assertions**

In `TestFusionResultModel` in `data_agent/test_fusion_v2_integration.py`, add:

```python
    def test_semantic_product_fields_exist(self):
        from data_agent.fusion.models import FusionResult

        r = FusionResult()
        self.assertEqual(r.semantic_product_path, "")
        self.assertEqual(r.semantic_summary, {})
        self.assertEqual(r.derived_fields, [])
        self.assertEqual(r.inferred_fields, [])

    def test_semantic_product_helpers_exported(self):
        from data_agent.fusion import build_semantic_fusion_product
        from data_agent.fusion_engine import write_semantic_product_manifest

        self.assertTrue(callable(build_semantic_fusion_product))
        self.assertTrue(callable(write_semantic_product_manifest))
```

- [ ] **Step 2: Run targeted tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_integration.py::TestFusionResultModel -q
```

Expected: FAIL because new fields and/or exports are missing.

- [ ] **Step 3: Add FusionResult fields**

In `data_agent/fusion/models.py`, add to `FusionResult`:

```python
    # semantic fusion product
    semantic_product_path: str = ""
    semantic_summary: dict = field(default_factory=dict)
    derived_fields: list = field(default_factory=list)
    inferred_fields: list = field(default_factory=list)
```

- [ ] **Step 4: Re-export helpers**

In `data_agent/fusion/__init__.py`, add:

```python
from .semantic_product import (
    DEFAULT_SEMANTIC_PRODUCT_CONFIG,
    build_semantic_fusion_product,
    write_semantic_product_manifest,
)
```

In `data_agent/fusion_engine.py`, add these names to the explicit import list:

```python
    DEFAULT_SEMANTIC_PRODUCT_CONFIG,
    build_semantic_fusion_product,
    write_semantic_product_manifest,
```

- [ ] **Step 5: Run targeted model/export tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_integration.py::TestFusionResultModel -q
```

Expected: PASS.

---

### Task 6: Wire Semantic Product into execute_fusion

**Files:**
- Modify: `data_agent/fusion/execution.py`
- Modify: `data_agent/test_fusion_v2_integration.py`

- [ ] **Step 1: Add failing integration test**

In `TestExecuteFusionV2` in `data_agent/test_fusion_v2_integration.py`, add:

```python
    @patch("data_agent.fusion.db.record_operation")
    @patch("data_agent.fusion.execution._generate_output_path")
    def test_with_semantic_product_manifest(self, mock_path, mock_record):
        """execute_fusion writes semantic product manifest when enabled."""
        from data_agent.fusion.execution import execute_fusion
        from data_agent.fusion.models import FusionSource

        out_path = os.path.join(self.tmp, "out.geojson")
        mock_path.return_value = out_path
        gdf = gpd.GeoDataFrame(
            {
                "parcel_id": ["P1", "P2"],
                "floors": [5, 18],
                "slope": [2.0, 30.0],
                "area": [1000.0, 2000.0],
            },
            geometry=[Point(0, 0), Point(1, 1)],
            crs="EPSG:4326",
        )
        src = FusionSource(
            file_path="source.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=2,
            columns=[
                {"name": "parcel_id", "dtype": "object", "null_pct": 0},
                {"name": "floors", "dtype": "int64", "null_pct": 0},
                {"name": "slope", "dtype": "float64", "null_pct": 0},
                {"name": "area", "dtype": "float64", "null_pct": 0},
            ],
        )

        result = execute_fusion(
            [("vector", gdf), ("vector", gdf.copy())],
            "spatial_join",
            [src, src],
            semantic_config={"enabled": True, "feature_sample_limit": 1},
        )

        self.assertTrue(result.semantic_product_path.endswith(".semantic.json"))
        self.assertTrue(os.path.exists(result.semantic_product_path))
        self.assertIn("building_height", result.derived_fields)
        output_gdf = gpd.read_file(result.output_path)
        self.assertIn("building_height", output_gdf.columns)
```

- [ ] **Step 2: Run targeted failing test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_integration.py::TestExecuteFusionV2::test_with_semantic_product_manifest -q
```

Expected: FAIL with `TypeError: execute_fusion() got an unexpected keyword argument 'semantic_config'`.

- [ ] **Step 3: Add semantic_config to execute_fusion signature**

In `data_agent/fusion/execution.py`, add parameter:

```python
    semantic_config: Optional[dict] = None,
```

- [ ] **Step 4: Move quality validation before final save and add semantic product call**

In `execute_fusion()`, after conflict resolution and before final return, adjust flow to:

```python
# Quality validation before optional semantic product; run again after enrichment if needed.
quality = validate_quality(output_gdf, sources)

semantic_product_path = ""
semantic_summary = {}
derived_field_names = []
inferred_field_names = []
if semantic_config:
    try:
        from .semantic_product import build_semantic_fusion_product, write_semantic_product_manifest

        field_matches = report.field_matches if report else []
        output_gdf, semantic_manifest = build_semantic_fusion_product(
            output_gdf=output_gdf,
            sources=sources,
            strategy=strategy,
            field_matches=field_matches,
            quality=quality,
            alignment_log=alignment_log,
            temporal_log=temporal_log,
            conflict_summary=conflict_summary,
            config=semantic_config,
        )
        quality = validate_quality(output_gdf, sources)
        semantic_manifest["quality"] = {
            "score": quality["score"],
            "warnings": quality["warnings"],
        }
        output_gdf.to_file(output_path, driver="GeoJSON")
        semantic_product_path = write_semantic_product_manifest(
            semantic_manifest, output_path
        )
        semantic_summary = {
            "path": semantic_product_path,
            "ai_chunks": len(semantic_manifest.get("ai_metadata", {}).get("chunks", [])),
            "feature_semantics": len(semantic_manifest.get("feature_semantics", [])),
        }
        derived_field_names = [d["field"] for d in semantic_manifest.get("derived_fields", [])]
        inferred_field_names = [d["field"] for d in semantic_manifest.get("inferred_fields", [])]
    except Exception as e:
        logger.warning("Semantic fusion product generation failed: %s", e)
        semantic_summary = {"warning": str(e)}
```

Ensure the existing save still happens before this block so `output_path` exists:

```python
output_gdf.to_file(output_path, driver="GeoJSON")
```

Keep explainability behavior intact. If explainability currently runs after validation, preserve that behavior or run semantic product after explainability so `_fusion_confidence` is available in feature summaries.

- [ ] **Step 5: Populate new FusionResult fields**

Add to returned `FusionResult`:

```python
        semantic_product_path=semantic_product_path,
        semantic_summary=semantic_summary,
        derived_fields=derived_field_names,
        inferred_fields=inferred_field_names,
```

- [ ] **Step 6: Run targeted integration test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_integration.py::TestExecuteFusionV2::test_with_semantic_product_manifest -q
```

Expected: PASS.

---

### Task 7: Add Tool Layer semantic_product Parameter

**Files:**
- Modify: `data_agent/toolsets/fusion_tools.py`
- Modify: `data_agent/test_fusion_v2_integration.py`

- [ ] **Step 1: Add failing signature/default test**

In `TestFuseDatasetsV2Params` in `data_agent/test_fusion_v2_integration.py`, add:

```python
    def test_fuse_datasets_has_semantic_product_param(self):
        import inspect
        from data_agent.toolsets.fusion_tools import fuse_datasets

        sig = inspect.signature(fuse_datasets)
        self.assertIn("semantic_product", sig.parameters)
        self.assertEqual(sig.parameters["semantic_product"].default, "true")
```

- [ ] **Step 2: Run targeted failing test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_integration.py::TestFuseDatasetsV2Params::test_fuse_datasets_has_semantic_product_param -q
```

Expected: FAIL because parameter is missing.

- [ ] **Step 3: Add parameter to fuse_datasets signature**

In `data_agent/toolsets/fusion_tools.py`, change signature:

```python
async def fuse_datasets(
    file_paths: str,
    strategy: str = "auto",
    params_json: str = "{}",
    enable_temporal: str = "auto",
    conflict_strategy: str = "",
    enable_explainability: str = "true",
    use_llm_semantic: str = "false",
    semantic_product: str = "true",
) -> str:
```

- [ ] **Step 4: Pass semantic_config into execute_fusion**

Inside `fuse_datasets()`, before calling `fusion_engine.execute_fusion`, build:

```python
semantic_config = None
if str(semantic_product).lower() in ("1", "true", "yes", "on"):
    semantic_config = {
        "enabled": True,
        "use_ontology": True,
        "derive_fields": True,
        "infer_fields": True,
        "feature_sample_limit": 25,
        "ai_chunks": True,
    }
```

Pass:

```python
semantic_config=semantic_config,
```

Also pass `use_ontology=True` into `assess_compatibility()` when `semantic_product` is true:

```python
report = fusion_engine.assess_compatibility(
    sources,
    use_embedding=(use_llm_semantic.lower() == "true"),
    use_llm_schema=(use_llm_semantic.lower() == "true"),
    use_ontology=semantic_config is not None,
)
```

If the current call site has different variable names, preserve existing behavior and only add these parameters.

- [ ] **Step 5: Include manifest in tool return text**

Add lines to the success response:

```python
if result.semantic_product_path:
    lines.append(f"语义融合产品清单: {result.semantic_product_path}")
    lines.append(f"派生字段: {len(result.derived_fields)} 个")
    lines.append(f"推理字段: {len(result.inferred_fields)} 个")
```

- [ ] **Step 6: Run targeted signature test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_integration.py::TestFuseDatasetsV2Params -q
```

Expected: PASS.

---

### Task 8: Run Focused Regression and Fix Failures

**Files:**
- Modify only files touched by prior tasks if failures require fixes.

- [ ] **Step 1: Run focused semantic/fusion tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_semantic_product.py data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py -q
```

Expected: PASS.

- [ ] **Step 2: If failures occur, fix production code or tests according to behavior**

Common likely fixes:

- If JSON serialization fails, add conversion to `_json_default()`.
- If ontology formula evaluation fails for `area ** 0.5`, leave formula as-is and ensure required fields exist only in tests that need it.
- If `execute_fusion()` semantic enrichment runs before explainability and feature quality is always high, this is acceptable for this iteration unless tests assert otherwise.
- If Chinese string assertions fail due console encoding only, inspect file with `Get-Content -Encoding UTF8`.

- [ ] **Step 3: Run broader MMFE regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py data_agent\test_fusion_v2_explainability.py data_agent\test_fusion_v2_conflict.py -q
```

Expected: PASS.

---

### Task 9: Document Final Implementation Notes

**Files:**
- Modify: `docs/semantic_fusion_engine_technical_spec.md` or add a short section to `docs/superpowers/specs/2026-06-15-mmfe-semantic-fusion-product-design.md`

- [ ] **Step 1: Add implementation note after tests pass**

Append to the design spec:

```markdown
## Implementation Notes

Implemented in:

- `data_agent/fusion/semantic_product.py`
- `data_agent/fusion/execution.py`
- `data_agent/fusion/compatibility.py`
- `data_agent/toolsets/fusion_tools.py`
- `data_agent/standards/gis_ontology.yaml`

The semantic fusion product is opt-in at the engine layer through
`semantic_config` and enabled by default at the FusionToolset layer through
`semantic_product="true"`. LanceDB remains a future indexing target; this
iteration emits embedding-ready chunks but does not add a LanceDB dependency.
```

- [ ] **Step 2: Run final focused tests again**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_semantic_product.py data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py -q
```

Expected: PASS.

---

## Self-Review Checklist

- Spec coverage: Tasks cover semantic product manifest, ontology entry in compatibility, execution integration, toolset exposure, ontology repair, tests, and Lance/LanceDB positioning.
- No unrelated files: Plan avoids NL2SQL files currently dirty in the worktree.
- Type consistency: `semantic_product_path`, `semantic_summary`, `derived_fields`, and `inferred_fields` are consistently named across model, execution, and tests.
- Backward compatibility: Engine-level semantic product is opt-in through `semantic_config`; existing `execute_fusion()` calls remain valid.

---

## Roadmap Progress: Raster Semantic Hints

Completed as a follow-up increment after the initial semantic product contract.

- Added `FusionSource.semantic_hints` as an additive field at the end of the dataclass to preserve backward-compatible positional constructors.
- Extended raster profiling to extract evidence-backed hints from filename tokens, raster band descriptions, band tags, and conservative value ranges.
- Covered common raster semantic themes: NDVI/vegetation index, DEM/elevation, slope, and land-cover classification.
- Propagated source hints into `manifest.sources[].semantic_hints`, keeping them available for business review, AI retrieval, and later pgvector/LanceDB indexing jobs.
- Added focused TDD coverage in `data_agent/test_fusion_engine.py` and `data_agent/test_fusion_semantic_product.py`.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource data_agent\test_fusion_semantic_product.py -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py data_agent\test_fusion_semantic_alignment.py data_agent\test_fusion_semantic_product.py data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py data_agent\test_fusion_v2_explainability.py data_agent\test_fusion_v2_conflict.py -q
```

---

## Roadmap Progress: Point-Cloud Semantic Hints

Completed as the next hard-source increment after raster semantic hints.

- Extended point-cloud profiling to extract optional LAS dimension semantics when `laspy` can read the source.
- Added columns and statistics for classification, intensity, return number/count, RGB color, scan angle, and XYZ numeric ranges.
- Added ASPRS classification summaries and `classification_class` hints for recognized classes such as ground, high vegetation, building, and water.
- Added source-level `semantic_domain="lidar"` and source hints for classified lidar, intensity lidar, and colorized lidar.
- Fixed a compatibility gap by accepting both context-manager style LAS readers and ordinary `LasData` objects returned by `laspy.read()`.
- Preserved graceful fallback when `laspy` is not installed or a point-cloud source cannot be read.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py data_agent\test_fusion_semantic_alignment.py data_agent\test_fusion_semantic_product.py data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py data_agent\test_fusion_v2_explainability.py data_agent\test_fusion_v2_conflict.py -q
```

---

## Roadmap Progress: Raster Pixel Metadata and STAC Sidecar Semantics

Completed as a deeper raster-source increment after the initial raster semantic
hints.

- Extended raster profiling to preserve pixel-value metadata for each readable
  band: `nodata`, `scale`, `offset`, and `unit`.
- Added scaled band statistics when scale/offset metadata is available, while
  keeping original raw statistics for ordinary GIS consumers.
- Added evidence-backed `pixel_value_semantics` hints so AI workflows can tell
  whether a band uses scaled reflectance, nodata sentinels, physical units, or
  other band-level value conventions.
- Added sidecar metadata loading for `.stac.json`, `.metadata.json`, and `.json`
  files located next to the raster.
- Added STAC-like evidence extraction for platform, instrument, `eo:bands`, and
  `raster:bands`, including spectral common names and per-band scale/offset/
  nodata/unit metadata.
- Kept sidecar parsing dependency-free and conservative. These metadata hints
  enrich source profiles and semantic manifests, but do not force a physical
  pixel transformation or replace later STAC/COG/GeoParquet publishing work.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_carries_pixel_semantics_from_band_metadata data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_reads_stac_sidecar_metadata -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py data_agent\test_fusion_semantic_alignment.py data_agent\test_fusion_semantic_product.py data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py data_agent\test_fusion_v2_explainability.py data_agent\test_fusion_v2_conflict.py -q
```

---

## Roadmap Progress: CRS-Aware Raster Grid Semantics

Completed as the first dedicated CRS-aware pixel-semantics increment.

- Added raster grid metadata to source profiles: raster width/height, pixel
  width/height, CRS unit, projected/geographic CRS flags, and whether metric
  area requires projection.
- Added metric `pixel_area` only for projected CRS rasters, where the pixel size
  can be interpreted in the CRS linear unit.
- Added explicit `raster_grid_semantics` hints for projected metric grids,
  geographic degree grids, and unknown CRS grids.
- Added a geographic-CRS warning path so downstream business logic and AI agents
  do not treat degree-based pixel areas as square metres.
- Kept this increment non-transforming: MMFE records CRS-aware semantics but does
  not automatically reproject rasters, change pixel values, or run zonal
  aggregation.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_grid_semantics_for_projected_crs data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_grid_semantics_warn_for_geographic_crs -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource -q
```

---

## Roadmap Progress: STAC and ISO Raster Metadata Semantics

Completed as a metadata-evidence increment after CRS-aware grid semantics.

- Extended STAC sidecar parsing beyond platform/instrument/band metadata to
  capture collection, datetime, title, description, keywords, GSD, and
  `proj:epsg`.
- Added dependency-free ISO 19115-style XML sidecar parsing for common title,
  abstract, keywords, topic category, date stamp, and lineage statements.
- Added `metadata_title`, `metadata_description`, `metadata_keyword`,
  `metadata_topic`, `metadata_datetime`, `metadata_collection`,
  `metadata_lineage`, `raster_gsd`, and `projection_epsg` semantic hints.
- Fed normalized STAC/ISO text fields into deterministic raster theme inference,
  so authoritative sidecar metadata can classify a weakly named product as
  NDVI/vegetation index, elevation, slope, or land-cover classification.
- Kept the parser intentionally conservative: it covers high-value core fields
  without claiming complete ISO schema coverage or adding XML/STAC dependencies.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_reads_extended_stac_metadata data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_reads_iso_xml_sidecar_metadata -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource -q
```

---

## Roadmap Progress: Raster Feature Chip Summaries

Completed as the first raster-derived feature summary increment.

- Added deterministic center-window feature chip summaries to raster source
  profiles under `stats["feature_chips"]`.
- Added per-band chip min/max/mean/std and valid pixel counts.
- Added scaled chip statistics when band scale/offset metadata is available, so
  AI consumers can reason over physical/semantic values rather than only raw
  stored pixel values.
- Added dominant value summaries for low-cardinality classification chips,
  making land-cover/class rasters more useful for semantic review and retrieval.
- Added `raster_feature_chip` semantic hints marked as embedding-ready evidence.
- Kept this increment lightweight and dependency-free: it does not write chip
  image files, generate embeddings, or add a vision model runtime.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_builds_feature_chip_summary data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_feature_chip_summarizes_categorical_values -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource -q
```

---

## Roadmap Progress: AI Model Inference Semantic Sidecars

Completed as the first explicit bridge between deterministic MMFE semantics and
AI perception semantics.

- Added `.ai.json`, `.model.json`, and `.inference.json` sidecar ingestion for
  raster and point-cloud sources.
- Added a generic `model_inference` semantic level for labels produced by
  external AI models, such as cropland/forest from imagery or tree/building from
  point clouds.
- Preserved AI provenance in each semantic hint: model name, model version,
  model task, target, confidence, semantic domain, and evidence text.
- Allowed AI model observations to fill `semantic_domain` when deterministic
  metadata does not already provide one.
- Kept the boundary explicit: MMFE does not run remote-sensing classifiers,
  object detectors, or point-cloud segmentation models in this increment; it
  ingests and governs their outputs as semantic evidence.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource::test_profile_raster_ingests_ai_model_semantic_sidecar data_agent\test_fusion_engine.py::TestFusionSource::test_profile_point_cloud_ingests_ai_object_semantic_sidecar -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource -q
```

---

## Roadmap Progress: Third-Party AI Semantic Adapter Contract

Completed as the contract layer for integrating independent AI model runners.

- Added `data_agent/fusion/ai_semantics.py` as a dependency-free contract module
  for AI semantic sidecars.
- Added a model catalog covering practical external integration targets:
  Prithvi EO 2.0, TerraMind, SAM2+GroundingDINO, RandLA-Net, Pointcept/PTv3, and
  custom models.
- Added `build_ai_semantic_sidecar()` to normalize third-party observations into
  MMFE `.ai.json` documents with `semantic_level="model_inference"`.
- Added `validate_ai_semantic_sidecar()` so model runners can fail fast before
  MMFE ingests low-quality or malformed inference output.
- Added `write_ai_semantic_sidecar()` to write model outputs next to raster or
  point-cloud sources using the same sidecar path convention already consumed by
  profiling.
- Re-exported the helpers from both `data_agent.fusion` and
  `data_agent.fusion_engine` for backward-compatible use by tool wrappers.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_ai_semantics.py -q
```

---

## Roadmap Progress: AI Semantic Runner Wrapper Contract

Completed as the orchestration contract for independent model runners.

- Added `AI_SEMANTIC_RUNNER_SCHEMA = "mmfe.ai_runner.v1"` to describe external
  AI runner jobs without importing model runtimes or executing commands inside
  MMFE.
- Added `build_ai_semantic_runner_spec()` to normalize model id, task,
  source path, expected `.ai.json` output path, command arguments, model
  version, and runner parameters.
- Added `validate_ai_semantic_runner_spec()` to reject malformed runner specs
  and task/model mismatches before an external job is dispatched.
- Added `validate_ai_semantic_runner_output()` to read the expected sidecar
  file and apply the existing MMFE AI sidecar contract after a third-party
  model runner finishes.
- Re-exported the runner helpers from both `data_agent.fusion` and
  `data_agent.fusion_engine` so future tool wrappers can use the contract
  without depending on internal module paths.
- Kept the execution boundary strict: this increment does not download models,
  run Python scripts, invoke containers, or add Prithvi/SAM/Pointcept runtime
  dependencies. It defines how those independent tools are configured and how
  MMFE validates their semantic output.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_ai_semantics.py -q
```

---

## Roadmap Progress: Point-Cloud VLR/EVLR and LAZ Capability Semantics

Completed as the next point-cloud hard-source increment.

- Extended point-cloud profiling to extract LAS VLR and EVLR metadata summaries
  from readable `laspy` headers.
- Added `stats["las_metadata"]` with VLR/EVLR counts and capped record summaries
  including `user_id`, `record_id`, description, and record-data byte size.
- Added `point_cloud_metadata` semantic hints so downstream business review,
  AI retrieval, and governance tools can see that CRS, GeoTIFF projection keys,
  waveform metadata, lineage, or vendor metadata may exist in LAS records.
- Added explicit `.laz` capability reporting under `stats["laz"]` with
  compressed/readable/backend status.
- Preserved source identity for unreadable LAZ files and emitted a
  `point_cloud_capability` hint with `value="laz_backend_unavailable"` instead
  of silently degrading to an empty profile.
- Kept the increment dependency-free: MMFE still does not install LAZ backends
  or invoke PDAL. It reports the capability boundary so users and future tools
  can decide whether to provision `lazrs`, `laszip`, or a PDAL pipeline.

Verification used for this increment:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource::test_profile_point_cloud_extracts_vlr_and_evlr_metadata data_agent\test_fusion_engine.py::TestFusionSource::test_profile_laz_reports_backend_unavailable_without_losing_source_type -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py::TestFusionSource -q
```

Remaining hard parts are still real: very large point-cloud chunking, PDAL pipeline integration, concrete third-party model tool adapters/executors, production deployment guidance for LAZ decompression backends, and a separate optional publisher for pgvector/LanceDB.
