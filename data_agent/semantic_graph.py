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
    """Materialize G=(V,E) from live PostGIS catalog + static OGC vocab.

    Vertices: geo_entities from geometry_columns; intents and predicates
    from _register_ogc_vocab(); constraints synthesized from SRID/cast rules.
    Edges: has_geometry, topological/metric/knn (predicate classes),
    intent_routes (static), unit_rule (SRID range→cast).

    Zero-SRID rows are skipped (grid tables have no CRS). FK edges and
    D/M dimension/measure vertices are left for a later task — this body
    only implements the GIS subset used by paper §3.1.
    """
    from sqlalchemy import text
    from data_agent.db_engine import get_engine

    g = SemanticGraph()
    _register_ogc_vocab(g)

    engine = get_engine()
    with engine.connect() as conn:
        q = text(
            """
            SELECT f_table_name, f_geometry_column, srid, type
            FROM geometry_columns
            WHERE f_table_schema = :schema
            ORDER BY f_table_name
            """
        )
        rows = conn.execute(q, {"schema": schema}).fetchall()

    for table, geom_col, srid, geom_type in rows:
        if table_prefix and not table.startswith(table_prefix):
            continue
        if srid == 0:
            continue
        g.add_geo_entity(table, geom_col, int(srid), geom_type)

    return g


def _register_ogc_vocab(g: SemanticGraph) -> None:
    """Static registry of OGC SFA predicates + intent routing + unit rules."""
    topo = ["ST_Intersects", "ST_Contains", "ST_Within",
            "ST_Touches", "ST_Crosses", "ST_Overlaps", "ST_Equals"]
    metric = ["ST_Distance", "ST_Length", "ST_Area", "ST_DWithin"]
    knn = ["<->"]
    for p in topo:
        g.add_predicate(p, "topological")
    for p in metric:
        g.add_predicate(p, "metric")
    for p in knn:
        g.add_predicate(p, "knn")
    for i in ["attribute_filter", "aggregation", "spatial_join",
              "spatial_measurement", "knn", "preview_listing"]:
        g.add_intent(i)
    for p in topo:
        g.add_intent_route("spatial_join", p)
    for p in metric:
        g.add_intent_route("spatial_measurement", p)
    g.add_intent_route("knn", "<->")
    for p in metric:
        g.add_unit_rule(p, (4326, 4326), "geography", "metre")
