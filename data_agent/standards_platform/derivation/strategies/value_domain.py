"""ValueDomainStrategy — derive bound std_data_element rows that have a
value_domain into agent_semantic_hints rows that carry the value-domain
constraint (enum / range / pattern / external codelist).

Field mapping:
  scope_type     = 'column'
  scope_ref      = '<bound_table>.<bound_column>'
  hint_kind      = depends on std_value_domain.kind:
                     enumeration       -> 'value_enum'
                     range             -> 'value_range'
                     pattern           -> 'value_pattern'
                     external_codelist -> 'value_codelist'
  hint_text_zh   = human-readable summary built from the domain rows
  severity       = 'info'
  trigger_keywords = [bound_column, name_zh, *registry_aliases,
                      *first_few_enum_values]   (deduped)
  source_tag     = 'std:v<version_id>'
  std_derived_link_id = <link.id>
  std_version_id = <version_id>
  derived_status = 'active'

UNIQUE constraint on agent_semantic_hints is (scope_ref, hint_kind, hint_text_zh).
Manual rows (std_derived_link_id IS NULL) are NEVER touched.

Wave 6-eng: only the engineering surface — strategy + tests + runner wiring.
A/B evaluation against CQ-125 is a separate Wave 6-eval task.
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


_KIND_TO_HINT_KIND = {
    "enumeration": "value_enum",
    "range": "value_range",
    "pattern": "value_pattern",
    "external_codelist": "value_codelist",
}


def _summarize_domain(*, kind: str, items: list[dict],
                      domain_name: str | None,
                      domain_code: str | None) -> str:
    """Build a hint_text_zh string from value_domain + items.

    Schema notes:
      std_value_domain     has only (code, name, kind) — no range/pattern bodies.
      std_value_domain_item has (value, label_zh, label_en, ordinal).
    Bounds for 'range', regex for 'pattern', and external lookup keys for
    'external_codelist' are encoded as items themselves (the domain shape is
    intentionally schema-light at the std_* layer).
    """
    label = domain_name or domain_code or "(未命名值域)"
    if kind == "enumeration":
        if not items:
            return f"标准取值范围（{label}）：枚举（暂无明细）"
        # Take first 16 values to keep hint readable; LLM rarely needs 100+.
        head = items[:16]
        pairs = []
        for it in head:
            v = it.get("value")
            lbl = it.get("label_zh") or it.get("label_en")
            pairs.append(f"{v}={lbl}" if lbl else str(v))
        suffix = f"，共 {len(items)} 项" if len(items) > len(head) else ""
        return (
            f"标准取值范围（{label}）：枚举 "
            + ", ".join(pairs) + suffix
        )
    if kind == "range":
        if not items:
            return f"标准取值范围（{label}）：数值/时间范围（未给明界限）"
        # By convention the items carry low/high in 'value' or label.
        bounds = ", ".join(
            f"{it.get('label_zh') or it.get('value')}" for it in items
        )
        return f"标准取值范围（{label}）：{bounds}"
    if kind == "pattern":
        if not items:
            return f"标准取值范围（{label}）：模式约束（未给正则）"
        regex = items[0].get("value") or ""
        return f"标准取值范围（{label}）：必须匹配正则 {regex}"
    if kind == "external_codelist":
        # Expect 1 item with value=ref (e.g. 'GB/T 21010 一级类')
        if not items:
            return f"标准取值范围（{label}）：参照外部代码表（未指定）"
        ref = items[0].get("value") or ""
        return f"标准取值范围（{label}）：参照外部代码表 {ref}"
    # Defensive default — unknown kind treated as opaque label dump.
    return f"标准取值范围（{label}）：{kind}"


class ValueDomainStrategy(DerivationStrategy):
    name = "to_value_semantics"
    description = (
        "派生标准 data_element 的 value_domain 到 agent_semantic_hints "
        "(value_enum / value_range / value_pattern / value_codelist)"
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

            # Only data_elements that are bound AND have a value_domain.
            elements = conn.execute(text(
                "SELECT e.id, e.name_zh, e.bound_table, e.bound_column, "
                "       e.value_domain_id, "
                "       d.code AS domain_code, d.name AS domain_name, "
                "       d.kind AS domain_kind "
                "FROM std_data_element e "
                "JOIN std_value_domain d ON d.id = e.value_domain_id "
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
            try:
                hint_id = self._upsert_hint_and_link(
                    el=el, version_id=version_id,
                    by_user=by_user, result=result,
                )
                if hint_id is not None:
                    new_target_ids.add(hint_id)
            except Exception as e:
                result.failed.append((str(el["id"]), str(e)))

        stale_link_ids: list[str] = [
            link_id for tgt, link_id in prev_target_to_link.items()
            if tgt not in new_target_ids
        ]
        if stale_link_ids:
            link_repo.mark_stale(
                link_ids=stale_link_ids,
                reason=f"superseded by version {version_id}",
            )
            with get_engine().begin() as conn:
                conn.execute(text(
                    "UPDATE agent_semantic_hints SET derived_status='stale' "
                    "WHERE std_derived_link_id = ANY(CAST(:ids AS uuid[]))"
                ), {"ids": stale_link_ids})
            result.staled_links = stale_link_ids

        return result

    def _upsert_hint_and_link(self, *, el, version_id: str, by_user: str,
                              result: DerivationResult) -> str | None:
        kind = el["domain_kind"]
        hint_kind = _KIND_TO_HINT_KIND.get(kind)
        if hint_kind is None:
            # Unknown std_value_domain.kind — skip silently, surface as failure.
            raise ValueError(f"unsupported value_domain.kind={kind}")

        scope_ref = f"{el['bound_table']}.{el['bound_column']}"

        eng = get_engine()
        with eng.connect() as conn:
            items = conn.execute(text(
                "SELECT value, label_zh, label_en, ordinal "
                "FROM std_value_domain_item "
                "WHERE value_domain_id=:v "
                "ORDER BY ordinal, value"
            ), {"v": str(el["value_domain_id"])}).mappings().all()
            items_list = [dict(it) for it in items]

            # Pull registry aliases for trigger augmentation, same pattern as
            # SemanticHintStrategy. Manual edits to registry stay decoupled.
            reg = conn.execute(text(
                "SELECT aliases FROM agent_semantic_registry "
                "WHERE table_name=:t AND column_name=:c"
            ), {"t": el["bound_table"], "c": el["bound_column"]}).first()

        registry_aliases: list[str] = []
        if reg is not None and reg[0]:
            raw = reg[0]
            registry_aliases = raw if isinstance(raw, list) else (
                json.loads(raw) if raw else [])

        hint_text_zh = _summarize_domain(
            kind=kind, items=items_list,
            domain_name=el.get("domain_name"),
            domain_code=el.get("domain_code"),
        )

        # Trigger keywords: column + name + registry aliases + first few enum
        # values. Enum values let the user phrase the question with a literal
        # like "水田" or "0101" and still hit the hint.
        candidate_kws: list[str] = [
            el["bound_column"], el["name_zh"], *registry_aliases,
        ]
        if kind == "enumeration":
            for it in items_list[:8]:
                v = it.get("value")
                lbl = it.get("label_zh")
                if v:
                    candidate_kws.append(str(v))
                if lbl:
                    candidate_kws.append(str(lbl))

        seen: set[str] = set()
        merged: list[str] = []
        for kw in candidate_kws:
            if kw and kw not in seen:
                seen.add(kw)
                merged.append(kw)
        trigger_keywords = json.dumps(merged, ensure_ascii=False)
        source_tag = f"std:v{version_id}"

        with eng.begin() as conn:
            existing = conn.execute(text(
                "SELECT id, std_derived_link_id FROM agent_semantic_hints "
                "WHERE scope_ref=:sr AND hint_kind=:hk AND hint_text_zh=:ht"
            ), {"sr": scope_ref, "hk": hint_kind, "ht": hint_text_zh}).first()

            if existing is not None and existing[1] is None:
                # Manual row — leave alone, do not derive.
                return None

            if existing is not None:
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
                old_link_id = str(existing[1])
                conn.execute(text(
                    "UPDATE std_derived_link SET status='stale', "
                    "stale_reason='superseded by re-derive' WHERE id=:i"
                ), {"i": old_link_id})
            else:
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
