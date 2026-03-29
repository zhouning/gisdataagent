"""
Geographic Knowledge Graph -- entity-relationship model from spatial data.

Uses networkx for in-memory graph representation. Entities are spatial
features (parcels, buildings, roads, etc.) and relationships are
topological/semantic (contains, adjacent_to, within, overlaps).

v7.0: Lightweight graph builder from GeoDataFrames.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import box

from .db_engine import get_engine
from .gis_processors import _generate_output_path, _resolve_path
from .user_context import current_user_id

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENTITY_TYPES = {
    "parcel": ["地块", "parcel", "dlbm", "land_use", "tdly"],
    "building": ["建筑", "building", "bldg", "房屋", "jzw"],
    "road": ["道路", "road", "道", "highway", "dl"],
    "water": ["水体", "water", "河流", "lake", "sx"],
    "admin": ["行政区", "admin", "district", "区划", "xzq"],
    "vegetation": ["植被", "vegetation", "林地", "forest", "ld"],
    "poi": ["兴趣点", "poi", "point_of_interest", "设施"],
    "data_asset": [],  # v12.1: data lineage nodes (not auto-detected from columns)
}

RELATIONSHIP_TYPES = ["contains", "within", "adjacent_to", "overlaps", "nearest_to",
                      "derives_from", "feeds_into"]  # v12.1: lineage edges

T_KNOWLEDGE_GRAPHS = "agent_knowledge_graphs"

# Max pairs to process for spatial relationship detection (performance guard)
_MAX_SPATIAL_PAIRS = 1000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GraphStats:
    """Summary statistics for a knowledge graph."""
    node_count: int = 0
    edge_count: int = 0
    entity_types: dict = field(default_factory=dict)
    relationship_types: dict = field(default_factory=dict)
    connected_components: int = 0
    density: float = 0.0


# ---------------------------------------------------------------------------
# GeoKnowledgeGraph
# ---------------------------------------------------------------------------

class GeoKnowledgeGraph:
    """In-memory geographic knowledge graph built from spatial data.

    Nodes are spatial features with attributes. Edges represent topological
    and semantic relationships (adjacent_to, contains, within, overlaps).
    """

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()

    # ----- Build / Merge -----

    def build_from_geodataframe(
        self,
        gdf: gpd.GeoDataFrame,
        id_column: Optional[str] = None,
        entity_type: str = "feature",
        detect_adjacency: bool = True,
        detect_containment: bool = True,
    ) -> GraphStats:
        """Build the graph from a single GeoDataFrame.

        Each row becomes a node with its non-geometry attributes stored on the
        node. Spatial relationships (adjacency, containment) are detected
        automatically unless disabled.

        Args:
            gdf: GeoDataFrame to build graph from.
            id_column: Column to use as node ID. Auto-detected if None.
            entity_type: Entity type label for all nodes (or 'auto' to detect).
            detect_adjacency: Whether to detect touching/shared-boundary pairs.
            detect_containment: Whether to detect contains/within pairs.

        Returns:
            GraphStats summary of the resulting graph.
        """
        if gdf is None or len(gdf) == 0:
            return self.get_stats()

        # Auto-detect entity type if needed
        if entity_type in ("auto", "feature"):
            detected = self._detect_entity_type(gdf)
            if detected != "feature":
                entity_type = detected

        # Auto-detect ID column
        if id_column is None:
            id_column = self._detect_id_column(gdf)

        # Add nodes
        for idx, row in gdf.iterrows():
            if id_column and id_column in row.index:
                node_id = str(row[id_column])
            else:
                node_id = str(idx)

            attrs = {}
            for col in gdf.columns:
                if col == "geometry":
                    continue
                val = row[col]
                # Convert numpy types to Python native for JSON serialization
                if isinstance(val, (np.integer,)):
                    val = int(val)
                elif isinstance(val, (np.floating,)):
                    val = float(val)
                elif isinstance(val, (np.bool_,)):
                    val = bool(val)
                attrs[col] = val

            attrs["_entity_type"] = entity_type
            if hasattr(row, "geometry") and row.geometry is not None:
                attrs["_geometry_type"] = row.geometry.geom_type
                attrs["_geom_wkt"] = row.geometry.wkt
            else:
                attrs["_geometry_type"] = None

            self.graph.add_node(node_id, **attrs)

        # Detect spatial relationships
        if detect_adjacency and len(gdf) > 1:
            self._detect_adjacency(gdf, id_column)
        if detect_containment and len(gdf) > 1:
            self._detect_containment(gdf, id_column)

        return self.get_stats()

    def merge_layer(
        self,
        gdf: gpd.GeoDataFrame,
        entity_type: str,
        id_column: Optional[str] = None,
        relate_to_existing: bool = True,
    ) -> GraphStats:
        """Add a new layer of nodes to the graph and optionally detect
        cross-layer spatial relationships with existing nodes.

        New nodes are prefixed with ``{entity_type}_`` to avoid ID collisions.

        Args:
            gdf: GeoDataFrame with the new layer.
            entity_type: Entity type label for the new nodes.
            id_column: Column to use as node ID (auto-detected if None).
            relate_to_existing: Whether to detect relationships with existing nodes.

        Returns:
            GraphStats summary after merging.
        """
        if gdf is None or len(gdf) == 0:
            return self.get_stats()

        if id_column is None:
            id_column = self._detect_id_column(gdf)

        new_node_ids = []

        for idx, row in gdf.iterrows():
            if id_column and id_column in row.index:
                raw_id = str(row[id_column])
            else:
                raw_id = str(idx)
            node_id = f"{entity_type}_{raw_id}"

            attrs = {}
            for col in gdf.columns:
                if col == "geometry":
                    continue
                val = row[col]
                if isinstance(val, (np.integer,)):
                    val = int(val)
                elif isinstance(val, (np.floating,)):
                    val = float(val)
                elif isinstance(val, (np.bool_,)):
                    val = bool(val)
                attrs[col] = val

            attrs["_entity_type"] = entity_type
            if hasattr(row, "geometry") and row.geometry is not None:
                attrs["_geometry_type"] = row.geometry.geom_type
                attrs["_geom_wkt"] = row.geometry.wkt
            else:
                attrs["_geometry_type"] = None

            self.graph.add_node(node_id, **attrs)
            new_node_ids.append(node_id)

        # Cross-layer spatial relationships
        if relate_to_existing and new_node_ids:
            self._detect_cross_layer_relationships(new_node_ids)

        return self.get_stats()

    # ----- Query -----

    def query_neighbors(
        self,
        node_id: str,
        depth: int = 1,
        relationship_type: Optional[str] = None,
    ) -> dict:
        """Query neighbors of a node up to a given depth.

        Args:
            node_id: The source node ID.
            depth: Maximum traversal depth (default 1).
            relationship_type: If set, only follow edges of this type.

        Returns:
            Dict with node, depth, and list of neighbor info dicts.
        """
        if node_id not in self.graph:
            return {"node": node_id, "depth": depth, "neighbors": []}

        ego = nx.ego_graph(self.graph, node_id, radius=depth, undirected=True)

        neighbors = []
        for nid in ego.nodes():
            if nid == node_id:
                continue

            # Determine relationship from edges on shortest path
            rel = None
            # Check direct edge first
            if self.graph.has_edge(node_id, nid):
                rel = self.graph.edges[node_id, nid].get("type", "unknown")
            elif self.graph.has_edge(nid, node_id):
                rel = self.graph.edges[nid, node_id].get("type", "unknown")

            if relationship_type and rel != relationship_type:
                continue

            ndata = dict(self.graph.nodes[nid])
            etype = ndata.pop("_entity_type", "feature")
            ndata.pop("_geometry_type", None)
            ndata.pop("_geom_wkt", None)

            neighbors.append({
                "id": nid,
                "entity_type": etype,
                "relationship": rel,
                "attributes": ndata,
            })

        return {"node": node_id, "depth": depth, "neighbors": neighbors}

    def query_path(self, from_id: str, to_id: str) -> dict:
        """Find the shortest path between two nodes.

        Uses an undirected view so path can follow edges in either direction.

        Args:
            from_id: Source node.
            to_id: Target node.

        Returns:
            Dict with from, to, path list, and length (-1 if no path).
        """
        if from_id not in self.graph or to_id not in self.graph:
            return {"from": from_id, "to": to_id, "path": [], "length": -1}

        try:
            undirected = nx.Graph(self.graph)
            path = nx.shortest_path(undirected, from_id, to_id)
            return {"from": from_id, "to": to_id, "path": path, "length": len(path) - 1}
        except nx.NetworkXNoPath:
            return {"from": from_id, "to": to_id, "path": [], "length": -1}

    def query_by_type(self, entity_type: str) -> list[dict]:
        """Return all nodes of a given entity type.

        Args:
            entity_type: The entity type to filter by.

        Returns:
            List of dicts with id, entity_type, and cleaned attributes.
        """
        results = []
        for nid, data in self.graph.nodes(data=True):
            if data.get("_entity_type") == entity_type:
                attrs = {
                    k: v for k, v in data.items()
                    if k not in ("_entity_type", "_geometry_type", "_geom_wkt")
                }
                results.append({
                    "id": nid,
                    "entity_type": entity_type,
                    "attributes": attrs,
                })
        return results

    # ----- Export / Stats -----

    def export_to_json(self) -> dict:
        """Export graph as a JSON-serializable dict (node-link format).

        Strips ``_geom_wkt`` from node attributes to keep output compact.

        Returns:
            Node-link data dict.
        """
        # Work on a copy so we don't mutate the live graph
        g = self.graph.copy()
        for nid in g.nodes():
            if "_geom_wkt" in g.nodes[nid]:
                del g.nodes[nid]["_geom_wkt"]
        return nx.node_link_data(g)

    # --- v12.1: Data lineage edges ---

    def add_lineage_edge(self, source_id: str, target_id: str, tool_name: str = ""):
        """Add derives_from/feeds_into edges between data assets for lineage tracking."""
        for nid in (source_id, target_id):
            if nid not in self.graph:
                self.graph.add_node(nid, _entity_type="data_asset")
        self.graph.add_edge(source_id, target_id, type="feeds_into", tool=tool_name)
        self.graph.add_edge(target_id, source_id, type="derives_from", tool=tool_name)

    # --- v12.2: Catalog asset registration + domain edges ---

    _ASSET_TYPE_DOMAIN = {
        "vector": "GIS", "raster": "遥感", "tabular": "统计",
        "map": "可视化", "report": "报告", "script": "脚本",
    }

    def register_catalog_assets(self, assets: list[dict]):
        """Register data catalog assets as nodes with domain edges.

        Args:
            assets: List of dicts with keys: id, asset_name, asset_type, description, tags.
        """
        for a in assets:
            nid = f"asset:{a.get('id', '')}"
            self.graph.add_node(nid,
                _entity_type="data_asset",
                name=a.get("asset_name", ""),
                asset_type=a.get("asset_type", ""),
                description=a.get("description", ""),
            )
            # Domain edge based on asset_type
            domain = self._ASSET_TYPE_DOMAIN.get(a.get("asset_type", ""), "其他")
            domain_nid = f"domain:{domain}"
            if domain_nid not in self.graph:
                self.graph.add_node(domain_nid, _entity_type="domain", name=domain)
            self.graph.add_edge(nid, domain_nid, type="belongs_to_domain")

    def discover_related_assets(self, asset_id: int = None, depth: int = 2) -> list[dict]:
        """Find assets related to a given asset via lineage and domain edges.

        Args:
            asset_id: Catalog asset ID to find relations for.
            depth: Max traversal depth.

        Returns:
            List of related asset dicts with relationship info.
        """
        nid = f"asset:{asset_id}"
        if nid not in self.graph:
            return []

        related = []
        visited = {nid}
        queue = [(nid, 0)]

        while queue:
            current, d = queue.pop(0)
            if d >= depth:
                continue
            for neighbor in self.graph.neighbors(current):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                edge_data = self.graph.edges[current, neighbor]
                node_data = self.graph.nodes[neighbor]
                if node_data.get("_entity_type") == "data_asset":
                    related.append({
                        "id": neighbor.replace("asset:", ""),
                        "name": node_data.get("name", ""),
                        "asset_type": node_data.get("asset_type", ""),
                        "relationship": edge_data.get("type", ""),
                        "depth": d + 1,
                    })
                queue.append((neighbor, d + 1))

        return related

    def get_stats(self) -> GraphStats:
        """Compute summary statistics for the current graph state.

        Returns:
            GraphStats dataclass.
        """
        # Entity type counts
        etype_counts: dict[str, int] = {}
        for _, data in self.graph.nodes(data=True):
            et = data.get("_entity_type", "unknown")
            etype_counts[et] = etype_counts.get(et, 0) + 1

        # Relationship type counts
        rtype_counts: dict[str, int] = {}
        for _, _, data in self.graph.edges(data=True):
            rt = data.get("type", "unknown")
            rtype_counts[rt] = rtype_counts.get(rt, 0) + 1

        return GraphStats(
            node_count=self.graph.number_of_nodes(),
            edge_count=self.graph.number_of_edges(),
            entity_types=etype_counts,
            relationship_types=rtype_counts,
            connected_components=nx.number_weakly_connected_components(self.graph)
            if self.graph.number_of_nodes() > 0 else 0,
            density=nx.density(self.graph),
        )

    # ----- Private helpers -----

    def _detect_id_column(self, gdf: gpd.GeoDataFrame) -> Optional[str]:
        """Auto-detect the best ID column in a GeoDataFrame.

        Prefers well-known ID column names; falls back to the first column
        whose values are all unique.
        """
        preferred = ["id", "objectid", "fid", "gid", "pkid"]
        cols_lower = {c.lower(): c for c in gdf.columns if c != "geometry"}

        for name in preferred:
            if name in cols_lower:
                return cols_lower[name]

        # Fallback: first column with all unique values
        for col in gdf.columns:
            if col == "geometry":
                continue
            if gdf[col].is_unique:
                return col

        return None

    def _detect_adjacency(self, gdf: gpd.GeoDataFrame, id_column: Optional[str]):
        """Detect adjacent (touching) features and add bidirectional edges.

        Uses an STRtree spatial index for efficient pair detection.
        """
        if len(gdf) < 2:
            return

        from shapely import STRtree

        geoms = gdf.geometry.values
        tree = STRtree(geoms)

        node_ids = self._build_node_id_list(gdf, id_column)
        pairs_checked = 0

        for i, geom in enumerate(geoms):
            if geom is None or geom.is_empty:
                continue
            candidates = tree.query(geom)
            for j in candidates:
                if j <= i:
                    continue  # skip self and already-checked pairs
                if pairs_checked >= _MAX_SPATIAL_PAIRS:
                    return
                other = geoms[j]
                if other is None or other.is_empty:
                    continue
                try:
                    if geom.touches(other) or (
                        not geom.equals(other)
                        and geom.intersection(other).length > 0
                        and not geom.overlaps(other)
                    ):
                        nid_a, nid_b = node_ids[i], node_ids[j]
                        self.graph.add_edge(nid_a, nid_b, type="adjacent_to")
                        self.graph.add_edge(nid_b, nid_a, type="adjacent_to")
                        pairs_checked += 1
                except Exception:
                    pass  # skip invalid geometry pairs

    def _detect_containment(self, gdf: gpd.GeoDataFrame, id_column: Optional[str]):
        """Detect containment relationships (contains/within) between features.

        Uses an STRtree spatial index for candidate pair filtering.
        """
        if len(gdf) < 2:
            return

        from shapely import STRtree

        geoms = gdf.geometry.values
        tree = STRtree(geoms)

        node_ids = self._build_node_id_list(gdf, id_column)
        pairs_checked = 0

        for i, geom in enumerate(geoms):
            if geom is None or geom.is_empty:
                continue
            candidates = tree.query(geom)
            for j in candidates:
                if j == i:
                    continue
                if pairs_checked >= _MAX_SPATIAL_PAIRS:
                    return
                other = geoms[j]
                if other is None or other.is_empty:
                    continue
                try:
                    if geom.contains(other) and not geom.equals(other):
                        nid_a, nid_b = node_ids[i], node_ids[j]
                        # A contains B → directed edges
                        self.graph.add_edge(nid_a, nid_b, type="contains")
                        self.graph.add_edge(nid_b, nid_a, type="within")
                        pairs_checked += 1
                except Exception:
                    pass

    def _detect_cross_layer_relationships(self, new_node_ids: list[str]):
        """Detect spatial relationships between newly added nodes and existing
        nodes that have WKT geometry stored.

        Builds an STRtree from existing (non-new) node geometries and queries
        each new node against it.
        """
        from shapely import wkt as shapely_wkt, STRtree

        # Collect existing nodes (those NOT in the new batch) with geometry
        existing_ids = []
        existing_geoms = []
        for nid, data in self.graph.nodes(data=True):
            if nid in new_node_ids:
                continue
            wkt = data.get("_geom_wkt")
            if wkt:
                try:
                    existing_geoms.append(shapely_wkt.loads(wkt))
                    existing_ids.append(nid)
                except Exception:
                    pass

        if not existing_geoms:
            return

        tree = STRtree(existing_geoms)
        pairs_checked = 0

        for nid in new_node_ids:
            wkt = self.graph.nodes[nid].get("_geom_wkt")
            if not wkt:
                continue
            try:
                new_geom = shapely_wkt.loads(wkt)
            except Exception:
                continue

            candidates = tree.query(new_geom)
            for ci in candidates:
                if pairs_checked >= _MAX_SPATIAL_PAIRS:
                    return
                ex_geom = existing_geoms[ci]
                ex_id = existing_ids[ci]
                try:
                    if new_geom.contains(ex_geom) and not new_geom.equals(ex_geom):
                        self.graph.add_edge(nid, ex_id, type="contains")
                        self.graph.add_edge(ex_id, nid, type="within")
                        pairs_checked += 1
                    elif ex_geom.contains(new_geom) and not ex_geom.equals(new_geom):
                        self.graph.add_edge(ex_id, nid, type="contains")
                        self.graph.add_edge(nid, ex_id, type="within")
                        pairs_checked += 1
                    elif new_geom.overlaps(ex_geom):
                        self.graph.add_edge(nid, ex_id, type="overlaps")
                        self.graph.add_edge(ex_id, nid, type="overlaps")
                        pairs_checked += 1
                except Exception:
                    pass

    def _detect_entity_type(self, gdf: gpd.GeoDataFrame) -> str:
        """Detect entity type from column names by matching against ENTITY_TYPES keywords."""
        cols_lower = [c.lower() for c in gdf.columns if c != "geometry"]
        for etype, keywords in ENTITY_TYPES.items():
            for kw in keywords:
                if kw.lower() in cols_lower:
                    return etype
        return "feature"

    def _build_node_id_list(
        self, gdf: gpd.GeoDataFrame, id_column: Optional[str]
    ) -> list[str]:
        """Build an ordered list of node IDs matching gdf row order."""
        ids = []
        for idx, row in gdf.iterrows():
            if id_column and id_column in row.index:
                ids.append(str(row[id_column]))
            else:
                ids.append(str(idx))
        return ids


# ---------------------------------------------------------------------------
# Database functions
# ---------------------------------------------------------------------------

def ensure_knowledge_graph_tables():
    """Create knowledge graph tables if not exist. Called at startup."""
    engine = get_engine()
    if not engine:
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_KNOWLEDGE_GRAPHS} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    graph_name VARCHAR(200),
                    node_count INTEGER DEFAULT 0,
                    edge_count INTEGER DEFAULT 0,
                    entity_types JSONB DEFAULT '{{}}'::jsonb,
                    graph_data JSONB DEFAULT '{{}}'::jsonb,
                    source_files JSONB DEFAULT '[]'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_kg_username "
                f"ON {T_KNOWLEDGE_GRAPHS} (username)"
            ))
            conn.commit()
    except Exception as e:
        print(f"[KnowledgeGraph] WARNING: Failed to create tables: {e}")


def save_graph(
    graph: GeoKnowledgeGraph,
    graph_name: str,
    source_files: list[str],
) -> None:
    """Save a graph snapshot to the database.

    Args:
        graph: The GeoKnowledgeGraph instance to save.
        graph_name: Human-readable name for this graph.
        source_files: List of source file paths used to build the graph.
    """
    engine = get_engine()
    if not engine:
        return

    try:
        username = current_user_id.get()
        stats = graph.get_stats()
        graph_data = graph.export_to_json()

        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_KNOWLEDGE_GRAPHS}
                (username, graph_name, node_count, edge_count,
                 entity_types, graph_data, source_files)
                VALUES (:username, :graph_name, :node_count, :edge_count,
                        :entity_types, :graph_data, :source_files)
            """), {
                "username": username,
                "graph_name": graph_name,
                "node_count": stats.node_count,
                "edge_count": stats.edge_count,
                "entity_types": json.dumps(stats.entity_types),
                "graph_data": json.dumps(graph_data, default=str),
                "source_files": json.dumps(source_files),
            })
            conn.commit()
    except Exception as e:
        print(f"[KnowledgeGraph] WARNING: Failed to save graph: {e}")
