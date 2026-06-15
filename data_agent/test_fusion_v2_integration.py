"""Integration tests for Fusion v2.0 — end-to-end pipeline verification.

Covers: execution with v2 features enabled/disabled, backward compatibility,
        toolset registration, API route mounting, module imports.
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon


def _make_two_test_files(tmp_dir: str) -> tuple[str, str]:
    """Create two small GeoJSON files for fusion testing."""
    gdf1 = gpd.GeoDataFrame({
        "ID": [1, 2, 3],
        "VALUE": [10.0, 20.0, 30.0],
    }, geometry=[
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
    ], crs="EPSG:4326")
    path1 = os.path.join(tmp_dir, "source1.geojson")
    gdf1.to_file(path1, driver="GeoJSON")

    gdf2 = gpd.GeoDataFrame({
        "ID": [1, 2, 3],
        "SCORE": [100.0, 200.0, 300.0],
    }, geometry=[
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
    ], crs="EPSG:4326")
    path2 = os.path.join(tmp_dir, "source2.geojson")
    gdf2.to_file(path2, driver="GeoJSON")

    return path1, path2


class TestModuleImports(unittest.TestCase):
    """Verify all v2 modules can be imported."""

    def test_import_explainability(self):
        from data_agent.fusion.explainability import (
            add_explainability_fields, generate_quality_heatmap,
            generate_lineage_trace, explain_decision,
        )

    def test_import_temporal(self):
        from data_agent.fusion.temporal import TemporalAligner

    def test_import_ontology(self):
        from data_agent.fusion.ontology import OntologyReasoner

    def test_import_semantic_llm(self):
        from data_agent.fusion.semantic_llm import SemanticLLM

    def test_import_kg_integration(self):
        from data_agent.fusion.kg_integration import KGIntegration

    def test_import_conflict_resolver(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver

    def test_imports_from_package(self):
        """All v2 symbols exportable from fusion package."""
        from data_agent.fusion import (
            TemporalAligner, OntologyReasoner, SemanticLLM,
            KGIntegration, ConflictResolver,
            add_explainability_fields, generate_quality_heatmap,
            generate_lineage_trace, explain_decision,
            COL_CONFIDENCE, COL_SOURCES, COL_CONFLICTS, COL_METHOD,
        )


class TestExecuteFusionV2(unittest.TestCase):
    """Test execute_fusion with v2 parameters."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.tmp):
            shutil.rmtree(self.tmp)

    @patch("data_agent.fusion.db.record_operation")
    @patch("data_agent.fusion.execution._generate_output_path")
    def test_backward_compatible(self, mock_path, mock_record):
        """Existing call without v2 params works unchanged."""
        from data_agent.fusion.execution import execute_fusion
        from data_agent.fusion.profiling import profile_source
        from data_agent.fusion.alignment import align_sources
        from data_agent.fusion.compatibility import assess_compatibility

        path1, path2 = _make_two_test_files(self.tmp)
        mock_path.return_value = os.path.join(self.tmp, "out.geojson")

        s1 = profile_source(path1)
        s2 = profile_source(path2)
        report = assess_compatibility([s1, s2])
        aligned, _ = align_sources([s1, s2], report)
        result = execute_fusion(aligned, "spatial_join", [s1, s2])

        self.assertGreater(result.row_count, 0)
        self.assertEqual(result.explainability_path, "")
        self.assertEqual(result.temporal_log, [])
        self.assertEqual(result.conflict_summary, {})

    @patch("data_agent.fusion.db.record_operation")
    @patch("data_agent.fusion.execution._generate_output_path")
    @patch("data_agent.gis_processors._generate_output_path")
    def test_with_explainability(self, mock_gis_path, mock_exec_path, mock_record):
        """Test with enable_explainability=True."""
        from data_agent.fusion.execution import execute_fusion
        from data_agent.fusion.profiling import profile_source
        from data_agent.fusion.alignment import align_sources
        from data_agent.fusion.compatibility import assess_compatibility

        path1, path2 = _make_two_test_files(self.tmp)
        out_path = os.path.join(self.tmp, "out.geojson")
        heatmap_path = os.path.join(self.tmp, "heatmap.geojson")
        mock_exec_path.return_value = out_path
        mock_gis_path.return_value = heatmap_path

        s1 = profile_source(path1)
        s2 = profile_source(path2)
        report = assess_compatibility([s1, s2])
        aligned, _ = align_sources([s1, s2], report)
        result = execute_fusion(
            aligned, "spatial_join", [s1, s2],
            enable_explainability=True,
        )

        self.assertGreater(result.row_count, 0)
        # Explainability columns should be in the output
        output_gdf = gpd.read_file(result.output_path)
        self.assertIn("_fusion_confidence", output_gdf.columns)
        self.assertIn("_fusion_method", output_gdf.columns)

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

    @patch("data_agent.fusion.db.record_operation")
    @patch("data_agent.fusion.execution._generate_output_path")
    def test_semantic_summary_includes_alignment_review_count(self, mock_path, mock_record):
        """execute_fusion exposes semantic alignment review count in summary."""
        from data_agent.fusion.execution import execute_fusion
        from data_agent.fusion.models import CompatibilityReport, FusionSource

        out_path = os.path.join(self.tmp, "out.geojson")
        mock_path.return_value = out_path
        gdf = gpd.GeoDataFrame(
            {
                "DLBM": ["0101", "0201"],
                "AREA": [1000.0, 2000.0],
            },
            geometry=[Point(0, 0), Point(1, 1)],
            crs="EPSG:4326",
        )
        source_a = FusionSource(
            file_path="source_a.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=2,
            columns=[{"name": "DLBM", "dtype": "object", "null_pct": 0}],
        )
        source_b = FusionSource(
            file_path="source_b.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=2,
            columns=[{"name": "AREA", "dtype": "float64", "null_pct": 0}],
        )
        report = CompatibilityReport(
            field_matches=[
                {
                    "left": "DLBM",
                    "right": "AREA",
                    "confidence": 0.55,
                    "match_type": "fuzzy",
                }
            ]
        )

        result = execute_fusion(
            [("vector", gdf), ("vector", gdf.copy())],
            "spatial_join",
            [source_a, source_b],
            report=report,
            semantic_config={"enabled": True, "feature_sample_limit": 1},
        )

        self.assertEqual(result.semantic_summary["alignment_review_items"], 1)
        self.assertTrue(result.semantic_summary["requires_human_review"])


class TestToolsetRegistration(unittest.TestCase):
    """Verify toolset has v2 tools registered."""

    def test_fusion_toolset_has_v2_tools(self):
        from data_agent.toolsets.fusion_tools import _ALL_FUNCS
        func_names = [f.__name__ for f in _ALL_FUNCS]
        self.assertIn("standardize_timestamps", func_names)
        self.assertIn("validate_temporal_consistency", func_names)
        # Original tools still present
        self.assertIn("profile_fusion_sources", func_names)
        self.assertIn("fuse_datasets", func_names)
        self.assertEqual(len(_ALL_FUNCS), 7)


class TestAPIRoutes(unittest.TestCase):
    """Verify API routes are properly defined."""

    def test_fusion_v2_routes_list(self):
        from data_agent.api.fusion_v2_routes import get_fusion_v2_routes
        routes = get_fusion_v2_routes()
        self.assertEqual(len(routes), 5)
        paths = [r.path for r in routes]
        self.assertIn("/api/fusion/quality/{operation_id:int}", paths)
        self.assertIn("/api/fusion/lineage/{operation_id:int}", paths)
        self.assertIn("/api/fusion/conflicts/{operation_id:int}", paths)
        self.assertIn("/api/fusion/operations", paths)
        self.assertIn("/api/fusion/temporal-preview", paths)

    def test_routes_in_frontend_api(self):
        """Verify fusion v2 routes are mounted in get_frontend_api_routes."""
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/fusion/operations", paths)


class TestFusionResultModel(unittest.TestCase):
    """Verify FusionResult model has v2 fields."""

    def test_v2_fields_exist(self):
        from data_agent.fusion.models import FusionResult
        r = FusionResult()
        self.assertEqual(r.explainability_path, "")
        self.assertEqual(r.conflict_summary, {})
        self.assertEqual(r.temporal_log, [])

    def test_v2_fields_settable(self):
        from data_agent.fusion.models import FusionResult
        r = FusionResult(
            explainability_path="/tmp/heatmap.geojson",
            conflict_summary={"resolved": 5},
            temporal_log=["Standardized UTC"],
        )
        self.assertEqual(r.explainability_path, "/tmp/heatmap.geojson")

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

    def test_semantic_product_schema_helpers_exported(self):
        from data_agent.fusion import SEMANTIC_PRODUCT_SCHEMA
        from data_agent.fusion_engine import validate_semantic_product_manifest

        self.assertEqual(SEMANTIC_PRODUCT_SCHEMA["title"], "MMFE Semantic Fusion Product")
        self.assertTrue(callable(validate_semantic_product_manifest))

    def test_semantic_alignment_scoring_helpers_exported(self):
        from data_agent.fusion import (
            build_alignment_review_items,
            score_semantic_alignment,
        )
        from data_agent.fusion_engine import build_alignment_summary

        self.assertTrue(callable(score_semantic_alignment))
        self.assertTrue(callable(build_alignment_summary))
        self.assertTrue(callable(build_alignment_review_items))


# ---------------------------------------------------------------------------
# v2 Agent tool layer integration tests (new)
# ---------------------------------------------------------------------------

class TestFuseDatasetsV2Params(unittest.TestCase):
    """Test fuse_datasets passes v2 params to execute_fusion."""

    def test_inject_document_context_registered(self):
        """inject_document_context should be in _ALL_FUNCS."""
        from data_agent.toolsets.fusion_tools import _ALL_FUNCS
        func_names = [f.__name__ for f in _ALL_FUNCS]
        self.assertIn("inject_document_context", func_names)

    def test_convert_format_registered(self):
        """convert_format should be in FileToolset._ALL_FUNCS."""
        from data_agent.toolsets.file_tools import _ALL_FUNCS
        func_names = [f.__name__ for f in _ALL_FUNCS]
        self.assertIn("convert_format", func_names)

    def test_fuse_datasets_has_v2_params(self):
        """fuse_datasets should accept v2 keyword arguments."""
        import inspect
        from data_agent.toolsets.fusion_tools import fuse_datasets
        sig = inspect.signature(fuse_datasets)
        param_names = list(sig.parameters.keys())
        self.assertIn("enable_temporal", param_names)
        self.assertIn("conflict_strategy", param_names)
        self.assertIn("enable_explainability", param_names)
        self.assertIn("use_llm_semantic", param_names)
        self.assertIn("document_context", param_names)

    def test_fuse_datasets_v2_defaults(self):
        """Check default values for v2 parameters."""
        import inspect
        from data_agent.toolsets.fusion_tools import fuse_datasets
        sig = inspect.signature(fuse_datasets)
        self.assertEqual(sig.parameters["enable_temporal"].default, "auto")
        self.assertEqual(sig.parameters["conflict_strategy"].default, "")
        self.assertEqual(sig.parameters["enable_explainability"].default, "true")
        self.assertEqual(sig.parameters["use_llm_semantic"].default, "false")
        self.assertEqual(sig.parameters["document_context"].default, "")

    def test_fuse_datasets_has_semantic_product_param(self):
        import inspect
        from data_agent.toolsets.fusion_tools import fuse_datasets

        sig = inspect.signature(fuse_datasets)
        self.assertIn("semantic_product", sig.parameters)
        self.assertEqual(sig.parameters["semantic_product"].default, "true")

    def test_fuse_datasets_passes_document_context_to_semantic_config(self):
        from data_agent.fusion.models import (
            CompatibilityReport,
            FusionResult,
            FusionSource,
        )
        from data_agent.toolsets import fusion_tools

        source_a = FusionSource(
            file_path="a.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=1,
            columns=[{"name": "DLBM", "dtype": "object", "null_pct": 0}],
        )
        source_b = FusionSource(
            file_path="b.geojson",
            data_type="vector",
            crs="EPSG:4326",
            row_count=1,
            columns=[{"name": "land_use_code", "dtype": "object", "null_pct": 0}],
        )
        document_context = {
            "source_metadata": [
                {
                    "file": "land_dictionary.xlsx",
                    "field_definitions": [
                        {
                            "field": "DLBM",
                            "aliases": ["land_use_code"],
                            "meaning": "DLBM is the land use code.",
                        }
                    ],
                }
            ]
        }
        captured = {}

        def fake_execute_fusion(*args, **kwargs):
            captured["semantic_config"] = kwargs.get("semantic_config")
            return FusionResult(
                output_path="out.geojson",
                strategy_used="spatial_join",
                row_count=1,
                column_count=1,
                quality_score=1.0,
                duration_s=0.0,
            )

        with patch.object(fusion_tools, "_resolve_path", side_effect=lambda p: p), \
                patch.object(
                    fusion_tools.fusion_engine,
                    "profile_source",
                    side_effect=[source_a, source_b],
                ), \
                patch.object(
                    fusion_tools.fusion_engine,
                    "assess_compatibility",
                    return_value=CompatibilityReport(
                        field_matches=[
                            {
                                "left": "DLBM",
                                "right": "land_use_code",
                                "confidence": 0.72,
                                "match_type": "fuzzy",
                            }
                        ],
                    ),
                ), \
                patch.object(
                    fusion_tools.fusion_engine,
                    "align_sources",
                    return_value=([("vector", object()), ("vector", object())], []),
                ), \
                patch.object(
                    fusion_tools.fusion_engine,
                    "execute_fusion",
                    side_effect=fake_execute_fusion,
                ), \
                patch.object(fusion_tools.fusion_engine, "record_operation"):
            result_text = asyncio.run(
                fusion_tools.fuse_datasets(
                    "a.geojson,b.geojson",
                    document_context=json.dumps(document_context),
                )
            )

        result = json.loads(result_text)
        self.assertEqual(result["output_path"], "out.geojson")
        self.assertEqual(
            captured["semantic_config"]["document_context"],
            document_context,
        )


class TestProfilingGdbRecognition(unittest.TestCase):
    """Test that profiling.py recognizes .gdb as vector format."""

    def test_gdb_detected_as_vector(self):
        from data_agent.fusion.profiling import _detect_data_type
        self.assertEqual(_detect_data_type("poi_data.gdb"), "vector")

    def test_shp_still_vector(self):
        from data_agent.fusion.profiling import _detect_data_type
        self.assertEqual(_detect_data_type("roads.shp"), "vector")

    def test_tif_still_raster(self):
        from data_agent.fusion.profiling import _detect_data_type
        self.assertEqual(_detect_data_type("dem.tif"), "raster")


if __name__ == "__main__":
    unittest.main()
