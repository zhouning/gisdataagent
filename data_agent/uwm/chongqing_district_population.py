"""Chongqing district population statistics from local planning sample."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


CHONGQING_DISTRICT_POPULATION_SCHEMA = "uwm.chongqing_district_population_stats.v1"
CHONGQING_DISTRICT_POPULATION_DATASET_ID = "chongqing_district_population_stats_2021_local"


def build_chongqing_district_population_proxy(
    *,
    records: list[dict[str, Any]],
    source_ref: str,
    created_at: str,
) -> dict[str, Any]:
    """Normalize Chongqing district population rows into an auditable UWM asset."""

    rows = [_normalise_row(record) for record in records]
    rows = [row for row in rows if row.get("admin_code")]
    city_total_rows = [row for row in rows if row["admin_code"] == "500000"]
    district_rows = [row for row in rows if row["admin_code"] != "500000"]
    resident_sum = sum(_float(row.get("resident_population_10k")) for row in district_rows)
    registered_sum = sum(_float(row.get("registered_population_10k")) for row in district_rows)
    return {
        "schema": CHONGQING_DISTRICT_POPULATION_SCHEMA,
        "dataset_id": CHONGQING_DISTRICT_POPULATION_DATASET_ID,
        "source": "local planning sample Excel; row source field cites Chongqing Statistical Yearbook 2022",
        "source_ref": source_ref,
        "created_at": created_at,
        "year": _first_year(rows),
        "record_counts": {
            "raw_rows": len(records),
            "district_rows": len(district_rows),
            "city_total_rows": len(city_total_rows),
        },
        "city_total": city_total_rows[0] if city_total_rows else {},
        "district_rows": district_rows,
        "summary": {
            "district_resident_population_10k_sum": round(resident_sum, 6),
            "district_registered_population_10k_sum": round(registered_sum, 6),
            "district_count": len(district_rows),
            "max_resident_population_district": _max_row(district_rows, "resident_population_10k"),
            "max_urbanization_rate_district": _max_row(district_rows, "urbanization_rate_percent"),
        },
        "mmfe_target_roles": ["population_vulnerability", "equity_evaluation", "baseline_context"],
        "synthetic_flags": [{"dataset_id": CHONGQING_DISTRICT_POPULATION_DATASET_ID, "status": "real"}],
        "claim_boundary": {
            "max_claim_level": "fragile",
            "reason": "Local planning-sample district statistics support bounded context only until source license and lineage are fully verified.",
        },
        "limitations": [
            "district_level_not_township_or_grid_population",
            "source_license_and_redistribution_terms_pending",
            "2021_statistics_not_scene_2024_population",
            "not_observed_policy_outcome",
            "does_not_replace_ghsl_township_alignment_or_local_census_microdata",
        ],
        "empirical_superiority_claim": False,
    }


def write_chongqing_district_population_snapshot(
    *,
    output_dir: str | Path,
    records: list[dict[str, Any]],
    source_ref: str,
    created_at: str,
) -> dict[str, Any]:
    """Persist normalized population proxy, district CSV and snapshot manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    proxy = build_chongqing_district_population_proxy(
        records=records,
        source_ref=source_ref,
        created_at=created_at,
    )
    _write_json(output_path / "chongqing_district_population_proxy.json", proxy)
    _write_rows_csv(output_path / "chongqing_district_population_district_rows.csv", proxy["district_rows"])
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": f"{CHONGQING_DISTRICT_POPULATION_DATASET_ID}_snapshot",
        "source_dataset_ids": [CHONGQING_DISTRICT_POPULATION_DATASET_ID],
        "fetched_at": created_at,
        "source_ref": source_ref,
        "files": {
            "normalized_proxy": "chongqing_district_population_proxy.json",
            "district_rows_csv": "chongqing_district_population_district_rows.csv",
        },
        "record_counts": proxy["record_counts"],
        "summary": proxy["summary"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "mmfe_target_roles": proxy["mmfe_target_roles"],
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def build_chongqing_district_population_mmfe_state_input(
    proxy: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert district population statistics into MMFE UWM state input."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    if proxy.get("schema") != CHONGQING_DISTRICT_POPULATION_SCHEMA:
        raise ValueError(f"proxy schema must be {CHONGQING_DISTRICT_POPULATION_SCHEMA}")
    district_count = (proxy.get("record_counts") or {}).get("district_rows", 0)
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": "mmfe-chongqing-district-population-2021",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.58},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "district_has_resident_population",
                "uwm_usage": "population_vulnerability",
                "relation_count": district_count,
            },
            {
                "semantic_relation_type": "district_has_urbanization_rate",
                "uwm_usage": "equity_evaluation",
                "relation_count": district_count,
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "district_admin_unit",
                "crs": "tabular_admin_code",
                "feature_count": district_count,
                "temporal_extent": str(proxy.get("year") or "2021"),
            },
            "role_bindings": [
                {
                    "role": "district_resident_population_2021",
                    "uwm_role": "population_vulnerability",
                    "object_type": "district_table",
                    "source_dataset_id": CHONGQING_DISTRICT_POPULATION_DATASET_ID,
                    "synthetic_status": "real",
                },
                {
                    "role": "district_urbanization_rate_2021",
                    "uwm_role": "equity_evaluation",
                    "object_type": "district_table",
                    "source_dataset_id": CHONGQING_DISTRICT_POPULATION_DATASET_ID,
                    "synthetic_status": "real",
                },
            ],
        },
        timestamp=timestamp,
    )
    payload["source_proxy"] = {
        "schema": proxy.get("schema"),
        "record_counts": proxy.get("record_counts"),
        "summary": proxy.get("summary"),
        "claim_boundary": proxy.get("claim_boundary"),
        "limitations": proxy.get("limitations") or [],
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "District population statistics are local real context but do not replace township/grid population alignment or observed policy outcome data"
    )
    return payload


def _normalise_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "admin_code": _admin_code(record.get("行政区划代码")),
        "district_name": str(record.get("区划名称") or "").strip(),
        "source_label": str(record.get("数据来源") or "").strip(),
        "year": _int(record.get("年份")),
        "registered_households_10k": _float(_pick(record, "户籍总户数(万户)", "户籍总户数_万户_")),
        "registered_population_10k": _float(_pick(record, "户籍总人口(万人)", "户籍总人口_万人_")),
        "registered_urban_population_10k": _float(_pick(record, "户籍城镇总人口(万人)", "户籍城镇总人口_万人_")),
        "registered_rural_population_10k": _float(_pick(record, "户籍乡村总人口(万人)", "户籍乡村总人口_万人_")),
        "resident_population_10k": _float(record.get("常住人口")),
        "resident_urban_population_10k": _float(record.get("常住城镇人口")),
        "urbanization_rate_percent": _float(record.get("城镇化率")),
    }


def _pick(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record.get(key)
    return None


def _first_year(rows: list[dict[str, Any]]) -> int | None:
    for row in rows:
        if row.get("year") is not None:
            return row["year"]
    return None


def _max_row(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not rows:
        return {}
    row = max(rows, key=lambda item: _float(item.get(key)))
    return {
        "admin_code": row["admin_code"],
        "district_name": row["district_name"],
        key: row[key],
    }


def _admin_code(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value).strip()


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
