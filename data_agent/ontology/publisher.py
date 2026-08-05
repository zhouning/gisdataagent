"""Transactional publisher from an immutable package to PostgreSQL authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from ..db_engine import get_engine
from .package_reader import OntologyPackageReader


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _batched(rows: list[dict[str, Any]], size: int = 1000):
    for index in range(0, len(rows), size):
        yield rows[index:index + size]


def _records(reader: OntologyPackageReader, filename: str) -> list[dict[str, Any]]:
    return list(reader._read_jsonl(reader.package_dir / filename))


def _columns(row: dict[str, Any], *names: str) -> dict[str, Any]:
    """Materialize omitted JSON nulls so SQLAlchemy executemany is uniform."""
    return {name: row.get(name) for name in names}


def publish_package(
    package_dir: str,
    *,
    actor: str,
    package_uri: str | None = None,
    activate: bool = True,
    engine: Any | None = None,
) -> dict[str, Any]:
    """Publish one validated package atomically; published content is immutable."""
    reader = OntologyPackageReader(package_dir, verify=True)
    manifest = reader.manifest
    if not manifest.validation_summary.get("conforms"):
        raise ValueError("only conforming ontology packages can be published")
    if not actor.strip():
        raise ValueError("publisher actor is required")
    authority_engine = engine or get_engine()
    if authority_engine is None:
        raise RuntimeError("GIS Data Agent PostgreSQL is not configured")

    sources = _records(reader, "sources.jsonl.gz")
    concepts = _records(reader, "concepts.jsonl.gz")
    properties = _records(reader, "properties.jsonl.gz")
    relations = _records(reader, "relations.jsonl.gz")
    mappings = _records(reader, "mappings.jsonl.gz")
    validation = reader.validation()
    version_id = manifest.ontology_version_id
    published_at = datetime.now(UTC)

    with authority_engine.begin() as connection:
        existing = connection.execute(text(
            "SELECT content_sha256, status FROM gda_ontology.ontology_version "
            "WHERE ontology_version_id = CAST(:version_id AS uuid)"
        ), {"version_id": version_id}).mappings().first()
        if existing:
            if existing["content_sha256"] != manifest.content_sha256:
                raise RuntimeError("ontology version identity exists with a different content hash")
            if activate:
                connection.execute(text(
                    "INSERT INTO gda_ontology.active_package "
                    "(ontology_key, ontology_version_id, package_id, activated_by) "
                    "VALUES (:ontology_key, CAST(:version_id AS uuid), :package_id, :actor) "
                    "ON CONFLICT (ontology_key) DO UPDATE SET "
                    "ontology_version_id = EXCLUDED.ontology_version_id, "
                    "package_id = EXCLUDED.package_id, activated_by = EXCLUDED.activated_by, "
                    "activated_at = now()"
                ), {
                    "ontology_key": manifest.ontology_key,
                    "version_id": version_id,
                    "package_id": manifest.package_id,
                    "actor": actor,
                })
            return {"status": "already_published", "version_id": version_id, "active": activate}

        connection.execute(text(
            "INSERT INTO gda_ontology.ontology_version ("
            "ontology_version_id, ontology_key, semantic_version, status, title, description, "
            "namespace_uri, source_fingerprint, content_sha256, model_profile, metadata, created_by"
            ") VALUES (CAST(:version_id AS uuid), :ontology_key, :semantic_version, 'draft', "
            ":title, :description, :namespace_uri, :source_fingerprint, :content_sha256, "
            ":model_profile, CAST(:metadata AS jsonb), :actor)"
        ), {
            "version_id": version_id,
            "ontology_key": manifest.ontology_key,
            "semantic_version": manifest.semantic_version,
            "title": manifest.title,
            "description": manifest.description,
            "namespace_uri": manifest.namespace_uri,
            "source_fingerprint": manifest.source_fingerprint,
            "content_sha256": manifest.content_sha256,
            "model_profile": manifest.model_profile,
            "metadata": _json({
                "stats": manifest.stats,
                "domain_stats": manifest.domain_stats,
                "vocabularies": manifest.vocabularies,
                "compatibility": manifest.compatibility,
            }),
            "actor": actor,
        })

        source_rows = [{
            "version_id": version_id,
            **_columns(
                row, "source_id", "source_kind", "title", "locator",
                "source_version", "sha256",
            ),
            "metadata": _json(row.get("metadata") or {}),
        } for row in sources]
        connection.execute(text(
            "INSERT INTO gda_ontology.ontology_source ("
            "ontology_version_id, source_id, source_kind, title, locator, source_version, sha256, metadata"
            ") VALUES (CAST(:version_id AS uuid), :source_id, :source_kind, :title, :locator, "
            ":source_version, :sha256, CAST(:metadata AS jsonb))"
        ), source_rows)

        concept_sql = text(
            "INSERT INTO gda_ontology.concept ("
            "ontology_version_id, concept_id, uri, kind, code, pref_label, alt_labels, definition, "
            "domain_id, source_system, source_id, source_object_id, ea_guid, package_path, "
            "geometry_type, lifecycle_status, provenance) VALUES ("
            "CAST(:version_id AS uuid), :concept_id, :uri, :kind, :code, :pref_label, "
            "CAST(:alt_labels AS jsonb), :definition, :domain_id, :source_system, :source_id, "
            ":source_object_id, :ea_guid, :package_path, :geometry_type, :lifecycle_status, "
            "CAST(:provenance AS jsonb))"
        )
        concept_rows = [{
            "version_id": version_id,
            **_columns(
                row, "concept_id", "uri", "kind", "code", "pref_label",
                "definition", "domain_id", "source_system", "source_id",
                "source_object_id", "ea_guid", "package_path", "geometry_type",
                "lifecycle_status",
            ),
            "alt_labels": _json(row.get("alt_labels") or []),
            "provenance": _json(row.get("provenance") or {}),
        } for row in concepts]
        for batch in _batched(concept_rows):
            connection.execute(concept_sql, batch)

        property_sql = text(
            "INSERT INTO gda_ontology.property ("
            "ontology_version_id, property_id, owner_concept_id, uri, code, pref_label, datatype, "
            "length, precision_value, scale_value, min_count, max_count, ordinal, value_domain, "
            "default_value, lifecycle_status, source_id, source_object_id, ea_guid, provenance) VALUES ("
            "CAST(:version_id AS uuid), :property_id, :owner_concept_id, :uri, :code, :pref_label, "
            ":datatype, :length, :precision_value, :scale_value, :min_count, :max_count, :ordinal, "
            "CAST(:value_domain AS jsonb), :default_value, :lifecycle_status, :source_id, "
            ":source_object_id, :ea_guid, CAST(:provenance AS jsonb))"
        )
        property_rows = [{
            "version_id": version_id,
            **_columns(
                row, "property_id", "owner_concept_id", "uri", "code",
                "pref_label", "datatype", "length", "precision_value",
                "scale_value", "min_count", "max_count", "ordinal",
                "default_value", "lifecycle_status", "source_id",
                "source_object_id", "ea_guid",
            ),
            "value_domain": _json(row.get("value_domain")) if row.get("value_domain") is not None else "null",
            "provenance": _json(row.get("provenance") or {}),
        } for row in properties]
        for batch in _batched(property_rows):
            connection.execute(property_sql, batch)

        relation_sql = text(
            "INSERT INTO gda_ontology.relation ("
            "ontology_version_id, relation_id, relation_type, source_concept_id, target_concept_id, "
            "pref_label, direction, is_transitive, is_symmetric, source_id, source_object_id, ea_guid, "
            "lifecycle_status, provenance) VALUES (CAST(:version_id AS uuid), :relation_id, "
            ":relation_type, :source_concept_id, :target_concept_id, :pref_label, :direction, "
            ":transitive, :symmetric, :source_id, :source_object_id, :ea_guid, :lifecycle_status, "
            "CAST(:provenance AS jsonb))"
        )
        relation_rows = [{
            "version_id": version_id,
            **_columns(
                row, "relation_id", "relation_type", "source_concept_id",
                "target_concept_id", "pref_label", "direction", "transitive",
                "symmetric", "source_id", "source_object_id", "ea_guid",
                "lifecycle_status",
            ),
            "provenance": _json(row.get("provenance") or {}),
        } for row in relations]
        for batch in _batched(relation_rows):
            connection.execute(relation_sql, batch)

        mapping_sql = text(
            "INSERT INTO gda_ontology.mapping ("
            "ontology_version_id, mapping_id, source_concept_id, target_concept_id, mapping_type, "
            "mapping_status, confidence, evidence, reviewed_by, reviewed_at) VALUES ("
            "CAST(:version_id AS uuid), :mapping_id, :source_concept_id, :target_concept_id, "
            ":mapping_type, :mapping_status, :confidence, CAST(:evidence AS jsonb), :reviewed_by, :reviewed_at)"
        )
        mapping_rows = [{
            "version_id": version_id,
            **_columns(
                row, "mapping_id", "source_concept_id", "target_concept_id",
                "mapping_type", "mapping_status", "confidence", "reviewed_by",
                "reviewed_at",
            ),
            "evidence": _json(row.get("evidence") or {}),
        } for row in mappings]
        for batch in _batched(mapping_rows):
            connection.execute(mapping_sql, batch)

        report_sha = manifest.artifacts["validation"].sha256
        connection.execute(text(
            "INSERT INTO gda_ontology.validation_result ("
            "ontology_version_id, validator_id, validation_kind, conforms, severity, issue_count, "
            "report, report_sha256) VALUES (CAST(:version_id AS uuid), :validator_id, "
            ":validation_kind, :conforms, :severity, :issue_count, CAST(:report AS jsonb), :report_sha256)"
        ), {
            "version_id": version_id,
            "validator_id": "ontology-package-release-gate-v1",
            "validation_kind": "structural+shacl+provenance",
            "conforms": bool(validation.get("conforms")),
            "severity": "warning" if validation.get("issue_count") else "info",
            "issue_count": int(validation.get("issue_count", 0)),
            "report": _json(validation),
            "report_sha256": report_sha,
        })
        connection.execute(text(
            "INSERT INTO gda_ontology.ontology_package ("
            "ontology_version_id, package_id, package_uri, package_sha256, rdf_sha256, "
            "shacl_sha256, jsonld_context_sha256, projection_status) VALUES ("
            "CAST(:version_id AS uuid), :package_id, :package_uri, :package_sha256, :rdf_sha256, "
            ":shacl_sha256, :context_sha256, 'pending')"
        ), {
            "version_id": version_id,
            "package_id": manifest.package_id,
            "package_uri": package_uri or reader.package_dir.as_uri(),
            "package_sha256": manifest.content_sha256,
            "rdf_sha256": manifest.artifacts["rdf"].sha256,
            "shacl_sha256": manifest.artifacts["shacl"].sha256,
            "context_sha256": manifest.artifacts["jsonld_context"].sha256,
        })
        connection.execute(text(
            "UPDATE gda_ontology.ontology_version SET status = 'published', "
            "published_by = :actor, published_at = :published_at "
            "WHERE ontology_version_id = CAST(:version_id AS uuid)"
        ), {"actor": actor, "published_at": published_at, "version_id": version_id})
        if activate:
            connection.execute(text(
                "INSERT INTO gda_ontology.active_package "
                "(ontology_key, ontology_version_id, package_id, activated_by) "
                "VALUES (:ontology_key, CAST(:version_id AS uuid), :package_id, :actor) "
                "ON CONFLICT (ontology_key) DO UPDATE SET "
                "ontology_version_id = EXCLUDED.ontology_version_id, package_id = EXCLUDED.package_id, "
                "activated_by = EXCLUDED.activated_by, activated_at = now()"
            ), {
                "ontology_key": manifest.ontology_key,
                "version_id": version_id,
                "package_id": manifest.package_id,
                "actor": actor,
            })
    return {
        "status": "published",
        "version_id": version_id,
        "semantic_version": manifest.semantic_version,
        "package_id": manifest.package_id,
        "content_sha256": manifest.content_sha256,
        "active": activate,
        "stats": manifest.stats,
    }
