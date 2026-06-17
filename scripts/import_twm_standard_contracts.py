#!/usr/bin/env python3
"""Import TWM One Map role contracts into the Standards Platform.

Default mode is dry-run and writes an import plan. Use --apply to insert or
replace the draft/released version in std_* tables, then optionally --derive to
run downstream derivation strategies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.db_engine import get_engine
from data_agent.standards_platform.derivation import runner as derive_runner


DEFAULT_CONTRACT = Path("data_agent/test_data/twm_standards/one_map_role_contracts.zh.json")
DEFAULT_ALIASES = Path("data_agent/test_data/twm_standards/one_map_field_aliases.zh.json")
DEFAULT_DOMAINS = Path("data_agent/test_data/twm_standards/one_map_value_domains.zh.json")
DEFAULT_PLAN_OUT = Path("data_agent/test_data/twm_standards/import_plan.json")
DEFAULT_DOC_CODE = "NR_ONE_MAP_TWM_CORE_2026"
DEFAULT_VERSION = "2026-06-16-draft"
ROLE_TO_LAYER = {
    "parcel_current": "parcel_current",
    "pbf": "synthetic_pbf",
    "eco_redline": "synthetic_eco_redline",
    "urban_boundary": "synthetic_urban_boundary",
    "planning_zone": "synthetic_planning_zones",
    "project": "synthetic_projects",
    "approval": "approval_records",
    "enforcement": "enforcement_events",
    "metadata_vector": "metadata_vector",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "role"


def _field_type(rule: dict[str, Any], field_name: str) -> tuple[str, str]:
    if rule.get("type") == "number":
        return "decimal", "numeric"
    if "pattern" in rule and field_name.upper().endswith(("SJ", "RQ")):
        return "datetime", "string"
    return "text", "string"


def _domain_kind(rule: dict[str, Any]) -> str | None:
    if "domain" in rule:
        return "enumeration"
    if "pattern" in rule:
        return "pattern"
    if any(k in rule for k in ("min", "max", "min_exclusive")):
        return "range"
    return None


def build_import_plan(
    *,
    contract_path: Path,
    aliases_path: Path,
    domains_path: Path,
    doc_code: str,
    version_label: str,
) -> dict[str, Any]:
    contract = _load_json(contract_path)
    aliases = _load_json(aliases_path).get("field_aliases", {})
    domains = _load_json(domains_path).get("domains", {})
    roles = contract.get("roles", {})

    clauses = []
    data_elements = []
    value_domains: dict[str, dict[str, Any]] = {}

    for role_index, (role, role_contract) in enumerate(roles.items(), start=1):
        bound_table = ROLE_TO_LAYER.get(role, role)
        table_codes = [
            t.get("table_code", "")
            for t in role_contract.get("standard_tables", [])
            if t.get("table_code")
        ]
        clause_code = f"ROLE.{_slug(role)}"
        required = set(role_contract.get("required_fields", []))
        recommended = set(role_contract.get("recommended_fields", []))
        field_rules = role_contract.get("field_rules", {})
        clauses.append(
            {
                "code": clause_code,
                "ordinal_path": f"{role_index}",
                "heading": f"{role} / {role_contract.get('role_alias_zh', role)}",
                "body_md": (
                    f"TWM role `{role}` maps to One Map tables "
                    f"{', '.join(table_codes) or 'N/A'} and runtime target `{bound_table}`."
                ),
                "source_origin": {
                    "role": role,
                    "standard_tables": role_contract.get("standard_tables", []),
                    "layer_candidates": role_contract.get("layer_candidates", []),
                    "twm_binding": role_contract.get("twm_binding", {}),
                },
            }
        )
        ordered_fields = [
            *role_contract.get("required_fields", []),
            *[
                f
                for f in role_contract.get("recommended_fields", [])
                if f not in required
            ],
        ]
        for field in ordered_fields:
            rule = field_rules.get(field, {})
            representation_class, datatype = _field_type(rule, field)
            domain_code = rule.get("domain")
            pattern = rule.get("pattern")
            if domain_code and domain_code in domains:
                value_domains.setdefault(
                    domain_code,
                    {
                        "code": domain_code,
                        "name": domain_code,
                        "kind": "enumeration",
                        "items": domains[domain_code],
                    },
                )
            elif pattern:
                domain_code = f"{role}.{field}.pattern"
                value_domains.setdefault(
                    domain_code,
                    {
                        "code": domain_code,
                        "name": f"{aliases.get(field, field)}格式",
                        "kind": "pattern",
                        "items": [{"code": pattern, "name_zh": pattern}],
                    },
                )
            elif _domain_kind(rule) == "range":
                domain_code = f"{role}.{field}.range"
                items = []
                for key in ("min", "min_exclusive", "max"):
                    if key in rule:
                        items.append({"code": f"{key}:{rule[key]}", "name_zh": f"{key}={rule[key]}"})
                value_domains.setdefault(
                    domain_code,
                    {
                        "code": domain_code,
                        "name": f"{aliases.get(field, field)}数值范围",
                        "kind": "range",
                        "items": items,
                    },
                )
            data_elements.append(
                {
                    "code": f"{role}.{field}",
                    "role": role,
                    "field": field,
                    "name_zh": aliases.get(field, field),
                    "definition": f"{role_contract.get('role_alias_zh', role)}.{aliases.get(field, field)}",
                    "representation_class": representation_class,
                    "datatype": datatype,
                    "unit": rule.get("unit", ""),
                    "value_domain_code": domain_code or "",
                    "obligation": "mandatory" if field in required else "optional",
                    "bound_table": bound_table,
                    "bound_column": field,
                    "defined_by_clause_code": clause_code,
                }
            )

    return {
        "doc_code": doc_code,
        "title": contract.get("standard_name_zh", "自然资源一张图 TWM 核心角色标准契约"),
        "version_label": version_label,
        "standard_id": contract.get("standard_id", doc_code),
        "source_contract": str(contract_path),
        "source_aliases": str(aliases_path),
        "source_domains": str(domains_path),
        "counts": {
            "roles": len(roles),
            "clauses": len(clauses),
            "data_elements": len(data_elements),
            "value_domains": len(value_domains),
            "value_domain_items": sum(len(v.get("items", [])) for v in value_domains.values()),
        },
        "clauses": clauses,
        "value_domains": list(value_domains.values()),
        "data_elements": data_elements,
    }


def _delete_existing_version(conn, doc_code: str, version_label: str) -> None:
    row = conn.execute(
        text(
            "SELECT v.id FROM std_document_version v "
            "JOIN std_document d ON d.id = v.document_id "
            "WHERE d.doc_code=:code AND d.source_type='enterprise' "
            "  AND v.version_label=:label"
        ),
        {"code": doc_code, "label": version_label},
    ).first()
    if row:
        conn.execute(text("DELETE FROM std_document_version WHERE id=:v"), {"v": str(row[0])})


def apply_plan(plan: dict[str, Any], *, owner: str, status: str, derive: bool) -> dict[str, Any]:
    eng = get_engine()
    doc_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    clause_ids: dict[str, str] = {}
    domain_ids: dict[str, str] = {}

    with eng.begin() as conn:
        _delete_existing_version(conn, plan["doc_code"], plan["version_label"])
        doc_row = conn.execute(
            text(
                "SELECT id FROM std_document "
                "WHERE doc_code=:code AND source_type='enterprise'"
            ),
            {"code": plan["doc_code"]},
        ).first()
        if doc_row:
            doc_id = str(doc_row[0])
            conn.execute(
                text(
                    "UPDATE std_document SET title=:title, status='drafting', "
                    "raw_file_path=:path, tags=:tags, updated_by=:u, updated_at=now() "
                    "WHERE id=:id"
                ),
                {
                    "id": doc_id,
                    "title": plan["title"],
                    "path": plan.get("source_contract", ""),
                    "tags": ["twm", "one-map", "natural-resource"],
                    "u": owner,
                },
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO std_document "
                    "(id, doc_code, title, source_type, language, status, owner_user_id, "
                    " raw_file_path, tags, created_by, updated_by) "
                    "VALUES (:id, :code, :title, 'enterprise', 'zh-CN', 'drafting', :owner, "
                    "        :path, :tags, :owner, :owner)"
                ),
                {
                    "id": doc_id,
                    "code": plan["doc_code"],
                    "title": plan["title"],
                    "owner": owner,
                    "path": plan.get("source_contract", ""),
                    "tags": ["twm", "one-map", "natural-resource"],
                },
            )
        conn.execute(
            text(
                "INSERT INTO std_document_version "
                "(id, document_id, version_label, semver_major, semver_minor, semver_patch, "
                " status, snapshot_blob, created_by, updated_by, release_notes, released_at) "
                "VALUES (:id, :doc, :label, 2026, 6, 16, :status, CAST(:snapshot AS jsonb), "
                "        :owner, :owner, :notes, CASE WHEN :status='released' THEN now() ELSE NULL END)"
            ),
            {
                "id": version_id,
                "doc": doc_id,
                "label": plan["version_label"],
                "status": status,
                "snapshot": json.dumps(
                    {
                        "standard_id": plan.get("standard_id"),
                        "counts": plan.get("counts", {}),
                        "source_contract": plan.get("source_contract"),
                    },
                    ensure_ascii=False,
                ),
                "owner": owner,
                "notes": "Imported from TWM One Map role contract JSON.",
            },
        )
        conn.execute(
            text("UPDATE std_document SET current_version_id=:v WHERE id=:d"),
            {"v": version_id, "d": doc_id},
        )

        for clause in plan["clauses"]:
            clause_id = str(uuid.uuid4())
            clause_ids[clause["code"]] = clause_id
            conn.execute(
                text(
                    "INSERT INTO std_clause "
                    "(id, document_id, document_version_id, ordinal_path, heading, clause_no, "
                    " kind, body_md, source_origin, created_by, updated_by) "
                    "VALUES (:id, :doc, :ver, CAST(:path AS ltree), :heading, :code, "
                    "        'section', :body, CAST(:origin AS jsonb), :owner, :owner)"
                ),
                {
                    "id": clause_id,
                    "doc": doc_id,
                    "ver": version_id,
                    "path": clause["ordinal_path"],
                    "heading": clause["heading"],
                    "code": clause["code"],
                    "body": clause["body_md"],
                    "origin": json.dumps(clause.get("source_origin", {}), ensure_ascii=False),
                    "owner": owner,
                },
            )

        for domain in plan["value_domains"]:
            domain_id = str(uuid.uuid4())
            domain_ids[domain["code"]] = domain_id
            conn.execute(
                text(
                    "INSERT INTO std_value_domain "
                    "(id, document_version_id, code, name, kind) "
                    "VALUES (:id, :ver, :code, :name, :kind)"
                ),
                {
                    "id": domain_id,
                    "ver": version_id,
                    "code": domain["code"],
                    "name": domain["name"],
                    "kind": domain["kind"],
                },
            )
            for ordinal, item in enumerate(domain.get("items", []), start=1):
                value = str(item.get("code", item.get("value", "")))
                if not value:
                    continue
                conn.execute(
                    text(
                        "INSERT INTO std_value_domain_item "
                        "(id, value_domain_id, value, label_zh, ordinal) "
                        "VALUES (:id, :domain, :value, :label, :ordinal)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "domain": domain_id,
                        "value": value,
                        "label": item.get("name_zh", item.get("name", value)),
                        "ordinal": ordinal,
                    },
                )

        for element in plan["data_elements"]:
            conn.execute(
                text(
                    "INSERT INTO std_data_element "
                    "(id, document_version_id, code, name_zh, definition, representation_class, "
                    " datatype, unit, value_domain_id, obligation, cardinality, "
                    " defined_by_clause_id, data_classification, bound_table, bound_column) "
                    "VALUES (:id, :ver, :code, :name, :definition, :repr, :datatype, :unit, "
                    "        :domain, :obligation, '1', :clause, 'internal', :table, :column)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ver": version_id,
                    "code": element["code"],
                    "name": element["name_zh"],
                    "definition": element["definition"],
                    "repr": element["representation_class"],
                    "datatype": element["datatype"],
                    "unit": element.get("unit") or None,
                    "domain": domain_ids.get(element.get("value_domain_code", "")),
                    "obligation": element["obligation"],
                    "clause": clause_ids.get(element["defined_by_clause_code"]),
                    "table": element["bound_table"],
                    "column": element["bound_column"],
                },
            )

    derive_results = {}
    if derive:
        derive_results = derive_runner.dispatch(version_id=version_id, by_user=owner)
    return {
        "document_id": doc_id,
        "version_id": version_id,
        "status": status,
        "derive_results": derive_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    parser.add_argument("--domains", default=str(DEFAULT_DOMAINS))
    parser.add_argument("--plan-out", default=str(DEFAULT_PLAN_OUT))
    parser.add_argument("--doc-code", default=DEFAULT_DOC_CODE)
    parser.add_argument("--version-label", default=DEFAULT_VERSION)
    parser.add_argument("--owner", default="system")
    parser.add_argument("--status", choices=["draft", "released"], default="released")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--derive", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = build_import_plan(
        contract_path=Path(args.contract),
        aliases_path=Path(args.aliases),
        domains_path=Path(args.domains),
        doc_code=args.doc_code,
        version_label=args.version_label,
    )
    plan_out = Path(args.plan_out)
    plan_out.parent.mkdir(parents=True, exist_ok=True)
    plan_out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    result: dict[str, Any] = {
        "mode": "dry_run",
        "plan": str(plan_out),
        "counts": plan["counts"],
    }
    if args.apply:
        applied = apply_plan(plan, owner=args.owner, status=args.status, derive=args.derive)
        result.update({"mode": "applied", **applied})
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
