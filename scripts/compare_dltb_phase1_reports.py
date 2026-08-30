#!/usr/bin/env python3
"""Compare stored phase-1 PostGIS and lake-SQL DLTB query reports.

This is an offline evidence checker. It does not call an LLM or re-run a
database query; it proves that two already completed phase-1 runs used the
same governed product and returned equivalent semantic results.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


QUESTIONS = (
    "各地类图斑数量和面积是多少？",
    "列出面积属性与几何面积差异较大的图斑",
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"report must be an object: {path}")
    return payload


def _products(report: dict[str, Any]) -> dict[str, Any]:
    return ((report.get("paper9_handoff") or {}).get("products") or {})


def _area(row: dict[str, Any]) -> float:
    for key in ("总面积_m2", "总面积", "area_sqm", "total_area_sqm", "total_area"):
        if key in row and row[key] is not None:
            return float(row[key])
    raise ValueError(f"area column missing from row: {list(row)}")


def _count(row: dict[str, Any]) -> int:
    for key in ("图斑数量", "feature_count", "parcel_count", "记录数"):
        if key in row and row[key] is not None:
            return int(row[key])
    raise ValueError(f"count column missing from row: {list(row)}")


def _bsm(row: dict[str, Any]) -> str:
    value = row.get("BSM", row.get("feature_identifier"))
    return str(value).removesuffix(".0")


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, tuple[int, float]]:
    return {
        str(row.get("DLMC", row.get("land_use_name"))): (_count(row), _area(row))
        for row in rows
    }


def _consistency_summary(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    return [(_bsm(row), float(row["_gda_area_delta_sqm"])) for row in rows]


def _same_float(left: float, right: float, tolerance: float = 1e-8) -> bool:
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) / scale <= tolerance


def compare(postgis_path: Path, lake_path: Path) -> dict[str, Any]:
    postgis = _load(postgis_path)
    lake = _load(lake_path)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, **detail: Any) -> None:
        checks.append({"check": name, "passed": bool(passed), **detail})

    post_identity = postgis.get("dataset_identity") or {}
    lake_identity = lake.get("dataset_identity") or {}
    check(
        "dataset_identity",
        post_identity.get("dataset_id") == lake_identity.get("dataset_id") == "bishan"
        and post_identity.get("identity_verified") is True
        and lake_identity.get("identity_verified") is True,
        postgis_dataset_id=post_identity.get("dataset_id"),
        lake_dataset_id=lake_identity.get("dataset_id"),
        postgis_verification=post_identity.get("verification_status"),
        lake_verification=lake_identity.get("verification_status"),
    )
    post_dltb = _products(postgis).get("dltb") or {}
    lake_dltb = _products(lake).get("dltb") or {}
    check(
        "same_governed_dltb",
        post_dltb.get("sha256") == lake_dltb.get("sha256")
        and post_dltb.get("feature_count") == lake_dltb.get("feature_count") == 101657,
        sha256=post_dltb.get("sha256"),
        postgis_product=post_dltb.get("path"),
        lake_product=lake_dltb.get("path"),
        feature_count=post_dltb.get("feature_count"),
    )
    post_projection = (postgis.get("semantic_projection") or {}).get("projection") or {}
    lake_projection = (lake.get("semantic_projection") or {}).get("projection") or {}
    check(
        "same_semantic_projection_source",
        post_projection.get("target_sha256") == lake_projection.get("target_sha256")
        and post_projection.get("semantic_source") == lake_projection.get("semantic_source")
        == "land_parcel_current",
        semantic_source=post_projection.get("semantic_source"),
        target_sha256=post_projection.get("target_sha256"),
        postgis_projection_id=post_projection.get("projection_id"),
        lake_projection_id=lake_projection.get("projection_id"),
    )

    post_queries = postgis.get("semantic_queries") or []
    lake_queries = lake.get("semantic_queries") or []
    query_checks: list[dict[str, Any]] = []
    for question in QUESTIONS:
        left = next((item for item in post_queries if item.get("question") == question), None)
        right = next((item for item in lake_queries if item.get("question") == question), None)
        base = {"question": question, "postgis_present": bool(left), "lake_present": bool(right)}
        if not left or not right:
            query_checks.append({**base, "equivalent": False, "reason": "query missing"})
            continue
        evidence_ok = all(
            item.get("status") == "succeeded"
            and item.get("fallback_used") is False
            and item.get("diagnostic_only") is False
            and (item.get("llm") or {}).get("status") == "succeeded"
            for item in (left, right)
        )
        if question == QUESTIONS[0]:
            left_value = _group_summary(left.get("rows") or [])
            right_value = _group_summary(right.get("rows") or [])
            equivalent = left_value.keys() == right_value.keys() and all(
                left_value[key][0] == right_value[key][0]
                and _same_float(left_value[key][1], right_value[key][1])
                for key in left_value
            )
            detail = {
                "result_kind": "grouped_land_use_summary",
                "postgis_group_count": len(left_value),
                "lake_group_count": len(right_value),
                "postgis_total_rows": len(left.get("rows") or []),
                "lake_total_rows": len(right.get("rows") or []),
            }
        else:
            left_value = _consistency_summary(left.get("rows") or [])
            right_value = _consistency_summary(right.get("rows") or [])
            equivalent = len(left_value) == len(right_value) and all(
                l_id == r_id and _same_float(l_delta, r_delta)
                for (l_id, l_delta), (r_id, r_delta) in zip(left_value, right_value, strict=True)
            )
            detail = {
                "result_kind": "area_delta_top_n",
                "postgis_row_count": len(left_value),
                "lake_row_count": len(right_value),
                "top_bsm": [item[0] for item in left_value[:5]],
            }
        query_checks.append(
            {
                **base,
                "equivalent": bool(equivalent and evidence_ok),
                "result_equivalent": bool(equivalent),
                "llm_evidence_complete": evidence_ok,
                "sql_equal": left.get("sql") == right.get("sql"),
                "postgis_sql": left.get("sql"),
                "lake_sql": right.get("sql"),
                "postgis_llm": left.get("llm"),
                "lake_llm": right.get("llm"),
                **detail,
            }
        )
    checks.append(
        {
            "check": "semantic_queries",
            "passed": all(item.get("equivalent") for item in query_checks),
            "query_count": len(query_checks),
        }
    )
    return {
        "schema": "gda.dltb-phase1-report-comparison.v1",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reference_engine": "postgis",
        "reports": {"postgis": str(postgis_path.resolve()), "lake": str(lake_path.resolve())},
        "checks": checks,
        "query_checks": query_checks,
        "all_passed": all(item.get("passed") for item in checks),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgis-report", required=True, type=Path)
    parser.add_argument("--lake-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compare(args.postgis_report.resolve(), args.lake_report.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"output": str(args.output.resolve()), "all_passed": report["all_passed"]},
            ensure_ascii=False,
        )
    )
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
