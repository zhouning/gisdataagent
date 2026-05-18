"""SemanticHintStrategy — derive bound std_data_element rows to
agent_semantic_hints (column-scope hints).

Field mapping (see plan top "Spec → Actual DB Reality" table):
  scope_type     = 'column'
  scope_ref      = '<bound_table>.<bound_column>'
  hint_kind      = 'other'
  hint_text_zh   = '标准定义：<name_zh>（类型 <datatype>，<obligation>）'
  severity       = 'info'
  trigger_keywords = json.dumps([<bound_column>, <name_zh>])
  source_tag     = 'std:v<version_id>'
  std_derived_link_id = <link.id>
  std_version_id = <version_id>
  derived_status = 'active'

UNIQUE constraint on agent_semantic_hints is (scope_ref, hint_kind, hint_text_zh).
Manual rows (std_derived_link_id IS NULL) are NEVER touched.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from ....db_engine import get_engine
from ..strategy_base import (
    DerivationLink,
    DerivationResult,
    DerivationStrategy,
)
from .. import link_repo


class SemanticHintStrategy(DerivationStrategy):
    name = "to_semantic_hint"
    description = "派生标准 data_element 到 agent_semantic_hints 表 (column-scope hint)"

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

            elements = conn.execute(text(
                "SELECT id, name_zh, datatype, obligation, "
                "       bound_table, bound_column "
                "FROM std_data_element "
                "WHERE document_version_id=:v "
                "  AND bound_table IS NOT NULL"
            ), {"v": version_id}).mappings().all()

            prev_active = conn.execute(text(
                "SELECT l.id, l.target_id "
                "FROM std_derived_link l "
                "JOIN std_document_version v ON v.id = l.source_version_id "
                "WHERE v.document_id=:d "
                "  AND l.derivation_strategy=:s "
                "  AND l.status='active'"
            ), {"d": doc_id, "s": self.name}).mappings().all()
            prev_target_to_link = {
                str(r["target_id"]): str(r["id"]) for r in prev_active
            }

        new_target_ids: set[str] = set()

        # Build hints + links transactionally per data_element to keep error
        # isolation possible (one bad element shouldn't fail the rest).
        for el in elements:
            try:
                hint_id = self._upsert_hint_and_link(
                    el=el, version_id=version_id,
                    by_user=by_user, result=result,
                )
                if hint_id is not None:
                    new_target_ids.add(hint_id)
            except Exception as e:
                result.failed.append((str(el["id"]), str(e)))

        # Mark prev active links not present in new_target_ids as stale.
        stale_link_ids: list[str] = [
            link_id for tgt, link_id in prev_target_to_link.items()
            if tgt not in new_target_ids
        ]
        if stale_link_ids:
            link_repo.mark_stale(
                link_ids=stale_link_ids,
                reason=f"superseded by version {version_id}",
            )
            with eng.begin() as conn:
                conn.execute(text(
                    "UPDATE agent_semantic_hints SET derived_status='stale' "
                    "WHERE std_derived_link_id = ANY(CAST(:ids AS uuid[]))"
                ), {"ids": stale_link_ids})
            result.staled_links = stale_link_ids

        return result

    def _upsert_hint_and_link(self, *, el, version_id: str, by_user: str,
                              result: DerivationResult) -> str | None:
        """Upsert one hint row and create active link. Returns hint id (text)
        or None when manual row was found and skipped.
        """
        scope_ref = f"{el['bound_table']}.{el['bound_column']}"
        hint_kind = "other"
        hint_text_zh = (
            f"标准定义：{el['name_zh']}"
            f"（类型 {el['datatype'] or 'unspecified'}，"
            f"{el['obligation']}）"
        )
        trigger_keywords = json.dumps(
            [el["bound_column"], el["name_zh"]], ensure_ascii=False
        )
        source_tag = f"std:v{version_id}"

        eng = get_engine()
        with eng.begin() as conn:
            # Detect existing row keyed by UNIQUE (scope_ref, hint_kind, hint_text_zh).
            existing = conn.execute(text(
                "SELECT id, std_derived_link_id FROM agent_semantic_hints "
                "WHERE scope_ref=:sr AND hint_kind=:hk AND hint_text_zh=:ht"
            ), {"sr": scope_ref, "hk": hint_kind, "ht": hint_text_zh}).first()

            if existing is not None and existing[1] is None:
                # Manual row — leave alone, do not derive.
                return None

            if existing is not None:
                # Existing derived row → update metadata, reuse hint id.
                hint_id = str(existing[0])
                conn.execute(text(
                    "UPDATE agent_semantic_hints SET "
                    "  trigger_keywords=CAST(:tk AS jsonb), "
                    "  source_tag=:st, "
                    "  std_version_id=:vid, "
                    "  derived_status='active', "
                    "  updated_at=now() "
                    "WHERE id=:i"
                ), {"tk": trigger_keywords, "st": source_tag,
                     "vid": version_id, "i": int(hint_id)})
                # The std_derived_link_id of this hint may be from a previous
                # version; we need to retire it and link to a new active one.
                # Simplest: mark old link stale, link this hint to a new one.
                old_link_id = str(existing[1])
                conn.execute(text(
                    "UPDATE std_derived_link SET status='stale', "
                    "stale_reason='superseded by re-derive' WHERE id=:i"
                ), {"i": old_link_id})
            else:
                # Brand-new derived row.
                row = conn.execute(text(
                    "INSERT INTO agent_semantic_hints "
                    "(scope_type, scope_ref, hint_kind, hint_text_zh, "
                    " severity, trigger_keywords, source_tag, "
                    " std_version_id, derived_status, owner_username) "
                    "VALUES ('column', :sr, :hk, :ht, 'info', "
                    "        CAST(:tk AS jsonb), :st, :vid, 'active', :u) "
                    "RETURNING id"
                ), {"sr": scope_ref, "hk": hint_kind, "ht": hint_text_zh,
                     "tk": trigger_keywords, "st": source_tag,
                     "vid": version_id, "u": by_user}).first()
                hint_id = str(row[0])

            # Create new active link
            link_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(id, source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy, status) "
                "VALUES (:i, 'data_element', :s, :v, 'semantic_hint', "
                "        'agent_semantic_hints', :t, :ds, 'active')"
            ), {"i": link_id, "s": str(el["id"]), "v": version_id,
                 "t": hint_id, "ds": self.name})
            # Wire hint.std_derived_link_id to point at the new active link.
            conn.execute(text(
                "UPDATE agent_semantic_hints SET std_derived_link_id=:l "
                "WHERE id=:i"
            ), {"l": link_id, "i": int(hint_id)})

        result.new_links.append(DerivationLink(
            source_kind="data_element", source_id=str(el["id"]),
            target_kind="semantic_hint",
            target_table="agent_semantic_hints", target_id=hint_id,
        ))
        return hint_id
