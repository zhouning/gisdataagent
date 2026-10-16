"""Native structured-output contract for bounded SQL semantic review."""
from __future__ import annotations

import os

REVIEW_ASPECTS = ("outputs", "row_grain", "relationships", "filters", "ordering")


def review_checklist_enabled() -> bool:
    value = os.environ.get("GDA_NL2SQL_REVIEW_CHECKLIST", "0").strip().casefold()
    if value in {"0", "false", "off", "no", ""}:
        return False
    if value in {"1", "true", "on", "yes"}:
        return True
    raise ValueError("GDA_NL2SQL_REVIEW_CHECKLIST must be a boolean")


def review_response_format() -> dict:
    """Constrain syntax; source permissions and SQL guards still run later."""
    result = {
        "type": "json_schema",
        "json_schema": {
            "name": "nl2sql_semantic_review", "strict": True,
            "schema": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "decision": {"type": "string", "enum": ["keep", "revise"]},
                    "issues": {"type": "array", "maxItems": 5,
                               "items": {"type": "string"}},
                    "sql": {"type": "string", "minLength": 1},
                },
                "required": ["decision", "issues", "sql"],
            },
        },
    }
    if review_checklist_enabled():
        schema = result["json_schema"]["schema"]
        checks = {"type": "object", "additionalProperties": False,
                  "properties": {}, "required": list(REVIEW_ASPECTS)}
        for aspect in REVIEW_ASPECTS:
            checks["properties"][aspect] = {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["matched", "mismatch", "uncertain"]},
                    "finding": {"type": "string", "minLength": 1, "maxLength": 320}},
                "required": ["status", "finding"]}
        # Generate the concrete comparisons before making the final decision.
        schema["properties"] = {"checks": checks, **schema["properties"]}
        schema["required"] = ["checks", *schema["required"]]
    return result
