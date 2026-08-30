#!/usr/bin/env python3
"""Validate all DLTB semantic-query engines with identical questions."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.dltb_multi_engine_query import query_dltb

ENGINES = ("postgis", "lake", "geopandas")
CASES = (
    {
        "id": "dataset_count",
        "question": "地类图斑一共有多少条记录？",
        "kind": "count",
    },
    {
        "id": "cultivated_summary",
        "question": "统计地类编码以01开头的耕地图斑数量和图斑面积。",
        "kind": "count_area",
    },
    {
        "id": "parcel_lookup",
        "question": "查询BSM为658291的图斑，返回BSM、地类编码和地类名称。",
        "kind": "parcel",
    },
)


def _row_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    normalized = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        if name.casefold() in normalized:
            return normalized[name.casefold()]
    return None


def _count_value(row: dict[str, Any]) -> Any:
    value = _row_value(
        row,
        (
            "feature_count",
            "count",
            "count(*)",
            "count_star()",
            "record_count",
            "total_count",
            "parcel_count",
            "图斑数量",
            "记录数",
        ),
    )
    if value is not None:
        return value
    return next(
        (value for key, value in row.items() if "count" in str(key).casefold()),
        None,
    )


def _area_value(row: dict[str, Any]) -> Any:
    value = _row_value(
        row,
        (
            "area_sqm",
            "parcel_area_sqm",
            "total_area_sqm",
            "total_area",
            "图斑面积",
        ),
    )
    if value is not None:
        return value
    return next(
        (
            value
            for key, value in row.items()
            if "area" in str(key).casefold() or "sum" in str(key).casefold()
        ),
        None,
    )


def _normalize(rows: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    row = rows[0] if rows else {}
    if kind == "count":
        return {"feature_count": int(_count_value(row))}
    if kind == "count_area":
        counts = [_count_value(item) for item in rows]
        areas = [_area_value(item) for item in rows]
        return {
            "feature_count": int(sum(value for value in counts if value is not None)),
            "area_sqm": float(sum(value for value in areas if value is not None)),
        }
    if kind == "parcel":
        return {
            "BSM": str(_row_value(row, ("BSM", "feature_identifier"))).removesuffix(".0"),
            "DLBM": str(_row_value(row, ("DLBM", "land_use_code"))),
            "DLMC": str(_row_value(row, ("DLMC", "land_use_name"))),
        }
    raise ValueError(f"unsupported validation kind: {kind}")


def _equivalent(kind: str, left: dict[str, Any], right: dict[str, Any]) -> bool:
    if kind != "count_area":
        return left == right
    if left["feature_count"] != right["feature_count"]:
        return False
    scale = max(abs(left["area_sqm"]), abs(right["area_sqm"]), 1.0)
    return abs(left["area_sqm"] - right["area_sqm"]) / scale <= 1e-9


def run_validation(projection: Path) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for case in CASES:
        for engine in ENGINES:
            result = query_dltb(
                projection,
                case["question"],
                execution_engine=engine,
                limit=100,
            )
            normalized = _normalize(result.get("rows") or [], case["kind"])
            runs.append(
                {
                    "case_id": case["id"],
                    "question": case["question"],
                    "kind": case["kind"],
                    "engine": engine,
                    "normalized_result": normalized,
                    "result": result,
                }
            )

    comparisons = []
    for case in CASES:
        case_runs = [row for row in runs if row["case_id"] == case["id"]]
        reference = next(row for row in case_runs if row["engine"] == "postgis")
        comparisons.append(
            {
                "case_id": case["id"],
                "reference_engine": "postgis",
                "equivalent": all(
                    _equivalent(
                        case["kind"],
                        reference["normalized_result"],
                        row["normalized_result"],
                    )
                    for row in case_runs
                ),
                "results": {row["engine"]: row["normalized_result"] for row in case_runs},
            }
        )
    return {
        "schema": "gda.dltb-multi-engine-validation.v1",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "projection": str(projection.resolve()),
        "default_engine": "postgis",
        "engines": list(ENGINES),
        "all_equivalent": all(row["equivalent"] for row in comparisons),
        "comparisons": comparisons,
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_validation(args.projection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "all_equivalent": report["all_equivalent"],
                "comparisons": report["comparisons"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["all_equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
