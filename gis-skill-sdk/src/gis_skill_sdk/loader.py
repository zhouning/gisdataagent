"""Skill loading utilities."""

import os
from typing import Optional

from .base_skill import BaseSkill


def load_skill(path: str) -> BaseSkill:
    """Load a skill from a directory or SKILL.md file.

    Args:
        path: Path to skill directory or SKILL.md file
    """
    if os.path.isdir(path):
        return BaseSkill.from_directory(path)
    elif os.path.isfile(path):
        return BaseSkill.from_yaml(path)
    else:
        raise FileNotFoundError(f"Skill not found: {path}")


def load_skills_directory(base_dir: str) -> list[BaseSkill]:
    """Load all skills from a directory of skill directories.

    Expects structure:
        base_dir/
            skill-a/
                SKILL.md
            skill-b/
                SKILL.md
    """
    skills = []
    if not os.path.isdir(base_dir):
        return skills

    for entry in sorted(os.listdir(base_dir)):
        skill_dir = os.path.join(base_dir, entry)
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if os.path.isdir(skill_dir) and os.path.exists(skill_md):
            try:
                skill = BaseSkill.from_directory(skill_dir)
                skills.append(skill)
            except Exception as e:
                print(f"Warning: Failed to load skill from {skill_dir}: {e}")

    return skills


def discover_skills(base_dir: str) -> list[dict]:
    """Discover skills and return metadata only (lightweight).

    Returns list of dicts with name, description, pattern, source_path.
    """
    results = []
    if not os.path.isdir(base_dir):
        return results

    for entry in sorted(os.listdir(base_dir)):
        skill_dir = os.path.join(base_dir, entry)
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if os.path.isdir(skill_dir) and os.path.exists(skill_md):
            try:
                skill = BaseSkill.from_yaml(skill_md)
                results.append(
                    {
                        "name": skill.metadata.name,
                        "description": skill.metadata.description,
                        "pattern": skill.metadata.pattern,
                        "trigger_keywords": skill.metadata.trigger_keywords,
                        "toolsets": skill.metadata.toolsets,
                        "source_path": skill_dir,
                    }
                )
            except Exception:
                results.append(
                    {"name": entry, "source_path": skill_dir, "error": True}
                )

    return results
