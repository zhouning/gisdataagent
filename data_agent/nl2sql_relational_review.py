"""Bounded semantic review using the same authorized grounding as generation.

The reviewer sees the question, schema, registered relationships and optional
literal lookup evidence. It never receives benchmark evidence or expected SQL.
Its output must go through the normal product postprocessor and safety guards.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from .nl2sql_output_contracts import REVIEW_ASPECTS, review_checklist_enabled


@dataclass(frozen=True)
class RelationalReview:
    sql: str
    decision: str
    issues: tuple[str, ...]
    error: str = ""
    checks: dict | None = None

    def to_dict(self) -> dict:
        result = {"decision": self.decision, "issues": list(self.issues), "error": self.error,
                  "reviewed_sql": self.sql}
        if self.checks is not None:
            result["checks"] = self.checks
        return result


def review_relational_sql(
    question: str,
    sql: str,
    payload: dict,
    generate: Callable[[str], str],
    *,
    literal_evidence: list[dict] | None = None,
) -> RelationalReview:
    """Review business meaning without executing or selecting by gold results."""
    tables = payload.get("candidate_tables") or []
    checklist = review_checklist_enabled()
    identities = [
        {"table": table["table_name"], "primary_key": table.get("primary_keys") or [],
         "relationships": table.get("foreign_keys") or []}
        for table in tables if table.get("table_name")
    ]
    prompt = (
        "You are reviewing a read-only SQL draft for the GIS Data Agent.\n"
        "Compare the draft with the QUESTION and governed schema. Correct a "
        "specific mismatch only when supported by the question or metadata. "
        "A draft that executes can still answer the wrong business question.\n"
        "Check: which table owns each requested attribute or measure; requested "
        "output columns and their order; target entity versus detail rows; "
        "join multiplicity; required aggregation grain; extrema and ties; "
        "units, categorical codes, stored date/duration formats, and inclusive "
        "versus exclusive boundaries. Follow explicit business definitions. "
        "A stored primary key identifies a row, which may be an observation "
        "rather than a distinct business entity. Group by the requested entity's "
        "identifier, not merely a non-unique name. For an extremum, handle tied "
        "entities unless the question specifies a top-K limit. For highest or "
        "lowest known values, NULL is not an extremum: specify NULLS LAST in "
        "ranking without inventing a separate non-null filter. A stated date "
        "scope applies to both the target rows and any comparison population "
        "unless the question explicitly says otherwise. "
        "Do not invent filters, metrics, output identifiers, relationships, "
        "or interpretations to make the query seem more useful.\n"
        "Literal lookup evidence is a small set of observed values, not a "
        "complete value domain. Exact-match evidence concerns that literal "
        "alone and says nothing about other filters. Similar values are "
        "suggestions, not permission to change the entity. Use a suggested "
        "spelling only if it clearly names the same requested entity.\n"
        f"Output one JSON object only, with exactly these keys: {'checks (comparison record), ' if checklist else ''}decision "
        "(keep or revise), issues (at most five short strings naming actual "
        "mismatches), sql (one complete read-only PostgreSQL statement). "
        "If no supported mismatch exists, keep the SQL unchanged. "
        "No Markdown and no running commentary.\n\n"
        f"GOVERNED CONTEXT:\n{payload.get('grounding_prompt') or ''}\n\n"
        f"ROW IDENTITIES AND REGISTERED RELATIONSHIPS:\n{json.dumps(identities, ensure_ascii=False)}\n\n"
        f"OBSERVED LITERAL VALUES:\n{json.dumps(literal_evidence or [], ensure_ascii=False)}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"DRAFT SQL:\n{sql}"
    )
    if checklist:
        prompt += (
            "\n\nREQUIRED COMPARISON RECORD:\n"
            "Use exactly four top-level keys: checks, decision, issues, sql. "
            "Write checks first with exactly outputs, row_grain, relationships, filters, ordering. "
            "Each check contains status (matched, mismatch or uncertain) and finding "
            "(one brief factual comparison, at most 320 characters). Compare the actual "
            "draft with the requested answer, citing relevant governed fields; do not "
            "merely say the SQL is valid. outputs checks the requested columns and "
            "derived units; row_grain checks whether one entity or category appears "
            "once or is repeated by detail joins; relationships checks attribute owners "
            "and join populations; filters checks all conditions, boundaries and codes; "
            "ordering checks the requested ranking, ties, time scope and limits. "
            "Mark uncertainty explicitly; it does not authorize a guessed correction. "
            "An identified mismatch must lead to revise with a specific issue; "
            "revise requires at least one identified mismatch. SQL syntax and source "
            "safety will still be validated independently.\n"
        )
    try:
        raw = generate(prompt).strip()
        if raw.startswith(chr(96) * 3):
            raw = raw.split("\n", 1)[1].rsplit(chr(96) * 3, 1)[0].strip()
        response = json.loads(raw)
        expected_keys = {"decision", "issues", "sql"} | ({"checks"} if checklist else set())
        if not isinstance(response, dict) or set(response) != expected_keys:
            raise ValueError("Review response has invalid fields")
        decision, issues, revised = response["decision"], response["issues"], response["sql"]
        if decision not in {"keep", "revise"}:
            raise ValueError("Review response has invalid decision")
        if (not isinstance(issues, list) or len(issues) > 5
                or any(not isinstance(issue, str) for issue in issues)):
            raise ValueError("Review response has invalid issues")
        if not isinstance(revised, str) or not revised.strip():
            raise ValueError("Review response has no SQL")
        checks = response.get("checks")
        if checklist:
            if not isinstance(checks, dict) or set(checks) != set(REVIEW_ASPECTS):
                raise ValueError("Review comparison record is incomplete")
            for check in checks.values():
                if (not isinstance(check, dict) or set(check) != {"status", "finding"}
                        or check["status"] not in {"matched", "mismatch", "uncertain"}
                        or not isinstance(check["finding"], str)
                        or not 1 <= len(check["finding"].strip()) <= 320):
                    raise ValueError("Review comparison record has an invalid check")
            mismatch = any(check["status"] == "mismatch" for check in checks.values())
            if (decision == "revise") != mismatch:
                raise ValueError("Review decision contradicts its comparison record")
        if decision == "keep":
            return RelationalReview(sql, "keep", tuple(issues), checks=checks)
        if not any(issue.strip() for issue in issues):
            raise ValueError("Revision requires a supported mismatch")
        import sqlglot
        from sqlglot import exp

        statements = sqlglot.parse(revised, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
            raise ValueError("Review response is not one read-only query")
        if any(isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create,
                                 exp.Drop, exp.Alter, exp.Command))
               for node in statements[0].walk()):
            raise ValueError("Review response contains a forbidden operation")
        original = sqlglot.parse_one(sql, read="postgres")
        if statements[0] == original:
            raise ValueError("Review claims a revision but SQL is unchanged")
        return RelationalReview(revised.strip().rstrip(";"), "revise", tuple(issues), checks=checks)
    except Exception as exc:
        # Failed review cannot replace a valid draft with a placeholder.
        return RelationalReview(sql, "unavailable", (), str(exc)[:300])
