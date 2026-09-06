"""Evidence-bound relationship candidates for the Abu Dhabi source catalogs.

Relationship documentation is useful for discovery, but it is not an approved
join graph.  Every emitted edge therefore remains review-only and carries its
original documentation evidence and cardinality caveats.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "gda.abu-dhabi-semantic-relationship-candidates.v1"
_MMD_EDGE_RE = re.compile(
    r'^\s*(?:[A-Za-z0-9_]+)\["`([^`"]+)`"\]\s*-->'
    r'\|"([^"|]+)"\|\s*(?:[A-Za-z0-9_]+)\["`([^`"]+)`"\]'
)
_RELATION_TABLE_RE = re.compile(
    r'\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*=\s*`([^`]+)`\s*\|\s*(.*?)\s*\|'
)
_SPATIAL_RE = re.compile(
    r'(ST_(?:Intersects|Contains|Within|DWithin|Touches|Crosses|Overlaps))\s*\('\
    r'\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\s*,\s*'
    r'([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\s*\)',
    re.IGNORECASE,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object_required:{path.name}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resource_names(catalog: dict[str, Any]) -> set[str]:
    return {
        str(item.get("physical_table") or "").split(".")[-1].casefold()
        for item in catalog.get("resources") or []
        if isinstance(item, dict) and item.get("physical_table")
    }


def _qualify(name: str, names: set[str]) -> str | None:
    key = str(name or "").strip().strip("`").split(".")[-1].casefold()
    if key in names:
        return f"public.{key}"
    return None


def _edge(
    *, source: str, target: str, source_field: str | None, target_field: str | None,
    predicate: str, evidence_type: str, evidence_path: Path, notes: str = "",
    confidence: str | None = None,
) -> dict[str, Any]:
    relation_id = "abu_dhabi.relationship." + hashlib.sha1(
        f"{source}|{target}|{source_field}|{target_field}|{predicate}|{evidence_path}".encode()
    ).hexdigest()[:16]
    return {
        "relation_id": relation_id,
        "source_table": source,
        "target_table": target,
        "source_field": source_field,
        "target_field": target_field,
        "predicate": predicate,
        "evidence_type": evidence_type,
        "confidence_label": confidence,
        "cardinality_notes": notes,
        "evidence_path": str(evidence_path),
        "evidence_sha256": _sha(evidence_path),
        "review_status": "candidate_review_required",
        "execution_authorized": False,
    }


def build_relationship_candidate_catalog(
    *, catalog_path: Path, alignment_path: Path, dictionary_root: Path, source_kind: str
) -> dict[str, Any]:
    if source_kind not in {"liveability", "makani"}:
        raise ValueError("source_kind must be liveability or makani")
    catalog = _load(catalog_path)
    alignment = _load(alignment_path)
    names = _resource_names(catalog)
    relations: list[dict[str, Any]] = []
    evidence_files: list[Path] = []
    if source_kind == "liveability":
        graph = dictionary_root / "livability" / "graph"
        files = sorted(graph.glob("relationships_*.mmd"))
        for path in files:
            evidence_files.append(path)
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = _MMD_EDGE_RE.match(line)
                if not match:
                    continue
                source_raw, label, target_raw = match.groups()
                source = _qualify(source_raw, names)
                target = _qualify(target_raw, names)
                if not source or not target:
                    continue
                field_part, _, confidence_part = label.partition("/")
                source_field, _, target_field = field_part.partition("->")
                relations.append(
                    _edge(
                        source=source,
                        target=target,
                        source_field=source_field.strip() or None,
                        target_field=target_field.strip() or None,
                        predicate="field_equality_candidate",
                        evidence_type="livability_graph_mmd",
                        evidence_path=path,
                        confidence=confidence_part.strip() or None,
                        notes=label.strip(),
                    )
                )
    else:
        for item in alignment.get("resources") or []:
            if not isinstance(item, dict):
                continue
            document = item.get("dictionary_document") or {}
            raw_path = document.get("path")
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if not path.exists() or path.suffix.casefold() != ".md":
                continue
            evidence_files.append(path)
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _RELATION_TABLE_RE.finditer(text):
                target_raw, left, right, notes = match.groups()
                left_table, _, left_field = left.rpartition(".")
                right_table, _, right_field = right.rpartition(".")
                source = _qualify(left_table, names)
                target = _qualify(right_table or target_raw, names)
                if not source or not target:
                    continue
                relations.append(
                    _edge(
                        source=source,
                        target=target,
                        source_field=left_field or None,
                        target_field=right_field or None,
                        predicate="field_equality_candidate",
                        evidence_type="makani_dictionary_relation_table",
                        evidence_path=path,
                        notes=notes,
                    )
                )
            for match in _SPATIAL_RE.finditer(text):
                predicate, left_table, left_field, right_table, right_field = match.groups()
                source = _qualify(left_table, names)
                target = _qualify(right_table, names)
                if not source or not target:
                    continue
                relations.append(
                    _edge(
                        source=source,
                        target=target,
                        source_field=left_field,
                        target_field=right_field,
                        predicate=predicate.upper(),
                        evidence_type="makani_dictionary_spatial_note",
                        evidence_path=path,
                        notes="Spatial predicate documented; CRS and cardinality require review.",
                    )
                )

    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for relation in relations:
        key = tuple(relation.get(name) for name in ("source_table", "target_table", "source_field", "target_field", "predicate"))
        deduped.setdefault(key, relation)
    relations = sorted(deduped.values(), key=lambda item: str(item["relation_id"]))
    predicates = Counter(str(item["predicate"]) for item in relations)
    return {
        "schema": SCHEMA,
        "catalog_id": f"abu-dhabi-{source_kind}-relationship-candidates-v1",
        "source_kind": source_kind,
        "source_evidence": {
            "catalog_path": str(catalog_path),
            "catalog_sha256": _sha(catalog_path),
            "alignment_path": str(alignment_path),
            "alignment_sha256": _sha(alignment_path),
            "dictionary_root": str(dictionary_root),
            "evidence_file_count": len(set(evidence_files)),
        },
        "coverage": {
            "resource_count": len(catalog.get("resources") or []),
            "relationship_candidate_count": len(relations),
            "field_equality_candidate_count": predicates["field_equality_candidate"],
            "spatial_predicate_candidate_count": sum(
                count for predicate, count in predicates.items() if predicate.startswith("ST_")
            ),
            "candidate_review_required_count": len(relations),
        },
        "runtime_role": {
            "candidate_relationships_may_execute": False,
            "join_admission": "reviewed relationship and cardinality approval required",
            "source_rows_persisted": False,
        },
        "claim_boundary": {
            "documentation_is_evidence_not_authority": True,
            "every_relationship_requires_review": True,
            "spatial_crs_requires_review": True,
        },
        "relationships": relations,
    }


def write_relationship_candidate_catalog(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = ["SCHEMA", "build_relationship_candidate_catalog", "write_relationship_candidate_catalog"]
