"""Tests for MMFE third-party AI semantic adapter contracts."""

import json
import os
import tempfile
import unittest


class TestAISemanticAdapters(unittest.TestCase):
    def test_model_catalog_describes_external_capabilities(self):
        from data_agent.fusion.ai_semantics import get_ai_semantic_model_catalog

        catalog = get_ai_semantic_model_catalog()
        model_ids = {model["id"] for model in catalog}

        self.assertIn("prithvi-eo-2", model_ids)
        self.assertIn("sam2-grounding-dino", model_ids)
        self.assertIn("pointcept-ptv3", model_ids)
        prithvi = next(model for model in catalog if model["id"] == "prithvi-eo-2")
        self.assertEqual(prithvi["source_type"], "raster")
        self.assertIn("land_cover_classification", prithvi["tasks"])
        self.assertEqual(prithvi["integration_mode"], "external_sidecar")

    def test_build_ai_semantic_sidecar_normalizes_observations(self):
        from data_agent.fusion.ai_semantics import build_ai_semantic_sidecar

        sidecar = build_ai_semantic_sidecar(
            model_id="prithvi-eo-2",
            observations=[
                {
                    "target": "scene",
                    "type": "land_cover_class",
                    "label": "cropland",
                    "confidence": "0.91",
                    "domain": "land_cover",
                    "evidence": "fine tuned crop classifier",
                }
            ],
            source_path="sample.tif",
        )

        self.assertEqual(sidecar["schema"], "mmfe.ai_semantics.v1")
        self.assertEqual(sidecar["source_path"], "sample.tif")
        self.assertEqual(sidecar["model"]["id"], "prithvi-eo-2")
        observation = sidecar["observations"][0]
        self.assertEqual(observation["value"], "cropland")
        self.assertEqual(observation["confidence"], 0.91)
        self.assertEqual(observation["semantic_level"], "model_inference")
        self.assertEqual(observation["evidence"], ["fine tuned crop classifier"])

    def test_validate_ai_semantic_sidecar_reports_contract_errors(self):
        from data_agent.fusion.ai_semantics import validate_ai_semantic_sidecar

        errors = validate_ai_semantic_sidecar(
            {
                "schema": "mmfe.ai_semantics.v1",
                "model": {"id": "custom-model"},
                "observations": [
                    {"target": "scene", "type": "land_cover_class"},
                    {"target": "object:1", "value": "tree", "confidence": 1.5},
                ],
            }
        )

        self.assertTrue(any("model.name" in error for error in errors))
        self.assertTrue(any("observations[0].value" in error for error in errors))
        self.assertTrue(any("observations[1].confidence" in error for error in errors))

    def test_write_ai_semantic_sidecar_next_to_source(self):
        from data_agent.fusion.ai_semantics import (
            build_ai_semantic_sidecar,
            write_ai_semantic_sidecar,
        )

        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "urban_scan.las")
            sidecar = build_ai_semantic_sidecar(
                model_id="pointcept-ptv3",
                observations=[
                    {
                        "target": "object:42",
                        "type": "object_class",
                        "value": "building",
                        "confidence": 0.93,
                        "domain": "lidar",
                    }
                ],
                source_path=source_path,
            )

            out_path = write_ai_semantic_sidecar(sidecar, source_path)

            self.assertTrue(out_path.endswith(".ai.json"))
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["observations"][0]["value"], "building")

    def test_ai_semantic_helpers_are_reexported(self):
        from data_agent.fusion import build_ai_semantic_sidecar
        from data_agent.fusion_engine import write_ai_semantic_sidecar

        self.assertTrue(callable(build_ai_semantic_sidecar))
        self.assertTrue(callable(write_ai_semantic_sidecar))


if __name__ == "__main__":
    unittest.main()
