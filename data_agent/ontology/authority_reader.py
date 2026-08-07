"""Read-only PostgreSQL authority backend for the ontology runtime."""

from __future__ import annotations

import os
from collections import defaultdict, deque
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import bindparam, text

from .contracts import ONTOLOGY_KEY

DOMAIN_MODEL_KINDS = {
    "DomainClass",
    "ProcessClass",
    "StateClass",
    "RoleClass",
    "InformationClass",
    "ObservationClass",
}


class OntologyAuthorityUnavailable(RuntimeError):
    """Raised when no published active ontology exists in PostgreSQL."""


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class PostgresOntologyReader:
    """Query one active, published ontology version with strict query budgets."""

    def __init__(self, engine: Any, *, ontology_key: str = ONTOLOGY_KEY):
        self.engine = engine
        self.ontology_key = ontology_key
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT v.ontology_version_id::text AS ontology_version_id, "
                "v.semantic_version, v.title, v.description, v.namespace_uri, "
                "v.content_sha256, v.model_profile, v.metadata, v.published_at, "
                "p.package_id, p.package_uri, p.projection_status, p.projection_checkpoint "
                "FROM gda_ontology.active_package a "
                "JOIN gda_ontology.ontology_version v "
                "  ON v.ontology_version_id = a.ontology_version_id "
                "JOIN gda_ontology.ontology_package p "
                "  ON p.ontology_version_id = v.ontology_version_id "
                "WHERE a.ontology_key = :ontology_key AND v.status = 'published'"
            ), {"ontology_key": ontology_key}).mappings().first()
        if not row:
            raise OntologyAuthorityUnavailable(
                f"no active published PostgreSQL ontology for {ontology_key}"
            )
        self._active = _json_ready(dict(row))
        self.version_id = self._active["ontology_version_id"]
        self.manifest = SimpleNamespace(
            ontology_version_id=self.version_id,
            semantic_version=self._active["semantic_version"],
            content_sha256=self._active["content_sha256"],
            package_id=self._active["package_id"],
        )

    @staticmethod
    def _rows(result: Any) -> list[dict[str, Any]]:
        return [_json_ready(dict(row)) for row in result.mappings()]

    def status(self) -> dict[str, Any]:
        metadata = self._active.get("metadata") or {}
        validation = self.validation()
        return {
            "available": True,
            "backend": "postgresql_authority",
            "package_id": self.manifest.package_id,
            "ontology_version_id": self.version_id,
            "semantic_version": self.manifest.semantic_version,
            "content_sha256": self.manifest.content_sha256,
            "published_at": self._active.get("published_at"),
            "model_profile": self._active.get("model_profile"),
            "stats": metadata.get("stats") or {},
            "validation": {
                "conforms": bool(validation.get("conforms")),
                "issue_count": int(validation.get("issue_count", 0)),
                "severity_counts": validation.get("severity_counts") or {},
            },
            "projection": {
                "rdf": True,
                "shacl": True,
                "sparql_endpoint": bool(os.environ.get("ONTOLOGY_SPARQL_ENDPOINT")),
                "status": self._active.get("projection_status"),
                "checkpoint": self._active.get("projection_checkpoint") or {},
            },
        }

    def versions(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = self._rows(connection.execute(text(
                "SELECT v.ontology_version_id::text AS ontology_version_id, "
                "v.semantic_version, v.title, v.status, v.content_sha256, "
                "v.created_at, v.published_at, "
                "(a.ontology_version_id IS NOT NULL) AS active "
                "FROM gda_ontology.ontology_version v "
                "LEFT JOIN gda_ontology.active_package a "
                "  ON a.ontology_key = v.ontology_key "
                " AND a.ontology_version_id = v.ontology_version_id "
                "WHERE v.ontology_key = :ontology_key "
                "ORDER BY v.created_at DESC"
            ), {"ontology_key": self.ontology_key}))
        return rows

    def domains(self) -> list[dict[str, Any]]:
        metadata = self._active.get("metadata") or {}
        return list(metadata.get("domain_stats") or [])

    def _version_params(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"version_id": self.version_id, **(values or {})}

    def search(
        self,
        *,
        query: str = "",
        domain_id: str | None = None,
        kinds: set[str] | None = None,
        source_system: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        clauses = ["c.ontology_version_id = CAST(:version_id AS uuid)"]
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        terms = [term.casefold() for term in query.split() if term.strip()]
        for index, term in enumerate(terms):
            key = f"term_{index}"
            clauses.append(
                "lower(coalesce(c.code, '') || ' ' || c.pref_label || ' ' || "
                "coalesce(c.alt_labels::text, '') || ' ' || coalesce(c.definition, '') || ' ' || "
                "coalesce(c.package_path, '') || ' ' || coalesce(c.ea_guid, '')) LIKE :" + key
            )
            params[key] = f"%{term}%"
        if domain_id:
            clauses.append("c.domain_id = :domain_id")
            params["domain_id"] = domain_id
        if source_system:
            clauses.append("c.source_system = :source_system")
            params["source_system"] = source_system
        statement_suffix = ""
        if kinds:
            clauses.append("c.kind IN :kinds")
            params["kinds"] = sorted(kinds)
            statement_suffix = "kinds"
        where = " AND ".join(clauses)
        folded = query.casefold().strip()
        params.update({
            "folded": folded,
            "prefix": f"{folded}%",
        })
        count_sql = text(f"SELECT count(*) FROM gda_ontology.concept c WHERE {where}")
        items_sql = text(
            "SELECT c.concept_id, c.uri, c.kind, c.code, c.pref_label, c.alt_labels, "
            "c.definition, c.domain_id, c.source_system, c.source_id, c.source_object_id, "
            "c.ea_guid, c.package_path, c.geometry_type, c.lifecycle_status, c.provenance, "
            "(SELECT count(*) FROM gda_ontology.property p "
            "  WHERE p.ontology_version_id = c.ontology_version_id "
            "    AND p.owner_concept_id = c.concept_id) AS property_count "
            f"FROM gda_ontology.concept c WHERE {where} "
            "ORDER BY CASE WHEN lower(coalesce(c.code, '')) = :folded THEN 0 "
            "              WHEN lower(c.pref_label) = :folded THEN 1 "
            "              WHEN lower(coalesce(c.code, '')) LIKE :prefix THEN 2 "
            "              WHEN lower(c.pref_label) LIKE :prefix THEN 3 ELSE 4 END, "
            "c.pref_label, c.concept_id OFFSET :offset LIMIT :limit"
        )
        if statement_suffix:
            count_sql = count_sql.bindparams(bindparam("kinds", expanding=True))
            items_sql = items_sql.bindparams(bindparam("kinds", expanding=True))
        with self.engine.connect() as connection:
            bound = self._version_params(params)
            total = int(connection.execute(count_sql, bound).scalar_one())
            items = self._rows(connection.execute(items_sql, bound))
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    def concept(self, concept_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT c.concept_id, c.uri, c.kind, c.code, c.pref_label, c.alt_labels, "
                "c.definition, c.domain_id, c.source_system, c.source_id, c.source_object_id, "
                "c.ea_guid, c.package_path, c.geometry_type, c.lifecycle_status, c.provenance, "
                "(SELECT count(*) FROM gda_ontology.property p WHERE p.ontology_version_id = c.ontology_version_id "
                "  AND p.owner_concept_id = c.concept_id) AS property_count, "
                "(SELECT count(*) FROM gda_ontology.relation r WHERE r.ontology_version_id = c.ontology_version_id "
                "  AND r.source_concept_id = c.concept_id) AS outgoing_relation_count, "
                "(SELECT count(*) FROM gda_ontology.relation r WHERE r.ontology_version_id = c.ontology_version_id "
                "  AND r.target_concept_id = c.concept_id) AS incoming_relation_count, "
                "(SELECT count(*) FROM gda_ontology.mapping m WHERE m.ontology_version_id = c.ontology_version_id "
                "  AND (m.source_concept_id = c.concept_id OR m.target_concept_id = c.concept_id)) AS mapping_count "
                "FROM gda_ontology.concept c WHERE c.ontology_version_id = CAST(:version_id AS uuid) "
                "AND c.concept_id = :concept_id"
            ), self._version_params({"concept_id": concept_id})).mappings().first()
        return _json_ready(dict(row)) if row else None

    @staticmethod
    def _property_origin(concept: dict[str, Any]) -> dict[str, Any]:
        return {
            "concept_id": concept.get("concept_id"),
            "pref_label": concept.get("pref_label"),
            "code": concept.get("code"),
            "kind": concept.get("kind"),
            "source_system": concept.get("source_system"),
        }

    def properties(
        self,
        concept_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        include_effective: bool = False,
    ) -> dict[str, Any]:
        params = self._version_params({"concept_id": concept_id, "offset": offset, "limit": limit})
        if not include_effective:
            with self.engine.connect() as connection:
                total = int(connection.execute(text(
                    "SELECT count(*) FROM gda_ontology.property WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND owner_concept_id = :concept_id"
                ), params).scalar_one())
                rows = self._rows(connection.execute(text(
                    "SELECT property_id, owner_concept_id, uri, code, pref_label, datatype, length, "
                    "precision_value, scale_value, min_count, max_count, ordinal, value_domain, "
                    "default_value, lifecycle_status, source_id, source_object_id, ea_guid, provenance "
                    "FROM gda_ontology.property WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND owner_concept_id = :concept_id ORDER BY ordinal, code, property_id "
                    "OFFSET :offset LIMIT :limit"
                ), params))
            return {"items": rows, "total": total, "offset": offset, "limit": limit}

        lineage_sql = text(
            "WITH RECURSIVE lineage(concept_id, depth, path) AS ("
            "  SELECT c.concept_id, 0, ARRAY[c.concept_id]::text[] "
            "  FROM gda_ontology.concept c "
            "  WHERE c.ontology_version_id = CAST(:version_id AS uuid) AND c.concept_id = :concept_id "
            "  UNION ALL "
            "  SELECT r.target_concept_id, lineage.depth + 1, lineage.path || r.target_concept_id "
            "  FROM lineage JOIN gda_ontology.relation r "
            "    ON r.ontology_version_id = CAST(:version_id AS uuid) "
            "   AND r.source_concept_id = lineage.concept_id "
            "   AND r.relation_type = 'subClassOf' "
            "  WHERE lineage.depth < 32 AND NOT r.target_concept_id = ANY(lineage.path)"
            "), nearest AS ("
            "  SELECT concept_id, min(depth) AS depth FROM lineage GROUP BY concept_id"
            ") "
            "SELECT c.concept_id, c.pref_label, c.code, c.kind, c.source_system, nearest.depth "
            "FROM nearest JOIN gda_ontology.concept c "
            "  ON c.ontology_version_id = CAST(:version_id AS uuid) AND c.concept_id = nearest.concept_id "
            "ORDER BY nearest.depth, c.concept_id"
        )
        with self.engine.connect() as connection:
            lineage_rows = self._rows(connection.execute(lineage_sql, params))
            if not lineage_rows:
                return {
                    "items": [], "total": 0, "offset": offset, "limit": limit,
                    "effective": True,
                    "group_counts": {"direct": 0, "inherited": 0, "mapped": 0},
                }

            lineage_ids = [row["concept_id"] for row in lineage_rows]
            property_sql = text(
                "SELECT property_id, owner_concept_id, uri, code, pref_label, datatype, length, "
                "precision_value, scale_value, min_count, max_count, ordinal, value_domain, "
                "default_value, lifecycle_status, source_id, source_object_id, ea_guid, provenance "
                "FROM gda_ontology.property WHERE ontology_version_id = CAST(:version_id AS uuid) "
                "AND owner_concept_id IN :owner_ids ORDER BY owner_concept_id, ordinal, code, property_id"
            ).bindparams(bindparam("owner_ids", expanding=True))
            lineage_properties = self._rows(connection.execute(
                property_sql,
                self._version_params({"owner_ids": lineage_ids}),
            ))

            mapping_sql = text(
                "SELECT mapping_id, source_concept_id, target_concept_id, mapping_type, "
                "mapping_status, confidence, evidence "
                "FROM gda_ontology.mapping WHERE ontology_version_id = CAST(:version_id AS uuid) "
                "AND mapping_status = 'confirmed' "
                "AND (source_concept_id IN :source_lineage_ids "
                "OR target_concept_id IN :target_lineage_ids) ORDER BY mapping_id"
            ).bindparams(
                bindparam("source_lineage_ids", expanding=True),
                bindparam("target_lineage_ids", expanding=True),
            )
            mappings = self._rows(connection.execute(
                mapping_sql,
                self._version_params({
                    "source_lineage_ids": lineage_ids,
                    "target_lineage_ids": lineage_ids,
                }),
            ))
            lineage_set = set(lineage_ids)
            mapped_ids = sorted({
                mapping["target_concept_id"]
                if mapping["source_concept_id"] in lineage_set
                else mapping["source_concept_id"]
                for mapping in mappings
            } - lineage_set)
            mapped_concepts: list[dict[str, Any]] = []
            mapped_properties: list[dict[str, Any]] = []
            if mapped_ids:
                concept_sql = text(
                    "SELECT concept_id, pref_label, code, kind, source_system "
                    "FROM gda_ontology.concept WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND concept_id IN :mapped_ids"
                ).bindparams(bindparam("mapped_ids", expanding=True))
                mapped_concepts = self._rows(connection.execute(
                    concept_sql,
                    self._version_params({"mapped_ids": mapped_ids}),
                ))
                mapped_properties = self._rows(connection.execute(
                    property_sql,
                    self._version_params({"owner_ids": mapped_ids}),
                ))

        lineage_by_id = {row["concept_id"]: row for row in lineage_rows}
        mapped_by_id = {row["concept_id"]: row for row in mapped_concepts}
        props_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for prop in lineage_properties + mapped_properties:
            props_by_owner[prop["owner_concept_id"]].append(prop)

        effective: list[dict[str, Any]] = []
        group_counts = {"direct": 0, "inherited": 0, "mapped": 0}
        seen_property_ids: set[str] = set()
        for owner_id in lineage_ids:
            owner = lineage_by_id[owner_id]
            depth = int(owner["depth"])
            origin_type = "direct" if depth == 0 else "inherited"
            for prop in props_by_owner.get(owner_id, []):
                property_id = prop["property_id"]
                if property_id in seen_property_ids:
                    continue
                seen_property_ids.add(property_id)
                effective.append(dict(
                    prop,
                    origin_type=origin_type,
                    origin_depth=depth,
                    origin_concept=self._property_origin(owner),
                ))
                group_counts[origin_type] += 1

        seen_mappings: set[str] = set()
        mappings_by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for mapping in mappings:
            if mapping["source_concept_id"] in lineage_set:
                mappings_by_anchor[mapping["source_concept_id"]].append(mapping)
            if mapping["target_concept_id"] in lineage_set:
                mappings_by_anchor[mapping["target_concept_id"]].append(mapping)
        for anchor_id in lineage_ids:
            anchor = lineage_by_id[anchor_id]
            for mapping in mappings_by_anchor.get(anchor_id, []):
                mapping_id = mapping["mapping_id"]
                if mapping_id in seen_mappings:
                    continue
                seen_mappings.add(mapping_id)
                mapped_id = (
                    mapping["target_concept_id"]
                    if mapping["source_concept_id"] == anchor_id
                    else mapping["source_concept_id"]
                )
                mapped = mapped_by_id.get(mapped_id)
                if mapped is None:
                    continue
                for prop in props_by_owner.get(mapped_id, []):
                    property_id = prop["property_id"]
                    if property_id in seen_property_ids:
                        continue
                    seen_property_ids.add(property_id)
                    effective.append(dict(
                        prop,
                        origin_type="mapped",
                        origin_depth=int(anchor["depth"]),
                        origin_concept=self._property_origin(mapped),
                        mapped_from_concept=self._property_origin(anchor),
                        mapping=mapping,
                    ))
                    group_counts["mapped"] += 1

        return {
            "items": effective[offset:offset + limit],
            "total": len(effective),
            "offset": offset,
            "limit": limit,
            "effective": True,
            "group_counts": group_counts,
        }

    def property_candidates(
        self,
        *,
        code: str = "",
        label: str = "",
        domain_id: str | None = None,
        owner_kinds: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not code and not label:
            return []
        matches = []
        params: dict[str, Any] = {"code": code.casefold(), "label": label.casefold(), "limit": limit}
        if code:
            matches.append("lower(p.code) = :code")
        if label:
            matches.append("lower(p.pref_label) = :label")
        clauses = [
            "p.ontology_version_id = CAST(:version_id AS uuid)",
            "(" + " OR ".join(matches) + ")",
        ]
        if domain_id:
            clauses.append("c.domain_id = :domain_id")
            params["domain_id"] = domain_id
        statement = text(
            "SELECT p.property_id, p.owner_concept_id, p.uri, p.code, p.pref_label, p.datatype, "
            "p.length, p.precision_value, p.scale_value, p.min_count, p.max_count, p.ordinal, "
            "p.value_domain, p.default_value, p.lifecycle_status, p.source_id, p.source_object_id, "
            "p.ea_guid, p.provenance, c.pref_label AS owner_label, c.code AS owner_code, c.kind AS owner_kind, "
            "CASE WHEN lower(p.code) = :code THEN 'exact_code' ELSE 'exact_label' END AS match_type "
            "FROM gda_ontology.property p JOIN gda_ontology.concept c "
            "ON c.ontology_version_id = p.ontology_version_id AND c.concept_id = p.owner_concept_id "
            "WHERE " + " AND ".join(clauses) + " "
            "ORDER BY CASE WHEN lower(p.code) = :code THEN 0 ELSE 1 END, c.pref_label, p.property_id "
            "LIMIT :limit"
        )
        if owner_kinds:
            clauses.append("c.kind IN :owner_kinds")
            params["owner_kinds"] = sorted(owner_kinds)
            statement = text(
                "SELECT p.property_id, p.owner_concept_id, p.uri, p.code, p.pref_label, p.datatype, "
                "p.length, p.precision_value, p.scale_value, p.min_count, p.max_count, p.ordinal, "
                "p.value_domain, p.default_value, p.lifecycle_status, p.source_id, p.source_object_id, "
                "p.ea_guid, p.provenance, c.pref_label AS owner_label, c.code AS owner_code, c.kind AS owner_kind, "
                "CASE WHEN lower(p.code) = :code THEN 'exact_code' ELSE 'exact_label' END AS match_type "
                "FROM gda_ontology.property p JOIN gda_ontology.concept c "
                "ON c.ontology_version_id = p.ontology_version_id AND c.concept_id = p.owner_concept_id "
                "WHERE " + " AND ".join(clauses) + " "
                "ORDER BY CASE WHEN lower(p.code) = :code THEN 0 ELSE 1 END, c.pref_label, p.property_id "
                "LIMIT :limit"
            ).bindparams(bindparam("owner_kinds", expanding=True))
        with self.engine.connect() as connection:
            rows = self._rows(connection.execute(statement, self._version_params(params)))
        results = []
        for row in rows:
            match_type = row.pop("match_type")
            owner_label = row.pop("owner_label")
            owner_code = row.pop("owner_code")
            row.pop("owner_kind", None)
            results.append({
                "owner_concept_id": row["owner_concept_id"],
                "owner_label": owner_label,
                "owner_code": owner_code,
                "property": row,
                "match_type": match_type,
                "status": "candidate",
                "confidence": 1.0 if match_type == "exact_code" else 0.95,
            })
        return results

    def relations(self, concept_id: str, *, direction: str = "both", limit: int = 200) -> dict[str, Any]:
        branches = []
        count_branches = []
        relation_columns = (
            "r.relation_id, r.relation_type, r.source_concept_id, r.target_concept_id, "
            "r.pref_label, r.direction, r.is_transitive AS transitive, "
            "r.is_symmetric AS symmetric, r.source_id, r.source_object_id, r.ea_guid, "
            "r.lifecycle_status, r.provenance"
        )
        if direction in {"both", "out"}:
            branches.append(
                "SELECT " + relation_columns + ", 'out' AS traversal_direction, o.concept_id AS other_id, "
                "o.pref_label AS other_label, o.code AS other_code, o.kind AS other_kind "
                "FROM gda_ontology.relation r JOIN gda_ontology.concept o "
                "ON o.ontology_version_id = r.ontology_version_id AND o.concept_id = r.target_concept_id "
                "WHERE r.ontology_version_id = CAST(:version_id AS uuid) AND r.source_concept_id = :concept_id"
            )
            count_branches.append("source_concept_id = :concept_id")
        if direction in {"both", "in"}:
            branches.append(
                "SELECT " + relation_columns + ", 'in' AS traversal_direction, o.concept_id AS other_id, "
                "o.pref_label AS other_label, o.code AS other_code, o.kind AS other_kind "
                "FROM gda_ontology.relation r JOIN gda_ontology.concept o "
                "ON o.ontology_version_id = r.ontology_version_id AND o.concept_id = r.source_concept_id "
                "WHERE r.ontology_version_id = CAST(:version_id AS uuid) AND r.target_concept_id = :concept_id"
            )
            count_branches.append("target_concept_id = :concept_id")
        params = self._version_params({"concept_id": concept_id, "limit": limit})
        with self.engine.connect() as connection:
            total = int(connection.execute(text(
                "SELECT count(*) FROM gda_ontology.relation WHERE ontology_version_id = CAST(:version_id AS uuid) "
                "AND (" + " OR ".join(count_branches) + ")"
            ), params).scalar_one())
            rows = self._rows(connection.execute(text(" UNION ALL ".join(branches) + " LIMIT :limit"), params))
        for row in rows:
            row["other_concept"] = {
                "concept_id": row.pop("other_id"),
                "pref_label": row.pop("other_label"),
                "code": row.pop("other_code"),
                "kind": row.pop("other_kind"),
            }
            row.pop("ontology_version_id", None)
        return {"items": rows, "total": total, "limit": limit}

    def mappings(
        self,
        *,
        status: str | None = None,
        domain_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        clauses = ["m.ontology_version_id = CAST(:version_id AS uuid)"]
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            clauses.append("m.mapping_status = :status")
            params["status"] = status
        if domain_id:
            clauses.append("(s.domain_id = :domain_id OR t.domain_id = :domain_id)")
            params["domain_id"] = domain_id
        where = " AND ".join(clauses)
        base = (
            " FROM gda_ontology.mapping m "
            "JOIN gda_ontology.concept s ON s.ontology_version_id = m.ontology_version_id "
            " AND s.concept_id = m.source_concept_id "
            "JOIN gda_ontology.concept t ON t.ontology_version_id = m.ontology_version_id "
            " AND t.concept_id = m.target_concept_id WHERE " + where
        )
        bound = self._version_params(params)
        with self.engine.connect() as connection:
            total = int(connection.execute(text("SELECT count(*)" + base), bound).scalar_one())
            rows = self._rows(connection.execute(text(
                "SELECT m.*, s.code AS source_code, s.pref_label AS source_label, s.kind AS source_kind, "
                "t.code AS target_code, t.pref_label AS target_label, t.kind AS target_kind" + base +
                " ORDER BY m.mapping_status, m.mapping_id OFFSET :offset LIMIT :limit"
            ), bound))
        for row in rows:
            row.pop("ontology_version_id", None)
            row["source_concept"] = {
                "concept_id": row["source_concept_id"],
                "code": row.pop("source_code"),
                "pref_label": row.pop("source_label"),
                "kind": row.pop("source_kind"),
            }
            row["target_concept"] = {
                "concept_id": row["target_concept_id"],
                "code": row.pop("target_code"),
                "pref_label": row.pop("target_label"),
                "kind": row.pop("target_kind"),
            }
        return {"items": rows, "total": total, "offset": offset, "limit": limit}

    @staticmethod
    def _kind_lane(kind: str) -> int:
        return {
            "Domain": 0,
            "DomainClass": 1,
            "InformationClass": 1,
            "ObservationClass": 2,
            "StateClass": 2,
            "RoleClass": 2,
            "ProcessClass": 3,
            "ReferenceScheme": 3,
            "ReferenceConcept": 4,
            "SchemaArtifact": 4,
            "StandardDocument": 1,
            "Package": 1,
            "FeatureType": 2,
            "ObjectType": 2,
            "ValueDomain": 2,
            "DatasetSchema": 3,
            "ActionType": 3,
        }.get(kind, 4)

    def _graph_nodes(self, concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lane_counts: dict[int, int] = defaultdict(int)
        nodes = []
        for row in concepts:
            kind = row.get("kind", "Concept")
            lane = self._kind_lane(kind)
            lane_index = lane_counts[lane]
            lane_counts[lane] += 1
            nodes.append({
                "id": row["concept_id"],
                "type": "ontologyConcept",
                "position": {
                    "x": lane * 900 + (lane_index % 3) * 280,
                    "y": (lane_index // 3) * 116,
                },
                "data": {
                    "label": row.get("pref_label"),
                    "code": row.get("code"),
                    "kind": kind,
                    "sourceSystem": row.get("source_system"),
                    "propertyCount": int(row.get("property_count") or 0),
                    "geometryType": row.get("geometry_type"),
                    "lifecycleStatus": row.get("lifecycle_status"),
                },
            })
        return nodes

    def graph(
        self,
        *,
        root_id: str | None = None,
        domain_id: str | None = None,
        depth: int = 1,
        limit: int = 250,
        include_mappings: bool = True,
    ) -> dict[str, Any]:
        selected: list[str] = []
        selected_set: set[str] = set()
        relation_rows: dict[str, dict[str, Any]] = {}
        truncated = False

        def add(concept_id: str) -> bool:
            nonlocal truncated
            if concept_id in selected_set:
                return False
            if len(selected) >= limit:
                truncated = True
                return False
            selected.append(concept_id)
            selected_set.add(concept_id)
            return True

        with self.engine.connect() as connection:
            if root_id:
                root_kind = connection.execute(text(
                    "SELECT kind FROM gda_ontology.concept "
                    "WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND concept_id = :root_id"
                ), self._version_params({"root_id": root_id})).scalar_one_or_none()
                if root_kind:
                    add(root_id)
                semantic_root = root_kind in DOMAIN_MODEL_KINDS | {"Domain"}
                queue = deque([(root_id, 0)]) if root_kind else deque()
                while queue and len(selected) < limit:
                    current, level = queue.popleft()
                    if level >= depth:
                        continue
                    statement = text(
                        "SELECT r.relation_id, r.relation_type, r.source_concept_id, "
                        "r.target_concept_id, r.pref_label, r.lifecycle_status, "
                        "CASE WHEN r.source_concept_id = :current THEN target.kind "
                        "ELSE source.kind END AS other_kind "
                        "FROM gda_ontology.relation r "
                        "JOIN gda_ontology.concept source "
                        "ON source.ontology_version_id = r.ontology_version_id "
                        "AND source.concept_id = r.source_concept_id "
                        "JOIN gda_ontology.concept target "
                        "ON target.ontology_version_id = r.ontology_version_id "
                        "AND target.concept_id = r.target_concept_id "
                        "WHERE r.ontology_version_id = CAST(:version_id AS uuid) "
                        "AND (r.source_concept_id = :current OR r.target_concept_id = :current) "
                        "ORDER BY r.relation_id LIMIT :edge_budget"
                    )
                    rows = self._rows(connection.execute(statement, self._version_params({
                        "current": current,
                        "edge_budget": max(limit * 4, 100),
                    })))
                    for relation in rows:
                        other_kind = relation.pop("other_kind")
                        if (
                            semantic_root
                            and other_kind not in DOMAIN_MODEL_KINDS | {"Domain"}
                        ):
                            continue
                        relation_rows[relation["relation_id"]] = relation
                        other = (
                            relation["target_concept_id"]
                            if relation["source_concept_id"] == current
                            else relation["source_concept_id"]
                        )
                        if add(other):
                            queue.append((other, level + 1))
            elif domain_id:
                domain_concept_id = connection.execute(text(
                    "SELECT concept_id FROM gda_ontology.concept "
                    "WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND domain_id = :domain_id AND kind = 'Domain' "
                    "ORDER BY concept_id LIMIT 1"
                ), self._version_params({"domain_id": domain_id})).scalar_one_or_none()
                if domain_concept_id:
                    add(domain_concept_id)

                class_statement = text(
                    "SELECT concept_id FROM gda_ontology.concept "
                    "WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND domain_id = :domain_id AND kind IN :domain_kinds "
                    "ORDER BY kind, pref_label, concept_id LIMIT :limit"
                ).bindparams(bindparam("domain_kinds", expanding=True))
                class_ids = list(connection.execute(
                    class_statement,
                    self._version_params({
                        "domain_id": domain_id,
                        "domain_kinds": tuple(sorted(DOMAIN_MODEL_KINDS)),
                        "limit": limit,
                    }),
                ).scalars())
                for concept_id in class_ids:
                    add(concept_id)

                if class_ids and len(selected) < limit:
                    ancestor_statement = text(
                        "WITH RECURSIVE ancestors(concept_id) AS ("
                        "SELECT r.target_concept_id FROM gda_ontology.relation r "
                        "WHERE r.ontology_version_id = CAST(:version_id AS uuid) "
                        "AND r.relation_type = 'subClassOf' "
                        "AND r.source_concept_id IN :seed_ids "
                        "UNION "
                        "SELECT r.target_concept_id FROM gda_ontology.relation r "
                        "JOIN ancestors a ON a.concept_id = r.source_concept_id "
                        "WHERE r.ontology_version_id = CAST(:version_id AS uuid) "
                        "AND r.relation_type = 'subClassOf'"
                        ") SELECT concept_id FROM ancestors ORDER BY concept_id "
                        "LIMIT :ancestor_limit"
                    ).bindparams(bindparam("seed_ids", expanding=True))
                    ancestor_ids = connection.execute(
                        ancestor_statement,
                        self._version_params({
                            "seed_ids": tuple(class_ids),
                            "ancestor_limit": limit - len(selected),
                        }),
                    ).scalars()
                    for concept_id in ancestor_ids:
                        add(concept_id)
            else:
                class_statement = text(
                    "SELECT concept_id FROM gda_ontology.concept "
                    "WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND kind IN :domain_kinds "
                    "ORDER BY kind, pref_label, concept_id LIMIT :limit"
                ).bindparams(bindparam("domain_kinds", expanding=True))
                ids = connection.execute(
                    class_statement,
                    self._version_params({
                        "domain_kinds": tuple(sorted(DOMAIN_MODEL_KINDS)),
                        "limit": limit,
                    }),
                ).scalars()
                for concept_id in ids:
                    add(concept_id)

            if not selected:
                return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0,
                        "truncated": False, "limit": limit, "depth": depth}

            concept_statement = text(
                "SELECT c.concept_id, c.code, c.pref_label, c.kind, c.source_system, c.geometry_type, "
                "c.lifecycle_status, (SELECT count(*) FROM gda_ontology.property p "
                "WHERE p.ontology_version_id = c.ontology_version_id "
                "AND p.owner_concept_id = c.concept_id) AS property_count "
                "FROM gda_ontology.concept c WHERE c.ontology_version_id = CAST(:version_id AS uuid) "
                "AND c.concept_id IN :selected"
            ).bindparams(bindparam("selected", expanding=True))
            concept_map = {
                row["concept_id"]: row for row in self._rows(connection.execute(
                    concept_statement, self._version_params({"selected": selected})
                ))
            }
            concepts = [concept_map[concept_id] for concept_id in selected if concept_id in concept_map]

            edge_statement = text(
                "SELECT relation_id, relation_type, source_concept_id, target_concept_id, pref_label "
                "FROM gda_ontology.relation WHERE ontology_version_id = CAST(:version_id AS uuid) "
                "AND source_concept_id IN :selected AND target_concept_id IN :selected"
            ).bindparams(bindparam("selected", expanding=True))
            for row in self._rows(connection.execute(
                edge_statement, self._version_params({"selected": selected})
            )):
                relation_rows[row["relation_id"]] = row

            if include_mappings:
                mapping_statement = text(
                    "SELECT mapping_id AS relation_id, mapping_type AS relation_type, "
                    "source_concept_id, target_concept_id, mapping_status, mapping_type AS pref_label "
                    "FROM gda_ontology.mapping WHERE ontology_version_id = CAST(:version_id AS uuid) "
                    "AND source_concept_id IN :selected AND target_concept_id IN :selected"
                ).bindparams(bindparam("selected", expanding=True))
                for row in self._rows(connection.execute(
                    mapping_statement, self._version_params({"selected": selected})
                )):
                    relation_rows[row["relation_id"]] = row

        edges = [{
            "id": row["relation_id"],
            "source": row["source_concept_id"],
            "target": row["target_concept_id"],
            "type": "ontologyRelation",
            "label": row.get("pref_label") or row.get("relation_type"),
            "data": {
                "relationType": row.get("relation_type"),
                "mappingStatus": row.get("mapping_status"),
            },
        } for row in sorted(relation_rows.values(), key=lambda item: item["relation_id"])
           if row["source_concept_id"] in selected_set and row["target_concept_id"] in selected_set]
        nodes = self._graph_nodes(concepts)
        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "truncated": truncated or len(selected) >= limit,
            "limit": limit,
            "depth": depth,
        }

    def validation(self) -> dict[str, Any]:
        with self.engine.connect() as connection:
            report = connection.execute(text(
                "SELECT report FROM gda_ontology.validation_result "
                "WHERE ontology_version_id = CAST(:version_id AS uuid) "
                "ORDER BY validated_at DESC LIMIT 1"
            ), self._version_params()).scalar()
        normalized = _json_ready(report or {})
        # Release reports keep the gate report under ``validation`` alongside
        # competency and semantic-quality evidence artifacts.
        if isinstance(normalized, dict) and isinstance(normalized.get("validation"), dict):
            return normalized["validation"]
        return normalized or {"conforms": False, "issue_count": 0}
