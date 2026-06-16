"""Tests for MMFE third-party AI semantic adapter contracts."""

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock


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

    def test_build_ai_semantic_runner_spec_renders_external_command(self):
        from data_agent.fusion.ai_semantics import (
            AI_SEMANTIC_RUNNER_SCHEMA,
            build_ai_semantic_runner_spec,
        )

        spec = build_ai_semantic_runner_spec(
            model_id="prithvi-eo-2",
            source_path="imagery/field_tile.tif",
            task="land_cover_classification",
            command_template=[
                "python",
                "run_prithvi.py",
                "--input",
                "{source_path}",
                "--output",
                "{output_path}",
                "--task",
                "{task}",
            ],
            output_path="imagery/field_tile.ai.json",
            model_version="2.0",
            parameters={"tile_size": 512},
        )

        self.assertEqual(spec["schema"], AI_SEMANTIC_RUNNER_SCHEMA)
        self.assertEqual(spec["integration_mode"], "external_command")
        self.assertEqual(spec["sidecar_schema"], "mmfe.ai_semantics.v1")
        self.assertEqual(spec["model"]["id"], "prithvi-eo-2")
        self.assertEqual(spec["model"]["task"], "land_cover_classification")
        self.assertEqual(spec["model"]["version"], "2.0")
        self.assertEqual(spec["expected_output_path"], "imagery/field_tile.ai.json")
        self.assertEqual(
            spec["command"],
            [
                "python",
                "run_prithvi.py",
                "--input",
                "imagery/field_tile.tif",
                "--output",
                "imagery/field_tile.ai.json",
                "--task",
                "land_cover_classification",
            ],
        )
        self.assertEqual(spec["parameters"]["tile_size"], 512)

    def test_validate_ai_semantic_runner_spec_reports_contract_errors(self):
        from data_agent.fusion.ai_semantics import validate_ai_semantic_runner_spec

        errors = validate_ai_semantic_runner_spec(
            {
                "schema": "mmfe.ai_runner.v1",
                "model": {"id": "prithvi-eo-2", "name": "Prithvi EO 2.0", "task": "tree_detection"},
                "source_path": "imagery/field_tile.tif",
                "expected_output_path": "imagery/field_tile.ai.json",
                "sidecar_schema": "mmfe.ai_semantics.v1",
                "integration_mode": "external_command",
                "command": ["python", "run_prithvi.py"],
            }
        )

        self.assertTrue(any("model.task" in error for error in errors))

    def test_validate_ai_semantic_runner_output_reads_and_checks_sidecar(self):
        from data_agent.fusion.ai_semantics import (
            build_ai_semantic_runner_spec,
            build_ai_semantic_sidecar,
            validate_ai_semantic_runner_output,
        )

        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "field_tile.tif")
            output_path = os.path.join(tmp, "field_tile.ai.json")
            spec = build_ai_semantic_runner_spec(
                model_id="custom-model",
                source_path=source_path,
                task="custom_semantic_inference",
                command_template=["python", "runner.py", "--input", "{source_path}", "--output", "{output_path}"],
                output_path=output_path,
            )
            sidecar = build_ai_semantic_sidecar(
                model_id="custom-model",
                observations=[
                    {
                        "target": "scene",
                        "type": "land_cover_class",
                        "value": "forest",
                        "confidence": 0.84,
                    }
                ],
                source_path=source_path,
            )
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f)

            result = validate_ai_semantic_runner_output(spec)

            self.assertTrue(result["valid"])
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["observation_count"], 1)
            self.assertEqual(result["sidecar"]["observations"][0]["value"], "forest")

    def test_validate_ai_semantic_runner_output_reports_missing_file(self):
        from data_agent.fusion.ai_semantics import (
            build_ai_semantic_runner_spec,
            validate_ai_semantic_runner_output,
        )

        spec = build_ai_semantic_runner_spec(
            model_id="custom-model",
            source_path="scan.las",
            task="custom_semantic_inference",
            command_template=["python", "runner.py", "--input", "{source_path}", "--output", "{output_path}"],
        )

        result = validate_ai_semantic_runner_output(spec)

        self.assertFalse(result["valid"])
        self.assertTrue(any("expected_output_path does not exist" in error for error in result["errors"]))

    def test_run_ai_semantic_runner_invokes_executor_and_validates_sidecar(self):
        from data_agent.fusion.ai_semantics import (
            build_ai_semantic_runner_spec,
            build_ai_semantic_sidecar,
            run_ai_semantic_runner,
        )

        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "field_tile.tif")
            output_path = os.path.join(tmp, "field_tile.ai.json")
            spec = build_ai_semantic_runner_spec(
                model_id="custom-model",
                source_path=source_path,
                task="custom_semantic_inference",
                command_template=["python", "runner.py", "--output", "{output_path}"],
                output_path=output_path,
            )
            sidecar = build_ai_semantic_sidecar(
                model_id="custom-model",
                observations=[
                    {
                        "target": "scene",
                        "type": "land_cover_class",
                        "value": "orchard",
                        "confidence": 0.82,
                    }
                ],
                source_path=source_path,
            )
            completed = subprocess.CompletedProcess(
                spec["command"],
                0,
                stdout="AI sidecar written",
                stderr="",
            )

            def executor(command, **kwargs):
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(sidecar, f)
                return completed

            result = run_ai_semantic_runner(spec, executor=executor)

            self.assertTrue(result["valid"])
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(result["command"], spec["command"])
            self.assertTrue(result["output_exists"])
            self.assertEqual(result["observation_count"], 1)
            self.assertEqual(result["sidecar"]["observations"][0]["value"], "orchard")
            self.assertIn("AI sidecar written", result["stdout"])

    def test_run_ai_semantic_runner_reports_process_failure(self):
        from data_agent.fusion.ai_semantics import (
            build_ai_semantic_runner_spec,
            run_ai_semantic_runner,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = os.path.join(tmp, "failed.ai.json")
            spec = build_ai_semantic_runner_spec(
                model_id="custom-model",
                source_path=os.path.join(tmp, "field_tile.tif"),
                task="custom_semantic_inference",
                command_template=["python", "runner.py", "--output", "{output_path}"],
                output_path=output_path,
            )
            completed = subprocess.CompletedProcess(
                spec["command"],
                2,
                stdout="",
                stderr="model failed",
            )

            result = run_ai_semantic_runner(spec, executor=Mock(return_value=completed))

            self.assertFalse(result["valid"])
            self.assertEqual(result["returncode"], 2)
            self.assertFalse(result["output_exists"])
            self.assertTrue(any("returncode" in error for error in result["errors"]))
            self.assertTrue(any("expected_output_path does not exist" in error for error in result["errors"]))

    def test_ai_semantic_runner_helpers_are_reexported(self):
        from data_agent.fusion import build_ai_semantic_runner_spec, run_ai_semantic_runner
        from data_agent.fusion_engine import (
            run_ai_semantic_runner as proxy_run_ai_semantic_runner,
            validate_ai_semantic_runner_output,
        )

        self.assertTrue(callable(build_ai_semantic_runner_spec))
        self.assertTrue(callable(run_ai_semantic_runner))
        self.assertTrue(callable(proxy_run_ai_semantic_runner))
        self.assertTrue(callable(validate_ai_semantic_runner_output))


if __name__ == "__main__":
    unittest.main()
