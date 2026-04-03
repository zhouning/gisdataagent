"""Fusion v2.0 — Knowledge Graph Integration module.

Bridges the existing GeoKnowledgeGraph to enrich fusion results
with entity relationships and support conflict resolution via KG context.
"""
import logging
from typing import Any, Optional

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


class KGIntegration:
    """Knowledge Graph integration for fusion enrichment and conflict resolution."""

    def __init__(self, kg=None):
        """Initialize with an optional GeoKnowledgeGraph instance.

        Args:
            kg: GeoKnowledgeGraph instance. If None, attempts lazy import.
        """
        self._kg = kg
        if self._kg is None:
            try:
                from ..knowledge_graph import GeoKnowledgeGraph
                self._kg = GeoKnowledgeGraph()
            except Exception as e:
                logger.warning("KG not available: %s", e)

    @property
    def is_available(self) -> bool:
        return self._kg is not None

    def enrich_with_relationships(
        self,
        gdf: gpd.GeoDataFrame,
        entity_column: str = "name",
    ) -> gpd.GeoDataFrame:
        """Enrich features with knowledge graph relationships.

        For each row, queries the KG for relationships (contains, adjacent_to, within).
        Adds columns: _kg_relationships (JSON), _kg_entity_type.

        Args:
            gdf: Input GeoDataFrame.
            entity_column: Column containing entity names/IDs for KG lookup.

        Returns:
            GeoDataFrame with added KG columns.
        """
        if not self.is_available:
            logger.info("KG not available; skipping enrichment")
            return gdf

        if entity_column not in gdf.columns:
            logger.warning("Entity column '%s' not found; skipping KG enrichment", entity_column)
            return gdf

        result = gdf.copy()
        relationships = []
        entity_types = []

        for _, row in result.iterrows():
            entity = row.get(entity_column)
            if pd.isna(entity):
                relationships.append("{}")
                entity_types.append(None)
                continue

            rels, etype = self._query_entity(str(entity))
            relationships.append(str(rels))
            entity_types.append(etype)

        result["_kg_relationships"] = relationships
        result["_kg_entity_type"] = entity_types
        return result

    def resolve_conflicts_with_kg(
        self,
        conflicting_values: list,
        entity_id: str,
        attribute: str,
    ) -> tuple[Any, str]:
        """Use KG context to resolve conflicting attribute values.

        Queries the KG for the entity and its neighbors, then selects
        the most contextually consistent value.

        Args:
            conflicting_values: List of conflicting values from different sources.
            entity_id: Entity identifier in the KG.
            attribute: Attribute name being resolved.

        Returns:
            (best_value, reasoning).
        """
        if not self.is_available or not conflicting_values:
            return conflicting_values[0] if conflicting_values else None, "KG not available; using first value"

        # Query KG for entity context
        try:
            if hasattr(self._kg, "graph") and entity_id in self._kg.graph:
                node_data = self._kg.graph.nodes[entity_id]
                # If the KG has a stored value for this attribute, prefer it
                if attribute in node_data:
                    kg_value = node_data[attribute]
                    if kg_value in conflicting_values:
                        return kg_value, f"KG 记录值: {kg_value}"

                # Check neighbors for consensus
                neighbors = list(self._kg.graph.neighbors(entity_id))
                neighbor_vals = []
                for n in neighbors:
                    n_data = self._kg.graph.nodes.get(n, {})
                    if attribute in n_data:
                        neighbor_vals.append(n_data[attribute])

                if neighbor_vals:
                    # Find value most consistent with neighbors
                    for val in conflicting_values:
                        if val in neighbor_vals:
                            return val, f"与邻域实体一致: {val}"
        except Exception as e:
            logger.warning("KG conflict resolution failed: %s", e)

        return conflicting_values[0], "KG无匹配; 使用首选值"

    def build_kg_from_sources(
        self,
        source_data: list[tuple[str, gpd.GeoDataFrame]],
        entity_column: str = "name",
    ) -> None:
        """Build/extend KG from multiple source GeoDataFrames.

        Args:
            source_data: List of (source_name, GeoDataFrame) tuples.
            entity_column: Column to use as entity identifier.
        """
        if not self.is_available:
            logger.info("KG not available; skipping KG build")
            return

        try:
            for source_name, gdf in source_data:
                if entity_column not in gdf.columns:
                    continue
                for _, row in gdf.iterrows():
                    entity = row.get(entity_column)
                    if pd.isna(entity):
                        continue
                    # Add entity node with attributes
                    attrs = {c: row[c] for c in gdf.columns
                             if c not in ("geometry", entity_column) and pd.notna(row[c])}
                    attrs["_source"] = source_name
                    if hasattr(self._kg, "graph"):
                        self._kg.graph.add_node(str(entity), **attrs)

            logger.info("KG enriched with %d sources", len(source_data))
        except Exception as e:
            logger.warning("Failed to build KG from sources: %s", e)

    def _query_entity(self, entity_name: str) -> tuple[dict, Optional[str]]:
        """Query KG for entity relationships and type."""
        try:
            if not hasattr(self._kg, "graph"):
                return {}, None

            if entity_name not in self._kg.graph:
                return {}, None

            node_data = self._kg.graph.nodes[entity_name]
            entity_type = node_data.get("entity_type") or node_data.get("type")

            # Get relationships
            rels = {}
            for neighbor in self._kg.graph.neighbors(entity_name):
                edge_data = self._kg.graph.edges[entity_name, neighbor]
                rel_type = edge_data.get("relationship", "related_to")
                rels.setdefault(rel_type, []).append(neighbor)

            return rels, entity_type
        except Exception:
            return {}, None
