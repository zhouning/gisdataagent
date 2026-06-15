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
        self.assertEqual(len(ai_metadata["chunks"]), 2)
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
