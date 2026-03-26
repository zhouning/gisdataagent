"""Skill output structured validation schemas (Pydantic v2).

Provides standardized output schemas for Generator/Reviewer skill patterns.
Skills can optionally specify an `output_schema` field to enable automatic
validation of their output before returning to users.
"""

import logging
from typing import Any, Literal, Optional

logger = logging.getLogger("data_agent.skill_output_schemas")

try:
    from pydantic import BaseModel, Field, ValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    BaseModel = object  # type: ignore
    Field = lambda *a, **kw: None  # type: ignore
    ValidationError = Exception  # type: ignore


# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

if PYDANTIC_AVAILABLE:

    class Finding(BaseModel):
        """A single finding from a quality review."""
        dimension: str = Field(description="Quality dimension (completeness, accuracy, etc.)")
        severity: Literal["pass", "warn", "fail"] = Field(default="pass")
        message: str = Field(description="Human-readable finding description")
        field_name: Optional[str] = Field(default=None, description="Related field name if applicable")

    class QualityReportOutput(BaseModel):
        """Output schema for data-quality-reviewer and similar reviewer skills."""
        verdict: Literal["pass", "warn", "fail"] = Field(description="Overall verdict")
        pass_rate: float = Field(ge=0, le=1, description="Fraction of checks passed (0-1)")
        findings: list[Finding] = Field(default_factory=list)
        recommendations: list[str] = Field(default_factory=list)
        summary: str = Field(default="", description="One-line summary")

    class GeneratorOutput(BaseModel):
        """Output schema for generator skills that produce files or datasets."""
        generated_files: list[str] = Field(default_factory=list, description="List of output file paths")
        parameters_used: dict[str, Any] = Field(default_factory=dict)
        quality_metrics: dict[str, Any] = Field(default_factory=dict)
        summary: str = Field(default="", description="Brief description of what was generated")

    class ReviewerOutput(BaseModel):
        """Output schema for any reviewer skill (governance, compliance, etc.)."""
        verdict: Literal["approved", "needs_revision", "rejected"] = Field(description="Review decision")
        score: float = Field(ge=0, le=100, description="Numeric quality score (0-100)")
        issues: list[dict[str, Any]] = Field(default_factory=list, description="List of identified issues")
        recommendations: list[str] = Field(default_factory=list)
        reviewed_items: int = Field(default=0, description="Number of items reviewed")

    class PipelineStepOutput(BaseModel):
        """Output schema for pipeline steps / analysis results."""
        step_name: str = Field(description="Name of the analysis step")
        status: Literal["success", "partial", "failed"] = Field(default="success")
        output_files: list[str] = Field(default_factory=list)
        metrics: dict[str, Any] = Field(default_factory=dict)
        duration_seconds: Optional[float] = Field(default=None)

else:
    # Fallback stubs when pydantic is not installed
    class Finding: pass  # type: ignore
    class QualityReportOutput: pass  # type: ignore
    class GeneratorOutput: pass  # type: ignore
    class ReviewerOutput: pass  # type: ignore
    class PipelineStepOutput: pass  # type: ignore


# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------

SCHEMA_REGISTRY: dict[str, type] = {}
if PYDANTIC_AVAILABLE:
    SCHEMA_REGISTRY = {
        "quality_report": QualityReportOutput,
        "generator": GeneratorOutput,
        "reviewer": ReviewerOutput,
        "pipeline_step": PipelineStepOutput,
    }


def list_schemas() -> list[dict]:
    """List all available output schemas with their field info."""
    result = []
    for name, schema_cls in SCHEMA_REGISTRY.items():
        fields = []
        if hasattr(schema_cls, "model_fields"):
            for fname, finfo in schema_cls.model_fields.items():
                fields.append({
                    "name": fname,
                    "type": str(finfo.annotation) if finfo.annotation else "any",
                    "required": finfo.is_required(),
                    "description": finfo.description or "",
                })
        result.append({"name": name, "fields": fields})
    return result


def validate_skill_output(output: dict, schema_name: str) -> dict:
    """Validate a skill output dict against a named schema.

    Returns:
        {"valid": True, "validated": <dict>} on success
        {"valid": False, "errors": [<error messages>]} on failure
        {"valid": True, "validated": output, "skipped": True} if pydantic unavailable
    """
    if not PYDANTIC_AVAILABLE:
        return {"valid": True, "validated": output, "skipped": True,
                "message": "Pydantic not installed, validation skipped"}

    schema_cls = SCHEMA_REGISTRY.get(schema_name)
    if not schema_cls:
        return {"valid": True, "validated": output, "skipped": True,
                "message": f"Unknown schema '{schema_name}', validation skipped"}

    try:
        validated = schema_cls.model_validate(output)
        return {"valid": True, "validated": validated.model_dump()}
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = " → ".join(str(l) for l in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg', '')}")
        return {"valid": False, "errors": errors}


def try_validate_output(output: Any, schema_name: Optional[str]) -> Any:
    """Best-effort validation wrapper. Returns original output if validation fails or is skipped."""
    if not schema_name or not isinstance(output, dict):
        return output
    result = validate_skill_output(output, schema_name)
    if result.get("valid"):
        return result.get("validated", output)
    else:
        logger.warning("Output validation failed for schema '%s': %s", schema_name, result.get("errors"))
        return output
