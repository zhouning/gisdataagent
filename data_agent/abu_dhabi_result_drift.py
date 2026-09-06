"""Classify result differences against evaluation-only Abu Dhabi Gold.

This module produces evidence for source-data drift without changing Gold,
runtime semantic artifacts, or persisting source rows.  It deliberately emits
only fingerprints and governance metadata so the report is safe to publish
alongside benchmark summaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-report.v1"
PRIVATE_GOLD_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-private-gold.v1"
DRIFT_SCHEMA = "gda.abu-dhabi-nl2sql-result-drift-evidence.v1"


class DriftEvidenceError(ValueError):
    """Input reports do not form a valid drift comparison."""


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DriftEvidenceError(f"artifact_unreadable:{path}") from exc
    if not isinstance(payload, dict):
        raise DriftEvidenceError(f"artifact_object_required:{path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if report.get("schema") != REPORT_SCHEMA:
        raise DriftEvidenceError("report_schema_invalid")
    cases = [item for item in report.get("cases") or [] if isinstance(item, dict)]
    mapped = {str(item.get("case_id") or ""): item for item in cases}
    if not cases or "" in mapped or len(mapped) != len(cases):
        raise DriftEvidenceError("report_case_ids_invalid")
    return mapped


def _gold_map(gold: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if gold.get("schema") != PRIVATE_GOLD_SCHEMA:
        raise DriftEvidenceError("private_gold_schema_invalid")
    cases = [item for item in gold.get("cases") or [] if isinstance(item, dict)]
    mapped = {str(item.get("case_id") or ""): item for item in cases}
    if not cases or "" in mapped or len(mapped) != len(cases):
        raise DriftEvidenceError("private_gold_case_ids_invalid")
    return mapped


def _plan(case: dict[str, Any]) -> dict[str, Any]:
    return (case.get("observed") or {}).get("semantic_plan") or {}


def _contract_id(case: dict[str, Any]) -> str | None:
    contract = (case.get("observed") or {}).get("semantic_metric_contract") or {}
    value = str(contract.get("contract_id") or "").strip()
    if value:
        return value
    ir = (_plan(case).get("semantic_ir") or {})
    value = str(ir.get("metric_contract_id") or "").strip()
    return value or None


def _statement_hash(case: dict[str, Any]) -> str | None:
    observed = case.get("observed") or {}
    evidence = observed.get("query_evidence") or {}
    value = str(evidence.get("sql_sha256") or "").strip()
    if value:
        return value
    physical = observed.get("physical_plan") or {}
    value = str(physical.get("statement_sha256") or "").strip()
    if value:
        return value
    fingerprints = _plan(case).get("fingerprints") or {}
    value = str(fingerprints.get("compiled_statement_sha256") or "").strip()
    return value or None


def _source_fingerprint(case: dict[str, Any]) -> str | None:
    sources = ((_plan(case).get("semantic_ir") or {}).get("sources") or [])
    if not sources or not isinstance(sources[0], dict):
        return None
    value = str(sources[0].get("discovery_fingerprint") or "").strip()
    return value or None


def _result_evidence(case: dict[str, Any]) -> dict[str, Any]:
    observed = case.get("observed") or {}
    result = observed.get("result") or {}
    return {
        "status": observed.get("status"),
        "row_count": result.get("row_count"),
        "result_fingerprint": result.get("result_fingerprint"),
        "unordered_position_numeric6_fingerprint": (
            (result.get("equivalence_fingerprints") or {}).get(
                "unordered_position_numeric6_fingerprint"
            )
        ),
        "contract_id": _contract_id(case),
        "canonical_sql_sha256": _statement_hash(case),
        "source_discovery_fingerprint": _source_fingerprint(case),
        "route_evidence_valid": (case.get("checks") or {}).get("route_evidence_valid"),
        "semantic_spec_match": (case.get("checks") or {}).get("semantic_spec_match"),
    }


def _classify(
    baseline: dict[str, Any], candidate: dict[str, Any], gold: dict[str, Any]
) -> tuple[str, list[str]]:
    left = _result_evidence(baseline)
    right = _result_evidence(candidate)
    expected = gold.get("expected_result") or {}
    expected_fp = (expected.get("equivalence_fingerprints") or {}).get(
        "unordered_position_numeric6_fingerprint"
    )
    same_result = (
        left["row_count"] == right["row_count"]
        and left["unordered_position_numeric6_fingerprint"]
        == right["unordered_position_numeric6_fingerprint"]
    )
    same_plan = (
        left["contract_id"]
        and left["contract_id"] == right["contract_id"]
        and left["canonical_sql_sha256"]
        and left["canonical_sql_sha256"] == right["canonical_sql_sha256"]
    )
    both_valid = all(
        item.get("status") == "ok"
        and item.get("route_evidence_valid") is True
        and item.get("semantic_spec_match") is True
        for item in (left, right)
    )
    reasons: list[str] = []
    if same_result:
        reasons.append("both_routes_return_same_current_result")
    if same_plan:
        reasons.append("both_routes_use_same_reviewed_contract_and_statement")
    if both_valid:
        reasons.append("both_routes_pass_route_and_semantic_spec_checks")
    if expected_fp and left["unordered_position_numeric6_fingerprint"] != expected_fp:
        reasons.append("current_result_differs_from_frozen_gold")
    if both_valid and same_result and same_plan and expected_fp != left[
        "unordered_position_numeric6_fingerprint"
    ]:
        return "source_data_drift_candidate", reasons
    if not same_plan:
        reasons.append("route_or_contract_not_identical")
    if left["row_count"] != expected.get("row_count") or right["row_count"] != expected.get(
        "row_count"
    ):
        reasons.append("row_count_differs_from_frozen_gold")
    return "inconclusive_or_runtime_mismatch", reasons


def build_drift_evidence(
    baseline: dict[str, Any], candidate: dict[str, Any], gold: dict[str, Any], *,
    baseline_path: str | None = None, candidate_path: str | None = None,
    gold_path: str | None = None,
) -> dict[str, Any]:
    if baseline.get("execution_profile") != "baseline_sql":
        raise DriftEvidenceError("baseline_execution_profile_invalid")
    if candidate.get("execution_profile") != "semantic_ir_experimental":
        raise DriftEvidenceError("candidate_execution_profile_invalid")
    left_cases = _case_map(baseline)
    right_cases = _case_map(candidate)
    gold_cases = _gold_map(gold)
    selected = list((baseline.get("public_benchmark") or {}).get("selected_case_ids") or [])
    if not selected:
        raise DriftEvidenceError("selected_case_ids_missing")
    if set(selected) - set(left_cases) or set(selected) - set(right_cases) or set(selected) - set(gold_cases):
        raise DriftEvidenceError("selected_case_set_mismatch")
    entries: list[dict[str, Any]] = []
    for case_id in selected:
        left = left_cases[str(case_id)]
        right = right_cases[str(case_id)]
        gold_item = gold_cases[str(case_id)]
        if str(left.get("scope") or "") != "makani":
            continue
        if gold_item.get("outcome") != "execute":
            continue
        classification, reasons = _classify(left, right, gold_item)
        entries.append(
            {
                "case_id": str(case_id),
                "scope": "makani",
                "observed_at": {
                    "baseline": baseline.get("generated_at"),
                    "candidate": candidate.get("generated_at"),
                },
                "frozen_gold": {
                    "private_gold_contract_id": gold.get("contract_id"),
                    "row_count": (gold_item.get("expected_result") or {}).get("row_count"),
                    "unordered_position_numeric6_fingerprint": (
                        (gold_item.get("expected_result") or {}).get("equivalence_fingerprints") or {}
                    ).get("unordered_position_numeric6_fingerprint"),
                },
                "baseline": _result_evidence(left),
                "candidate": _result_evidence(right),
                "classification": classification,
                "classification_reasons": reasons,
            }
        )
    counts: dict[str, int] = {}
    for item in entries:
        key = str(item["classification"])
        counts[key] = counts.get(key, 0) + 1
    return {
        "schema": DRIFT_SCHEMA,
        "status": "complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "comparison": {
            "baseline_report": baseline_path,
            "candidate_report": candidate_path,
            "private_gold": gold_path,
            "baseline_report_sha256": None,
            "candidate_report_sha256": None,
            "private_gold_sha256": None,
        },
        "metrics": {
            "makani_case_count": len(entries),
            "classification_counts": dict(sorted(counts.items())),
            "source_data_drift_candidate_count": counts.get("source_data_drift_candidate", 0),
        },
        "cases": entries,
        "claim_boundary": {
            "gold_changed": False,
            "runtime_semantic_changed": False,
            "source_rows_persisted": False,
            "classification_is_not_a_gold_refresh": True,
        },
        "limitations": [
            "A drift candidate requires identical governed plans and matching current results across both routes.",
            "This report does not authorize changing private Gold; a Gold refresh requires a separately reviewed source snapshot.",
            "The report intentionally excludes questions, SQL text, and source rows.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--private-gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_drift_evidence(
        _load(args.baseline_report), _load(args.candidate_report), _load(args.private_gold),
        baseline_path=str(args.baseline_report), candidate_path=str(args.candidate_report),
        gold_path=str(args.private_gold),
    )
    report["comparison"].update(
        baseline_report_sha256=_sha256(args.baseline_report),
        candidate_report_sha256=_sha256(args.candidate_report),
        private_gold_sha256=_sha256(args.private_gold),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "metrics": report["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
