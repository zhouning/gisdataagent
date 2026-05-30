"""DefectTaxonomyStrategy — derive bound std_data_element rows into
agent_defect_code_bindings, mapping element constraints to defect codes
defined in standards/defect_taxonomy.yaml.

Mapping rules (one element can fan out to multiple bindings):

  obligation=mandatory                       ->  MIS-001  (A, info_missing)
  value_domain.kind=enumeration              ->  NRM-003  (B, norm_violation)
  value_domain.kind=range                    ->  NRM-003  (B, norm_violation)
  value_domain.kind=pattern                  ->  NRM-002  (C, norm_violation)
  representation_class=geometry              ->  (defer; topology defects
                                                  in YAML are object-level
                                                  not field-level)
  external_codelist                          ->  NRM-003  (treat as enum)

Severity and category are fetched from DefectTaxonomy at run time — if
the YAML file changes (e.g. a code is retired), we surface the failure
in DerivationResult.failed rather than silently writing stale data.

Manual rows (binding_kind='manual') are NEVER touched. Derived rows
keyed by (std_data_element_id, defect_code, binding_kind) where
binding_kind != 'manual' are upsert-managed by this strategy.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from ....db_engine import get_engine
from ....standard_registry import DefectTaxonomy
from ..strategy_base import (
    DerivationLink,
    DerivationResult,
    DerivationStrategy,
)
from .. import link_repo


# (binding_kind, defect_code) — severity/category resolved from taxonomy
_OBLIGATION_BINDING = ("mandatory", "MIS-001")
_DOMAIN_KIND_TO_BINDING = {
    "enumeration":       ("enumeration", "NRM-003"),
    "range":             ("range",       "NRM-003"),
    "pattern":           ("pattern",     "NRM-002"),
    "external_codelist": ("enumeration", "NRM-003"),
}


def _resolve_defect(defect_code: str) -> tuple[str, str]:
    """Return (severity, category) for a defect_code from the YAML taxonomy.

    Raises LookupError if the code is missing — taxonomy YAML drift is a
    real failure mode (e.g. a code rename) that must surface explicitly.
    """
    dt = DefectTaxonomy.get_by_code(defect_code)
    if dt is None:
        raise LookupError(
            f"defect_code {defect_code!r} not found in defect_taxonomy.yaml"
        )
    return dt.severity, dt.category


class DefectTaxonomyStrategy(DerivationStrategy):
    name = "to_defect_code"
    description = (
        "派生标准 data_element 到 agent_defect_code_bindings "
        "(mandatory→MIS-001, enum/range→NRM-003, pattern→NRM-002)"
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

            elements = conn.execute(text(
                "SELECT e.id, e.name_zh, e.bound_table, e.bound_column, "
                "       e.obligation, e.value_domain_id, "
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
            # Build the candidate set for this element. Each candidate is
            # (binding_kind, defect_code).
            candidates: list[tuple[str, str]] = []
            if el["obligation"] == "mandatory":
                candidates.append(_OBLIGATION_BINDING)
            kind = el.get("domain_kind")
            if kind in _DOMAIN_KIND_TO_BINDING:
                candidates.append(_DOMAIN_KIND_TO_BINDING[kind])

            for binding_kind, defect_code in candidates:
                try:
                    bid = self._upsert_binding_and_link(
                        el=el, version_id=version_id,
                        binding_kind=binding_kind,
                        defect_code=defect_code,
                        by_user=by_user, result=result,
                    )
                    if bid is not None:
                        new_target_ids.add(bid)
                except Exception as e:
                    result.failed.append(
                        (f"{el['id']}:{binding_kind}:{defect_code}", str(e)))

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
                    "UPDATE agent_defect_code_bindings "
                    "SET derived_status='stale', updated_at=now() "
                    "WHERE std_derived_link_id = ANY(CAST(:ids AS uuid[]))"
                ), {"ids": stale_link_ids})
            result.staled_links = stale_link_ids

        return result

    def _upsert_binding_and_link(
        self, *, el, version_id: str, binding_kind: str,
        defect_code: str, by_user: str, result: DerivationResult,
    ) -> str | None:
        severity, category = _resolve_defect(defect_code)
        owner = by_user or "system"
        source_tag = f"std:v{version_id}"

        eng = get_engine()
        with eng.begin() as conn:
            # UNIQUE (std_data_element_id, defect_code, binding_kind) — but
            # `manual` overrides exist on a different binding_kind so they
            # never collide. We still defensively skip if a manual row
            # somehow shares all three (shouldn't happen).
            existing = conn.execute(text(
                "SELECT id, std_derived_link_id, binding_kind "
                "FROM agent_defect_code_bindings "
                "WHERE std_data_element_id=:e "
                "  AND defect_code=:dc "
                "  AND binding_kind=:bk"
            ), {"e": str(el["id"]), "dc": defect_code,
                "bk": binding_kind}).first()

            if existing is not None and existing[1] is None:
                # Same key with no link = manual row (only possible if a
                # human used a derived binding_kind, which is unlikely but
                # we honour it).
                return None

            if existing is not None:
                bid = str(existing[0])
                conn.execute(text(
                    "UPDATE agent_defect_code_bindings SET "
                    "  severity=:sv, "
                    "  category=:cat, "
                    "  source_tag=:st, "
                    "  std_version_id=:vid, "
                    "  derived_status='active', "
                    "  updated_at=now() "
                    "WHERE id=:i"
                ), {"sv": severity, "cat": category, "st": source_tag,
                     "vid": version_id, "i": bid})
                old_link_id = str(existing[1])
                conn.execute(text(
                    "UPDATE std_derived_link SET status='stale', "
                    "stale_reason='superseded by re-derive' WHERE id=:i"
                ), {"i": old_link_id})
            else:
                row = conn.execute(text(
                    "INSERT INTO agent_defect_code_bindings "
                    "(std_data_element_id, defect_code, severity, category, "
                    " binding_kind, source_tag, std_version_id, "
                    " derived_status, owner_username) "
                    "VALUES (:e, :dc, :sv, :cat, :bk, :st, :vid, "
                    "        'active', :u) "
                    "RETURNING id"
                ), {"e": str(el["id"]), "dc": defect_code, "sv": severity,
                     "cat": category, "bk": binding_kind, "st": source_tag,
                     "vid": version_id, "u": owner}).first()
                bid = str(row[0])

            link_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(id, source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy, status) "
                "VALUES (:i, 'data_element', :s, :v, 'defect_code', "
                "        'agent_defect_code_bindings', :t, :ds, 'active')"
            ), {"i": link_id, "s": str(el["id"]), "v": version_id,
                 "t": bid, "ds": self.name})
            conn.execute(text(
                "UPDATE agent_defect_code_bindings SET std_derived_link_id=:l "
                "WHERE id=:i"
            ), {"l": link_id, "i": bid})

        result.new_links.append(DerivationLink(
            source_kind="data_element", source_id=str(el["id"]),
            target_kind="defect_code",
            target_table="agent_defect_code_bindings", target_id=bid,
        ))
        return bid
