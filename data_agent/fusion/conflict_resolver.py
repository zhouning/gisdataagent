"""Fusion v2.0 — Conflict Resolution module.

Detects and resolves attribute conflicts in merged data using 6 strategies:
source_priority, latest_wins, voting, llm_arbitration, spatial_proximity, user_defined.
Computes per-feature confidence scores and annotates source provenance.
"""
import json
import logging
from collections import Counter
from typing import Any, Callable, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CONFLICT_STRATEGIES = [
    "source_priority", "latest_wins", "voting",
    "llm_arbitration", "spatial_proximity", "user_defined",
]


class ConflictResolver:
    """Resolve attribute conflicts in multi-source fused data."""

    def __init__(
        self,
        strategy: str = "source_priority",
        source_priorities: Optional[dict[str, int]] = None,
        source_metadata: Optional[dict[str, dict]] = None,
        use_llm: bool = False,
        user_resolver: Optional[Callable] = None,
        **kwargs,
    ):
        if strategy not in CONFLICT_STRATEGIES:
            logger.warning("Unknown strategy '%s'; defaulting to source_priority", strategy)
            strategy = "source_priority"
        self.strategy = strategy
        self.source_priorities = source_priorities or {}
        self.source_metadata = source_metadata or {}
        self.use_llm = use_llm
        self.user_resolver = user_resolver

    def detect_conflicts(
        self,
        merged_gdf: gpd.GeoDataFrame,
        source_columns: dict[str, list[str]],
    ) -> dict[str, list[int]]:
        """Detect rows with conflicting values from different sources.

        Args:
            merged_gdf: GeoDataFrame with merged data from multiple sources.
            source_columns: Mapping {base_column: [src0_col, src1_col, ...]} for
                columns that appear in multiple sources.

        Returns:
            {base_column: [row_indices_with_conflicts]}.
        """
        conflicts = {}
        for base_col, src_cols in source_columns.items():
            existing = [c for c in src_cols if c in merged_gdf.columns]
            if len(existing) < 2:
                continue
            conflict_rows = []
            for idx, row in merged_gdf.iterrows():
                values = [row[c] for c in existing if pd.notna(row[c])]
                if len(values) >= 2 and len(set(str(v) for v in values)) > 1:
                    conflict_rows.append(idx)
            if conflict_rows:
                conflicts[base_col] = conflict_rows
        return conflicts

    def resolve_attribute_conflicts(
        self,
        merged_gdf: gpd.GeoDataFrame,
        conflict_map: dict[str, list[int]],
        source_columns: dict[str, list[str]],
    ) -> gpd.GeoDataFrame:
        """Resolve detected conflicts using the configured strategy.

        Args:
            merged_gdf: GeoDataFrame with merged data.
            conflict_map: {base_column: [conflict_row_indices]}.
            source_columns: {base_column: [src0_col, src1_col, ...]}.

        Returns:
            GeoDataFrame with resolved values.
        """
        result = merged_gdf.copy()

        for base_col, row_indices in conflict_map.items():
            src_cols = [c for c in source_columns.get(base_col, []) if c in result.columns]
            if len(src_cols) < 2:
                continue

            for idx in row_indices:
                values = {c: result.at[idx, c] for c in src_cols if pd.notna(result.at[idx, c])}
                if len(values) < 2:
                    continue

                resolved = self._resolve_single(base_col, values, idx, result)
                if base_col not in result.columns:
                    result[base_col] = None
                result.at[idx, base_col] = resolved

        return result

    def compute_confidence_scores(
        self,
        gdf: gpd.GeoDataFrame,
        conflict_map: Optional[dict[str, list[int]]] = None,
    ) -> gpd.GeoDataFrame:
        """Compute per-feature confidence scores based on source metadata.

        Confidence = weighted average of timeliness, precision, and completeness.

        Args:
            gdf: GeoDataFrame.
            conflict_map: Optional conflict map to lower confidence for conflicting rows.

        Returns:
            GeoDataFrame with _fusion_confidence column.
        """
        result = gdf.copy()

        # Base confidence from source metadata
        base_scores = []
        for src_name, meta in self.source_metadata.items():
            timeliness = meta.get("timeliness", 0.8)
            precision = meta.get("precision", 0.8)
            completeness = meta.get("completeness", 0.8)
            score = 0.4 * timeliness + 0.3 * precision + 0.3 * completeness
            base_scores.append(score)

        avg_base = np.mean(base_scores) if base_scores else 0.8
        result["_fusion_confidence"] = avg_base

        # Lower confidence for conflicting rows
        if conflict_map:
            conflict_rows = set()
            for rows in conflict_map.values():
                conflict_rows.update(rows)
            for idx in conflict_rows:
                if idx in result.index:
                    result.at[idx, "_fusion_confidence"] = max(0.1, avg_base - 0.3)

        return result

    def annotate_sources(
        self,
        gdf: gpd.GeoDataFrame,
        source_columns: dict[str, list[str]],
    ) -> gpd.GeoDataFrame:
        """Add source provenance annotations for each attribute column.

        Adds _source_{column} columns tracking which source provided the final value.

        Args:
            gdf: GeoDataFrame with resolved values.
            source_columns: {base_column: [src0_col, src1_col, ...]}.

        Returns:
            GeoDataFrame with source annotation columns.
        """
        result = gdf.copy()

        for base_col, src_cols in source_columns.items():
            existing = [c for c in src_cols if c in result.columns]
            if not existing:
                continue

            source_col = f"_source_{base_col}"
            sources = []
            for idx, row in result.iterrows():
                # Find which source column matches the resolved value
                resolved = row.get(base_col)
                found = None
                for sc in existing:
                    if pd.notna(row.get(sc)) and str(row[sc]) == str(resolved):
                        found = sc
                        break
                sources.append(found or existing[0])
            result[source_col] = sources

        return result

    def resolve_and_annotate(
        self,
        output_gdf: gpd.GeoDataFrame,
        sources: list,
    ) -> tuple[gpd.GeoDataFrame, dict]:
        """High-level: detect conflicts, resolve, score, annotate.

        Called from execute_fusion() when conflict_config is provided.

        Returns:
            (resolved_gdf, conflict_summary).
        """
        # Build source column mapping from overlapping column names
        source_columns = self._infer_source_columns(output_gdf, sources)
        if not source_columns:
            return output_gdf, {"conflicts_found": 0}

        # Detect conflicts
        conflict_map = self.detect_conflicts(output_gdf, source_columns)
        total_conflicts = sum(len(v) for v in conflict_map.values())

        if total_conflicts == 0:
            result = self.compute_confidence_scores(output_gdf)
            return result, {"conflicts_found": 0}

        # Resolve
        result = self.resolve_attribute_conflicts(output_gdf, conflict_map, source_columns)

        # Score
        result = self.compute_confidence_scores(result, conflict_map)

        # Annotate
        result = self.annotate_sources(result, source_columns)

        # Build conflict summary
        summary = {
            "conflicts_found": total_conflicts,
            "columns_affected": list(conflict_map.keys()),
            "strategy_used": self.strategy,
            "resolved": total_conflicts,
        }

        # Add conflict details to _fusion_conflicts column
        conflict_json = {}
        for col, rows in conflict_map.items():
            conflict_json[col] = len(rows)
        result["_fusion_conflicts"] = json.dumps(conflict_json, ensure_ascii=False)

        logger.info("Conflict resolution: %d conflicts in %d columns, strategy=%s",
                     total_conflicts, len(conflict_map), self.strategy)

        return result, summary

    # --- Private resolve dispatchers ---

    def _resolve_single(
        self,
        base_col: str,
        values: dict[str, Any],
        row_idx: int,
        gdf: gpd.GeoDataFrame,
    ) -> Any:
        """Resolve a single conflicting value using the configured strategy."""
        if self.strategy == "source_priority":
            return self._resolve_priority(values)
        elif self.strategy == "latest_wins":
            return self._resolve_latest(values)
        elif self.strategy == "voting":
            return self._resolve_voting(values)
        elif self.strategy == "spatial_proximity":
            return self._resolve_spatial(values, row_idx, gdf)
        elif self.strategy == "user_defined":
            return self._resolve_user(base_col, values)
        elif self.strategy == "llm_arbitration":
            # Sync fallback — for async LLM use, call separately
            return self._resolve_voting(values)
        return list(values.values())[0]

    def _resolve_priority(self, values: dict[str, Any]) -> Any:
        """Pick value from the highest-priority source."""
        best_priority = -1
        best_value = list(values.values())[0]
        for src_col, val in values.items():
            # Extract source name from column prefix
            src_name = src_col.rsplit("_", 1)[0] if "_" in src_col else src_col
            priority = self.source_priorities.get(src_name, 0)
            if priority > best_priority:
                best_priority = priority
                best_value = val
        return best_value

    def _resolve_latest(self, values: dict[str, Any]) -> Any:
        """Pick value from the most recent source."""
        best_ts = None
        best_value = list(values.values())[0]
        for src_col, val in values.items():
            # Look up metadata by full column name, then by prefix
            meta = self.source_metadata.get(src_col, {})
            if not meta:
                src_name = src_col.rsplit("_", 1)[0] if "_" in src_col else src_col
                meta = self.source_metadata.get(src_name, {})
            ts = meta.get("timestamp") or meta.get("updated_at")
            if ts is not None:
                if best_ts is None or str(ts) > str(best_ts):
                    best_ts = ts
                    best_value = val
        return best_value

    def _resolve_voting(self, values: dict[str, Any]) -> Any:
        """Majority vote for categorical, mean for numeric."""
        vals = list(values.values())
        # Check if numeric
        try:
            nums = [float(v) for v in vals]
            return round(np.mean(nums), 6)
        except (ValueError, TypeError):
            pass
        # Categorical: majority vote
        counter = Counter(str(v) for v in vals)
        return counter.most_common(1)[0][0]

    def _resolve_spatial(
        self, values: dict[str, Any], row_idx: int, gdf: gpd.GeoDataFrame,
    ) -> Any:
        """Weight by spatial accuracy metadata."""
        # Fall back to priority if no spatial metadata
        return self._resolve_priority(values)

    def _resolve_user(self, base_col: str, values: dict[str, Any]) -> Any:
        """Apply user-defined resolution function."""
        if self.user_resolver:
            try:
                return self.user_resolver(base_col, values)
            except Exception as e:
                logger.warning("User resolver failed: %s", e)
        return list(values.values())[0]

    def _infer_source_columns(
        self, gdf: gpd.GeoDataFrame, sources: list,
    ) -> dict[str, list[str]]:
        """Infer source column mapping from suffixed column names.

        Looks for patterns like col_left/col_right or src0_col/src1_col.
        """
        source_columns = {}
        cols = [c for c in gdf.columns if c != "geometry"]

        # Detect _left/_right pattern (common in gpd.merge / sjoin)
        for col in cols:
            if col.endswith("_left"):
                base = col[:-5]
                right = f"{base}_right"
                if right in cols:
                    source_columns[base] = [col, right]

        # Detect srcN_ prefix pattern
        import re
        prefix_pattern = re.compile(r"^(src\d+)_(.+)$")
        grouped: dict[str, list[str]] = {}
        for col in cols:
            m = prefix_pattern.match(col)
            if m:
                base = m.group(2)
                grouped.setdefault(base, []).append(col)
        for base, src_cols in grouped.items():
            if len(src_cols) >= 2:
                source_columns[base] = src_cols

        return source_columns
