"""SynonymStrategy — derive std_data_element + std_term names/aliases into
agent_semantic_sources.derived_synonyms keyed by bound_table.

Field mapping:
  std_data_element with bound_table → contributes [name_zh, name_en] to
    agent_semantic_sources where table_name = bound_table
  std_term defined_by_clause_id → for each clause, find every data_element
    bound to (bound_table, *) under that clause, and contribute the term's
    [name_zh, name_en, *aliases] to those tables
  agent_semantic_sources.derived_synonyms = JSONB array of dedup'd strings
  std_derived_link.target_kind = 'synonym'
  std_derived_link.target_table = 'agent_semantic_sources'
  std_derived_link.target_id = str(agent_semantic_sources.id)

Link cardinality (A-plan, conforms to spec §7.2 #5 active uniqueness):
  Each target table has AT MOST ONE active std_derived_link row even when
  many data_elements/terms contribute to its derived_synonyms. The link's
  source_id points at the FIRST data_element bound to that table (by
  created_at) as a representative anchor; remaining contributors live
  exclusively in the derived_synonyms array. This is a fan-in shape that
  cannot be expressed in std_derived_link 1:1 without changing the active
  uniqueness constraint, so we accept the lossier source-tracing in
  exchange for spec compliance.

Stale model:
  Per (table_name) target the derived_synonyms list is overwritten in full
  each run. Tables touched by a prior version but not the new version get
  their derived_synonyms cleared and the link marked stale. Manual
  `synonyms` column is NEVER touched.

Wave 6+ to_synonym engineering surface. A/B evaluation against CQ-125 is
a separate eval task (Wave 6+ -eval).
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict

from sqlalchemy import text

from ....db_engine import get_engine
from ..strategy_base import (
    DerivationLink,
    DerivationResult,
    DerivationStrategy,
)
from .. import link_repo


class SynonymStrategy(DerivationStrategy):
    name = "to_synonym"
    description = (
        "派生标准 data_element + term 的名称别名到 "
        "agent_semantic_sources.derived_synonyms (按 bound_table 分组)"
    )

    def run(self, *, version_id: str, by_user: str = "system") -> DerivationResult:
        result = DerivationResult(strategy=self.name)

        eng = get_engine()
        with eng.connect() as conn:
            doc_id_row = conn.execute(text(
                "SELECT document_id FROM std_document_version WHERE id=:v"
            ), {"v": version_id}).first()
            if doc_id_row is None:
                raise LookupError(f"version {version_id} not found")
            doc_id = str(doc_id_row[0])

            # Order by created_at so anchor selection is deterministic.
            elements = conn.execute(text(
                "SELECT id, name_zh, name_en, bound_table, "
                "       defined_by_clause_id, created_at "
                "FROM std_data_element "
                "WHERE document_version_id=:v "
                "  AND bound_table IS NOT NULL "
                "ORDER BY created_at, id"
            ), {"v": version_id}).mappings().all()

            terms = conn.execute(text(
                "SELECT id, name_zh, name_en, aliases, defined_by_clause_id "
                "FROM std_term "
                "WHERE document_version_id=:v"
            ), {"v": version_id}).mappings().all()

            source_rows = conn.execute(text(
                "SELECT id, table_name FROM agent_semantic_sources"
            )).mappings().all()
            table_to_source_id: dict[str, int] = {
                r["table_name"]: r["id"] for r in source_rows
            }

            # Prior active links for this strategy across this document,
            # indexed by target table id (string of source.id).
            prev_active = conn.execute(text(
                "SELECT l.id, l.target_id "
                "FROM std_derived_link l "
                "JOIN std_document_version v ON v.id = l.source_version_id "
                "WHERE v.document_id=:d "
                "  AND l.derivation_strategy=:s "
                "  AND l.status='active'"
            ), {"d": doc_id, "s": self.name}).mappings().all()
            prev_link_by_target = {str(r["target_id"]): str(r["id"])
                                   for r in prev_active}

        # --- Build (table_name → set[synonyms]) and (table_name → anchor element)
        table_synonyms: dict[str, set[str]] = defaultdict(set)
        # First data_element bound to each table = anchor source for the link.
        # elements is already ordered by created_at.
        table_anchor: dict[str, dict] = {}
        for el in elements:
            tbl = el["bound_table"]
            if tbl not in table_to_source_id:
                continue
            for kw in (el.get("name_zh"), el.get("name_en")):
                if kw:
                    table_synonyms[tbl].add(kw)
            table_anchor.setdefault(tbl, el)

        # Term contributions follow clause anchoring.
        clause_to_tables: dict[str, set[str]] = defaultdict(set)
        for el in elements:
            cid = el.get("defined_by_clause_id")
            if cid and el.get("bound_table") in table_to_source_id:
                clause_to_tables[str(cid)].add(el["bound_table"])

        for term in terms:
            cid = term.get("defined_by_clause_id")
            if not cid:
                continue
            anchor_tables = clause_to_tables.get(str(cid), set())
            if not anchor_tables:
                continue
            term_kws: list[str] = []
            for kw in (term.get("name_zh"), term.get("name_en")):
                if kw:
                    term_kws.append(kw)
            aliases = term.get("aliases") or []
            if isinstance(aliases, list):
                term_kws.extend(a for a in aliases if a)
            for tbl in anchor_tables:
                table_synonyms[tbl].update(term_kws)

        # --- Persist: write derived_synonyms + 1 link per touched table ---
        new_target_ids: set[str] = set()
        with eng.begin() as conn:
            for tbl, kw_set in table_synonyms.items():
                source_id = table_to_source_id[tbl]
                target_id = str(source_id)
                kws_sorted = sorted(kw_set)
                conn.execute(text(
                    "UPDATE agent_semantic_sources "
                    "SET derived_synonyms = CAST(:ds AS jsonb), "
                    "    updated_at = now() "
                    "WHERE id = :i"
                ), {"ds": json.dumps(kws_sorted, ensure_ascii=False),
                     "i": source_id})
                new_target_ids.add(target_id)

                anchor = table_anchor[tbl]
                anchor_id = str(anchor["id"])

                existing_link_id = prev_link_by_target.pop(target_id, None)
                if existing_link_id:
                    # Refresh anchor + status; reuse link uuid.
                    conn.execute(text(
                        "UPDATE std_derived_link "
                        "SET source_id=:s, source_kind='data_element', "
                        "    source_version_id=:v, status='active', "
                        "    stale_reason=NULL, generated_at=now() "
                        "WHERE id=:i"
                    ), {"s": anchor_id, "v": version_id,
                         "i": existing_link_id})
                else:
                    new_link_id = str(uuid.uuid4())
                    conn.execute(text(
                        "INSERT INTO std_derived_link "
                        "(id, source_kind, source_id, source_version_id, "
                        " target_kind, target_table, target_id, "
                        " derivation_strategy, status) "
                        "VALUES (:i, 'data_element', :s, :v, 'synonym', "
                        "        'agent_semantic_sources', :t, :ds, "
                        "        'active')"
                    ), {"i": new_link_id, "s": anchor_id, "v": version_id,
                         "t": target_id, "ds": self.name})

                result.new_links.append(DerivationLink(
                    source_kind="data_element",
                    source_id=anchor_id,
                    target_kind="synonym",
                    target_table="agent_semantic_sources",
                    target_id=target_id,
                ))

            # Tables previously derived but no longer touched: clear synonyms,
            # mark link stale.
            for stale_target, stale_link_id in prev_link_by_target.items():
                conn.execute(text(
                    "UPDATE agent_semantic_sources "
                    "SET derived_synonyms = '[]'::jsonb, updated_at=now() "
                    "WHERE id=:i"
                ), {"i": int(stale_target)})

        stale_link_ids: list[str] = list(prev_link_by_target.values())
        if stale_link_ids:
            link_repo.mark_stale(
                link_ids=stale_link_ids,
                reason=f"superseded by version {version_id}",
            )
            result.staled_links = stale_link_ids

        return result

