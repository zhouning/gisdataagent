"""Tests for ADK Skills framework integration (v1.26).

Validates SKILL.md loading, SkillToolset construction, and Planner integration.
"""
import pathlib
import unittest
import asyncio
import yaml


SKILLS_DIR = pathlib.Path(__file__).parent / "skills"

EXPECTED_SKILLS = [
    "3d-visualization",
    "advanced-analysis",
    "buffer-overlay",
    "coordinate-transform",
    "data-import-export",
    "data-profiling",
    "ecological-assessment",
    "farmland-compliance",
    "geocoding",
    "knowledge-retrieval",
    "land-fragmentation",
    "multi-source-fusion",
    "postgis-analysis",
    "site-selection",
    "spatial-clustering",
    "team-collaboration",
    "thematic-mapping",
    "topology-validation",
]

SKILLS_WITH_REFERENCES = [
    "coordinate-transform",
    "ecological-assessment",
    "farmland-compliance",
    "land-fragmentation",
    "postgis-analysis",
    "spatial-clustering",
]


class TestSkillDirectoryStructure(unittest.TestCase):
    """Verify the skills/ directory has the expected layout."""

    def test_skills_dir_exists(self):
        self.assertTrue(SKILLS_DIR.is_dir())

    def test_init_exists(self):
        self.assertTrue((SKILLS_DIR / "__init__.py").exists())

    def test_all_skill_dirs_exist(self):
        for name in EXPECTED_SKILLS:
            skill_dir = SKILLS_DIR / name
            self.assertTrue(skill_dir.is_dir(), f"Missing skill dir: {name}")

    def test_all_skill_md_exist(self):
        for name in EXPECTED_SKILLS:
            skill_md = SKILLS_DIR / name / "SKILL.md"
            self.assertTrue(skill_md.exists(), f"Missing SKILL.md: {name}")

    def test_references_dirs(self):
        """Skills with references/ should have the directory."""
        for name in SKILLS_WITH_REFERENCES:
            ref_dir = SKILLS_DIR / name / "references"
            self.assertTrue(ref_dir.is_dir(), f"Missing references/: {name}")

    def test_no_extra_skill_dirs(self):
        """Only expected skill dirs (excluding __pycache__, __init__.py)."""
        actual = sorted(
            p.name for p in SKILLS_DIR.iterdir()
            if p.is_dir() and not p.name.startswith("__")
        )
        self.assertEqual(actual, EXPECTED_SKILLS)


class TestSkillMDFrontmatter(unittest.TestCase):
    """Validate SKILL.md YAML frontmatter conforms to ADK Frontmatter schema."""

    def _parse_frontmatter(self, skill_name: str) -> dict:
        text = (SKILLS_DIR / skill_name / "SKILL.md").read_text(encoding="utf-8")
        # Extract YAML between --- markers
        parts = text.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, f"Invalid frontmatter in {skill_name}")
        return yaml.safe_load(parts[1])

    def test_frontmatter_has_required_fields(self):
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            self.assertIn("name", fm, f"{name}: missing 'name'")
            self.assertIn("description", fm, f"{name}: missing 'description'")

    def test_name_matches_directory(self):
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            self.assertEqual(fm["name"], name, f"SKILL.md name != dir name for {name}")

    def test_name_is_kebab_case(self):
        import re
        pattern = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            self.assertRegex(fm["name"], pattern, f"{name}: name not kebab-case")

    def test_description_not_empty(self):
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            self.assertTrue(len(fm["description"]) > 0)

    def test_description_within_limit(self):
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            self.assertLessEqual(len(fm["description"]), 1024)

    def test_metadata_values_are_strings(self):
        """ADK Frontmatter requires metadata: dict[str, str]."""
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            metadata = fm.get("metadata", {})
            for key, value in metadata.items():
                self.assertIsInstance(
                    value, str,
                    f"{name}: metadata['{key}'] must be str, got {type(value).__name__}"
                )

    def test_metadata_has_domain(self):
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            self.assertIn("domain", fm.get("metadata", {}), f"{name}: no domain")

    def test_metadata_has_intent_triggers(self):
        for name in EXPECTED_SKILLS:
            fm = self._parse_frontmatter(name)
            triggers = fm.get("metadata", {}).get("intent_triggers", "")
            self.assertTrue(len(triggers) > 0, f"{name}: empty intent_triggers")


class TestSkillLoading(unittest.TestCase):
    """Test load_skill() and load_all_skills() from skills/__init__.py."""

    def test_load_single_skill(self):
        from data_agent.skills import load_skill
        skill = load_skill("farmland-compliance")
        self.assertEqual(skill.name, "farmland-compliance")
        self.assertTrue(len(skill.description) > 0)

    def test_load_all_skills_count(self):
        from data_agent.skills import load_all_skills
        skills = load_all_skills()
        self.assertEqual(len(skills), 18)

    def test_load_all_skills_names(self):
        from data_agent.skills import load_all_skills
        skills = load_all_skills()
        names = sorted(s.name for s in skills)
        self.assertEqual(names, EXPECTED_SKILLS)

    def test_load_nonexistent_raises(self):
        from data_agent.skills import load_skill
        with self.assertRaises((ValueError, FileNotFoundError)):
            load_skill("nonexistent-skill")

    def test_skill_has_instructions(self):
        """L2 content: skills should have instruction body (Markdown after frontmatter)."""
        from data_agent.skills import load_skill
        skill = load_skill("thematic-mapping")
        # The skill object should have instructions loaded
        self.assertTrue(hasattr(skill, "instructions") or hasattr(skill, "instruction"))

    def test_skill_has_metadata(self):
        from data_agent.skills import load_skill
        skill = load_skill("postgis-analysis")
        self.assertIsNotNone(skill.frontmatter.metadata)


class TestSkillToolsetIntegration(unittest.TestCase):
    """Test ADK SkillToolset wrapping of skills."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_build_all_skills_toolset(self):
        from data_agent.toolsets.skill_bundles import build_all_skills_toolset
        ts = build_all_skills_toolset()
        from google.adk.tools.skill_toolset import SkillToolset
        self.assertIsInstance(ts, SkillToolset)

    def test_build_single_skill_toolset(self):
        from data_agent.toolsets.skill_bundles import build_skill_toolset
        ts = build_skill_toolset("team-collaboration")
        from google.adk.tools.skill_toolset import SkillToolset
        self.assertIsInstance(ts, SkillToolset)

    def test_skill_toolset_has_tools(self):
        """SkillToolset should provide internal tools (list_skills, load_skill, etc.)."""
        from data_agent.toolsets.skill_bundles import build_all_skills_toolset
        ts = build_all_skills_toolset()
        tools = self._run(ts.get_tools())
        tool_names = [t.name for t in tools]
        self.assertIn("list_skills", tool_names)
        self.assertIn("load_skill", tool_names)
        self.assertGreaterEqual(len(tools), 2)

    def test_skill_toolset_list_skills_returns_all(self):
        """list_skills tool should return metadata for all 16 skills."""
        from data_agent.toolsets.skill_bundles import build_all_skills_toolset
        ts = build_all_skills_toolset()
        # Access the skills list directly
        self.assertEqual(len(ts._skills), 18)

    def test_single_skill_toolset_count(self):
        from data_agent.toolsets.skill_bundles import build_skill_toolset
        ts = build_skill_toolset("data-profiling")
        self.assertEqual(len(ts._skills), 1)


class TestPlannerSkillIntegration(unittest.TestCase):
    """Verify Planner agent includes SkillToolset."""

    def test_planner_has_skill_toolset(self):
        from data_agent.agent import planner_agent
        from google.adk.tools.skill_toolset import SkillToolset
        has_skill_toolset = any(
            isinstance(t, SkillToolset) for t in planner_agent.tools
        )
        self.assertTrue(has_skill_toolset, "Planner should include SkillToolset")

    def test_planner_skill_toolset_has_18_skills(self):
        from data_agent.agent import planner_agent
        from google.adk.tools.skill_toolset import SkillToolset
        for t in planner_agent.tools:
            if isinstance(t, SkillToolset):
                self.assertEqual(len(t._skills), 18)
                return
        self.fail("No SkillToolset found in Planner tools")

    def test_planner_still_has_other_toolsets(self):
        """Planner should retain Memory, Admin, Team, DataLake toolsets."""
        from data_agent.agent import planner_agent
        tool_types = [type(t).__name__ for t in planner_agent.tools]
        self.assertIn("MemoryToolset", tool_types)
        self.assertIn("AdminToolset", tool_types)
        self.assertIn("TeamToolset", tool_types)
        self.assertIn("DataLakeToolset", tool_types)

    def test_pipeline_agents_no_skill_toolset(self):
        """Pipeline agents (narrow experts) should NOT have SkillToolset."""
        from data_agent.agent import (
            data_exploration_agent, data_processing_agent, data_analysis_agent,
            data_visualization_agent, data_summary_agent,
        )
        from google.adk.tools.skill_toolset import SkillToolset
        for agent in [data_exploration_agent, data_processing_agent,
                      data_analysis_agent, data_visualization_agent,
                      data_summary_agent]:
            for t in agent.tools:
                self.assertNotIsInstance(
                    t, SkillToolset,
                    f"{agent.name} should not have SkillToolset"
                )


class TestLegacySkillBundlesCompat(unittest.TestCase):
    """Ensure legacy SkillBundle API still works after migration."""

    def test_all_bundles_still_accessible(self):
        from data_agent.toolsets.skill_bundles import ALL_BUNDLES, get_bundle
        self.assertEqual(len(ALL_BUNDLES), 5)
        for b in ALL_BUNDLES:
            self.assertIs(get_bundle(b.name), b)

    def test_legacy_build_toolsets(self):
        from data_agent.toolsets.skill_bundles import SPATIAL_ANALYSIS
        toolsets = SPATIAL_ANALYSIS.build_toolsets()
        self.assertGreater(len(toolsets), 0)

    def test_legacy_intent_mapping(self):
        from data_agent.toolsets.skill_bundles import get_bundles_for_intent
        bundles = get_bundles_for_intent("governance")
        names = [b.name for b in bundles]
        self.assertIn("spatial_analysis", names)
        self.assertIn("data_quality", names)

    def test_legacy_build_toolsets_for_intent(self):
        from data_agent.toolsets.skill_bundles import build_toolsets_for_intent
        toolsets = build_toolsets_for_intent("governance")
        self.assertGreater(len(toolsets), 0)
        # No duplicates
        class_names = [type(ts).__name__ for ts in toolsets]
        self.assertEqual(len(class_names), len(set(class_names)))


if __name__ == "__main__":
    unittest.main()
