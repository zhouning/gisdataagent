"""Optional semantic review; permission and execution guards remain mandatory."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from .nl2sql_literal_grounding import collect_literal_evidence
from .nl2sql_relational_review import review_relational_sql


def review_enabled(settings: Mapping[str, str] | None = None) -> bool:
    env = os.environ if settings is None else settings
    value = env.get("GDA_NL2SQL_RELATIONAL_REVIEW", "0").strip().casefold()
    if value in {"0", "false", "off", "no", ""}:
        return False
    if value in {"1", "true", "on", "yes"}:
        return True
    raise ValueError("GDA_NL2SQL_RELATIONAL_REVIEW must be a boolean")


def review_draft(question: str, sql: str, payload: dict,
                 generate_json: Callable[[str], str],
                 validate_revision: Callable[[str], None]) -> tuple[str, dict]:
    """Fall back to the original when the reviewer exceeds its authority.

    The supplied validator must enforce the same registered source boundary as
    execution. A successful review does not waive later postprocessing or the
    execution guard. Disabling review also disables its source lookups.
    """
    if not review_enabled():
        return sql, {"decision": "disabled", "issues": [], "literal_evidence": []}
    literals = []
    if os.environ.get("GDA_NL2SQL_LITERAL_GROUNDING", "1").strip().casefold() in {"1", "true", "yes", "on"}:
        literals = collect_literal_evidence(question, sql, payload)
    result = review_relational_sql(question, sql, payload, generate_json, literal_evidence=literals)
    audit = {**result.to_dict(), "literal_evidence": literals}
    if result.decision == "revise":
        try:
            validate_revision(result.sql)
        except Exception as exc:
            audit.update(decision="revision_rejected", error=str(exc)[:300])
            return sql, audit
    return result.sql, audit
