"""Typed contracts for agent-facing ontology analysis."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OntologyQueryType(StrEnum):
    CONCEPT_EXPLANATION = "concept_explanation"
    HIERARCHY = "hierarchy"
    RELATION_PATH = "relation_path"
    TRANSITION_RULES = "transition_rules"
    SCHEMA_MAPPING = "schema_mapping"
    DEMO_SCENARIO_ANALYSIS = "demo_scenario_analysis"


class OntologyQueryPlan(BaseModel):
    """Closed query plan. It intentionally has no SQL or SPARQL field."""

    model_config = ConfigDict(extra="forbid")

    query_type: OntologyQueryType
    subject: str = ""
    target: str = ""
    domain_id: str | None = None
    field_codes: list[str] = Field(default_factory=list, max_length=50)
    scenario_id: str | None = None
    depth: int = Field(default=2, ge=0, le=4)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("subject", "target")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 200:
            raise ValueError("ontology concept reference is limited to 200 characters")
        return value

    @field_validator("domain_id")
    @classmethod
    def valid_domain(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) != 2 or not value.isdigit():
            raise ValueError("domain_id must be a two-digit one-map domain identifier")
        return value

    @field_validator("field_codes")
    @classmethod
    def bounded_fields(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = str(raw).strip()
            if not value:
                continue
            if len(value) > 128:
                raise ValueError("field code is limited to 128 characters")
            folded = value.casefold()
            if folded not in seen:
                seen.add(folded)
                result.append(value)
        return result

    def audit_parameters(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
