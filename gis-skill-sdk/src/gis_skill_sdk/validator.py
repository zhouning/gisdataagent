"""Skill validation utilities."""

import os
import re
from typing import Optional

from .metadata import SkillMetadata


def validate_skill_directory(path: str) -> dict:
    """Validate a skill directory structure and content.

    Returns:
        {"valid": bool, "errors": list[str], "warnings": list[str]}
    """
    errors = []
    warnings = []

    # Check directory exists
    if not os.path.isdir(path):
        return {
            "valid": False,
            "errors": [f"Directory not found: {path}"],
            "warnings": [],
        }

    # Check SKILL.md exists
    skill_md = os.path.join(path, "SKILL.md")
    if not os.path.exists(skill_md):
        errors.append("SKILL.md not found")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Try to load and parse
    try:
        from .base_skill import BaseSkill

        skill = BaseSkill.from_yaml(skill_md)
    except Exception as e:
        errors.append(f"Failed to parse SKILL.md: {e}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Validate metadata
    meta_issues = _validate_metadata(skill.metadata)
    for issue in meta_issues:
        if issue.startswith("ERROR"):
            errors.append(issue)
        else:
            warnings.append(issue)

    # Validate instruction content
    if len(skill.instruction) < 20:
        warnings.append("Instruction is very short (< 20 chars)")
    if len(skill.instruction) > 50000:
        warnings.append("Instruction is very long (> 50K chars)")

    # Check directory naming convention
    dirname = os.path.basename(os.path.normpath(path))
    if dirname != skill.metadata.name and skill.metadata.name:
        warnings.append(
            f"Directory name '{dirname}' doesn't match skill name '{skill.metadata.name}'"
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "skill_name": skill.metadata.name,
        "pattern": skill.metadata.pattern,
        "toolsets": skill.metadata.toolsets,
    }


def _validate_metadata(metadata: SkillMetadata) -> list[str]:
    """Validate skill metadata fields. Returns list of issues."""
    issues = []

    if not metadata.name:
        issues.append("ERROR: name is required")
    elif (
        not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", metadata.name)
        and len(metadata.name) > 2
    ):
        issues.append(
            f"WARNING: name '{metadata.name}' should be kebab-case (e.g., 'my-skill')"
        )

    if metadata.pattern not in SkillMetadata.VALID_PATTERNS:
        issues.append(
            f"WARNING: unknown pattern '{metadata.pattern}', expected one of {sorted(SkillMetadata.VALID_PATTERNS)}"
        )

    if metadata.model_tier not in SkillMetadata.VALID_TIERS:
        issues.append(
            f"WARNING: unknown model_tier '{metadata.model_tier}', expected one of {sorted(SkillMetadata.VALID_TIERS)}"
        )

    if not metadata.trigger_keywords:
        issues.append("WARNING: no trigger_keywords defined")

    if not metadata.toolsets:
        issues.append("WARNING: no toolsets specified")

    if not metadata.description:
        issues.append("WARNING: description is empty")

    return issues
