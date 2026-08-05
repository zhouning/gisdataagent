"""Read-only, template-only Apache Jena Fuseki adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from .contracts import BASE_URI


class SparqlProjectionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SparqlProjectionResult:
    template_id: str
    rows: list[dict[str, Any]]
    endpoint: str


class SparqlReadAdapter:
    """Execute only pre-registered SELECT templates with strict budgets."""

    MAX_ROWS = 100
    MAX_RESPONSE_BYTES = 2_000_000

    PREFIXES = """
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX gda: <https://ontology.gis-data-agent.local/natural-resource/one-map/>
PREFIX ann: <https://ontology.gis-data-agent.local/natural-resource/one-map/annotation/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

    def __init__(self, endpoint: str | None = None):
        self.endpoint = (endpoint or os.environ.get("ONTOLOGY_SPARQL_ENDPOINT") or "").strip()
        self.timeout_seconds = min(
            max(float(os.environ.get("ONTOLOGY_SPARQL_TIMEOUT_SECONDS", "5")), 0.5),
            30.0,
        )
        self.username = os.environ.get("ONTOLOGY_SPARQL_USERNAME") or None
        self.password = os.environ.get("ONTOLOGY_SPARQL_PASSWORD") or None

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    @staticmethod
    def _concept_uri(uri: str) -> str:
        uri = str(uri).strip()
        if not uri.startswith(BASE_URI) or any(char in uri for char in '<>"{}|\\^`'):
            raise ValueError("concept URI is outside the governed ontology namespace")
        return f"<{uri}>"

    def select(
        self,
        template_id: str,
        *,
        concept_uri: str,
        limit: int = 50,
    ) -> SparqlProjectionResult:
        if not self.configured:
            raise SparqlProjectionUnavailable("ONTOLOGY_SPARQL_ENDPOINT is not configured")
        bounded_limit = min(max(int(limit), 1), self.MAX_ROWS)
        concept = self._concept_uri(concept_uri)
        query = self._render(template_id, concept=concept, limit=bounded_limit)
        payload = self._execute_select(query)

        bindings = ((payload.get("results") or {}).get("bindings") or [])[:bounded_limit]
        rows = [
            {
                key: value.get("value")
                for key, value in binding.items()
                if isinstance(value, dict) and "value" in value
            }
            for binding in bindings
            if isinstance(binding, dict)
        ]
        return SparqlProjectionResult(template_id, rows, self.endpoint)

    def probe(self, *, expected_triples: int | None = None) -> dict[str, Any]:
        """Verify that the configured read projection is queryable and complete."""
        if not self.configured:
            return {"status": "not_configured", "live": False}
        try:
            payload = self._execute_select("SELECT (COUNT(*) AS ?triples) WHERE { ?s ?p ?o }")
            bindings = (payload.get("results") or {}).get("bindings") or []
            count = int(bindings[0]["triples"]["value"])
        except (SparqlProjectionUnavailable, KeyError, IndexError, TypeError, ValueError) as exc:
            return {"status": "unavailable", "live": False, "error": str(exc)}

        matches = expected_triples is None or count == expected_triples
        return {
            "status": "ready" if matches else "mismatch",
            "live": True,
            "triple_count": count,
            "expected_triple_count": expected_triples,
            "count_matches_package": matches,
            "verification_mode": "live_allowlisted_count",
        }

    def _execute_select(self, query: str) -> dict[str, Any]:
        auth = (self.username, self.password or "") if self.username else None
        try:
            with httpx.Client(timeout=self.timeout_seconds, auth=auth) as client:
                response = client.post(
                    self.endpoint,
                    data={"query": query},
                    headers={"Accept": "application/sparql-results+json"},
                )
                response.raise_for_status()
                if len(response.content) > self.MAX_RESPONSE_BYTES:
                    raise SparqlProjectionUnavailable("SPARQL response exceeded the byte budget")
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SparqlProjectionUnavailable(f"Fuseki query failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise SparqlProjectionUnavailable("Fuseki returned a non-object result")
        return payload

    def _render(self, template_id: str, *, concept: str, limit: int) -> str:
        templates = {
            "concept_summary": f"""
SELECT ?id ?label ?definition ?code ?role WHERE {{
  VALUES ?concept {{ {concept} }}
  OPTIONAL {{ ?concept dcterms:identifier ?id }}
  OPTIONAL {{ ?concept skos:prefLabel ?label }}
  OPTIONAL {{ ?concept skos:definition ?definition }}
  OPTIONAL {{ ?concept gda:code ?code }}
  OPTIONAL {{ ?concept gda:modelingRole ?role }}
}} LIMIT {limit}
""",
            "direct_hierarchy": f"""
SELECT ?direction ?related ?id ?label ?role WHERE {{
  VALUES ?concept {{ {concept} }}
  {{ ?concept rdfs:subClassOf ?related . FILTER(isIRI(?related)) BIND("parent" AS ?direction) }}
  UNION
  {{ ?related rdfs:subClassOf ?concept . FILTER(isIRI(?related)) BIND("child" AS ?direction) }}
  OPTIONAL {{ ?related dcterms:identifier ?id }}
  OPTIONAL {{ ?related skos:prefLabel ?label }}
  OPTIONAL {{ ?related gda:modelingRole ?role }}
}} ORDER BY ?direction ?label LIMIT {limit}
""",
            "transition_rules": f"""
SELECT ?rule ?state ?id ?label ?role WHERE {{
  VALUES ?concept {{ {concept} }}
  VALUES ?rule {{ ann:allowedSource ann:allowedTarget }}
  ?concept ?rule ?state .
  OPTIONAL {{ ?state dcterms:identifier ?id }}
  OPTIONAL {{ ?state skos:prefLabel ?label }}
  OPTIONAL {{ ?state gda:modelingRole ?role }}
}} ORDER BY ?rule ?label LIMIT {limit}
""",
            "state_transition_processes": f"""
SELECT DISTINCT ?process ?processLabel ?rule ?state ?stateLabel WHERE {{
  VALUES ?concept {{ {concept} }}
  {{ ?state rdfs:subClassOf* ?concept }}
  UNION
  {{ ?concept rdfs:subClassOf* ?state }}
  VALUES ?rule {{ ann:allowedSource ann:allowedTarget }}
  ?process ?rule ?state .
  OPTIONAL {{ ?process skos:prefLabel ?processLabel }}
  OPTIONAL {{ ?state skos:prefLabel ?stateLabel }}
}} ORDER BY ?processLabel ?rule ?stateLabel LIMIT {limit}
""",
        }
        body = templates.get(template_id)
        if body is None:
            raise ValueError(f"SPARQL template is not allowlisted: {template_id}")
        return self.PREFIXES + body
