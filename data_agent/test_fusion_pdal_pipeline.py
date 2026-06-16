"""Tests for MMFE PDAL pipeline planning contracts."""

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock


class TestPdalPipelineContracts(unittest.TestCase):
    def test_build_point_cloud_chunk_artifact_manifest_from_chunking_plan(self):
        from data_agent.fusion.pdal_pipeline import (
            POINT_CLOUD_CHUNK_ARTIFACT_SCHEMA,
            build_point_cloud_chunk_artifact_manifest,
        )

        source_profile = {
            "file_path": "input/urban_scan.laz",
            "crs": "EPSG:32650",
            "stats": {
                "chunking": {
                    "required": True,
                    "strategy": "point_cloud_chunk_iterator",
                    "point_count": 1_250_000,
                    "chunk_size_points": 500_000,
                    "chunk_count": 3,
                    "last_chunk_points": 250_000,
                    "reasons": ["point_count 1250000 exceeds threshold 500000"],
                },
                "laz": {
                    "compressed": True,
                    "readable": True,
                    "backend_available": True,
                },
            },
        }

        manifest = build_point_cloud_chunk_artifact_manifest(
            source_profile,
            artifact_dir="chunks/urban_scan",
            output_format="copc_laz",
            metadata={"run_id": "mmfe-test"},
        )

        self.assertEqual(manifest["schema"], POINT_CLOUD_CHUNK_ARTIFACT_SCHEMA)
        self.assertEqual(manifest["source"]["path"], "input/urban_scan.laz")
        self.assertEqual(manifest["source"]["crs"], "EPSG:32650")
        self.assertEqual(manifest["artifact_dir"], "chunks/urban_scan")
        self.assertEqual(manifest["output_format"], "copc_laz")
        self.assertEqual(manifest["chunking"]["chunk_count"], 3)
        self.assertEqual(len(manifest["chunks"]), 3)
        self.assertEqual(manifest["chunks"][0]["chunk_id"], "chunk-000001")
        self.assertEqual(manifest["chunks"][0]["point_start"], 0)
        self.assertEqual(manifest["chunks"][0]["point_count"], 500_000)
        self.assertEqual(manifest["chunks"][0]["status"], "planned")
        self.assertTrue(manifest["chunks"][0]["artifact_path"].endswith("chunk-000001.copc.laz"))
        self.assertEqual(manifest["chunks"][2]["point_start"], 1_000_000)
        self.assertEqual(manifest["chunks"][2]["point_count"], 250_000)
        self.assertTrue(manifest["embedding_ready"])
        self.assertEqual(manifest["metadata"]["run_id"], "mmfe-test")
        self.assertTrue(
            any(
                hint.get("type") == "point_cloud_processing"
                and hint.get("value") == "chunk_artifacts_planned"
                for hint in manifest["semantic_hints"]
            )
        )

    def test_validate_point_cloud_chunk_artifact_manifest_reports_errors(self):
        from data_agent.fusion.pdal_pipeline import validate_point_cloud_chunk_artifact_manifest

        errors = validate_point_cloud_chunk_artifact_manifest(
            {
                "schema": "mmfe.point_cloud_chunks.v1",
                "source": {"path": ""},
                "artifact_dir": "",
                "chunking": {"required": True, "chunk_count": 2},
                "chunks": [
                    {"chunk_id": "chunk-000001", "point_start": 0, "point_count": 100},
                ],
            }
        )

        self.assertTrue(any("source.path" in error for error in errors))
        self.assertTrue(any("artifact_dir" in error for error in errors))
        self.assertTrue(any("chunks length" in error for error in errors))

    def test_write_point_cloud_chunk_artifact_manifest_outputs_json(self):
        from data_agent.fusion.pdal_pipeline import (
            build_point_cloud_chunk_artifact_manifest,
            write_point_cloud_chunk_artifact_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            source_profile = {
                "file_path": os.path.join(tmp, "small_scan.las"),
                "stats": {
                    "chunking": {
                        "required": False,
                        "point_count": 12,
                        "chunk_size_points": 500_000,
                        "chunk_count": 1,
                    }
                },
            }
            artifact_dir = os.path.join(tmp, "small_scan_chunks")
            manifest = build_point_cloud_chunk_artifact_manifest(
                source_profile,
                artifact_dir=artifact_dir,
                output_format="las",
            )

            manifest_path = write_point_cloud_chunk_artifact_manifest(manifest)

            self.assertTrue(manifest_path.endswith(".chunks.json"))
            self.assertTrue(os.path.exists(manifest_path))
            with open(manifest_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["schema"], "mmfe.point_cloud_chunks.v1")
            self.assertEqual(loaded["chunks"][0]["point_count"], 12)

    def test_point_cloud_chunk_artifact_helpers_are_reexported(self):
        from data_agent.fusion import build_point_cloud_chunk_artifact_manifest
        from data_agent.fusion_engine import validate_point_cloud_chunk_artifact_manifest

        self.assertTrue(callable(build_point_cloud_chunk_artifact_manifest))
        self.assertTrue(callable(validate_point_cloud_chunk_artifact_manifest))

    def test_build_pdal_pipeline_spec_uses_chunking_and_laz_metadata(self):
        from data_agent.fusion.pdal_pipeline import (
            PDAL_PIPELINE_SCHEMA,
            build_pdal_pipeline_spec,
        )

        source_profile = {
            "file_path": "input/urban_scan.laz",
            "crs": "EPSG:32650",
            "stats": {
                "chunking": {
                    "required": True,
                    "chunk_size_points": 500_000,
                    "chunk_count": 3,
                    "reasons": ["point_count 1250000 exceeds threshold 500000"],
                },
                "laz": {
                    "compressed": True,
                    "readable": True,
                    "backend_available": True,
                },
            },
        }

        spec = build_pdal_pipeline_spec(
            source_profile,
            output_path="output/urban_scan.copc.laz",
            pipeline_task="normalize_and_tile",
            filters=[
                {"type": "filters.reprojection", "out_srs": "EPSG:3857"},
                {"type": "filters.range", "limits": "Classification![7:7]"},
            ],
            writer_options={"forward": "all"},
        )

        self.assertEqual(spec["schema"], PDAL_PIPELINE_SCHEMA)
        self.assertEqual(spec["execution_mode"], "external_pdal")
        self.assertEqual(spec["pipeline_task"], "normalize_and_tile")
        self.assertEqual(spec["source"]["path"], "input/urban_scan.laz")
        self.assertEqual(spec["source"]["compressed"], True)
        self.assertEqual(spec["chunking"]["required"], True)
        self.assertEqual(spec["chunking"]["chunk_count"], 3)
        self.assertEqual(spec["pipeline"][0]["type"], "readers.las")
        self.assertEqual(spec["pipeline"][-1]["type"], "writers.copc")
        self.assertEqual(spec["pipeline"][-1]["filename"], "output/urban_scan.copc.laz")
        self.assertEqual(spec["pipeline"][-1]["forward"], "all")
        self.assertTrue(
            any(
                hint.get("type") == "point_cloud_processing"
                and hint.get("value") == "pdal_pipeline_required"
                for hint in spec["semantic_hints"]
            )
        )

    def test_validate_pdal_pipeline_spec_reports_errors(self):
        from data_agent.fusion.pdal_pipeline import validate_pdal_pipeline_spec

        errors = validate_pdal_pipeline_spec(
            {
                "schema": "mmfe.pdal_pipeline.v1",
                "source": {"path": ""},
                "pipeline": [{"type": "readers.las"}],
                "chunking": {"required": True, "chunk_count": 0},
            }
        )

        self.assertTrue(any("source.path" in error for error in errors))
        self.assertTrue(any("pipeline must end with a writer" in error for error in errors))
        self.assertTrue(any("chunking.chunk_count" in error for error in errors))

    def test_write_pdal_pipeline_spec_outputs_json(self):
        from data_agent.fusion.pdal_pipeline import (
            build_pdal_pipeline_spec,
            write_pdal_pipeline_spec,
        )

        with tempfile.TemporaryDirectory() as tmp:
            source_profile = {
                "file_path": os.path.join(tmp, "small_scan.las"),
                "stats": {"chunking": {"required": False, "chunk_count": 1}},
            }
            output_path = os.path.join(tmp, "small_scan.las")
            spec = build_pdal_pipeline_spec(source_profile, output_path=output_path)

            path = write_pdal_pipeline_spec(spec, output_path)

            self.assertTrue(path.endswith(".pdal.json"))
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["schema"], "mmfe.pdal_pipeline.v1")
            self.assertEqual(loaded["pipeline"][0]["filename"], source_profile["file_path"])

    def test_pdal_pipeline_helpers_are_reexported(self):
        from data_agent.fusion import build_pdal_pipeline_spec
        from data_agent.fusion_engine import validate_pdal_pipeline_spec

        self.assertTrue(callable(build_pdal_pipeline_spec))
        self.assertTrue(callable(validate_pdal_pipeline_spec))

    def test_build_pdal_runner_spec_renders_command(self):
        from data_agent.fusion.pdal_pipeline import (
            build_pdal_pipeline_spec,
            build_pdal_runner_spec,
            write_pdal_pipeline_spec,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = os.path.join(tmp, "urban_scan.copc.laz")
            source_profile = {
                "file_path": os.path.join(tmp, "urban_scan.laz"),
                "stats": {"chunking": {"required": True, "chunk_count": 3}},
            }
            pipeline = build_pdal_pipeline_spec(source_profile, output_path=output_path)
            pipeline_path = write_pdal_pipeline_spec(pipeline, output_path)

            runner = build_pdal_runner_spec(pipeline, pipeline_path)

            self.assertEqual(runner["schema"], "mmfe.pdal_runner.v1")
            self.assertEqual(runner["execution_mode"], "external_pdal")
            self.assertEqual(runner["pipeline_path"], pipeline_path)
            self.assertEqual(runner["expected_output_path"], output_path)
            self.assertEqual(runner["command"], ["pdal", "pipeline", pipeline_path])
            self.assertEqual(runner["chunking"]["chunk_count"], 3)

    def test_run_pdal_pipeline_invokes_runner_and_validates_output(self):
        from data_agent.fusion.pdal_pipeline import (
            build_pdal_pipeline_spec,
            build_pdal_runner_spec,
            run_pdal_pipeline,
            write_pdal_pipeline_spec,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = os.path.join(tmp, "small_scan.las")
            source_profile = {
                "file_path": os.path.join(tmp, "small_scan_source.las"),
                "stats": {"chunking": {"required": False, "chunk_count": 1}},
            }
            pipeline = build_pdal_pipeline_spec(source_profile, output_path=output_path)
            pipeline_path = write_pdal_pipeline_spec(pipeline, output_path)
            runner = build_pdal_runner_spec(pipeline, pipeline_path)
            completed = subprocess.CompletedProcess(
                runner["command"],
                0,
                stdout="PDAL pipeline completed",
                stderr="",
            )

            def executor(command, **kwargs):
                with open(output_path, "wb") as f:
                    f.write(b"LAS")
                return completed

            result = run_pdal_pipeline(runner, executor=executor)

            self.assertTrue(result["valid"])
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(result["command"], runner["command"])
            self.assertEqual(result["expected_output_path"], output_path)
            self.assertTrue(result["output_exists"])
            self.assertIn("PDAL pipeline completed", result["stdout"])

    def test_run_pdal_pipeline_reports_process_failure(self):
        from data_agent.fusion.pdal_pipeline import (
            build_pdal_pipeline_spec,
            build_pdal_runner_spec,
            run_pdal_pipeline,
            write_pdal_pipeline_spec,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = os.path.join(tmp, "failed_scan.las")
            source_profile = {
                "file_path": os.path.join(tmp, "failed_scan_source.las"),
                "stats": {"chunking": {"required": False, "chunk_count": 1}},
            }
            pipeline = build_pdal_pipeline_spec(source_profile, output_path=output_path)
            pipeline_path = write_pdal_pipeline_spec(pipeline, output_path)
            runner = build_pdal_runner_spec(pipeline, pipeline_path)
            completed = subprocess.CompletedProcess(
                runner["command"],
                2,
                stdout="",
                stderr="reader error",
            )

            result = run_pdal_pipeline(runner, executor=Mock(return_value=completed))

            self.assertFalse(result["valid"])
            self.assertEqual(result["returncode"], 2)
            self.assertTrue(any("returncode" in error for error in result["errors"]))
            self.assertTrue(any("expected output was not created" in error for error in result["errors"]))

    def test_pdal_runner_helpers_are_reexported(self):
        from data_agent.fusion import build_pdal_runner_spec
        from data_agent.fusion_engine import run_pdal_pipeline

        self.assertTrue(callable(build_pdal_runner_spec))
        self.assertTrue(callable(run_pdal_pipeline))


if __name__ == "__main__":
    unittest.main()
