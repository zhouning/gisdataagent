"""Skill metadata model."""

from typing import ClassVar, Optional
from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """Metadata for a GIS Data Agent skill."""

    name: str = Field(description="Skill identifier (kebab-case)")
    display_name: str = Field(default="", description="Human-readable name")
    description: str = Field(default="", description="Brief description")
    version: str = Field(default="1.0", description="Semantic version")
    category: str = Field(default="general", description="Skill category")
    pattern: str = Field(
        default="command",
        description="Skill pattern: command, inversion, probe, suggestion, reactive",
    )
    trigger_keywords: list[str] = Field(
        default_factory=list, description="Keywords that trigger this skill"
    )
    toolsets: list[str] = Field(
        default_factory=list, description="Required toolset names"
    )
    model_tier: str = Field(
        default="standard", description="LLM tier: standard, advanced, basic"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Dependent skill names"
    )
    output_schema: Optional[str] = Field(
        default=None, description="Output validation schema name"
    )

    VALID_PATTERNS: ClassVar[set[str]] = {"command", "inversion", "probe", "suggestion", "reactive"}
    VALID_TIERS: ClassVar[set[str]] = {"basic", "standard", "advanced"}
