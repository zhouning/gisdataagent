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


def _alignment_sources() -> list[FusionSource]:
    return [
        FusionSource(
            file_path="/data/source_a.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=2,
            columns=[
                {"name": "面积", "dtype": "float64", "null_pct": 0},
                {"name": "DLBM", "dtype": "object", "null_pct": 0},
            ],
            stats={"面积": {"min": 1000.0, "max": 2000.0, "mean": 1500.0}},
        ),
        FusionSource(
            file_path="/data/source_b.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=2,
            columns=[
                {"name": "AREA", "dtype": "float64", "null_pct": 0},
                {"name": "land_use_code", "dtype": "object", "null_pct": 0},
            ],
            stats={"AREA": {"min": 1000.0, "max": 2000.0, "mean": 1500.0}},
        ),
    ]


def _document_semantic_source() -> FusionSource:
    return FusionSource(
        file_path="/docs/project_brief.md",
        data_type="document",
        row_count=1,
        columns=[
            {"name": "title", "dtype": "text", "null_pct": 0},
            {"name": "body", "dtype": "text", "null_pct": 0},
        ],
        semantic_domain="project_knowledge",
        semantic_hints=[
            {
                "type": "document_theme",
                "value": "major_project",
                "confidence": 0.82,
                "evidence": ["title mentions major project"],
            }
        ],
        modality="text",
        media_type="text/markdown",
        adapter_family="generic",
    )


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

    def test_source_manifest_preserves_universal_modality_metadata(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            [_document_semantic_source()],
            strategy="semantic_context_join",
            config={"enabled": True, "use_ontology": False},
        )

        source = manifest["sources"][0]
        self.assertEqual(source["data_type"], "document")
        self.assertEqual(source["modality"], "text")
        self.assertEqual(source["media_type"], "text/markdown")
        self.assertEqual(source["adapter_family"], "generic")
        self.assertEqual(source["semantic_hints"][0]["value"], "major_project")

    def test_manifest_v11_schema_and_field_contracts(self):
        from data_agent.fusion.semantic_product import (
            SEMANTIC_PRODUCT_SCHEMA,
            build_semantic_fusion_product,
            validate_semantic_product_manifest,
        )

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _semantic_sources(),
            strategy="spatial_join",
            config={"enabled": True, "derive_fields": True, "infer_fields": True},
        )

        self.assertEqual(manifest["version"], "1.1")
        self.assertTrue(manifest["product_id"].startswith("sfp-"))
        self.assertEqual(SEMANTIC_PRODUCT_SCHEMA["title"], "MMFE Semantic Fusion Product")
        self.assertEqual(validate_semantic_product_manifest(manifest), [])

        contracts = {item["field"]: item for item in manifest["field_contracts"]}
        self.assertEqual(contracts["area"]["semantic_role"], "source_attribute")
        self.assertEqual(contracts["building_height"]["semantic_role"], "derived")
        self.assertEqual(contracts["slope_class"]["semantic_role"], "inferred")

    def test_manifest_validation_reports_missing_required_keys(self):
        from data_agent.fusion.semantic_product import (
            build_semantic_fusion_product,
            validate_semantic_product_manifest,
        )

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _semantic_sources(),
            strategy="spatial_join",
            config={"enabled": True},
        )
        broken = dict(manifest)
        broken.pop("lineage")

        errors = validate_semantic_product_manifest(broken)

        self.assertIn("missing required property: lineage", errors)

    def test_field_contracts_include_value_profiles(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _semantic_sources(),
            strategy="spatial_join",
            config={"enabled": True},
        )

        contracts = {item["field"]: item for item in manifest["field_contracts"]}
        area_profile = contracts["area"]["value_profile"]
        self.assertEqual(area_profile["kind"], "numeric")
        self.assertEqual(area_profile["min"], 1000.0)
        self.assertEqual(area_profile["max"], 2000.0)

        parcel_profile = contracts["parcel_id"]["value_profile"]
        self.assertEqual(parcel_profile["kind"], "categorical")
        self.assertEqual(parcel_profile["unique_count"], 2)
        self.assertEqual(parcel_profile["samples"], ["P1", "P2"])

    def test_semantic_mappings_include_alignment_evidence(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _alignment_sources(),
            strategy="spatial_join",
            field_matches=[
                {
                    "left": "面积",
                    "right": "AREA",
                    "confidence": 0.85,
                    "match_type": "ontology",
                    "group_id": "area",
                }
            ],
            config={"enabled": True},
        )

        mapping = manifest["semantic_mappings"][0]
        self.assertEqual(mapping["confidence_band"], "high")
        self.assertEqual(mapping["source_profile"]["dtype"], "float64")
        self.assertEqual(mapping["target_profile"]["dtype"], "float64")
        self.assertIn(
            {"type": "ontology", "detail": "same ontology group: area"},
            mapping["evidence"],
        )
        self.assertIn("面积 -> AREA", mapping["explanation"])

    def test_semantic_mapping_alignment_score_decision(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _alignment_sources(),
            strategy="spatial_join",
            field_matches=[
                {
                    "left": "面积",
                    "right": "AREA",
                    "confidence": 0.85,
                    "match_type": "ontology",
                    "group_id": "area",
                },
                {
                    "left": "DLBM",
                    "right": "AREA",
                    "confidence": 0.55,
                    "match_type": "fuzzy",
                },
            ],
            config={"enabled": True},
        )

        accepted = manifest["semantic_mappings"][0]["alignment_score"]
        self.assertEqual(accepted["decision"], "accept")
        self.assertGreaterEqual(accepted["score"], 0.85)
        self.assertEqual(accepted["components"]["dtype_compatibility"], 1.0)

        rejected = manifest["semantic_mappings"][1]["alignment_score"]
        self.assertEqual(rejected["decision"], "reject")
        self.assertLess(rejected["score"], 0.6)
        self.assertEqual(rejected["components"]["dtype_compatibility"], 0.0)

    def test_semantic_mappings_include_document_context_evidence(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _alignment_sources(),
            strategy="spatial_join",
            field_matches=[
                {
                    "left": "DLBM",
                    "right": "land_use_code",
                    "confidence": 0.72,
                    "match_type": "fuzzy",
                }
            ],
            config={
                "enabled": True,
                "document_context": {
                    "source_metadata": [
                        {
                            "file": "land_dictionary.xlsx",
                            "field_definitions": [
                                {
                                    "field": "DLBM",
                                    "name": "land_use_code",
                                    "meaning": "Domain dictionary defines DLBM as the land use classification code.",
                                    "aliases": ["land_use_code", "land code"],
                                }
                            ],
                        }
                    ]
                },
            },
        )

        mapping = manifest["semantic_mappings"][0]
        doc_evidence = [
            item for item in mapping["evidence"]
            if item.get("type") == "document_context"
        ]
        self.assertEqual(len(doc_evidence), 1)
        self.assertEqual(doc_evidence[0]["source"], "land_dictionary.xlsx")
        self.assertEqual(
            mapping["alignment_score"]["components"]["document_context_support"],
            1.0,
        )
        self.assertEqual(mapping["alignment_score"]["decision"], "accept")

    def test_ai_metadata_summarizes_alignment_decisions(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _alignment_sources(),
            strategy="spatial_join",
            field_matches=[
                {
                    "left": "面积",
                    "right": "AREA",
                    "confidence": 0.85,
                    "match_type": "ontology",
                    "group_id": "area",
                },
                {
                    "left": "DLBM",
                    "right": "AREA",
                    "confidence": 0.55,
                    "match_type": "fuzzy",
                },
            ],
            config={"enabled": True},
        )

        summary = manifest["ai_metadata"]["alignment_summary"]
        self.assertEqual(summary["total_mappings"], 2)
        self.assertEqual(summary["decisions"]["accept"], 1)
        self.assertEqual(summary["decisions"]["reject"], 1)
        self.assertIn("accepted mappings: 1", manifest["ai_metadata"]["retrieval_text"])

    def test_ai_metadata_includes_alignment_review_items(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            _alignment_sources(),
            strategy="spatial_join",
            field_matches=[
                {
                    "left": "闈㈢Н",
                    "right": "AREA",
                    "confidence": 0.85,
                    "match_type": "ontology",
                    "group_id": "area",
                },
                {
                    "left": "DLBM",
                    "right": "AREA",
                    "confidence": 0.55,
                    "match_type": "fuzzy",
                },
            ],
            config={"enabled": True},
        )

        review = manifest["ai_metadata"]["alignment_review"]
        self.assertTrue(review["requires_human_review"])
        self.assertEqual(review["review_item_count"], 1)
        self.assertEqual(review["items"][0]["source_field"], "DLBM")
        self.assertEqual(review["items"][0]["target_field"], "AREA")
        self.assertIn("dtype_conflict", review["items"][0]["reason_codes"])
        self.assertIn("review items: 1", manifest["ai_metadata"]["retrieval_text"])

    def test_source_manifest_carries_raster_semantic_hints(self):
        from data_agent.fusion.semantic_product import build_semantic_fusion_product

        sources = [
            FusionSource(
                file_path="/data/city_ndvi_2024.tif",
                data_type="raster",
                crs="EPSG:4326",
                columns=[{"name": "band_1", "dtype": "float32", "null_pct": 0}],
                semantic_domain="remote_sensing",
                semantic_hints=[
                    {
                        "type": "raster_theme",
                        "value": "ndvi",
                        "confidence": 0.95,
                        "evidence": [
                            "filename contains ndvi",
                            "band_1 description contains NDVI",
                        ],
                    },
                    {
                        "type": "band_semantic",
                        "field": "band_1",
                        "value": "ndvi",
                        "confidence": 0.95,
                        "evidence": ["band_1 tags contain vegetation index"],
                    },
                ],
            )
        ]

        _, manifest = build_semantic_fusion_product(
            _semantic_test_gdf(),
            sources,
            strategy="zonal_statistics",
            config={"enabled": True},
        )

        source_manifest = manifest["sources"][0]
        self.assertEqual(source_manifest["semantic_domain"], "remote_sensing")
        self.assertEqual(source_manifest["semantic_hints"][0]["value"], "ndvi")
        self.assertEqual(source_manifest["semantic_hints"][1]["field"], "band_1")

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
        self.assertEqual(len(ai_metadata["chunks"]), 2)
        self.assertIn("nearest_join", ai_metadata["chunks"][0]["text"])

    def test_write_manifest_next_to_output(self):
        from data_agent.fusion.semantic_product import (
            build_semantic_fusion_product,
            write_semantic_product_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = os.path.join(tmp, "fused.geojson")
            _, manifest = build_semantic_fusion_product(
                _semantic_test_gdf(),
                _semantic_sources(),
                strategy="spatial_join",
                config={"enabled": True},
            )
            manifest_path = write_semantic_product_manifest(manifest, output_path)
            self.assertTrue(manifest_path.endswith(".semantic.json"))
            self.assertTrue(os.path.exists(manifest_path))
            with open(manifest_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["product_type"], "semantic_fusion_product")
            self.assertEqual(loaded["business_output"]["path"], output_path)


if __name__ == "__main__":
    unittest.main()
