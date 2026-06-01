"""DataModelStrategy — derive a std_document_version into a CDM/LDM/PDM
data model snapshot + PostgreSQL DDL.

Pattern follows QcRuleStrategy / DefectTaxonomyStrategy: read the version's
bound std_data_element rows, build the IR, render layers, write a snapshot
row, write a std_derived_link row, mark prior active stale.

Granularity differs from element-level strategies: one version produces
exactly one snapshot + one std_derived_link. The link uses
source_kind='document_version' and source_id=version_id (admitted by
migration 085's CHECK widening). target_kind='data_model'.

re-derive semantics:
  Each call inserts a fresh snapshot row (immutable history) and creates a
  new link. The previous active link is mark_stale()'d and the previous
  snapshot's derived_status flips to 'stale'. Caller can list history via
  /api/std/data-model/{vid}/snapshots.

Manual rows (derived_status='manual') are NEVER touched.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from ....db_engine import get_engine
from ..data_model_renderer import (
    build_model,
    render_cdm,
    render_ddl,
    render_ldm,
    render_pdm,
)
from ..strategy_base import (
    DerivationLink,
    DerivationResult,
    DerivationStrategy,
)
from .. import link_repo


class DataModelStrategy(DerivationStrategy):
    name = "to_data_model"
    description = (
        "派生标准 data_element 到 CDM/LDM/PDM 三层模型 + PostgreSQL DDL"
    )

    def run(self, *, version_id: str,
            by_user: str = "system") -> DerivationResult:
        result = DerivationResult(strategy=self.name)
        owner = by_user or "system"
        source_tag = f"std:v{version_id}"

        eng = get_engine()
        with eng.connect() as conn:
            # 1. Verify version + grab document_id (used for stale-detection).
            v_row = conn.execute(text(
                "SELECT v.document_id "
                "FROM std_document_version v WHERE v.id=:v"
            ), {"v": version_id}).first()
            if v_row is None:
                raise LookupError(f"version {version_id} not found")
            doc_id = str(v_row[0])

            # 2. Read all bound elements (left-joined with value_domain).
            elements = [dict(r) for r in conn.execute(text(
                "SELECT e.id, e.code, e.name_zh, e.name_en, e.definition, "
                "       e.representation_class, e.datatype, e.unit, "
                "       e.value_domain_id, e.obligation, "
                "       e.bound_table, e.bound_column, e.term_id "
                "FROM std_data_element e "
                "WHERE e.document_version_id=:v "
                "  AND e.bound_table IS NOT NULL "
                "  AND e.bound_column IS NOT NULL "
                "ORDER BY e.bound_table, e.bound_column"
            ), {"v": version_id}).mappings().all()]

            # 3. Read referenced value_domains + items.
            domain_ids = {str(e["value_domain_id"])
                          for e in elements if e["value_domain_id"]}
            value_domains: dict[str, dict] = {}
            if domain_ids:
                d_rows = conn.execute(text(
                    "SELECT id, code, name, kind FROM std_value_domain "
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ), {"ids": list(domain_ids)}).mappings().all()
                for d in d_rows:
                    value_domains[str(d["id"])] = {
                        "code": d["code"], "name": d["name"],
                        "kind": d["kind"], "items": [],
                    }
                i_rows = conn.execute(text(
                    "SELECT value_domain_id, value, label_zh, label_en, "
                    "       ordinal "
                    "FROM std_value_domain_item "
                    "WHERE value_domain_id = ANY(CAST(:ids AS uuid[])) "
                    "ORDER BY value_domain_id, ordinal, value"
                ), {"ids": list(domain_ids)}).mappings().all()
                for i in i_rows:
                    value_domains[str(i["value_domain_id"])]["items"].append({
                        "value": i["value"],
                        "label_zh": i["label_zh"],
                        "label_en": i["label_en"],
                        "ordinal": i["ordinal"],
                    })

            # 4. Read terms referenced by elements (for entity name_zh).
            term_ids = {str(e["term_id"])
                        for e in elements if e["term_id"]}
            terms: dict[str, dict] = {}
            if term_ids:
                t_rows = conn.execute(text(
                    "SELECT id, name_zh, name_en, definition "
                    "FROM std_term WHERE id = ANY(CAST(:ids AS uuid[]))"
                ), {"ids": list(term_ids)}).mappings().all()
                for t in t_rows:
                    terms[str(t["id"])] = {
                        "name_zh": t["name_zh"],
                        "name_en": t["name_en"],
                        "definition": t["definition"],
                    }

            # 5. Find prior active link for this document so we can stale it.
            prev_active = conn.execute(text(
                "SELECT l.id, l.target_id "
                "FROM std_derived_link l "
                "JOIN std_document_version v ON v.id = l.source_version_id "
                "WHERE v.document_id=:d "
                "  AND l.derivation_strategy=:s "
                "  AND l.status='active'"
            ), {"d": doc_id, "s": self.name}).mappings().all()

        # 6. Build IR + render layers + DDL.
        try:
            model = build_model(elements=elements,
                                 value_domains=value_domains,
                                 terms=terms)
            cdm = render_cdm(model)
            ldm = render_ldm(model)
            pdm = render_pdm(model)
            ddl = render_ddl(model)
        except Exception as e:
            result.failed.append((version_id, f"render: {e}"))
            return result

        stats = model.get("stats", {})

        # 7. Write snapshot + link in a single transaction.
        snapshot_id = str(uuid.uuid4())
        link_id = str(uuid.uuid4())
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_data_model_snapshot "
                "(id, document_version_id, generated_by, "
                " cdm_json, ldm_json, pdm_json, ddl_postgresql, "
                " entity_count, attribute_count, constraint_count, "
                " derived_status, source_tag) "
                "VALUES (:i, :v, :u, "
                "        CAST(:c AS jsonb), CAST(:l AS jsonb), "
                "        CAST(:p AS jsonb), :d, "
                "        :ec, :ac, :cc, 'active', :st)"
            ), {
                "i": snapshot_id, "v": version_id, "u": owner,
                "c": json.dumps(cdm, ensure_ascii=False),
                "l": json.dumps(ldm, ensure_ascii=False),
                "p": json.dumps(pdm, ensure_ascii=False),
                "d": ddl,
                "ec": stats.get("entity_count", 0),
                "ac": stats.get("attribute_count", 0),
                "cc": stats.get("constraint_count", 0),
                "st": source_tag,
            })

            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(id, source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy, status) "
                "VALUES (:i, 'document_version', :s, :v, "
                "        'data_model', 'std_data_model_snapshot', :t, "
                "        :ds, 'active')"
            ), {"i": link_id, "s": version_id, "v": version_id,
                 "t": snapshot_id, "ds": self.name})

            conn.execute(text(
                "UPDATE std_data_model_snapshot SET std_derived_link_id=:l "
                "WHERE id=:i"
            ), {"l": link_id, "i": snapshot_id})

        result.new_links.append(DerivationLink(
            source_kind="document_version", source_id=version_id,
            target_kind="data_model",
            target_table="std_data_model_snapshot",
            target_id=snapshot_id,
            notes={
                "entity_count": stats.get("entity_count", 0),
                "attribute_count": stats.get("attribute_count", 0),
                "warnings": model.get("warnings", []),
            },
        ))

        # 8. Mark prior active links + snapshots stale.
        stale_link_ids = [str(r["id"]) for r in prev_active]
        if stale_link_ids:
            link_repo.mark_stale(
                link_ids=stale_link_ids,
                reason=f"superseded by version {version_id}",
            )
            stale_target_ids = [str(r["target_id"]) for r in prev_active]
            with eng.begin() as conn:
                conn.execute(text(
                    "UPDATE std_data_model_snapshot "
                    "SET derived_status='stale' "
                    "WHERE id = ANY(CAST(:ids AS uuid[])) "
                    "  AND derived_status='active'"
                ), {"ids": stale_target_ids})
            result.staled_links = stale_link_ids

        return result
