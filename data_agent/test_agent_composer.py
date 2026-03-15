"""Tests for Agent Composer (v12.0.2, Design Pattern Ch21).

Covers DataProfile extraction, blueprint creation, domain detection,
and agent composition.
"""
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class TestDataProfile(unittest.TestCase):
    def test_defaults(self):
        from data_agent.agent_composer import DataProfile
        p = DataProfile()
        self.assertEqual(p.domain, "general")
        self.assertEqual(p.row_count, 0)

    def test_to_dict(self):
        from data_agent.agent_composer import DataProfile
        p = DataProfile(file_path="test.shp", domain="landuse", row_count=100)
        d = p.to_dict()
        self.assertEqual(d["domain"], "landuse")
        self.assertEqual(d["row_count"], 100)


class TestDomainDetection(unittest.TestCase):
    def test_landuse_domain(self):
        from data_agent.agent_composer import extract_profile
        # Create temp GeoJSON with landuse columns
        path = os.path.join(tempfile.gettempdir(), "landuse_test.geojson")
        import geopandas as gpd
        from shapely.geometry import box
        gdf = gpd.GeoDataFrame(
            {"dlbm": ["0101", "0201"], "地类名称": ["旱地", "有林地"]},
            geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)]
        )
        gdf.to_file(path, driver="GeoJSON")
        profile = extract_profile(path)
        self.assertEqual(profile.domain, "landuse")
        self.assertIn("dlbm", profile.domain_keywords)
        os.remove(path)

    def test_transport_domain(self):
        from data_agent.agent_composer import DataProfile, _DOMAIN_KEYWORDS
        p = DataProfile(columns=["road_id", "road_type", "length"])
        # Manually test keyword matching
        all_cols_lower = " ".join(c.lower() for c in p.columns)
        score = sum(1 for kw in _DOMAIN_KEYWORDS["transport"] if kw.lower() in all_cols_lower)
        self.assertGreater(score, 0)

    def test_general_fallback(self):
        from data_agent.agent_composer import extract_profile
        path = os.path.join(tempfile.gettempdir(), "general_test.csv")
        with open(path, "w") as f:
            f.write("col_a,col_b\n1,2\n3,4\n")
        profile = extract_profile(path)
        self.assertEqual(profile.domain, "general")
        os.remove(path)


class TestAgentBlueprint(unittest.TestCase):
    def test_defaults(self):
        from data_agent.agent_composer import AgentBlueprint
        bp = AgentBlueprint()
        self.assertEqual(bp.model_tier, "standard")
        self.assertEqual(bp.name, "DynamicAgent")

    def test_to_dict(self):
        from data_agent.agent_composer import AgentBlueprint
        bp = AgentBlueprint(name="LandAgent", toolset_names=["ExplorationToolset"])
        d = bp.to_dict()
        self.assertEqual(d["name"], "LandAgent")
        self.assertIn("ExplorationToolset", d["toolset_names"])


class TestCreateBlueprint(unittest.TestCase):
    def test_landuse_blueprint(self):
        from data_agent.agent_composer import DataProfile, create_blueprint
        profile = DataProfile(
            domain="landuse",
            domain_keywords=["dlbm", "耕地"],
            row_count=5000,
            geometry_types=["Polygon"],
            crs="EPSG:4490",
            numeric_columns=["area", "slope"],
        )
        bp = create_blueprint(profile)
        self.assertIn("ExplorationToolset", bp.toolset_names)
        self.assertIn("AnalysisToolset", bp.toolset_names)
        self.assertEqual(bp.model_tier, "standard")
        self.assertIn("用地", bp.instruction)

    def test_large_data_premium(self):
        from data_agent.agent_composer import DataProfile, create_blueprint
        profile = DataProfile(domain="general", row_count=50000)
        bp = create_blueprint(profile)
        self.assertEqual(bp.model_tier, "premium")

    def test_small_data_fast(self):
        from data_agent.agent_composer import DataProfile, create_blueprint
        profile = DataProfile(domain="general", row_count=50)
        bp = create_blueprint(profile)
        self.assertEqual(bp.model_tier, "fast")

    def test_all_domains_have_toolsets(self):
        from data_agent.agent_composer import _DOMAIN_TOOLSETS
        for domain, toolsets in _DOMAIN_TOOLSETS.items():
            self.assertGreater(len(toolsets), 0, f"Domain '{domain}' has no toolsets")
            self.assertIn("ExplorationToolset", toolsets,
                         f"Domain '{domain}' missing ExplorationToolset")

    def test_all_domains_have_instructions(self):
        from data_agent.agent_composer import _DOMAIN_INSTRUCTIONS
        for domain in ("landuse", "transport", "hydrology", "ecology", "urban", "general"):
            self.assertIn(domain, _DOMAIN_INSTRUCTIONS)


class TestComposition(unittest.TestCase):
    def test_compose_agent_returns_agent_or_none(self):
        """compose_agent should return an agent or None gracefully."""
        from data_agent.agent_composer import DataProfile, compose_agent
        # Without proper toolset setup, should return None gracefully
        profile = DataProfile(domain="general")
        result = compose_agent(profile)
        # May be None (if registry returns empty) or an agent — either is acceptable
        # The key is it doesn't crash
        self.assertTrue(result is None or hasattr(result, 'name'))

    def test_compose_pipeline_empty(self):
        """compose_pipeline with empty list returns None."""
        from data_agent.agent_composer import compose_pipeline
        self.assertIsNone(compose_pipeline([]))

    def test_compose_pipeline_none_profiles(self):
        from data_agent.agent_composer import compose_pipeline
        self.assertIsNone(compose_pipeline(None))


class TestConstants(unittest.TestCase):
    def test_dynamic_composition_default(self):
        from data_agent.agent_composer import DYNAMIC_COMPOSITION
        self.assertIsInstance(DYNAMIC_COMPOSITION, bool)

    def test_domain_keywords_structure(self):
        from data_agent.agent_composer import _DOMAIN_KEYWORDS
        self.assertIn("landuse", _DOMAIN_KEYWORDS)
        self.assertIn("transport", _DOMAIN_KEYWORDS)
        self.assertGreater(len(_DOMAIN_KEYWORDS["landuse"]), 5)


if __name__ == "__main__":
    unittest.main()
