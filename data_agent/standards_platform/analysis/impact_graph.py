"""Read-only version-level cross-standard impact graph builder."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine
from . import deduper


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value) if value is not None else None


def _graph_kind(db_kind: str | None) -> str:
    if not db_kind:
        return "unknown"
    return db_kind.removeprefix("std_")


def _node_id(kind: str, raw_id: Any) -> str:
    return f"{_graph_kind(kind)}:{raw_id}"


def version_impact_graph(
    version_id: str,
    include_similar: bool = True,
    min_similarity: float = 0.8,
    top_k: int = 20,
) -> dict:
    """Aggregate derivation, reference, and similar-clause edges for a version."""
    eng = get_engine()
    nodes_by_id: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(
        graph_id: str,
        *,
        kind: str,
        label: str | None = None,
        document_id: Any = None,
        version_id: Any = None,
        metadata: dict | None = None,
    ) -> dict:
        node = nodes_by_id.get(graph_id)
        if node is None:
            node = {
                "id": graph_id,
                "kind": kind,
                "label": label or graph_id,
                "metadata": metadata or {},
            }
            if document_id is not None:
                node["document_id"] = str(document_id)
            if version_id is not None:
                node["version_id"] = str(version_id)
            nodes_by_id[graph_id] = node
            return node

        if label and node.get("label") == graph_id:
            node["label"] = label
        if document_id is not None and "document_id" not in node:
            node["document_id"] = str(document_id)
        if version_id is not None and "version_id" not in node:
            node["version_id"] = str(version_id)
        if metadata:
            node.setdefault("metadata", {}).update(metadata)
        return node

    def edge_summary() -> dict:
        by_type = Counter(e["edge_type"] for e in edges)
        return {
            "node_count": len(nodes_by_id),
            "edge_count": len(edges),
            "by_edge_type": dict(by_type),
            "cross_version_edge_count": sum(
                1 for e in edges if e.get("metadata", {}).get("cross_version")
            ),
        }

    def result() -> dict:
        return {
            "version_id": str(version_id),
            "nodes": list(nodes_by_id.values()),
            "edges": edges,
            "summary": edge_summary(),
        }

    if eng is None:
        return result()

    with eng.connect() as conn:
        version = conn.execute(text(
            "SELECT v.id, v.document_id, v.version_label, v.status, "
            "d.doc_code, d.title "
            "FROM std_document_version v "
            "JOIN std_document d ON d.id = v.document_id "
            "WHERE v.id=:v"
        ), {"v": version_id}).mappings().first()
        if version is None:
            return result()

        add_node(
            f"version:{version['id']}",
            kind="version",
            label=f"{version['doc_code']} {version['version_label']}",
            document_id=version["document_id"],
            version_id=version["id"],
            metadata={
                "doc_code": version["doc_code"],
                "title": version["title"],
                "status": version["status"],
            },
        )

        derivations = conn.execute(text(
            "SELECT id, source_kind, source_id, source_version_id, target_kind, "
            "target_table, target_id, derivation_strategy, status, "
            "stale_reason, generated_at "
            "FROM std_derived_link "
            "WHERE source_version_id=:v "
            "ORDER BY generated_at DESC, id"
        ), {"v": version_id}).mappings().all()
        for row in derivations:
            source = _node_id(row["source_kind"], row["source_id"])
            target = _node_id(row["target_kind"], row["target_id"])
            add_node(
                source,
                kind=_graph_kind(row["source_kind"]),
                label=f"{_graph_kind(row['source_kind'])}:{row['source_id']}",
                version_id=row["source_version_id"],
            )
            add_node(
                target,
                kind=_graph_kind(row["target_kind"]),
                label=f"{_graph_kind(row['target_kind'])}:{row['target_id']}",
            )
            edges.append({
                "id": f"derive:{row['id']}",
                "edge_type": "derives",
                "source": source,
                "target": target,
                "label": row["derivation_strategy"],
                "status": row["status"],
                "metadata": {
                    "derivation_strategy": row["derivation_strategy"],
                    "target_table": row["target_table"],
                    "generated_at": _jsonable(row["generated_at"]),
                    "stale_reason": row["stale_reason"],
                    "cross_version": False,
                },
            })

        refs = conn.execute(text(
            "SELECT r.id, r.source_clause_id, r.source_data_element_id, "
            "r.target_kind, "
            "r.target_clause_id, r.target_data_element_id, r.target_term_id, "
            "r.target_document_id, r.target_url, r.snapshot_id, "
            "r.citation_text, r.confidence, r.verification_status, "
            "r.inserted_by, r.inserted_at, "
            "sc.document_id AS source_clause_document_id, "
            "sc.document_version_id AS source_clause_version_id, "
            "sde.document_version_id AS source_data_element_version_id, "
            "sde.code AS source_data_element_code, "
            "sde.name_zh AS source_data_element_name, "
            "sdev.document_id AS source_data_element_document_id, "
            "tc.document_id AS target_clause_document_id, "
            "tc.document_version_id AS target_clause_version_id, "
            "tc.clause_no AS target_clause_no, tc.body_md AS target_clause_body, "
            "de.document_version_id AS target_data_element_version_id, "
            "de.code AS target_data_element_code, de.name_zh AS target_data_element_name, "
            "tdev.document_id AS target_data_element_document_id, "
            "tm.document_version_id AS target_term_version_id, "
            "tm.name_zh AS target_term_name, "
            "ttv.document_id AS target_term_document_id, "
            "td.doc_code AS target_document_code, td.title AS target_document_title "
            "FROM std_reference r "
            "LEFT JOIN std_clause sc ON sc.id = r.source_clause_id "
            "LEFT JOIN std_data_element sde ON sde.id = r.source_data_element_id "
            "LEFT JOIN std_document_version sdev "
            "  ON sdev.id = sde.document_version_id "
            "LEFT JOIN std_clause tc ON tc.id = r.target_clause_id "
            "LEFT JOIN std_data_element de ON de.id = r.target_data_element_id "
            "LEFT JOIN std_document_version tdev "
            "  ON tdev.id = de.document_version_id "
            "LEFT JOIN std_term tm ON tm.id = r.target_term_id "
            "LEFT JOIN std_document_version ttv "
            "  ON ttv.id = tm.document_version_id "
            "LEFT JOIN std_document td ON td.id = r.target_document_id "
            "WHERE sc.document_version_id=:v "
            "   OR sde.document_version_id=:v "
            "ORDER BY r.inserted_at DESC, r.id"
        ), {"v": version_id}).mappings().all()
        for row in refs:
            source_clause_matches = (
                row["source_clause_version_id"] is not None
                and str(row["source_clause_version_id"]) == str(version_id)
            )
            source_data_element_matches = (
                row["source_data_element_version_id"] is not None
                and str(row["source_data_element_version_id"]) == str(version_id)
            )
            if source_clause_matches or (
                row["source_clause_id"] is not None
                and not source_data_element_matches
            ):
                source = f"clause:{row['source_clause_id']}"
                source_kind = "clause"
                source_label = f"clause:{row['source_clause_id']}"
                source_document_id = row["source_clause_document_id"]
                source_version_id = row["source_clause_version_id"]
            else:
                source = f"data_element:{row['source_data_element_id']}"
                source_kind = "data_element"
                source_label = (
                    row["source_data_element_code"]
                    or row["source_data_element_name"]
                    or source
                )
                source_document_id = row["source_data_element_document_id"]
                source_version_id = row["source_data_element_version_id"]
            add_node(
                source,
                kind=source_kind,
                label=source_label,
                document_id=source_document_id,
                version_id=source_version_id,
            )

            target, target_version, target_document, label = _reference_target(row)
            add_node(
                target,
                kind=_graph_kind(row["target_kind"]),
                label=label,
                document_id=target_document,
                version_id=target_version,
                metadata={"target_kind": row["target_kind"]},
            )
            cross_version = (
                target_version is not None and str(target_version) != str(version_id)
            )
            edges.append({
                "id": f"reference:{row['id']}",
                "edge_type": "references",
                "source": source,
                "target": target,
                "label": row["target_kind"],
                "status": row["verification_status"],
                "metadata": {
                    "citation_text": row["citation_text"],
                    "confidence": _jsonable(row["confidence"]),
                    "target_kind": row["target_kind"],
                    "target_version_id": (
                        str(target_version) if target_version is not None else None
                    ),
                    "target_url": row["target_url"],
                    "snapshot_id": _jsonable(row["snapshot_id"]),
                    "inserted_by": row["inserted_by"],
                    "inserted_at": _jsonable(row["inserted_at"]),
                    "cross_version": cross_version,
                },
            })

    if include_similar:
        for hit in deduper.find_similar_clauses(
            version_id=str(version_id),
            top_k=top_k,
            min_similarity=min_similarity,
        ):
            source_clause_id = hit["source_clause_id"]
            target_clause_id = hit["target_clause_id"]
            target_version_id = hit.get("document_version_id")
            source = f"clause:{source_clause_id}"
            target = f"clause:{target_clause_id}"
            add_node(source, kind="clause", label=f"clause:{source_clause_id}",
                     version_id=version_id)
            add_node(
                target,
                kind="clause",
                label=hit.get("body_md") or f"clause:{target_clause_id}",
                version_id=target_version_id,
                metadata={"body_md": hit.get("body_md")},
            )
            score = float(hit["similarity"])
            edges.append({
                "id": f"similar:{source_clause_id}:{target_clause_id}",
                "edge_type": "similar_clause",
                "source": source,
                "target": target,
                "label": f"similar {score:.3f}",
                "score": score,
                "metadata": {
                    "target_version_id": (
                        str(target_version_id)
                        if target_version_id is not None else None
                    ),
                    "cross_version": True,
                },
            })

    return result()


def _reference_target(row: dict) -> tuple[str, Any, Any, str]:
    target_kind = row["target_kind"]
    if target_kind == "std_clause":
        target_id = row["target_clause_id"]
        label = row["target_clause_no"] or row["target_clause_body"]
        return (
            f"clause:{target_id}",
            row["target_clause_version_id"],
            row["target_clause_document_id"],
            label or f"clause:{target_id}",
        )
    if target_kind == "std_data_element":
        target_id = row["target_data_element_id"]
        label = row["target_data_element_code"] or row["target_data_element_name"]
        return (
            f"data_element:{target_id}",
            row["target_data_element_version_id"],
            row["target_data_element_document_id"],
            label or f"data_element:{target_id}",
        )
    if target_kind == "std_term":
        target_id = row["target_term_id"]
        return (
            f"term:{target_id}",
            row["target_term_version_id"],
            row["target_term_document_id"],
            row["target_term_name"] or f"term:{target_id}",
        )
    if target_kind == "std_document":
        target_id = row["target_document_id"]
        label = row["target_document_code"] or row["target_document_title"]
        return f"document:{target_id}", None, target_id, label or f"document:{target_id}"
    if target_kind in {"external_url", "web_snapshot"}:
        target = row["target_url"] or row["snapshot_id"] or row["id"]
        return f"{target_kind}:{target}", None, None, str(target)
    target = row["target_url"] or row["snapshot_id"] or row["id"]
    return f"{_graph_kind(target_kind)}:{target}", None, None, str(target)
