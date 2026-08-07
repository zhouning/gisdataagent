"""Bounded semantic query gateway used by APIs and agent tools."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from ..db_engine import get_engine
from .authority_reader import OntologyAuthorityUnavailable, PostgresOntologyReader
from .package_reader import OntologyPackageReader

logger = logging.getLogger("data_agent.ontology.service")


class OntologyService:
    """Runtime facade with PostgreSQL authority and hash-verified fallback."""

    MAX_SEARCH_LIMIT = 200
    MAX_PROPERTY_LIMIT = 500
    MAX_RELATION_LIMIT = 500
    MAX_GRAPH_NODES = 500
    MAX_GRAPH_DEPTH = 3

    def __init__(self, package_dir: str | Path | None = None):
        backend = os.environ.get("ONTOLOGY_RUNTIME_BACKEND", "auto").strip().casefold()
        if backend not in {"auto", "postgresql", "package"}:
            raise ValueError("ONTOLOGY_RUNTIME_BACKEND must be auto, postgresql, or package")

        self.package_reader: OntologyPackageReader | None = None
        package_error: Exception | None = None
        try:
            self.package_reader = OntologyPackageReader(package_dir)
        except Exception as exc:
            package_error = exc

        authority_error: Exception | None = None
        self.reader: OntologyPackageReader | PostgresOntologyReader
        if backend in {"auto", "postgresql"}:
            try:
                engine = get_engine(readonly=True)
                if engine is None:
                    raise OntologyAuthorityUnavailable(
                        "GIS Data Agent PostgreSQL is not configured"
                    )
                self.reader = PostgresOntologyReader(engine)
            except Exception as exc:
                authority_error = exc
                if backend == "postgresql":
                    raise
                logger.info(
                    "ontology PostgreSQL authority unavailable; using package fallback: %s", exc
                )
                if self.package_reader is None:
                    raise RuntimeError(
                        "ontology PostgreSQL authority and immutable package are unavailable"
                    ) from exc
                self.reader = self.package_reader
        else:
            if self.package_reader is None:
                assert package_error is not None
                raise package_error
            self.reader = self.package_reader

        self._authority_error = str(authority_error) if authority_error else None
        self._package_error = str(package_error) if package_error else None
        self._query_engine = None

    def status(self) -> dict[str, Any]:
        payload = self.reader.status()
        sparql_endpoint = bool(os.environ.get("ONTOLOGY_SPARQL_ENDPOINT"))
        projection = payload.setdefault("projection", {})
        checkpoint_status = projection.get("status")
        projection.update(
            {
                "sparql_endpoint": sparql_endpoint,
                "store": "apache_jena_fuseki_tdb2" if sparql_endpoint else None,
                "access_mode": "read_only_allowlisted_templates",
            }
        )
        if sparql_endpoint:
            from .sparql_adapter import SparqlReadAdapter

            stats = payload.get("stats") or {}
            expected = int(stats.get("rdf_triple_count") or 0) or None
            projection["checkpoint_status"] = checkpoint_status
            projection.update(SparqlReadAdapter().probe(expected_triples=expected))
        else:
            projection["status"] = "not_configured"
            projection["live"] = False
        payload["authority_preferred"] = True
        payload["fallback"] = {
            "available": self.package_reader is not None,
            "hash_matches_active": bool(
                self.package_reader
                and self.package_reader.manifest.content_sha256
                == self.reader.manifest.content_sha256
            ),
        }
        if self._authority_error:
            payload["authority_state"] = "unavailable"
        else:
            payload["authority_state"] = "active"
        return payload

    def execute_query(self, plan: Any) -> dict[str, Any]:
        """Execute a typed ontology query plan through the semantic gateway."""
        if self._query_engine is None:
            from .query_engine import OntologyQueryEngine

            self._query_engine = OntologyQueryEngine(self)
        return self._query_engine.execute(plan)

    def versions(self) -> list[dict[str, Any]]:
        return self.reader.versions()

    def domains(self) -> list[dict[str, Any]]:
        return self.reader.domains()

    def search_concepts(self, **filters: Any) -> dict[str, Any]:
        filters["limit"] = min(max(int(filters.get("limit", 50)), 1), self.MAX_SEARCH_LIMIT)
        filters["offset"] = max(int(filters.get("offset", 0)), 0)
        kinds = filters.get("kinds")
        if kinds and not isinstance(kinds, set):
            filters["kinds"] = set(kinds)
        return self.reader.search(**filters)

    def get_concept(self, concept_id: str) -> dict[str, Any] | None:
        return self.reader.concept(concept_id)

    def get_properties(
        self,
        concept_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        include_effective: bool = False,
    ) -> dict[str, Any]:
        return self.reader.properties(
            concept_id,
            offset=max(offset, 0),
            limit=min(max(limit, 1), self.MAX_PROPERTY_LIMIT),
            include_effective=include_effective,
        )

    def get_relations(
        self, concept_id: str, *, direction: str = "both", limit: int = 200
    ) -> dict[str, Any]:
        if direction not in {"both", "in", "out"}:
            raise ValueError("direction must be one of both, in, out")
        return self.reader.relations(
            concept_id,
            direction=direction,
            limit=min(max(limit, 1), self.MAX_RELATION_LIMIT),
        )

    def get_mappings(self, **filters: Any) -> dict[str, Any]:
        filters["limit"] = min(max(int(filters.get("limit", 100)), 1), self.MAX_SEARCH_LIMIT)
        filters["offset"] = max(int(filters.get("offset", 0)), 0)
        return self.reader.mappings(**filters)

    def get_graph(self, **filters: Any) -> dict[str, Any]:
        filters["limit"] = min(max(int(filters.get("limit", 250)), 1), self.MAX_GRAPH_NODES)
        filters["depth"] = min(max(int(filters.get("depth", 1)), 0), self.MAX_GRAPH_DEPTH)
        return self.reader.graph(**filters)

    def validation(self) -> dict[str, Any]:
        return self.reader.validation()

    def export_path(self, export_format: str) -> tuple[Path, str, str]:
        mapping = {
            "turtle": ("rdf", "text/turtle", "natural-resource-one-map.ttl.gz"),
            "shacl": ("shacl", "text/turtle", "natural-resource-one-map-shapes.ttl"),
            "jsonld-context": ("jsonld_context", "application/ld+json", "context.jsonld"),
            "manifest": ("manifest", "application/json", "manifest.json"),
        }
        if export_format not in mapping:
            raise ValueError("unsupported ontology export format")
        if self.package_reader is None:
            raise FileNotFoundError("immutable ontology export package is unavailable")
        if self.package_reader.manifest.content_sha256 != self.reader.manifest.content_sha256:
            raise RuntimeError("immutable export package does not match the active ontology hash")
        key, media_type, filename = mapping[export_format]
        if key == "manifest":
            path = self.package_reader.package_dir / "manifest.json"
        else:
            path = self.package_reader.artifact_path(key)
        return path, media_type, filename

    def align_fields(
        self, fields: list[dict[str, Any]], *, domain_id: str | None = None
    ) -> dict[str, Any]:
        """Deterministically align a bounded schema without promoting candidates."""
        if len(fields) > 500:
            raise ValueError("field alignment is limited to 500 fields")
        results = []
        for field in fields:
            code = str(field.get("code") or field.get("name") or "").strip()
            label = str(field.get("label") or "").strip()
            field_candidates = self.reader.property_candidates(
                code=code,
                label=label,
                domain_id=domain_id,
                owner_kinds={"FeatureType", "DatasetSchema", "SchemaArtifact"},
                limit=20,
            )
            if not field_candidates:
                resolution_status = "unresolved"
            elif len(field_candidates) == 1:
                resolution_status = "candidate"
            else:
                resolution_status = "ambiguous"
            results.append(
                {
                    "input": field,
                    "candidates": field_candidates,
                    "resolution_status": resolution_status,
                }
            )
        return {
            "ontology_version": self.reader.manifest.semantic_version,
            "content_sha256": self.reader.manifest.content_sha256,
            "results": results,
            "promotion_allowed": False,
        }


_service: OntologyService | None = None
_service_lock = threading.Lock()


def get_ontology_service(*, refresh: bool = False) -> OntologyService:
    global _service
    if _service is None or refresh:
        with _service_lock:
            if _service is None or refresh:
                _service = OntologyService(os.environ.get("ONTOLOGY_PACKAGE_DIR") or None)
    return _service
