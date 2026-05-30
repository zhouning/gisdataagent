"""QcRuleStrategy — derive bound std_data_element rows into agent_quality_rules.

Mapping rules (one element can produce up to 2 rules in different rule_types):

  obligation=mandatory  →  rule_type='completeness'
                            config={'fields': [<bound_column>]}
                            severity = 'HIGH' if mandatory else 'MEDIUM'

  value_domain.kind=enumeration  →  rule_type='field_check'
                                     config={'standard_id': '<doc_code>',
                                             'field': <bound_column>,
                                             'allowed_values': [...]}

  value_domain.kind=range / pattern  →  rule_type='field_check'
                                         config carries 'range' or 'regex'

  geometry/topology hints                →  defer to Wave 7-eng-2 (needs
                                            domain semantics that std_*
                                            doesn't carry yet).

Field mapping:
  rule_name          = 'std:<bound_table>.<bound_column>:<rule_type>'
                       (deterministic key; 1:1 with link target)
  standard_id        = std_document.doc_code
  config             = JSONB body sketched above
  severity           = mandatory→HIGH, enum/range/pattern→MEDIUM
  owner_username     = by_user (defaults to 'system')
  is_shared          = TRUE (derived rules belong to the platform)
  std_derived_link_id, std_version_id, source_tag, derived_status — same
  scaffolding semantics as agent_semantic_hints (added by migration 083).

UNIQUE constraint on agent_quality_rules is (rule_name, owner_username), so
the rule_name above plus the system owner is our idempotency key. Manual
rows (std_derived_link_id IS NULL) keyed by the same (name, owner) — which
shouldn't happen if humans don't poach the 'std:' prefix — are NEVER
touched.

Stale model:
  Re-deriving a version produces a candidate set of (rule_name, target_id).
  Prior active links not in the candidate set are marked stale; their rule
  rows have derived_status='stale' set but the row itself is preserved so
  history queries / impact graphs still work.
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


_DOMAIN_KIND_TO_RULE = {
    "enumeration": "field_check",
    "range": "field_check",
    "pattern": "field_check",
    # external_codelist defers — needs reference-data plumbing to enumerate.
}


def _build_completeness_config(*, bound_column: str) -> dict:
    return {"fields": [bound_column], "check": "non_null"}


def _build_field_check_config(*, bound_column: str, doc_code: str | None,
                              kind: str, items: list[dict]) -> dict:
    cfg: dict = {"field": bound_column}
    if doc_code:
        cfg["standard_id"] = doc_code
    if kind == "enumeration":
        cfg["allowed_values"] = [it["value"] for it in items if it.get("value")]
    elif kind == "range":
        # Items convention: low/high carried as label_zh|value pairs. We
        # surface the raw items so downstream executors can interpret bounds
        # without us guessing the schema-light shape.
        cfg["range"] = [
            {"value": it.get("value"), "label": it.get("label_zh")}
            for it in items
        ]
    elif kind == "pattern":
        if items:
            cfg["regex"] = items[0].get("value", "")
    return cfg


class QcRuleStrategy(DerivationStrategy):
    name = "to_qc_rule"
    description = (
        "派生标准 data_element 到 agent_quality_rules "
        "(completeness for mandatory, field_check for value_domain)"
    )

    def run(self, *, version_id: str, by_user: str = "system") -> DerivationResult:
        result = DerivationResult(strategy=self.name)

        eng = get_engine()
        with eng.connect() as conn:
            doc_id_row = conn.execute(text(
                "SELECT v.document_id, d.doc_code "
                "FROM std_document_version v "
                "JOIN std_document d ON d.id = v.document_id "
                "WHERE v.id=:v"
            ), {"v": version_id}).first()
            if doc_id_row is None:
                raise LookupError(f"version {version_id} not found")
            doc_id = str(doc_id_row[0])
            doc_code = doc_id_row[1]

            elements = conn.execute(text(
                "SELECT e.id, e.name_zh, e.bound_table, e.bound_column, "
                "       e.obligation, e.value_domain_id, "
                "       d.code AS domain_code, d.name AS domain_name, "
                "       d.kind AS domain_kind "
                "FROM std_data_element e "
                "LEFT JOIN std_value_domain d ON d.id = e.value_domain_id "
                "WHERE e.document_version_id=:v "
                "  AND e.bound_table IS NOT NULL "
                "  AND e.bound_column IS NOT NULL"
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

        for el in elements:
            # Each element can fan out into multiple rule_types. We try each
            # in turn and isolate failures per (element, rule_type).
            try:
                if el["obligation"] == "mandatory":
                    rid = self._upsert_rule_and_link(
                        el=el, version_id=version_id,
                        doc_code=doc_code, by_user=by_user,
                        rule_type="completeness",
                        config=_build_completeness_config(
                            bound_column=el["bound_column"]),
                        severity="HIGH",
                        result=result,
                    )
                    if rid is not None:
                        new_target_ids.add(rid)
            except Exception as e:
                result.failed.append((str(el["id"]) + ":completeness", str(e)))

            kind = el.get("domain_kind")
            if kind in _DOMAIN_KIND_TO_RULE:
                try:
                    items = self._fetch_domain_items(
                        domain_id=str(el["value_domain_id"]))
                    rid = self._upsert_rule_and_link(
                        el=el, version_id=version_id,
                        doc_code=doc_code, by_user=by_user,
                        rule_type=_DOMAIN_KIND_TO_RULE[kind],
                        config=_build_field_check_config(
                            bound_column=el["bound_column"],
                            doc_code=doc_code,
                            kind=kind, items=items),
                        severity="MEDIUM",
                        result=result,
                    )
                    if rid is not None:
                        new_target_ids.add(rid)
                except Exception as e:
                    result.failed.append(
                        (str(el["id"]) + ":" + _DOMAIN_KIND_TO_RULE[kind],
                         str(e)))

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
                    "UPDATE agent_quality_rules SET derived_status='stale' "
                    "WHERE std_derived_link_id = ANY(CAST(:ids AS uuid[]))"
                ), {"ids": stale_link_ids})
            result.staled_links = stale_link_ids

        return result

    def _fetch_domain_items(self, *, domain_id: str) -> list[dict]:
        eng = get_engine()
        with eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT value, label_zh, label_en, ordinal "
                "FROM std_value_domain_item "
                "WHERE value_domain_id=:v "
                "ORDER BY ordinal, value"
            ), {"v": domain_id}).mappings().all()
        return [dict(r) for r in rows]

    def _upsert_rule_and_link(self, *, el, version_id: str,
                              doc_code: str | None, by_user: str,
                              rule_type: str, config: dict,
                              severity: str,
                              result: DerivationResult) -> str | None:
        rule_name = f"std:{el['bound_table']}.{el['bound_column']}:{rule_type}"
        owner = by_user or "system"
        source_tag = f"std:v{version_id}"

        eng = get_engine()
        with eng.begin() as conn:
            existing = conn.execute(text(
                "SELECT id, std_derived_link_id FROM agent_quality_rules "
                "WHERE rule_name=:n AND owner_username=:o"
            ), {"n": rule_name, "o": owner}).first()

            if existing is not None and existing[1] is None:
                # Manual row — leave alone.
                return None

            cfg_json = json.dumps(config, ensure_ascii=False)

            if existing is not None:
                rule_id = str(existing[0])
                # Update body but keep id; retire its old link.
                conn.execute(text(
                    "UPDATE agent_quality_rules SET "
                    "  rule_type=:rt, "
                    "  config=CAST(:c AS jsonb), "
                    "  standard_id=:sid, "
                    "  severity=:sv, "
                    "  source_tag=:st, "
                    "  std_version_id=:vid, "
                    "  derived_status='active', "
                    "  enabled=TRUE, "
                    "  is_shared=TRUE, "
                    "  updated_at=now() "
                    "WHERE id=:i"
                ), {"rt": rule_type, "c": cfg_json, "sid": doc_code,
                     "sv": severity, "st": source_tag, "vid": version_id,
                     "i": int(rule_id)})
                old_link_id = str(existing[1])
                conn.execute(text(
                    "UPDATE std_derived_link SET status='stale', "
                    "stale_reason='superseded by re-derive' WHERE id=:i"
                ), {"i": old_link_id})
            else:
                row = conn.execute(text(
                    "INSERT INTO agent_quality_rules "
                    "(rule_name, rule_type, config, owner_username, "
                    " standard_id, severity, is_shared, "
                    " source_tag, std_version_id, derived_status) "
                    "VALUES (:n, :rt, CAST(:c AS jsonb), :o, :sid, :sv, "
                    "        TRUE, :st, :vid, 'active') "
                    "RETURNING id"
                ), {"n": rule_name, "rt": rule_type, "c": cfg_json,
                     "o": owner, "sid": doc_code, "sv": severity,
                     "st": source_tag, "vid": version_id}).first()
                rule_id = str(row[0])

            link_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(id, source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy, status) "
                "VALUES (:i, 'data_element', :s, :v, 'qc_rule', "
                "        'agent_quality_rules', :t, :ds, 'active')"
            ), {"i": link_id, "s": str(el["id"]), "v": version_id,
                 "t": rule_id, "ds": self.name})
            conn.execute(text(
                "UPDATE agent_quality_rules SET std_derived_link_id=:l "
                "WHERE id=:i"
            ), {"l": link_id, "i": int(rule_id)})

        result.new_links.append(DerivationLink(
            source_kind="data_element", source_id=str(el["id"]),
            target_kind="qc_rule",
            target_table="agent_quality_rules", target_id=rule_id,
        ))
        return rule_id
