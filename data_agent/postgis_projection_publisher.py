"""Publish a governed GeoParquet projection to a versioned PostGIS relation."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

from .offline_ingest import _utc_now, sha256_tree

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _identifier(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"invalid PostGIS {label}: {value}")
    return normalized


def _qualified(schema: str, relation: str) -> str:
    return f'"{schema}"."{relation}"'


def publish_geoparquet_to_postgis(
    projection_path: str | Path,
    *,
    projection_id: str,
    table_name: str = "land_parcel_current",
    schema: str = "public",
    engine=None,
    chunksize: int = 5000,
) -> dict[str, Any]:
    """Publish one governed lake version and atomically switch a stable view.

    The immutable GeoParquet remains the governed source. Each publication is
    written to a versioned physical table first; only after row-count
    validation does the stable semantic view move to that version.
    """

    source = Path(projection_path).expanduser().resolve()
    if not source.exists() or source.suffix.casefold() != ".parquet":
        raise FileNotFoundError(str(source))
    stable_table = _identifier(table_name, label="table name")
    schema_name = _identifier(schema, label="schema")
    version_token = re.sub(r"[^a-f0-9]", "", projection_id.casefold())[:12]
    version_table = _identifier(
        f"{stable_table}__{version_token}_{uuid.uuid4().hex[:8]}",
        label="version table name",
    )

    if engine is None:
        from .db_engine import get_engine

        engine = get_engine()
    if engine is None:
        raise RuntimeError(
            "PostGIS publication requires POSTGRES_HOST, POSTGRES_PORT, "
            "POSTGRES_DATABASE, POSTGRES_USER and POSTGRES_PASSWORD"
        )
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostGIS publication requires a PostgreSQL SQLAlchemy engine")

    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - offline package gate
        raise RuntimeError("geopandas is required for PostGIS publication") from exc

    frame = gpd.read_parquet(source)
    if not hasattr(frame, "geometry") or frame.geometry.name not in frame.columns:
        raise ValueError("governed GeoParquet does not contain an active geometry column")
    if frame.crs is None:
        raise ValueError("governed GeoParquet must declare a CRS before PostGIS publication")

    expected_rows = int(len(frame))
    qualified_version = _qualified(schema_name, version_table)
    qualified_stable = _qualified(schema_name, stable_table)
    geometry_column = str(frame.geometry.name)
    try:
        frame.to_postgis(
            version_table,
            engine,
            schema=schema_name,
            if_exists="fail",
            index=False,
            chunksize=max(100, int(chunksize)),
        )
        with engine.begin() as connection:
            published_rows = int(
                connection.execute(text(f"SELECT COUNT(*) FROM {qualified_version}")).scalar_one()
            )
            if published_rows != expected_rows:
                raise RuntimeError(
                    "PostGIS publication row-count mismatch: "
                    f"expected {expected_rows}, got {published_rows}"
                )
            index_name = _identifier(
                f"{version_table}_{geometry_column.lower()}_gist",
                label="index name",
            )
            connection.execute(
                text(
                    f'CREATE INDEX "{index_name}" ON {qualified_version} '
                    f'USING GIST ("{geometry_column}")'
                )
            )
            # Geography-distance predicates are the governed metre-based
            # representation for geographic CRS layers.  A functional GiST
            # index keeps ST_DWithin/ST_Distance from falling back to a
            # quadratic geometry-to-geography cast over the whole relation.
            if bool(getattr(frame.crs, "is_geographic", False)):
                geography_index_name = _identifier(
                    f"{version_table}_{geometry_column.lower()}_geog_gist",
                    label="index name",
                )
                connection.execute(
                    text(
                        f'CREATE INDEX "{geography_index_name}" ON {qualified_version} '
                        f'USING GIST (("{geometry_column}"::geography))'
                    )
                )
            relation_kind = connection.execute(
                text(
                    "SELECT c.relkind FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :relation"
                ),
                {"schema": schema_name, "relation": stable_table},
            ).scalar_one_or_none()
            if relation_kind == "v":
                connection.execute(text(f"DROP VIEW {qualified_stable}"))
            elif relation_kind is not None:
                raise RuntimeError(
                    "refusing to replace a non-view PostGIS relation at "
                    f"{schema_name}.{stable_table}"
                )
            connection.execute(
                text(f"CREATE VIEW {qualified_stable} AS SELECT * FROM {qualified_version}")
            )
            connection.execute(
                text(
                    f"COMMENT ON VIEW {qualified_stable} IS "
                    "'GIS Data Agent governed semantic projection'"
                )
            )
    except Exception:
        try:
            with engine.begin() as connection:
                connection.execute(text(f"DROP TABLE IF EXISTS {qualified_version} CASCADE"))
        except Exception:
            pass
        raise

    srid = frame.crs.to_epsg()
    return {
        "status": "succeeded",
        "engine": "postgis",
        "table_name": f"{schema_name}.{stable_table}",
        "version_table_name": f"{schema_name}.{version_table}",
        "projection_id": projection_id,
        "projection_path": str(source),
        "projection_sha256": sha256_tree(source),
        "row_count": expected_rows,
        "geometry_column": geometry_column,
        "srid": int(srid) if srid else None,
        "published_at": _utc_now(),
    }
