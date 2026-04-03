"""Tests for Fusion v2.0 — Semantic Enhancement (ontology + LLM + KG).

Covers: OntologyReasoner, SemanticLLM (mocked), KGIntegration (mocked),
        ontology integration into matching pipeline.
"""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


class TestOntologyReasoner(unittest.TestCase):
    """Test OntologyReasoner."""

    def test_load_default_ontology(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        self.assertTrue(r.is_loaded)

    def test_find_equivalent_fields(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        equivs = r.find_equivalent_fields("mj")
        self.assertIn("面积", equivs)
        self.assertIn("area", equivs)

    def test_no_equivalences_for_unknown(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        equivs = r.find_equivalent_fields("xyzzy_random_field")
        self.assertEqual(equivs, [])

    def test_find_field_matches_by_ontology(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        left = [{"name": "面积", "dtype": "float64"}]
        right = [{"name": "AREA", "dtype": "float64"}, {"name": "ID", "dtype": "int64"}]
        matches = r.find_field_matches_by_ontology(left, right)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["left"], "面积")
        self.assertEqual(matches[0]["right"], "AREA")
        self.assertEqual(matches[0]["confidence"], 0.85)
        self.assertEqual(matches[0]["match_type"], "ontology")

    def test_derive_missing_fields(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        gdf = gpd.GeoDataFrame({
            "floors": [5, 10, 18],
            "area": [1000.0, 2000.0, 3000.0],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        result, derived = r.derive_missing_fields(gdf)
        self.assertIn("building_height", derived)
        self.assertAlmostEqual(result["building_height"].iloc[0], 15.0)
        self.assertAlmostEqual(result["building_height"].iloc[2], 54.0)

    def test_derive_with_equivalences(self):
        """Test derivation when required field is present under an alias."""
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        gdf = gpd.GeoDataFrame({
            "cs": [5, 10],  # alias for 'floors'
        }, geometry=[Point(0, 0), Point(1, 1)])
        result, derived = r.derive_missing_fields(gdf)
        # Should resolve 'cs' as 'floors' alias and derive building_height
        self.assertIn("building_height", derived)

    def test_apply_inference_rules(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        gdf = gpd.GeoDataFrame({
            "slope": [2.0, 30.0, 15.0],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        result, inferred = r.apply_inference_rules(gdf)
        self.assertIn("slope_class", inferred)
        self.assertEqual(result.loc[0, "slope_class"], "平地")
        self.assertEqual(result.loc[1, "slope_class"], "陡坡")

    def test_missing_ontology_file(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner(ontology_path="/nonexistent/path.yaml")
        self.assertFalse(r.is_loaded)
        equivs = r.find_equivalent_fields("area")
        self.assertEqual(equivs, [])

    def test_no_derivation_when_field_exists(self):
        from data_agent.fusion.ontology import OntologyReasoner
        r = OntologyReasoner()
        gdf = gpd.GeoDataFrame({
            "floors": [5],
            "building_height": [20.0],  # Already exists
        }, geometry=[Point(0, 0)])
        result, derived = r.derive_missing_fields(gdf)
        self.assertNotIn("building_height", derived)
        self.assertEqual(result["building_height"].iloc[0], 20.0)


class TestSemanticLLM(unittest.TestCase):
    """Test SemanticLLM with mocked Gemini API."""

    @patch("data_agent.fusion.semantic_llm.SemanticLLM._call_gemini")
    def test_understand_field_semantics(self, mock_gemini):
        from data_agent.fusion.semantic_llm import SemanticLLM
        mock_gemini.return_value = json.dumps({
            "semantic_type": "area",
            "unit": "m²",
            "description": "地块面积",
            "equivalent_terms": ["面积", "AREA"],
        })
        llm = SemanticLLM()
        # Make _call_gemini an async mock
        mock_gemini.side_effect = None
        async def _run():
            llm._call_gemini = AsyncMock(return_value=json.dumps({
                "semantic_type": "area", "unit": "m²",
                "description": "地块面积", "equivalent_terms": ["面积"],
            }))
            return await llm.understand_field_semantics("mj", [100.5, 200.3])
        result = asyncio.run(_run())
        self.assertEqual(result["semantic_type"], "area")

    def test_gemini_failure_graceful(self):
        from data_agent.fusion.semantic_llm import SemanticLLM
        llm = SemanticLLM()
        async def _run():
            llm._call_gemini = AsyncMock(return_value="")
            return await llm.understand_field_semantics("unknown", [])
        result = asyncio.run(_run())
        self.assertEqual(result["semantic_type"], "unknown")

    def test_match_fields_semantically(self):
        from data_agent.fusion.semantic_llm import SemanticLLM
        llm = SemanticLLM()
        async def _run():
            llm._call_gemini = AsyncMock(return_value=json.dumps([
                {"left": "面积", "right": "AREA", "confidence": 0.95, "reasoning": "同义"}
            ]))
            return await llm.match_fields_semantically(
                [{"name": "面积", "dtype": "float64"}],
                [{"name": "AREA", "dtype": "float64"}],
            )
        result = asyncio.run(_run())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["left"], "面积")

    def test_infer_derivable_fields(self):
        from data_agent.fusion.semantic_llm import SemanticLLM
        llm = SemanticLLM()
        async def _run():
            llm._call_gemini = AsyncMock(return_value=json.dumps({
                "derivable": True, "formula": "floors * 3.0"
            }))
            return await llm.infer_derivable_fields(["floors"], "building_height")
        result = asyncio.run(_run())
        self.assertEqual(result, "floors * 3.0")

    def test_detect_semantic_types(self):
        from data_agent.fusion.semantic_llm import SemanticLLM
        llm = SemanticLLM()
        async def _run():
            llm._call_gemini = AsyncMock(return_value=json.dumps({
                "面积": "area", "ID": "id"
            }))
            return await llm.detect_semantic_types([
                {"name": "面积"}, {"name": "ID"},
            ])
        result = asyncio.run(_run())
        self.assertEqual(result["面积"], "area")


class TestKGIntegration(unittest.TestCase):
    """Test KGIntegration with mocked KG."""

    def _make_mock_kg(self):
        import networkx as nx
        kg = MagicMock()
        kg.graph = nx.DiGraph()
        kg.graph.add_node("Building_A", entity_type="building", floors=10, area=500)
        kg.graph.add_node("Building_B", entity_type="building", floors=5, area=300)
        kg.graph.add_edge("Building_A", "Building_B", relationship="adjacent_to")
        return kg

    def test_enrich_with_relationships(self):
        from data_agent.fusion.kg_integration import KGIntegration
        kg = self._make_mock_kg()
        kgi = KGIntegration(kg=kg)
        gdf = gpd.GeoDataFrame({
            "name": ["Building_A", "Building_B", "Unknown"],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        result = kgi.enrich_with_relationships(gdf, "name")
        self.assertIn("_kg_relationships", result.columns)
        self.assertIn("_kg_entity_type", result.columns)
        self.assertEqual(result.loc[0, "_kg_entity_type"], "building")

    def test_resolve_conflicts_with_kg(self):
        from data_agent.fusion.kg_integration import KGIntegration
        kg = self._make_mock_kg()
        kgi = KGIntegration(kg=kg)
        value, reason = kgi.resolve_conflicts_with_kg(
            [10, 8, 12], "Building_A", "floors"
        )
        self.assertEqual(value, 10)  # KG has floors=10
        self.assertIn("KG", reason)

    def test_kg_not_available(self):
        from data_agent.fusion.kg_integration import KGIntegration
        kgi = KGIntegration(kg=None)
        kgi._kg = None
        self.assertFalse(kgi.is_available)
        gdf = gpd.GeoDataFrame({"name": ["A"]}, geometry=[Point(0, 0)])
        result = kgi.enrich_with_relationships(gdf, "name")
        self.assertNotIn("_kg_relationships", result.columns)

    def test_build_kg_from_sources(self):
        from data_agent.fusion.kg_integration import KGIntegration
        kg = self._make_mock_kg()
        kgi = KGIntegration(kg=kg)
        gdf = gpd.GeoDataFrame({
            "name": ["Park_C"],
            "area": [10000],
        }, geometry=[Point(3, 3)])
        kgi.build_kg_from_sources([("test_source", gdf)], "name")
        self.assertIn("Park_C", kg.graph.nodes)


class TestOntologyInMatching(unittest.TestCase):
    """Test ontology integration in _find_field_matches."""

    def test_ontology_tier_matches(self):
        from data_agent.fusion.matching import _find_field_matches
        from data_agent.fusion.models import FusionSource
        s1 = FusionSource(
            file_path="a.geojson", data_type="vector",
            columns=[{"name": "面积", "dtype": "float64"}, {"name": "ID", "dtype": "int64"}],
        )
        s2 = FusionSource(
            file_path="b.geojson", data_type="vector",
            columns=[{"name": "AREA", "dtype": "float64"}, {"name": "ID", "dtype": "int64"}],
        )
        matches = _find_field_matches([s1, s2], use_ontology=True)
        # ID should be exact match, 面积↔AREA should be ontology match
        area_match = [m for m in matches if m["left"] == "面积"]
        self.assertEqual(len(area_match), 1)
        self.assertEqual(area_match[0]["right"], "AREA")
        self.assertEqual(area_match[0]["confidence"], 0.85)

    def test_ontology_disabled_by_default(self):
        from data_agent.fusion.matching import _find_field_matches
        from data_agent.fusion.models import FusionSource
        s1 = FusionSource(
            file_path="a.geojson", data_type="vector",
            columns=[{"name": "面积", "dtype": "float64"}],
        )
        s2 = FusionSource(
            file_path="b.geojson", data_type="vector",
            columns=[{"name": "AREA", "dtype": "float64"}],
        )
        matches = _find_field_matches([s1, s2], use_ontology=False)
        # Without ontology, 面积↔AREA might match via equivalence groups or not
        onto_matches = [m for m in matches if m.get("match_type") == "ontology"]
        self.assertEqual(len(onto_matches), 0)


if __name__ == "__main__":
    unittest.main()
