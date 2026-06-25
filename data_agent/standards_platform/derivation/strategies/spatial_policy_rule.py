"""SpatialPolicyRuleStrategy — derive TWM policy-rule candidates.

This strategy is intentionally conservative. It only turns bound standard
data elements with clear spatial-policy signals into disabled TWM rules. The
rows are review-required candidates, not executable policy decisions.

Re-derive semantics:
  Each run inserts fresh twm_policy_rule rows and std_derived_link rows. Prior
  active links for the same document and strategy are marked stale, and their
  target rule metadata is marked derived_status='stale'. Rule rows are kept
  for audit history.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from ....db_engine import get_engine
from .. import link_repo
from ..strategy_base import (
    DerivationLink,
    DerivationResult,
    DerivationStrategy,
)


_BOUNDARY_TOKENS = {
    "boundary", "boundaries", "border", "geom", "geometry", "shape",
    "the_geom", "wkb_geometry", "空间", "几何", "边界", "范围", "控制线",
}
_HIGH_SEVERITY_ROLES = {"pbf", "eco_redline"}


@dataclass(frozen=True)
class _Candidate:
    target_role: str
    severity: str
    reasons: list[str]


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _signal_blob(el: dict[str, Any]) -> str:
    parts = [
        el.get("code"),
        el.get("name_zh"),
        el.get("name_en"),
        el.get("definition"),
        el.get("representation_class"),
        el.get("datatype"),
        el.get("unit"),
        el.get("bound_table"),
        el.get("bound_column"),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _contains_any(blob: str, tokens: tuple[str, ...]) -> bool:
    return any(token in blob for token in tokens)


def _classify_candidate(el: dict[str, Any]) -> _Candidate | None:
    blob = _signal_blob(el)
    reasons: list[str] = []

    role: str | None = None
    if _contains_any(blob, (
        "synthetic_pbf", "permanent_basic_farmland", "basic_farmland",
        "pbf", "永久基本农田", "基本农田",
    )):
        role = "pbf"
        reasons.append("pbf_signal")
    elif _contains_any(blob, (
        "synthetic_eco_redline", "eco_redline", "ecological_redline",
        "redline", "生态保护红线", "生态红线",
    )):
        role = "eco_redline"
        reasons.append("eco_redline_signal")
    elif _contains_any(blob, (
        "synthetic_urban_boundary", "urban_boundary",
        "urban_development_boundary", "城镇开发边界", "开发边界",
    )):
        role = "urban_boundary"
        reasons.append("urban_boundary_signal")
    elif _contains_any(blob, (
        "synthetic_planning_zones", "planning_zone", "planning_zones",
        "用途管制", "规划分区", "管制分区", "功能分区",
    )):
        role = "planning_zone"
        reasons.append("planning_zone_signal")
    elif _contains_any(blob, tuple(_BOUNDARY_TOKENS)):
        role = "boundary"
        reasons.append("boundary_or_geometry_signal")

    if _norm(el.get("representation_class")) == "geometry":
        reasons.append("representation_class_geometry")
        if role is None:
            role = "boundary"

    if role is None:
        return None

    severity = "high" if role in _HIGH_SEVERITY_ROLES else "medium"
    return _Candidate(target_role=role, severity=severity, reasons=reasons)


def _safe_code(value: Any, fallback: str) -> str:
    raw = str(value or fallback or "").upper()
    safe = re.sub(r"[^A-Z0-9]+", "-", raw).strip("-")
    return safe[:48] or "UNNAMED"


def _rule_body(*, target_role: str, el: dict[str, Any],
               reasons: list[str]) -> dict[str, Any]:
    return {
        "version": "1.0",
        "subject": {"object_type": "project"},
        "constraint": {
            "target_role": target_role,
            "spatial_predicate": "intersects",
            "min_overlap_area_m2": 1,
        },
        "hit_when": {
            "overlap_area_m2": {"gt": 1},
        },
        "evidence": {
            "required": ["source_feature", "rule_clause", "spatial_calc"],
        },
        "review": {"policy": "review_required"},
        "metadata": {
            "derived_from": "std_data_element",
            "std_data_element_id": str(el["id"]),
            "bound_table": el.get("bound_table"),
            "bound_column": el.get("bound_column"),
            "candidate_reasons": reasons,
        },
    }


class SpatialPolicyRuleStrategy(DerivationStrategy):
    name = "to_spatial_policy_rule"
    description = (
        "派生标准空间管控 data_element 到 TWM policy-rule 候选"
    )

    def run(self, *, version_id: str,
            by_user: str = "system") -> DerivationResult:
        result = DerivationResult(strategy=self.name)
        owner = by_user or "system"

        eng = get_engine()
        with eng.connect() as conn:
            version_row = conn.execute(text(
                "SELECT v.document_id, v.version_label, d.doc_code, d.title "
                "FROM std_document_version v "
                "JOIN std_document d ON d.id = v.document_id "
                "WHERE v.id=:v"
            ), {"v": version_id}).mappings().first()
            if version_row is None:
                raise LookupError(f"version {version_id} not found")

            doc_id = str(version_row["document_id"])
            doc_code = version_row["doc_code"]
            doc_title = version_row["title"]
            version_label = version_row["version_label"]

            elements = [dict(r) for r in conn.execute(text(
                "SELECT e.id, e.code, e.name_zh, e.name_en, e.definition, "
                "       e.representation_class, e.datatype, e.unit, "
                "       e.bound_table, e.bound_column, "
                "       e.defined_by_clause_id, e.term_id "
                "FROM std_data_element e "
                "WHERE e.document_version_id=:v "
                "  AND e.bound_table IS NOT NULL "
                "  AND e.bound_column IS NOT NULL "
                "ORDER BY e.bound_table, e.bound_column, e.code"
            ), {"v": version_id}).mappings().all()]

            prev_active = conn.execute(text(
                "SELECT l.id, l.target_id "
                "FROM std_derived_link l "
                "JOIN std_document_version v ON v.id = l.source_version_id "
                "WHERE v.document_id=:d "
                "  AND l.derivation_strategy=:s "
                "  AND l.status='active'"
            ), {"d": doc_id, "s": self.name}).mappings().all()

        candidates: list[tuple[dict[str, Any], _Candidate]] = []
        for el in elements:
            candidate = _classify_candidate(el)
            if candidate is not None:
                candidates.append((el, candidate))

        new_target_ids: list[str] = []
        if candidates:
            rule_set_id = self._ensure_rule_set(
                version_id=version_id,
                version_label=version_label,
                doc_code=doc_code,
                by_user=owner,
            )

            for el, candidate in candidates:
                try:
                    rule_id = self._insert_policy_rule_and_link(
                        rule_set_id=rule_set_id,
                        el=el,
                        candidate=candidate,
                        version_id=version_id,
                        version_label=version_label,
                        doc_code=doc_code,
                        doc_title=doc_title,
                        by_user=owner,
                    )
                    new_target_ids.append(rule_id)
                    result.new_links.append(DerivationLink(
                        source_kind="data_element",
                        source_id=str(el["id"]),
                        target_kind="spatial_policy_rule",
                        target_table="twm_policy_rule",
                        target_id=rule_id,
                        notes={
                            "target_role": candidate.target_role,
                            "candidate_reasons": candidate.reasons,
                        },
                    ))
                except Exception as exc:
                    result.failed.append((str(el["id"]), str(exc)))

        stale_link_ids = [str(r["id"]) for r in prev_active
                          if str(r["target_id"]) not in new_target_ids]
        if stale_link_ids:
            link_repo.mark_stale(
                link_ids=stale_link_ids,
                reason=f"superseded by version {version_id}",
            )
            stale_target_ids = [str(r["target_id"]) for r in prev_active
                                if str(r["target_id"]) not in new_target_ids]
            with eng.begin() as conn:
                conn.execute(text(
                    "UPDATE twm_policy_rule "
                    "SET metadata = metadata || "
                    "    '{\"derived_status\":\"stale\"}'::jsonb, "
                    "    updated_at = now() "
                    "WHERE id = ANY(:ids)"
                ), {"ids": stale_target_ids})
            result.staled_links = stale_link_ids

        return result

    def _ensure_rule_set(self, *, version_id: str, version_label: str | None,
                         doc_code: str | None, by_user: str) -> str:
        name = f"std:{doc_code or version_id}:spatial_policy_rules"
        eng = get_engine()
        with eng.begin() as conn:
            existing = conn.execute(text(
                "SELECT id FROM twm_rule_set "
                "WHERE source_std_version_id=:v "
                "  AND name=:n "
                "ORDER BY created_at DESC "
                "LIMIT 1"
            ), {"v": version_id, "n": name}).first()
            if existing is not None:
                return str(existing[0])

            rule_set_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO twm_rule_set "
                "(id, name, version_label, source_std_version_id, "
                " status, created_by) "
                "VALUES (:i, :n, :vl, :v, 'draft', :u)"
            ), {"i": rule_set_id, "n": name,
                 "vl": version_label or "", "v": version_id, "u": by_user})
            return rule_set_id

    def _insert_policy_rule_and_link(
        self,
        *,
        rule_set_id: str,
        el: dict[str, Any],
        candidate: _Candidate,
        version_id: str,
        version_label: str | None,
        doc_code: str | None,
        doc_title: str | None,
        by_user: str,
    ) -> str:
        rule_id = str(uuid.uuid4())
        link_id = str(uuid.uuid4())
        rule_code = f"STD-SPATIAL-{_safe_code(el.get('code'), rule_id[:8])}"
        title = str(el.get("name_zh") or el.get("name_en")
                    or el.get("bound_column") or rule_code)
        body = _rule_body(
            target_role=candidate.target_role,
            el=el,
            reasons=candidate.reasons,
        )
        legal_basis = {
            "std_document_code": doc_code,
            "std_document_title": doc_title,
            "std_version_id": version_id,
            "std_version_label": version_label,
            "std_data_element_id": str(el["id"]),
            "std_data_element_code": el.get("code"),
            "std_data_element_name": el.get("name_zh") or el.get("name_en"),
            "defined_by_clause_id": (
                str(el["defined_by_clause_id"])
                if el.get("defined_by_clause_id") else None
            ),
        }
        metadata = {
            "derived_status": "active",
            "derived_from": "std_data_element",
            "derivation_strategy": self.name,
            "generated_by": by_user,
            "target_role": candidate.target_role,
            "candidate_reasons": candidate.reasons,
            "bound_table": el.get("bound_table"),
            "bound_column": el.get("bound_column"),
            "review_note": "generated disabled; reviewer approval required",
        }

        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO twm_policy_rule "
                "(id, rule_set_id, rule_code, title, category, severity, "
                " rule_body, legal_basis, review_policy, enabled, metadata) "
                "VALUES (:i, :rs, :rc, :t, "
                "        'standard_derived_spatial_policy', :sv, "
                "        CAST(:rb AS jsonb), CAST(:lb AS jsonb), "
                "        'review_required', FALSE, CAST(:m AS jsonb))"
            ), {
                "i": rule_id,
                "rs": rule_set_id,
                "rc": rule_code,
                "t": title,
                "sv": candidate.severity,
                "rb": json.dumps(body, ensure_ascii=False),
                "lb": json.dumps(legal_basis, ensure_ascii=False),
                "m": json.dumps(metadata, ensure_ascii=False),
            })

            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(id, source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy, status) "
                "VALUES (:i, 'data_element', :s, :v, "
                "        'spatial_policy_rule', 'twm_policy_rule', :t, "
                "        :ds, 'active')"
            ), {
                "i": link_id,
                "s": str(el["id"]),
                "v": version_id,
                "t": rule_id,
                "ds": self.name,
            })

            conn.execute(text(
                "UPDATE twm_policy_rule SET std_derived_link_id=:l "
                "WHERE id=:i"
            ), {"l": link_id, "i": rule_id})

        return rule_id
