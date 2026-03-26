"""Base skill class for GIS Data Agent skills."""

import os
import re
import yaml
from typing import Optional

from .metadata import SkillMetadata


class BaseSkill:
    """Represents a GIS Data Agent skill loaded from a SKILL.md file.

    The SKILL.md format uses YAML frontmatter followed by Markdown instructions:

    ```
    ---
    name: my-skill
    description: Does something useful
    pattern: command
    trigger_keywords:
      - keyword1
      - keyword2
    toolsets:
      - ExplorationToolset
    model_tier: standard
    ---

    # My Skill Instructions

    Detailed instructions for the LLM agent...
    ```
    """

    def __init__(
        self, metadata: SkillMetadata, instruction: str, source_path: str = ""
    ):
        self.metadata = metadata
        self.instruction = instruction
        self.source_path = source_path

    @classmethod
    def from_yaml(cls, skill_md_path: str) -> "BaseSkill":
        """Load a skill from a SKILL.md file with YAML frontmatter."""
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()

        metadata_dict, instruction = _parse_frontmatter(content)
        metadata = SkillMetadata(**metadata_dict)

        return cls(
            metadata=metadata,
            instruction=instruction.strip(),
            source_path=skill_md_path,
        )

    @classmethod
    def from_directory(cls, skill_dir: str) -> "BaseSkill":
        """Load a skill from a skill directory containing SKILL.md."""
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skill_md):
            raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

        skill = cls.from_yaml(skill_md)

        # Load references if present
        refs_dir = os.path.join(skill_dir, "references")
        if os.path.isdir(refs_dir):
            for fname in os.listdir(refs_dir):
                fpath = os.path.join(refs_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            skill.instruction += (
                                f"\n\n## Reference: {fname}\n\n{f.read()}"
                            )
                    except (UnicodeDecodeError, OSError):
                        pass  # Skip binary files

        return skill

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def trigger_keywords(self) -> list[str]:
        return self.metadata.trigger_keywords

    @property
    def toolsets(self) -> list[str]:
        return self.metadata.toolsets

    def to_dict(self) -> dict:
        """Serialize skill to dictionary."""
        return {
            "metadata": self.metadata.model_dump(),
            "instruction": self.instruction,
            "source_path": self.source_path,
        }

    def validate(self) -> list[str]:
        """Validate skill configuration. Returns list of warnings/errors."""
        from .validator import _validate_metadata

        return _validate_metadata(self.metadata)

    def __repr__(self) -> str:
        return f"BaseSkill(name={self.name!r}, pattern={self.metadata.pattern!r})"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from Markdown content.

    Supports both `---` delimiters (standard) and content without delimiters.
    """
    # Standard frontmatter: --- ... ---
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if match:
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
            body = match.group(2)
            return metadata, body
        except yaml.YAMLError:
            pass

    # Fallback: try entire content as YAML
    try:
        metadata = yaml.safe_load(content) or {}
        if isinstance(metadata, dict) and "name" in metadata:
            return metadata, ""
    except yaml.YAMLError:
        pass

    return {}, content
