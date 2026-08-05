"""Hash-verifying reader for immutable ontology runtime packages."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from .contracts import PackageManifest


DEFAULT_PACKAGE_ROOT = (
    Path(__file__).resolve().parent
    / "packages"
    / "natural_resource_one_map"
)

DOMAIN_MODEL_KINDS = {
    "DomainClass",
    "ProcessClass",
    "StateClass",
    "RoleClass",
    "InformationClass",
    "ObservationClass",
}


def resolve_package_dir(package_dir: str | Path | None = None) -> Path:
    explicit = package_dir or os.environ.get("ONTOLOGY_PACKAGE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    active_path = DEFAULT_PACKAGE_ROOT / "active.json"
    if not active_path.is_file():
        raise FileNotFoundError(f"ontology active package pointer not found: {active_path}")
    active = json.loads(active_path.read_text(encoding="utf-8"))
    version = str(active.get("semantic_version") or "").strip()
    if not version or "/" in version or ".." in version:
        raise ValueError("invalid ontology active package pointer")
    return (DEFAULT_PACKAGE_ROOT / version).resolve()


class OntologyPackageReader:
    """Read a fixed package and expose bounded search/traversal operations."""

    def __init__(self, package_dir: str | Path | None = None, *, verify: bool = True):
        self.package_dir = resolve_package_dir(package_dir)
        self.manifest = PackageManifest.model_validate_json(
            (self.package_dir / "manifest.json").read_text(encoding="utf-8")
        )
        if verify:
            self.verify_artifacts()
        self._lock = threading.RLock()
        self._loaded = False
        self._concepts: dict[str, dict[str, Any]] = {}
        self._concept_order: list[str] = []
        self._properties: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._properties_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._properties_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._relations_out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._relations_in: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._mappings_out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._mappings_in: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def verify_artifacts(self) -> None:
        for artifact in self.manifest.artifacts.values():
            path = (self.package_dir / artifact.path).resolve()
            if self.package_dir not in path.parents:
                raise ValueError(f"artifact escapes package directory: {artifact.path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != artifact.sha256:
                raise ValueError(f"ontology artifact hash mismatch: {artifact.path}")

    @staticmethod
    def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            for row in self._read_jsonl(self.package_dir / "concepts.jsonl.gz"):
                self._concepts[row["concept_id"]] = row
                self._concept_order.append(row["concept_id"])
            for row in self._read_jsonl(self.package_dir / "properties.jsonl.gz"):
                self._properties[row["owner_concept_id"]].append(row)
                code = str(row.get("code") or "").casefold()
                label = str(row.get("pref_label") or "").casefold()
                if code:
                    self._properties_by_code[code].append(row)
                if label:
                    self._properties_by_label[label].append(row)
            for row in self._read_jsonl(self.package_dir / "relations.jsonl.gz"):
                self._relations_out[row["source_concept_id"]].append(row)
                self._relations_in[row["target_concept_id"]].append(row)
            for row in self._read_jsonl(self.package_dir / "mappings.jsonl.gz"):
                self._mappings_out[row["source_concept_id"]].append(row)
                self._mappings_in[row["target_concept_id"]].append(row)
            for rows in self._properties.values():
                rows.sort(key=lambda item: (item.get("ordinal", 0), item.get("code", "")))
            self._loaded = True

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "backend": "immutable_package",
            "package_dir": str(self.package_dir),
            "package_id": self.manifest.package_id,
            "ontology_version_id": self.manifest.ontology_version_id,
            "semantic_version": self.manifest.semantic_version,
            "content_sha256": self.manifest.content_sha256,
            "generated_at": self.manifest.generated_at.isoformat(),
            "model_profile": self.manifest.model_profile,
            "stats": self.manifest.stats,
            "validation": self.manifest.validation_summary,
            "projection": {
                "rdf": True,
                "shacl": True,
                "sparql_endpoint": bool(os.environ.get("ONTOLOGY_SPARQL_ENDPOINT")),
            },
        }

    def versions(self) -> list[dict[str, Any]]:
        return [{
            "ontology_version_id": self.manifest.ontology_version_id,
            "semantic_version": self.manifest.semantic_version,
            "title": self.manifest.title,
            "status": "published",
            "active": True,
            "content_sha256": self.manifest.content_sha256,
            "generated_at": self.manifest.generated_at.isoformat(),
        }]

    def domains(self) -> list[dict[str, Any]]:
        return list(self.manifest.domain_stats)

    @staticmethod
    def _search_text(row: dict[str, Any]) -> str:
        return " ".join([
            str(row.get("code") or ""),
            str(row.get("pref_label") or ""),
            " ".join(row.get("alt_labels") or []),
            str(row.get("definition") or ""),
            str(row.get("package_path") or ""),
            str(row.get("ea_guid") or ""),
        ]).casefold()

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
        self._ensure_loaded()
        terms = [term.casefold() for term in query.split() if term.strip()]
        matches: list[tuple[int, dict[str, Any]]] = []
        for concept_id in self._concept_order:
            row = self._concepts[concept_id]
            if domain_id and row.get("domain_id") != domain_id:
                continue
            if kinds and row.get("kind") not in kinds:
                continue
            if source_system and row.get("source_system") != source_system:
                continue
            haystack = self._search_text(row)
            if terms and not all(term in haystack for term in terms):
                continue
            code = str(row.get("code") or "").casefold()
            label = str(row.get("pref_label") or "").casefold()
            score = 0
            folded_query = query.casefold().strip()
            if folded_query:
                score += 100 if code == folded_query else 0
                score += 60 if label == folded_query else 0
                score += 30 if code.startswith(folded_query) else 0
                score += 20 if label.startswith(folded_query) else 0
            matches.append((score, row))
        matches.sort(key=lambda item: (-item[0], item[1].get("pref_label", ""), item[1]["concept_id"]))
        total = len(matches)
        items = [dict(row, property_count=len(self._properties.get(row["concept_id"], [])))
                 for _, row in matches[offset:offset + limit]]
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    def concept(self, concept_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        row = self._concepts.get(concept_id)
        if row is None:
            return None
        outgoing = self._relations_out.get(concept_id, [])
        incoming = self._relations_in.get(concept_id, [])
        mappings = self._mappings_out.get(concept_id, []) + self._mappings_in.get(concept_id, [])
        return dict(
            row,
            property_count=len(self._properties.get(concept_id, [])),
            outgoing_relation_count=len(outgoing),
            incoming_relation_count=len(incoming),
            mapping_count=len(mappings),
        )

    def properties(self, concept_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        self._ensure_loaded()
        rows = self._properties.get(concept_id, [])
        return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit}

    def property_candidates(
        self,
        *,
        code: str = "",
        label: str = "",
        domain_id: str | None = None,
        owner_kinds: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Resolve exact field matches without requiring an owner-table match first."""
        self._ensure_loaded()
        candidates: dict[str, tuple[dict[str, Any], str]] = {}
        if code:
            for row in self._properties_by_code.get(code.casefold(), []):
                candidates[row["property_id"]] = (row, "exact_code")
        if label:
            for row in self._properties_by_label.get(label.casefold(), []):
                candidates.setdefault(row["property_id"], (row, "exact_label"))
        results: list[dict[str, Any]] = []
        for row, match_type in candidates.values():
            owner = self._concepts.get(row["owner_concept_id"])
            if not owner:
                continue
            if domain_id and owner.get("domain_id") != domain_id:
                continue
            if owner_kinds and owner.get("kind") not in owner_kinds:
                continue
            results.append({
                "owner_concept_id": owner["concept_id"],
                "owner_label": owner.get("pref_label"),
                "owner_code": owner.get("code"),
                "property": row,
                "match_type": match_type,
                "status": "candidate",
                "confidence": 1.0 if match_type == "exact_code" else 0.95,
            })
        results.sort(key=lambda item: (
            0 if item["match_type"] == "exact_code" else 1,
            str(item.get("owner_label") or ""),
            item["property"]["property_id"],
        ))
        return results[:limit]

    def relations(self, concept_id: str, *, direction: str = "both", limit: int = 200) -> dict[str, Any]:
        self._ensure_loaded()
        rows: list[dict[str, Any]] = []
        if direction in {"both", "out"}:
            rows.extend(dict(row, traversal_direction="out") for row in self._relations_out.get(concept_id, []))
        if direction in {"both", "in"}:
            rows.extend(dict(row, traversal_direction="in") for row in self._relations_in.get(concept_id, []))
        enriched = []
        for row in rows[:limit]:
            other_id = row["target_concept_id"] if row["traversal_direction"] == "out" else row["source_concept_id"]
            other = self._concepts.get(other_id) or {}
            enriched.append(dict(row, other_concept={
                "concept_id": other_id,
                "pref_label": other.get("pref_label", other_id),
                "code": other.get("code"),
                "kind": other.get("kind"),
            }))
        return {"items": enriched, "total": len(rows), "limit": limit}

    def mappings(
        self,
        *,
        status: str | None = None,
        domain_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._ensure_loaded()
        rows = []
        seen = set()
        for mapping_rows in self._mappings_out.values():
            for row in mapping_rows:
                if row["mapping_id"] in seen:
                    continue
                seen.add(row["mapping_id"])
                source = self._concepts.get(row["source_concept_id"]) or {}
                target = self._concepts.get(row["target_concept_id"]) or {}
                if status and row.get("mapping_status") != status:
                    continue
                if domain_id and source.get("domain_id") != domain_id and target.get("domain_id") != domain_id:
                    continue
                rows.append(dict(row, source_concept={
                    "concept_id": row["source_concept_id"],
                    "code": source.get("code"),
                    "pref_label": source.get("pref_label"),
                    "kind": source.get("kind"),
                }, target_concept={
                    "concept_id": row["target_concept_id"],
                    "code": target.get("code"),
                    "pref_label": target.get("pref_label"),
                    "kind": target.get("kind"),
                }))
        rows.sort(key=lambda row: (row.get("mapping_status", ""), row["mapping_id"]))
        return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit}

    def graph(
        self,
        *,
        root_id: str | None = None,
        domain_id: str | None = None,
        depth: int = 1,
        limit: int = 250,
        include_mappings: bool = True,
    ) -> dict[str, Any]:
        self._ensure_loaded()
        depth = max(0, min(depth, 3))
        limit = max(1, min(limit, 500))
        selected: list[str] = []
        selected_set: set[str] = set()

        def add(concept_id: str) -> bool:
            if concept_id in selected_set or concept_id not in self._concepts or len(selected) >= limit:
                return False
            selected_set.add(concept_id)
            selected.append(concept_id)
            return True

        if root_id:
            add(root_id)
            queue = deque([(root_id, 0)])
            root_kind = (self._concepts.get(root_id) or {}).get("kind")
            semantic_root = (
                root_kind in DOMAIN_MODEL_KINDS | {"Domain"}
                and any(
                    row.get("kind") in DOMAIN_MODEL_KINDS
                    for row in self._concepts.values()
                )
            )
            while queue and len(selected) < limit:
                current, level = queue.popleft()
                if level >= depth:
                    continue
                adjacent = self._relations_out.get(current, []) + self._relations_in.get(current, [])
                for relation in adjacent:
                    other = relation["target_concept_id"] if relation["source_concept_id"] == current else relation["source_concept_id"]
                    if semantic_root and self._concepts[other].get("kind") not in DOMAIN_MODEL_KINDS | {"Domain"}:
                        continue
                    if add(other):
                        queue.append((other, level + 1))
        elif domain_id:
            domain_concept = next((row for row in self._concepts.values()
                                   if row.get("kind") == "Domain" and row.get("domain_id") == domain_id), None)
            if domain_concept:
                add(domain_concept["concept_id"])
            candidates = [
                row for row in self._concepts.values()
                if row.get("domain_id") == domain_id and row.get("kind") in DOMAIN_MODEL_KINDS
            ]
            candidates.sort(key=lambda row: (row.get("kind", ""), row.get("pref_label", ""), row["concept_id"]))
            for row in candidates:
                if len(selected) >= limit:
                    break
                add(row["concept_id"])
            # Include taxonomy ancestors so a subject-area view remains intelligible.
            queue = deque(selected)
            while queue and len(selected) < limit:
                current = queue.popleft()
                for relation in self._relations_out.get(current, []):
                    if relation.get("relation_type") != "subClassOf":
                        continue
                    parent = relation["target_concept_id"]
                    if add(parent):
                        queue.append(parent)
        else:
            for row in self._concepts.values():
                if row.get("kind") in DOMAIN_MODEL_KINDS:
                    add(row["concept_id"])
                    if len(selected) >= limit:
                        break

        edges: list[dict[str, Any]] = []
        edge_ids: set[str] = set()
        for concept_id in selected:
            for relation in self._relations_out.get(concept_id, []):
                if relation["target_concept_id"] in selected_set and relation["relation_id"] not in edge_ids:
                    edge_ids.add(relation["relation_id"])
                    edges.append(relation)
            if include_mappings:
                for mapping in self._mappings_out.get(concept_id, []):
                    if mapping["target_concept_id"] in selected_set and mapping["mapping_id"] not in edge_ids:
                        edge_ids.add(mapping["mapping_id"])
                        edges.append({
                            "relation_id": mapping["mapping_id"],
                            "relation_type": mapping["mapping_type"],
                            "source_concept_id": mapping["source_concept_id"],
                            "target_concept_id": mapping["target_concept_id"],
                            "mapping_status": mapping["mapping_status"],
                            "pref_label": mapping["mapping_type"].replace("_", " "),
                        })

        lane_counts: dict[int, int] = defaultdict(int)
        nodes = []
        for concept_id in selected:
            row = self._concepts[concept_id]
            lane = self._kind_lane(row.get("kind", "Concept"))
            lane_index = lane_counts[lane]
            lane_counts[lane] += 1
            nodes.append(self._graph_node(row, lane_index))
        graph_edges = [{
            "id": edge["relation_id"],
            "source": edge["source_concept_id"],
            "target": edge["target_concept_id"],
            "type": "ontologyRelation",
            "label": edge.get("pref_label") or edge.get("relation_type"),
            "data": {
                "relationType": edge.get("relation_type"),
                "mappingStatus": edge.get("mapping_status"),
            },
        } for edge in edges]
        return {
            "nodes": nodes,
            "edges": graph_edges,
            "node_count": len(nodes),
            "edge_count": len(graph_edges),
            "truncated": len(selected) >= limit,
            "limit": limit,
            "depth": depth,
        }

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
            "DatasetSchema": 3,
            "ObjectType": 2,
            "ValueDomain": 2,
            "ValueDomainMember": 3,
            "ActionType": 3,
        }.get(kind, 4)

    def _graph_node(self, row: dict[str, Any], lane_index: int) -> dict[str, Any]:
        kind = row.get("kind", "Concept")
        lane = self._kind_lane(kind)
        columns_per_lane = 3
        return {
            "id": row["concept_id"],
            "type": "ontologyConcept",
            "position": {
                "x": lane * 900 + (lane_index % columns_per_lane) * 280,
                "y": (lane_index // columns_per_lane) * 116,
            },
            "data": {
                "label": row.get("pref_label"),
                "code": row.get("code"),
                "kind": kind,
                "sourceSystem": row.get("source_system"),
                "propertyCount": len(self._properties.get(row["concept_id"], [])),
                "geometryType": row.get("geometry_type"),
                "lifecycleStatus": row.get("lifecycle_status"),
            },
        }

    def validation(self) -> dict[str, Any]:
        path = self.package_dir / "validation-report.json"
        if not path.is_file():
            return self.manifest.validation_summary
        return json.loads(path.read_text(encoding="utf-8"))

    def artifact_path(self, artifact_key: str) -> Path:
        artifact = self.manifest.artifacts.get(artifact_key)
        if artifact is None:
            raise KeyError(artifact_key)
        return self.package_dir / artifact.path
