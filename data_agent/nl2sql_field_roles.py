"""Present sourced field alternatives and their representation/grain contracts.

Role matches are candidates, not a forced interpretation. A role never grants
access to a field outside the current permission-filtered grounding payload.
"""
from __future__ import annotations

import hashlib
import json
import re


REPRESENTATIONS = {
    "display_text", "categorical_list", "row_measure", "snapshot_measure",
    "elapsed_duration", "clock_time",
}


def valid_field_role(role: dict) -> bool:
    if not isinstance(role, dict) or role.get("version") != 1:
        return False
    if role.get("representation") not in REPRESENTATIONS:
        return False
    if not all(isinstance(role.get(k), str) and role[k].strip()
               for k in ("concept", "meaning", "grain", "usage")):
        return False
    terms = role.get("request_terms")
    if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and t.strip() for t in terms):
        return False
    provenance = role.get("provenance") or {}
    return (isinstance(provenance, dict)
            and str(provenance.get("url", "")).startswith("https://")
            and bool(re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("artifact_sha256", "")))))


def field_role_candidates(payload: dict) -> list[dict]:
    """Retrieve a whole meaning group when one of its explicit terms matches."""
    question = str(payload.get("user_question") or "")
    groups: dict[str, list[dict]] = {}
    for table in payload.get("candidate_tables") or []:
        for column in table.get("columns") or []:
            role = (column.get("value_semantics") or {}).get("field_role")
            if not valid_field_role(role):
                continue
            matches = []
            for term in role["request_terms"]:
                pattern = re.escape(term)
                if not re.search(r"[\u4e00-\u9fff]", term):
                    pattern = r"(?<!\w)" + pattern + r"(?!\w)"
                if re.search(pattern, question, re.I):
                    matches.append(term)
            public_role = {k: role[k] for k in ("representation", "meaning", "grain", "usage")}
            public_role.update(field=table["table_name"] + "." + column["column_name"],
                               matched_terms=matches,
                               contract_sha256=hashlib.sha256(json.dumps(role, sort_keys=True).encode()).hexdigest())
            groups.setdefault(role["concept"], []).append(public_role)
    return [{"concept": concept, "alternatives": sorted(items, key=lambda x: x["field"]),
             "binding_status": "candidates_require_question_interpretation"}
            for concept, items in sorted(groups.items()) if any(x["matched_terms"] for x in items)]


def field_role_guidance(groups: list[dict]) -> str:
    if not groups:
        return ""
    return (
        "\n## Governed field alternatives and observation grain\n"
        "Select the representation the question actually requests. A full display string, "
        "a list of category tokens, and an exact whole-list value are different meanings. "
        "For list membership use the documented storage encoding; substring matching can "
        "match a different token. Whole-list equality requires the whole requested list. "
        "A recorded observation, an aggregate of observations, and a cumulative snapshot "
        "are different measures. Determine whether ranking is by one observation or a "
        "grouped total before choosing SUM/MAX/AVG. Do not silently invent an aggregation "
        "from the presence of an entity name. Preserve the requested unit and population. "
        "These alternatives supply meanings, not mandatory filters or benchmark answers.\n"
        + json.dumps(groups, ensure_ascii=False) + "\n"
    )
