"""
MetricFlow-compatible Semantic Model with GIS extensions (v19.0).

Stores YAML semantic model definitions with spatial dimension support.
Provides auto-generation from PostGIS table structure and
backward-compatible adapter for existing semantic_layer.py.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import yaml
from sqlalchemy import text

from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("semantic_model")


# ---------------------------------------------------------------------------
# YAML Schema (GIS-extended MetricFlow)
# ---------------------------------------------------------------------------

REQUIRED_MODEL_FIELDS = {"name"}
VALID_DIMENSION_TYPES = {"categorical", "time", "spatial"}
VALID_MEASURE_AGGS = {"sum", "count", "avg", "min", "max", "count_distinct"}


def validate_model(parsed: dict) -> list[str]:
    """Validate a parsed semantic model dict. Returns list of errors."""
    errors = []
    if not parsed.get("name"):
        errors.append("name is required")
    for dim in parsed.get("dimensions", []):
        if dim.get("type") and dim["type"] not in VALID_DIMENSION_TYPES:
            errors.append(f"dimension '{dim.get('name')}': invalid type '{dim['type']}'")
    for meas in parsed.get("measures", []):
        if meas.get("agg") and meas["agg"] not in VALID_MEASURE_AGGS:
            errors.append(f"measure '{meas.get('name')}': invalid agg '{meas['agg']}'")
    return errors


# ---------------------------------------------------------------------------
# SemanticModelStore — CRUD
# ---------------------------------------------------------------------------


class SemanticModelStore:
    """CRUD for agent_semantic_models table."""

    def load_from_yaml(self, yaml_text: str) -> dict:
        """Parse and validate a YAML semantic model definition.

        Returns parsed dict with extracted entities/dimensions/measures/metrics.
        Raises ValueError on validation failure.
        """
        try:
            raw = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

        # Support both top-level model and wrapped in semantic_models list
        if isinstance(raw, dict) and "semantic_models" in raw:
            models = raw["semantic_models"]
            if not models:
                raise ValueError("Empty semantic_models list")
            model = models[0]
        elif isinstance(raw, dict):
            model = raw
        else:
            raise ValueError("Expected a YAML mapping")

        errors = validate_model(model)
        if errors:
            raise ValueError(f"Validation errors: {'; '.join(errors)}")

        return {
            "name": model["name"],
            "description": model.get("description", ""),
            "source_table": model.get("source_table"),
            "srid": model.get("srid"),
            "geometry_type": model.get("geometry_type"),
            "entities": model.get("entities", []),
            "dimensions": model.get("dimensions", []),
            "measures": model.get("measures", []),
            "metrics": model.get("metrics", []),
        }

    def save(
        self,
        name: str,
        yaml_text: str,
        description: str = "",
        created_by: Optional[str] = None,
    ) -> Optional[int]:
        """Parse, validate, and upsert a semantic model. Returns id."""
        parsed = self.load_from_yaml(yaml_text)
        engine = get_engine()
        if not engine:
            return None
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        INSERT INTO agent_semantic_models
                            (name, description, yaml_content, parsed,
                             source_table, srid, geometry_type,
                             entities, dimensions, measures, metrics, created_by)
                        VALUES
                            (:name, :desc, :yaml, CAST(:parsed AS jsonb),
                             :src, :srid, :geom,
                             CAST(:ent AS jsonb), CAST(:dim AS jsonb), CAST(:meas AS jsonb), CAST(:met AS jsonb), :creator)
                        ON CONFLICT (name) DO UPDATE SET
                            description = EXCLUDED.description,
                            yaml_content = EXCLUDED.yaml_content,
                            parsed = EXCLUDED.parsed,
                            source_table = EXCLUDED.source_table,
                            srid = EXCLUDED.srid,
                            geometry_type = EXCLUDED.geometry_type,
                            entities = EXCLUDED.entities,
                            dimensions = EXCLUDED.dimensions,
                            measures = EXCLUDED.measures,
                            metrics = EXCLUDED.metrics,
                            version = agent_semantic_models.version + 1,
                            updated_at = NOW()
                        RETURNING id
                    """),
                    {
                        "name": name,
                        "desc": description or parsed.get("description", ""),
                        "yaml": yaml_text,
                        "parsed": json.dumps(parsed),
                        "src": parsed.get("source_table"),
                        "srid": parsed.get("srid"),
                        "geom": parsed.get("geometry_type"),
                        "ent": json.dumps(parsed.get("entities", [])),
                        "dim": json.dumps(parsed.get("dimensions", [])),
                        "meas": json.dumps(parsed.get("measures", [])),
                        "met": json.dumps(parsed.get("metrics", [])),
                        "creator": created_by,
                    },
                ).fetchone()
                conn.commit()
                return row[0] if row else None
        except Exception as e:
            logger.warning("Failed to save semantic model: %s", e)
            return None

    def get(self, name: str) -> Optional[dict]:
        engine = get_engine()
        if not engine:
            return None
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT id, name, description, yaml_content,
                               source_table, srid, geometry_type,
                               entities, dimensions, measures, metrics,
                               version, is_active, created_by, created_at
                        FROM agent_semantic_models WHERE name = :name
                    """),
                    {"name": name},
                ).fetchone()
                if not row:
                    return None
                return self._row_to_dict(row)
        except Exception as e:
            logger.warning("Failed to get semantic model: %s", e)
            return None

    def list_active(self) -> list[dict]:
        """List all active semantic models."""
        engine = get_engine()
        if not engine:
            return []
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, name, description, yaml_content,
                               source_table, srid, geometry_type,
                               entities, dimensions, measures, metrics,
                               version, is_active, created_by, created_at
                        FROM agent_semantic_models
                        WHERE is_active = TRUE
                        ORDER BY name
                    """)
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            logger.warning("Failed to list semantic models: %s", e)
            return []

    def delete(self, name: str) -> bool:
        engine = get_engine()
        if not engine:
            return False
        try:
            with engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM agent_semantic_models WHERE name = :name"),
                    {"name": name},
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("Failed to delete semantic model: %s", e)
            return False

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "yaml_content": row[3],
            "source_table": row[4],
            "srid": row[5],
            "geometry_type": row[6],
            "entities": row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]"),
            "dimensions": row[8] if isinstance(row[8], list) else json.loads(row[8] or "[]"),
            "measures": row[9] if isinstance(row[9], list) else json.loads(row[9] or "[]"),
            "metrics": row[10] if isinstance(row[10], list) else json.loads(row[10] or "[]"),
            "version": row[11],
            "is_active": row[12],
            "created_by": row[13],
            "created_at": row[14].isoformat() if row[14] else None,
        }


# ---------------------------------------------------------------------------
# Auto-generator from PostGIS table
# ---------------------------------------------------------------------------


class SemanticModelGenerator:
    """Auto-generate semantic model YAML from PostGIS table structure."""

    def generate_from_table(self, table_name: str) -> str:
        """Query table structure and generate a draft YAML model.

        Uses information_schema + geometry_columns for spatial metadata.
        Optionally calls LLM to suggest dimension/measure classification.
        """
        engine = get_engine()
        if not engine:
            raise RuntimeError("No database connection")

        with engine.connect() as conn:
            # Get columns
            cols = conn.execute(
                text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = :tbl
                    ORDER BY ordinal_position
                """),
                {"tbl": table_name},
            ).fetchall()

            if not cols:
                raise ValueError(f"Table '{table_name}' not found or has no columns")

            # Get geometry info
            geom_info = conn.execute(
                text("""
                    SELECT f_geometry_column, srid, type
                    FROM geometry_columns
                    WHERE f_table_name = :tbl
                    LIMIT 1
                """),
                {"tbl": table_name},
            ).fetchone()

        # Build model
        model = {
            "name": table_name,
            "source_table": table_name,
            "entities": [],
            "dimensions": [],
            "measures": [],
            "metrics": [],
        }

        if geom_info:
            model["srid"] = geom_info[1]
            model["geometry_type"] = geom_info[2]

        numeric_types = {"integer", "bigint", "numeric", "real", "double precision", "smallint"}

        for col_name, data_type, _ in cols:
            if col_name == "id":
                model["entities"].append({"name": col_name, "type": "primary", "column": col_name})
            elif geom_info and col_name == geom_info[0]:
                model["dimensions"].append({
                    "name": col_name,
                    "type": "spatial",
                    "column": col_name,
                    "srid": geom_info[1],
                    "geometry_type": geom_info[2],
                })
            elif data_type in numeric_types:
                model["measures"].append({
                    "name": col_name,
                    "agg": "sum",
                    "column": col_name,
                })
            elif data_type in ("character varying", "text"):
                model["dimensions"].append({
                    "name": col_name,
                    "type": "categorical",
                    "column": col_name,
                })
            elif "timestamp" in data_type or data_type == "date":
                model["dimensions"].append({
                    "name": col_name,
                    "type": "time",
                    "column": col_name,
                })

        # Generate simple metrics from measures
        for meas in model["measures"]:
            model["metrics"].append({
                "name": f"total_{meas['name']}",
                "type": "simple",
                "measure": meas["name"],
            })

        return yaml.dump(
            {"semantic_models": [model]},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
