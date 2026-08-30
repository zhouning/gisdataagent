#!/usr/bin/env python3
"""Build a non-authoritative row-level correction template for AR-0 JQDLTB.

The output is an intake template, not an approved correction artifact.  It
contains the exact source keys that currently fail the frozen positive-area
rule and leaves the business values empty.  The transformation executor will
reject the template until every value is supplied and bound to an approved
ResourceVersion and SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/规划院提供数据样例及"
    "Demo系统功能演示建议/"
    "01数据样例/07规划编制相关数据/村规划/璧山区福禄镇斑竹村土地利用规划成果汇交/"
    "3规划数据库/310基础要素/JQDLTB.shp"
)
DEFAULT_BASELINE = (
    REPO_ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
)
DEFAULT_DIAGNOSTIC = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs/reports/jqdltb_business_correction_template_2026-08-30.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def build_template(
    *,
    source_path: Path = DEFAULT_SOURCE,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
) -> dict[str, Any]:
    """Read the source and return an empty, identity-bound correction template."""

    source_path = source_path.resolve(strict=True)
    baseline = _read_json(baseline_path.resolve(strict=True))
    diagnostic = _read_json(diagnostic_path.resolve(strict=True))
    source_info = diagnostic.get("source") or {}
    numeric_constraints = diagnostic.get("numeric_constraints") or []
    expected_nonpositive = {
        str(item.get("field")): int(item.get("nonpositive_count") or 0)
        for item in numeric_constraints
        if item.get("field") in {"TBMJ", "TBDLMJ"}
    }

    import geopandas as gpd

    frame = gpd.read_file(source_path)
    required_columns = {"TBBH", "TBMJ", "TBDLMJ"}
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise ValueError("JQDLTB source is missing required columns: " + ", ".join(missing))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    observed_counts = {field: 0 for field in ("TBMJ", "TBDLMJ")}
    for _, record in frame.iterrows():
        key_value = record.get("TBBH")
        if key_value is None or str(key_value).strip() == "":
            continue
        key = str(key_value).strip()
        areas = {field: _number(record.get(field)) for field in ("TBMJ", "TBDLMJ")}
        failing = [field for field, value in areas.items() if value is None or value <= 0]
        for field in failing:
            observed_counts[field] += 1
        if not failing:
            continue
        if key in seen:
            raise ValueError(f"source contains duplicate non-positive TBBH: {key}")
        seen.add(key)
        rows.append(
            {
                "TBBH": key,
                "source_TBMJ": areas["TBMJ"],
                "source_TBDLMJ": areas["TBDLMJ"],
                "TBMJ": None,
                "TBDLMJ": None,
            }
        )

    if observed_counts != expected_nonpositive:
        raise ValueError(
            "source/diagnostic non-positive counts differ: "
            f"source={observed_counts}, diagnostic={expected_nonpositive}"
        )
    expected_union = max(expected_nonpositive.values(), default=0)
    if len(rows) != expected_union:
        raise ValueError(
            f"source non-positive union count {len(rows)} differs from expected {expected_union}"
        )

    records = sorted(rows, key=lambda item: item["TBBH"])
    return {
        "schema": "gda.jqdltb_business_correction_template.v1",
        "status": "draft_template_not_approved",
        "policy": "business_correction",
        "required_fields": ["TBBH", "TBMJ", "TBDLMJ"],
        "instructions": [
            "Fill TBMJ and TBDLMJ for every record; do not change TBBH.",
            "Register this exact file as a versioned correction ResourceVersion.",
            "Submit the ResourceVersion ID and exact file SHA-256 with the decision packet.",
        ],
        "source": {
            "relative_path": source_info.get("relative_path"),
            "source_resource_version_id": baseline.get("source_resource_version_id"),
            "archive_sha256": baseline.get("archive_sha256"),
            "bundle_sha256": baseline.get("bundle_sha256"),
            "diagnostic_sha256": baseline.get("diagnostic_sha256"),
            "feature_count": int(source_info.get("feature_count") or len(frame)),
            "crs": source_info.get("crs"),
        },
        "observed_nonpositive_counts": observed_counts,
        "records": records,
    }


def validate_artifact(
    *,
    artifact_path: Path,
    source_path: Path = DEFAULT_SOURCE,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
) -> dict[str, Any]:
    """Validate a filled correction artifact against the frozen source keys."""

    artifact_path = artifact_path.resolve(strict=True)
    template = build_template(
        source_path=source_path,
        baseline_path=baseline_path,
        diagnostic_path=diagnostic_path,
    )
    payload = _read_json(artifact_path)
    rows = payload.get("records")
    if not isinstance(rows, list):
        raise ValueError("business correction artifact must contain a records list")

    expected = {str(row["TBBH"]): row for row in template["records"]}
    indexed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"business correction row {index} must be an object")
        key_value = row.get("TBBH")
        if key_value is None or str(key_value).strip() == "":
            raise ValueError(f"business correction row {index} requires TBBH")
        key = str(key_value).strip()
        if key in indexed:
            raise ValueError(f"business correction contains duplicate TBBH: {key}")
        indexed[key] = row

    expected_keys = set(expected)
    observed_keys = set(indexed)
    if observed_keys != expected_keys:
        missing = sorted(expected_keys - observed_keys)
        extra = sorted(observed_keys - expected_keys)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("unexpected=" + ",".join(extra))
        raise ValueError("business correction key set differs: " + "; ".join(details))

    for key, row in indexed.items():
        for field in ("TBMJ", "TBDLMJ"):
            value = _number(row.get(field))
            if value is None or value <= 0:
                raise ValueError(
                    f"business correction {key}.{field} must be a finite positive number"
                )
        for field in ("source_TBMJ", "source_TBDLMJ"):
            if field in row and _number(row[field]) != _number(expected[key][field]):
                raise ValueError(f"business correction {key}.{field} differs from frozen source")

    return {
        "schema": "gda.jqdltb_business_correction_validation.v1",
        "status": "ready_for_resource_version_registration",
        "artifact_path": str(artifact_path),
        "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "records": len(indexed),
        "source_identity": template["source"],
        "resource_version_id": None,
        "authority_state_created": False,
        "data_product_version_created": False,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--validate",
        type=Path,
        help="validate a filled correction artifact instead of building a template",
    )
    args = parser.parse_args(argv)
    if args.validate is not None:
        try:
            report = validate_artifact(
                artifact_path=args.validate,
                source_path=args.source,
                baseline_path=args.baseline,
                diagnostic_path=args.diagnostic,
            )
            if args.output is not None:
                output = args.output.resolve()
                if output == args.validate.resolve():
                    raise ValueError("validation output must not overwrite the artifact")
                report["report_path"] = str(output)
                _write_json(output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(
                json.dumps(
                    {
                        "schema": "gda.jqdltb_business_correction_validation.v1",
                        "status": "invalid_fail_closed",
                        "error": str(exc),
                        "authority_state_created": False,
                        "data_product_version_created": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2

    payload = build_template(
        source_path=args.source,
        baseline_path=args.baseline,
        diagnostic_path=args.diagnostic,
    )
    output = (args.output or DEFAULT_OUTPUT).resolve()
    _write_json(output, payload)
    print(
        json.dumps(
            {
                "output": str(output),
                "status": payload["status"],
                "records": len(payload["records"]),
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
