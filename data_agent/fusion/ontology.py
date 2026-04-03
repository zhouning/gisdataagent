"""Fusion v2.0 — Ontology Reasoning module.

Loads GIS domain ontology from YAML, provides equivalence lookup,
field derivation, and inference rules for semantic field matching.
"""
import logging
import math
import os
from typing import Optional

import geopandas as gpd
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

_DEFAULT_ONTOLOGY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "standards", "gis_ontology.yaml"
)


class OntologyReasoner:
    """GIS domain ontology reasoning for semantic field matching and derivation."""

    def __init__(self, ontology_path: Optional[str] = None):
        self._ontology_path = ontology_path or _DEFAULT_ONTOLOGY_PATH
        self._ontology: dict = {}
        self._equiv_index: dict[str, str] = {}       # field_lower → group_id
        self._derivation_index: dict[str, dict] = {}  # target → rule
        self._inference_rules: list[dict] = []
        self._load_ontology()

    def _load_ontology(self):
        """Load and index the ontology YAML file."""
        if not os.path.exists(self._ontology_path):
            logger.warning("Ontology file not found: %s", self._ontology_path)
            return

        try:
            with open(self._ontology_path, "r", encoding="utf-8") as f:
                self._ontology = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Failed to load ontology: %s", e)
            return

        # Build equivalence index
        for group in self._ontology.get("equivalences", []):
            gid = group["group_id"]
            for field in group.get("fields", []):
                self._equiv_index[field.lower()] = gid

        # Build derivation index
        for rule in self._ontology.get("derivations", []):
            self._derivation_index[rule["target"]] = rule

        # Index inference rules
        self._inference_rules = self._ontology.get("inference_rules", [])

        logger.info(
            "Ontology loaded: %d equivalence groups, %d derivations, %d inference rules",
            len(self._ontology.get("equivalences", [])),
            len(self._derivation_index),
            len(self._inference_rules),
        )

    @property
    def is_loaded(self) -> bool:
        return bool(self._ontology)

    def find_equivalent_fields(self, field_name: str) -> list[str]:
        """Return all known equivalent field names for the given field.

        Args:
            field_name: Field name to look up.

        Returns:
            List of equivalent field names (excluding the input itself), or [].
        """
        gid = self._equiv_index.get(field_name.lower())
        if not gid:
            return []

        for group in self._ontology.get("equivalences", []):
            if group["group_id"] == gid:
                return [f for f in group["fields"] if f.lower() != field_name.lower()]
        return []

    def find_field_matches_by_ontology(
        self,
        left_columns: list[dict],
        right_columns: list[dict],
    ) -> list[dict]:
        """Find field matches between two column sets using ontology equivalences.

        Args:
            left_columns: List of {name, dtype, ...} dicts for left source.
            right_columns: List of {name, dtype, ...} dicts for right source.

        Returns:
            List of {left, right, confidence, match_type} dicts.
        """
        if not self._equiv_index:
            return []

        matches = []
        matched_right = set()

        for left_col in left_columns:
            left_name = left_col["name"]
            left_gid = self._equiv_index.get(left_name.lower())
            if not left_gid:
                continue

            for right_col in right_columns:
                right_name = right_col["name"]
                if right_name.lower() in matched_right:
                    continue
                right_gid = self._equiv_index.get(right_name.lower())
                if right_gid == left_gid:
                    matches.append({
                        "left": left_name,
                        "right": right_name,
                        "confidence": 0.85,
                        "match_type": "ontology",
                        "group_id": left_gid,
                    })
                    matched_right.add(right_name.lower())
                    break  # 1:1 matching

        return matches

    def derive_missing_fields(
        self, gdf: gpd.GeoDataFrame,
    ) -> tuple[gpd.GeoDataFrame, list[str]]:
        """Compute derivable fields from available columns using ontology rules.

        Args:
            gdf: Input GeoDataFrame.

        Returns:
            (enhanced_gdf, list_of_derived_field_names).
        """
        derived = []
        result = gdf.copy()

        for target, rule in self._derivation_index.items():
            if target in result.columns:
                continue  # Already exists

            required = rule.get("required_fields", [])
            # Resolve required fields through equivalences
            resolved = {}
            for req in required:
                col = self._resolve_column(result, req)
                if col is None:
                    break
                resolved[req] = col
            else:
                # All required fields found — compute
                try:
                    formula = rule["formula"]
                    result[target] = self._eval_formula(result, formula, resolved)
                    derived.append(target)
                    logger.info("Derived field '%s' using formula: %s", target, formula)
                except Exception as e:
                    logger.warning("Failed to derive '%s': %s", target, e)

        return result, derived

    def apply_inference_rules(
        self, gdf: gpd.GeoDataFrame,
    ) -> tuple[gpd.GeoDataFrame, list[str]]:
        """Apply inference rules to classify features.

        Args:
            gdf: Input GeoDataFrame.

        Returns:
            (enhanced_gdf, list_of_inferred_field_names).
        """
        inferred = []
        result = gdf.copy()

        for rule in self._inference_rules:
            conclusion = rule.get("conclusion", {})
            target_field = conclusion.get("field")
            target_value = conclusion.get("value")
            if not target_field or not target_value:
                continue

            conditions = rule.get("conditions", [])
            mask = pd.Series(True, index=result.index)

            for cond in conditions:
                col = self._resolve_column(result, cond["field"])
                if col is None:
                    mask = pd.Series(False, index=result.index)
                    break
                mask &= self._eval_condition(result[col], cond["operator"], cond["value"])

            if mask.any():
                if target_field not in result.columns:
                    result[target_field] = None
                result.loc[mask, target_field] = target_value
                if target_field not in inferred:
                    inferred.append(target_field)

        return result, inferred

    # --- Private helpers ---

    def _resolve_column(self, gdf: gpd.GeoDataFrame, field_name: str) -> Optional[str]:
        """Resolve a field name to an actual column, using ontology equivalences."""
        # Direct match
        if field_name in gdf.columns:
            return field_name

        # Check equivalences
        gid = self._equiv_index.get(field_name.lower())
        if gid:
            for group in self._ontology.get("equivalences", []):
                if group["group_id"] == gid:
                    for alias in group["fields"]:
                        if alias in gdf.columns:
                            return alias
                        # Case-insensitive check
                        for col in gdf.columns:
                            if col.lower() == alias.lower():
                                return col
        return None

    def _eval_formula(
        self, gdf: gpd.GeoDataFrame, formula: str, resolved: dict[str, str],
    ) -> pd.Series:
        """Safely evaluate a derivation formula using resolved column names."""
        # Build local namespace with resolved columns
        local_ns = {}
        for var_name, col_name in resolved.items():
            local_ns[var_name] = gdf[col_name].astype(float)

        # Replace variable names in formula and eval
        expr = formula
        for var_name in resolved:
            # Already available in namespace
            pass

        return pd.eval(expr, local_dict=local_ns)

    def _eval_condition(
        self, series: pd.Series, operator: str, value,
    ) -> pd.Series:
        """Evaluate a condition against a pandas Series."""
        if operator == ">=":
            return series.astype(float) >= float(value)
        elif operator == ">":
            return series.astype(float) > float(value)
        elif operator == "<=":
            return series.astype(float) <= float(value)
        elif operator == "<":
            return series.astype(float) < float(value)
        elif operator == "==":
            return series == value
        elif operator == "!=":
            return series != value
        elif operator == "startswith":
            return series.astype(str).str.startswith(str(value))
        elif operator == "contains":
            return series.astype(str).str.contains(str(value), na=False)
        else:
            logger.warning("Unknown operator: %s", operator)
            return pd.Series(False, index=series.index)
