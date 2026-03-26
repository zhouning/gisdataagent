"""Tests for gis-skill-sdk."""

import os
import sys
import tempfile
import unittest

# Add src to path for testing without install
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from gis_skill_sdk import BaseSkill, SkillMetadata
from gis_skill_sdk.validator import validate_skill_directory
from gis_skill_sdk.loader import load_skill, load_skills_directory, discover_skills


SAMPLE_SKILL_MD = """---
name: test-skill
description: A test skill for validation
version: "1.0"
category: analysis
pattern: command
trigger_keywords:
  - test
  - demo
toolsets:
  - ExplorationToolset
model_tier: standard
---

# Test Skill

This is a test skill with detailed instructions.

## Usage

Use this skill for testing purposes only.
"""


class TestSkillMetadata(unittest.TestCase):
    def test_create_metadata(self):
        m = SkillMetadata(name="my-skill", description="Test", pattern="command")
        self.assertEqual(m.name, "my-skill")
        self.assertEqual(m.pattern, "command")
        self.assertEqual(m.model_tier, "standard")

    def test_defaults(self):
        m = SkillMetadata(name="x")
        self.assertEqual(m.trigger_keywords, [])
        self.assertEqual(m.toolsets, [])
        self.assertEqual(m.category, "general")


class TestBaseSkill(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skill_dir = os.path.join(self.tmpdir, "test-skill")
        os.makedirs(self.skill_dir)
        with open(
            os.path.join(self.skill_dir, "SKILL.md"), "w", encoding="utf-8"
        ) as f:
            f.write(SAMPLE_SKILL_MD)

    def test_from_yaml(self):
        skill = BaseSkill.from_yaml(os.path.join(self.skill_dir, "SKILL.md"))
        self.assertEqual(skill.name, "test-skill")
        self.assertEqual(skill.metadata.pattern, "command")
        self.assertIn("test", skill.trigger_keywords)
        self.assertIn("Test Skill", skill.instruction)

    def test_from_directory(self):
        skill = BaseSkill.from_directory(self.skill_dir)
        self.assertEqual(skill.name, "test-skill")

    def test_to_dict(self):
        skill = BaseSkill.from_yaml(os.path.join(self.skill_dir, "SKILL.md"))
        d = skill.to_dict()
        self.assertIn("metadata", d)
        self.assertIn("instruction", d)
        self.assertEqual(d["metadata"]["name"], "test-skill")

    def test_validate(self):
        skill = BaseSkill.from_yaml(os.path.join(self.skill_dir, "SKILL.md"))
        issues = skill.validate()
        self.assertEqual(len([i for i in issues if i.startswith("ERROR")]), 0)

    def test_repr(self):
        skill = BaseSkill.from_yaml(os.path.join(self.skill_dir, "SKILL.md"))
        self.assertIn("test-skill", repr(skill))


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skill_dir = os.path.join(self.tmpdir, "test-skill")
        os.makedirs(self.skill_dir)
        with open(
            os.path.join(self.skill_dir, "SKILL.md"), "w", encoding="utf-8"
        ) as f:
            f.write(SAMPLE_SKILL_MD)

    def test_valid_skill(self):
        result = validate_skill_directory(self.skill_dir)
        self.assertTrue(result["valid"])
        self.assertEqual(result["skill_name"], "test-skill")

    def test_missing_directory(self):
        result = validate_skill_directory("/nonexistent/path")
        self.assertFalse(result["valid"])

    def test_missing_skill_md(self):
        empty = tempfile.mkdtemp()
        result = validate_skill_directory(empty)
        self.assertFalse(result["valid"])


class TestLoader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        for name in ["skill-a", "skill-b"]:
            d = os.path.join(self.tmpdir, name)
            os.makedirs(d)
            with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(
                    f"---\nname: {name}\ndescription: Test {name}\npattern: command\ntrigger_keywords:\n  - {name}\ntoolsets:\n  - ExplorationToolset\n---\n\n# {name}\nInstructions for {name}.\n"
                )

    def test_load_skill_from_dir(self):
        skill = load_skill(os.path.join(self.tmpdir, "skill-a"))
        self.assertEqual(skill.name, "skill-a")

    def test_load_skills_directory(self):
        skills = load_skills_directory(self.tmpdir)
        self.assertEqual(len(skills), 2)
        names = {s.name for s in skills}
        self.assertIn("skill-a", names)
        self.assertIn("skill-b", names)

    def test_discover_skills(self):
        found = discover_skills(self.tmpdir)
        self.assertEqual(len(found), 2)
        self.assertIn("skill-a", found[0]["name"])


if __name__ == "__main__":
    unittest.main()
