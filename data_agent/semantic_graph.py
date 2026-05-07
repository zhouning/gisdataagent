"""Metadata graph G=(V,E) for PostGIS semantic grounding.

V = E_geo (geographic entities) ∪ D (dimensions) ∪ M (measures) ∪
    I (intent tags) ∪ P (OGC predicates) ∪ C (safety/unit constraints).

E = E_hasGeom ∪ E_fk ∪ E_topo ∪ E_metric ∪ E_knn ∪
    E_intent_routes ∪ E_safety ∪ E_unit.

Executable subset of OGC SFA (06-104r4) the agent grounds against.
Paper §3.1 cites this module as the metadata-graph abstraction suggested
by the v2 peer-review report §3.A. Live PostGIS materialisation is in
Task 2 (build_semantic_graph body).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

import networkx as nx


class NodeKind(str, Enum):
    GEO_ENTITY = "geo_entity"
    DIMENSION = "dimension"
    MEASURE = "measure"
    INTENT = "intent"
    PREDICATE = "predicate"
    CONSTRAINT = "constraint"


class EdgeKind(str, Enum):
    HAS_GEOMETRY = "has_geometry"
    FK = "fk"
    TOPOLOGICAL = "topological"
    METRIC = "metric"
    KNN = "knn"
    INTENT_ROUTES = "intent_routes"
    SAFETY_CONSTRAINT = "safety_constraint"
    UNIT_RULE = "unit_rule"


@dataclass
class SemanticGraph:
    """Executable metadata graph backed by networkx.MultiDiGraph."""

    graph: Optional[nx.MultiDiGraph] = None

    def __post_init__(self) -> None:
        if self.graph is None:
            self.graph = nx.MultiDiGraph()

    def add_geo_entity(self, table: str, geom_col: str, srid: int, geom_type: str) -> None:
        self.graph.add_node(
            table, kind=NodeKind.GEO_ENTITY,
            geom_col=geom_col, srid=srid, geom_type=geom_type,
        )

    def add_intent(self, intent: str) -> None:
        self.graph.add_node(intent, kind=NodeKind.INTENT)

    def add_predicate(self, predicate: str, predicate_class: str) -> None:
        self.graph.add_node(
            predicate, kind=NodeKind.PREDICATE, predicate_class=predicate_class,
        )

    def add_intent_route(self, intent: str, predicate: str) -> None:
        self.graph.add_edge(intent, predicate, kind=EdgeKind.INTENT_ROUTES)

    def add_unit_rule(
        self, predicate: str, srid_range: Tuple[int, int],
        required_cast: str, yields_unit: str,
    ) -> None:
        lo, hi = srid_range
        node_key = f"unit::{predicate}::{lo}-{hi}"
        self.graph.add_node(node_key, kind=NodeKind.CONSTRAINT)
        self.graph.add_edge(
            predicate, node_key, kind=EdgeKind.UNIT_RULE,
            required_cast=required_cast, yields_unit=yields_unit, srid_range=srid_range,
        )

    def to_mermaid(self) -> str:
        lines = ["graph LR"]
        for node in sorted(self.graph.nodes, key=str):
            lines.append(f"    {node}")
        edges = [(u, v, d.get("kind")) for u, v, d in self.graph.edges(data=True)]
        edges.sort(key=lambda e: (str(e[0]), str(e[1]), str(e[2])))
        for src, dst, _kind in edges:
            lines.append(f"    {src} --> {dst}")
        return "\n".join(lines)


def build_semantic_graph(schema: str = "public", table_prefix: Optional[str] = None) -> SemanticGraph:
    """Build a SemanticGraph from live PostGIS metadata.

    Stub returning an empty graph; live materialisation lands in Task 2.
    """
    return SemanticGraph()
