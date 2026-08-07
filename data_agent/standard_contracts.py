"""Readers for auditable geospatial standard-contract catalogs.

The two project workbooks are discovery evidence, not authoritative schemas.
This module keeps that distinction explicit: screenshot-derived contracts are
usable for candidate matching and field-level gap reports, but never grant an
automatic publication decision.  A reviewed JSON catalog can carry the same
contract shape with ``authority`` set to ``ea_standard``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_identifier(value: Any) -> str:
    """Normalize field/layer names only for comparison, never for storage."""
    return re.sub(r"[\s_\-（）()：:./\\]+", "", _text(value)).lower()


def _header_row(rows: list[tuple[Any, ...]], required: set[str]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(rows):
        columns = {_text(value): position for position, value in enumerate(row) if _text(value)}
        if required.issubset(columns):
            return index, columns
    raise ValueError(f"workbook header not found: {sorted(required)}")


def _workbook_rows(path: Path, sheet: str) -> list[tuple[Any, ...]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    if sheet not in workbook.sheetnames:
        raise ValueError(f"sheet not found: {sheet}")
    return [tuple(row) for row in workbook[sheet].iter_rows(values_only=True)]


def load_shp_contract_catalog(path: str | Path) -> dict[str, Any]:
    """Parse the SHP workbook into contracts keyed by the layer code."""
    source = Path(path).expanduser().resolve()
    summary_rows = _workbook_rows(source, "数据表汇总")
    detail_rows = _workbook_rows(source, "字段明细")
    summary_at, summary_columns = _header_row(
        summary_rows, {"图层/数据表代码", "中文名称", "几何类型", "完整性/核验说明"}
    )
    detail_at, detail_columns = _header_row(
        detail_rows, {"图层/数据表代码", "字段序号", "字段名称", "字段类别"}
    )
    contracts: dict[str, dict[str, Any]] = {}
    for row in summary_rows[summary_at + 1 :]:
        code = _text(row[summary_columns["图层/数据表代码"]])
        if not code:
            continue
        note = _text(row[summary_columns["完整性/核验说明"]])
        contracts[code] = {
            "code": code,
            "name": _text(row[summary_columns["中文名称"]]),
            "geometry_type": _text(row[summary_columns["几何类型"]]),
            "field_count": int(row[summary_columns["可辨字段数"]] or 0)
            if "可辨字段数" in summary_columns
            else None,
            "source_photos": _text(row[summary_columns["来源照片"]]).split("、")
            if "来源照片" in summary_columns
            else [],
            "name_source": _text(row[summary_columns["名称来源"]])
            if "名称来源" in summary_columns
            else "",
            "completeness_note": note,
            "fields": [],
            "authority": "screenshot_candidate",
            "publication_gate": "manual_review",
            "requires_source_schema_verification": True,
        }
    for row in detail_rows[detail_at + 1 :]:
        code = _text(row[detail_columns["图层/数据表代码"]])
        field_name = _text(row[detail_columns["字段名称"]])
        if not code or not field_name or code not in contracts:
            continue
        contracts[code]["fields"].append(
            {
                "ordinal": int(row[detail_columns["字段序号"]] or 0),
                "name": field_name,
                "category": _text(row[detail_columns["字段类别"]]),
                "source_photo": _text(row[detail_columns["来源照片"]])
                if "来源照片" in detail_columns
                else "",
                "source": "SHP workbook screenshot",
            }
        )
    for contract in contracts.values():
        contract["fields"].sort(key=lambda item: item["ordinal"])
        contract["candidate_fields"] = [item["name"] for item in contract["fields"]]
        contract["field_categories"] = {
            item["name"]: item["category"] for item in contract["fields"]
        }
    return {
        "schema_version": "gda.standard-contract-catalog.v1",
        "generated_at": _now(),
        "source_workbooks": [source.name],
        "authority": "screenshot_candidate",
        "contracts": contracts,
    }


def load_contract_catalog(path: str | Path) -> dict[str, Any]:
    """Load either an Excel discovery workbook or a generated JSON catalog."""
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() in {".xlsx", ".xlsm", ".xltx"}:
        return load_shp_contract_catalog(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if "contracts" in payload:
        return payload
    # Legacy aliases JSON remains supported as a field-only catalog.
    aliases_payload = payload.get("field_aliases") or {
        key: value for key, value in payload.items() if isinstance(value, dict)
    }
    contracts = {
        code: {
            "code": code,
            "name": code,
            "geometry_type": "",
            "fields": [
                {
                    "ordinal": index,
                    "name": name,
                    "aliases": list(values),
                    "category": "",
                }
                for index, (name, values) in enumerate(fields.items(), 1)
            ],
            "candidate_fields": list(fields.keys()),
            "authority": "ea_standard",
            "publication_gate": "automatic",
            "requires_source_schema_verification": False,
        }
        for code, fields in aliases_payload.items()
    }
    return {"schema_version": "gda.standard-contract-catalog.v1", "contracts": contracts, **payload}


def aliases_from_catalog(catalog: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    """Build matching aliases without changing the workbook's displayed names."""
    result: dict[str, dict[str, set[str]]] = {}
    for code, contract in (catalog.get("contracts") or {}).items():
        result[code] = {}
        for field in contract.get("fields") or []:
            name = _text(field.get("code")) or _text(field.get("name"))
            display_name = _text(field.get("name"))
            if name:
                result[code][name] = {
                    name.lower(),
                    normalize_identifier(name),
                    display_name.lower() if display_name else "",
                    normalize_identifier(display_name) if display_name else "",
                    *(str(value).lower() for value in field.get("aliases", [])),
                } - {""}
    return result


def load_inventory_summary(path: str | Path) -> dict[str, Any]:
    """Keep the first workbook's data-list evidence alongside contracts."""
    source = Path(path).expanduser().resolve()
    rows = _workbook_rows(source, "客户提供数据清单梳理")
    header_at, columns = _header_row(rows, {"数据名称", "数据大类", "数据小类"})
    items = []
    for row in rows[header_at + 1 :]:
        name = _text(row[columns["数据名称"]])
        if not name:
            continue
        items.append(
            {
                "category": _text(row[columns["数据大类"]]),
                "subcategory": _text(row[columns["数据小类"]]),
                "name": name,
                "use_case": _text(row[columns["城市体检应用场景数据作用"]])
                if "城市体检应用场景数据作用" in columns
                else "",
                "format": _text(row[columns["数据格式"]]) if "数据格式" in columns else "",
                "note": _text(row[columns["说明"]]) if "说明" in columns else "",
                "source": "customer data inventory workbook",
            }
        )
    return {"source_workbook": source.name, "item_count": len(items), "items": items}


def build_catalog(
    shp_workbook: str | Path,
    inventory_workbook: str | Path | None = None,
) -> dict[str, Any]:
    catalog = load_shp_contract_catalog(shp_workbook)
    if inventory_workbook:
        catalog["data_inventory"] = load_inventory_summary(inventory_workbook)
    return catalog


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _load_csv_rows(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    with Path(path).expanduser().resolve().open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _infer_field_type(field: str, rule: dict[str, Any]) -> tuple[str | None, str]:
    """Infer only a machine-useful candidate type; never call it authoritative."""
    explicit = _text(rule.get("type")).lower()
    if explicit:
        return explicit, "rule_candidate"
    pattern = _text(rule.get("pattern"))
    if pattern == "^[0-9]{4}$":
        return "string", "pattern_candidate"
    if pattern == "^[0-9]{8}$":
        return "string", "pattern_candidate"
    return None, "missing_authoritative_definition"


def compile_standard_contract_catalog(
    *,
    role_contracts_path: str | Path,
    field_aliases_path: str | Path | None = None,
    value_domains_path: str | Path | None = None,
    field_catalog_path: str | Path | None = None,
    ea_table_comparison_path: str | Path | None = None,
    ea_logical_comparison_path: str | Path | None = None,
    shp_workbook: str | Path | None = None,
    inventory_workbook: str | Path | None = None,
    standard_version: str | None = None,
) -> dict[str, Any]:
    """Compile a reviewable production-contract *candidate*.

    The source workbooks and comparison CSVs are evidence.  They do not
    contain enough EA attribute metadata to authorize production publication,
    so the result is deliberately fail-closed until a reviewer supplies the
    missing type/length/constraint and signs the contract.
    """
    role_payload = _load_json(role_contracts_path)
    aliases_payload = _load_json(field_aliases_path) if field_aliases_path else {}
    domain_payload = _load_json(value_domains_path) if value_domains_path else {}
    field_rows = {
        _text(row.get("field_name")): row
        for row in _load_csv_rows(field_catalog_path)
        if _text(row.get("field_name"))
    }
    ea_rows = _load_csv_rows(ea_table_comparison_path)
    logical_rows = _load_csv_rows(ea_logical_comparison_path)
    aliases = aliases_payload.get("field_aliases") or {}
    domains = domain_payload.get("domains") or {}
    contracts: dict[str, dict[str, Any]] = {}
    source_paths = [
        role_contracts_path,
        field_aliases_path,
        value_domains_path,
        field_catalog_path,
        ea_table_comparison_path,
        ea_logical_comparison_path,
        shp_workbook,
        inventory_workbook,
    ]
    source_artifacts = [
        {
            "name": Path(path).name,
            "sha256": _sha256_file(path),
            "portable_locator": "deployment_config_source",
        }
        for path in source_paths
        if path and Path(path).expanduser().exists()
    ]
    for role_id, role in (role_payload.get("roles") or {}).items():
        required = list(dict.fromkeys(role.get("required_fields") or []))
        recommended = [
            field
            for field in dict.fromkeys(role.get("recommended_fields") or [])
            if field not in required
        ]
        rules = role.get("field_rules") or {}
        ordered_fields = (
            required
            + recommended
            + [field for field in rules if field not in required + recommended]
        )
        table_specs = role.get("standard_tables") or []
        for table_spec in table_specs:
            code = _text(table_spec.get("table_code"))
            if not code:
                continue
            fields = []
            missing_type = 0
            for ordinal, field in enumerate(ordered_fields, 1):
                rule = rules.get(field) or {}
                data_type, type_source = _infer_field_type(field, rule)
                registry = field_rows.get(field) or {}
                if not data_type:
                    missing_type += 1
                alias = _text(aliases.get(field)) or _text(registry.get("field_alias_zh"))
                domain_name = _text(rule.get("domain"))
                fields.append(
                    {
                        "ordinal": ordinal,
                        "code": field,
                        "name": alias,
                        "aliases": [value for value in [field, alias] if value],
                        "data_type": data_type,
                        "type_source": type_source,
                        "length": rule.get("length"),
                        "precision": rule.get("precision"),
                        "required": field in required,
                        "nullable": field not in required,
                        "primary_key": field == (role.get("twm_binding") or {}).get("object_id"),
                        "unique": field == (role.get("twm_binding") or {}).get("object_id"),
                        "unit": rule.get("unit"),
                        "value_domain": {
                            "name": domain_name,
                            "values": domains.get(domain_name, []),
                        }
                        if domain_name
                        else None,
                        "quality_rules": rule,
                        "source_registry": registry or None,
                        "authority": "candidate",
                    }
                )
            ea_evidence = [
                {
                    key: row.get(key, "")
                    for key in (
                        "match_mode",
                        "ea_object_id",
                        "ea_name",
                        "ea_alias",
                        "ea_path",
                        "ea_fields",
                        "matched_fields",
                        "field_coverage_pct",
                        "missing_fields",
                        "type_mismatches",
                        "length_mismatches",
                    )
                }
                for row in ea_rows + logical_rows
                if _text(row.get("standard_table")).lower() == code.lower()
            ]
            contracts[code] = {
                "code": code,
                "name": _text(table_spec.get("table_alias_zh")),
                "role_id": role_id,
                "module": _text(table_spec.get("module")),
                "geometry_type": role.get("geometry_type"),
                "spatial_reference": {
                    "required": "CGCS2000",
                    "srid": None,
                    "status": "pending_authoritative_confirmation",
                },
                "time_model": {
                    "status": "candidate",
                    "keys": [
                        key for key in ((role.get("twm_binding") or {}).get("temporal_key"),) if key
                    ],
                },
                "primary_key": (role.get("twm_binding") or {}).get("object_id"),
                "required_fields": required,
                "recommended_fields": recommended,
                "fields": fields,
                "quality_rules": {"role_field_rules": rules},
                "ea_evidence": ea_evidence,
                "sources": {
                    "standard_documents": role_payload.get("source_documents") or [],
                    "standard_package": (
                        Path(_text(role_payload.get("source_package"))).name
                        if _text(role_payload.get("source_package"))
                        else None
                    ),
                    "ea_comparison_is_summary_only": True,
                },
                "authority": "ea_analysis_candidate" if ea_evidence else "standard_candidate",
                "review_status": "pending",
                "publication_gate": "manual_review",
                "auto_publish": False,
                "field_completeness": {
                    "field_count": len(fields),
                    "required_count": len(required),
                    "recommended_count": len(recommended),
                    "missing_type_count": missing_type,
                    "missing_length_count": sum(item["length"] is None for item in fields),
                    "missing_precision_count": sum(item["precision"] is None for item in fields),
                    "missing_domain_count": sum(item["value_domain"] is None for item in fields),
                },
            }
    inventory = load_inventory_summary(inventory_workbook) if inventory_workbook else None
    inventory_resolution = []
    for item in (inventory or {}).get("items", []):
        item_name = _text(item.get("name"))
        tokens = {token.upper() for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}", item_name)}
        evidence = [
            row
            for row in ea_rows + logical_rows
            if _text(row.get("standard_table")).upper() in tokens
            or (
                len(_text(row.get("standard_title"))) >= 4
                and normalize_identifier(row.get("standard_title"))
                in normalize_identifier(item_name)
            )
        ]
        has_exact_evidence = bool(evidence)
        prefix_evidence = [
            row
            for row in ea_rows + logical_rows
            if any(
                len(token) >= 3
                and _text(row.get("standard_table"))
                and (
                    _text(row.get("standard_table")).upper().startswith(token)
                    or token.startswith(_text(row.get("standard_table")).upper())
                )
                for token in tokens
            )
        ]
        if not evidence and prefix_evidence:
            evidence = prefix_evidence
        codes = list(
            dict.fromkeys(
                _text(row.get("standard_table"))
                for row in evidence
                if _text(row.get("standard_table"))
            )
        )
        contract_codes = [code for code in codes if code in contracts]
        if contract_codes:
            status = "contract_candidate"
            action = "核对真实源字段后补齐合同并审批"
        elif prefix_evidence and not has_exact_evidence:
            status = "ambiguous_candidate"
            action = "确认代码前缀对应的唯一标准对象后编译合同"
        elif evidence:
            status = "ea_standard_candidate"
            action = "从 EA 原始属性导出和标准正文编译独立合同"
        else:
            status = "unresolved"
            action = "根据真实文件画像和标准正文人工确认标准对象"
        inventory_resolution.append(
            {
                **item,
                "status": status,
                "candidate_codes": codes,
                "contract_codes": contract_codes,
                "ea_evidence": [
                    {
                        key: row.get(key, "")
                        for key in (
                            "standard_table",
                            "standard_title",
                            "match_mode",
                            "ea_object_id",
                            "ea_name",
                            "ea_path",
                            "ea_fields",
                            "field_coverage_pct",
                        )
                    }
                    for row in evidence[:20]
                ],
                "required_action": action,
            }
        )
    inventory_coverage = {
        "items": inventory_resolution,
        "counts": {
            status: sum(item["status"] == status for item in inventory_resolution)
            for status in (
                "contract_candidate",
                "ea_standard_candidate",
                "ambiguous_candidate",
                "unresolved",
            )
        },
    }
    catalog = {
        "schema_version": "gda.standard-contract-catalog.v2",
        "contract_id": "nx-natural-resource-standard-candidate",
        "generated_at": _now(),
        "standard_version": standard_version
        or role_payload.get("version")
        or "pending-confirmation",
        "authority": "ea_analysis_candidate",
        "review_status": "pending",
        "publication_gate": "manual_review",
        "production_ready": False,
        "provenance": {
            "source_artifacts": source_artifacts,
            "ea_comparison_warning": (
                "EA comparison CSVs are aggregate evidence, not attribute exports."
            ),
            "synthetic_field_catalog_warning": (
                "standard_field_catalog marks fields as synthetic/not_for_production."
            ),
        },
        "contracts": contracts,
        "field_registry": sorted(field_rows.values(), key=lambda row: row.get("field_name", "")),
        "value_domains": domains,
        "data_inventory": inventory,
        "inventory_resolution": inventory_coverage,
        "coverage": {
            "inventory_items": (inventory or {}).get("item_count", 0),
            "contract_dataset_count": len(contracts),
            "unmapped_inventory": [
                item for item in inventory_resolution if item["status"] == "unresolved"
            ],
        },
    }
    catalog["coverage"]["unmapped_inventory_count"] = len(catalog["coverage"]["unmapped_inventory"])
    return catalog


def validate_contract_catalog(
    catalog: dict[str, Any], *, require_authoritative: bool = True
) -> list[str]:
    """Return deterministic blockers suitable for preflight and CI."""
    blockers: list[str] = []
    if catalog.get("schema_version") != "gda.standard-contract-catalog.v2":
        blockers.append("contract schema version is not v2")
    if require_authoritative and catalog.get("authority") != "ea_standard":
        blockers.append(
            f"catalog authority is {catalog.get('authority')!r}, expected 'ea_standard'"
        )
    for code, contract in (catalog.get("contracts") or {}).items():
        if require_authoritative and contract.get("authority") != "ea_standard":
            blockers.append(f"{code}: contract authority is not ea_standard")
        if not contract.get("fields"):
            blockers.append(f"{code}: no fields")
        for field in contract.get("fields") or []:
            if require_authoritative and not field.get("data_type"):
                blockers.append(f"{code}.{field.get('code')}: data_type missing")
    return blockers
