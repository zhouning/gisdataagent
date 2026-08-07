"""Governed map publications for versioned catalog assets."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text

from .database_tools import _inject_user_context
from .db_engine import get_engine
from .observability import get_logger
from .user_context import current_tenant_id, current_user_id, current_user_role

logger = get_logger("map_publications")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_COLUMN_RE = re.compile(
    r"password|secret|token|email|phone|mobile|passport|national.?id|ssn|person",
    re.IGNORECASE,
)
_SUPPORTED_PROPERTY_TYPES = frozenset(
    {
        "bigint",
        "boolean",
        "character",
        "character varying",
        "double precision",
        "integer",
        "numeric",
        "real",
        "smallint",
        "text",
    }
)
_FEATURE_ID_CANDIDATES = (
    "feature_id",
    "objectid",
    "object_id",
    "fid",
    "gid",
    "id",
)
_PROPERTY_PRIORITY = (
    "NAMEENGLISH",
    "PRIMARYUSEENGDESC",
    "PHYSICALSTATUS",
    "DISTRTICTNAMEENG",
    "DISTRICTNAMEENG",
    "COMMUNITYNAMEENG",
    "MUNICIPALITYNAME",
    "BUILDINGHEIGHT",
    "SOURCE",
)


class MapPublicationError(RuntimeError):
    """Base map publication failure."""


class MapPublicationNotFound(MapPublicationError):
    pass


class MapPublicationForbidden(MapPublicationError):
    pass


class MapPublicationInvalid(MapPublicationError):
    pass


class MapPublicationMaterializationRequired(MapPublicationError):
    pass


class MapPublicationUnavailable(MapPublicationError):
    pass


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _qualified_table(value: str) -> tuple[str, str]:
    parts = str(value or "").split(".")
    if len(parts) == 1:
        parts.insert(0, "public")
    if len(parts) != 2 or not all(_IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise MapPublicationInvalid("Asset has an invalid PostGIS serving reference")
    return parts[0], parts[1]


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise MapPublicationInvalid("Database metadata contains an invalid identifier")
    return f'"{value}"'


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_resource_component(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-._")
    return (normalized or fallback)[:100]


def _publication_timestamp(publication: dict[str, Any]) -> datetime:
    value = publication.get("published_at") or publication.get("created_at")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _default_style(geometry_type: str) -> dict[str, Any]:
    normalized = geometry_type.upper()
    if "POINT" in normalized:
        return {
            "fillColor": "#dc2626",
            "fillOpacity": 0.75,
            "color": "#991b1b",
        }
    if "LINESTRING" in normalized:
        return {"fillColor": "#2563eb", "fillOpacity": 0.7, "color": "#1d4ed8"}
    return {"fillColor": "#0f766e", "fillOpacity": 0.45, "color": "#115e59"}


def _extent_payload(row: Any, feature_count: int) -> tuple[dict[str, float], dict[str, float]]:
    data_extent = {
        "minx": float(row["minx"]),
        "miny": float(row["miny"]),
        "maxx": float(row["maxx"]),
        "maxy": float(row["maxy"]),
    }
    percentile_values = (
        row["display_minx"],
        row["display_miny"],
        row["display_maxx"],
        row["display_maxy"],
    )
    if feature_count < 100 or any(value is None for value in percentile_values):
        return data_extent, dict(data_extent)

    minx, miny, maxx, maxy = (float(value) for value in percentile_values)
    x_padding = max((maxx - minx) * 0.03, 0.0001)
    y_padding = max((maxy - miny) * 0.03, 0.0001)
    display_extent = {
        "minx": max(-180.0, minx - x_padding),
        "miny": max(-90.0, miny - y_padding),
        "maxx": min(180.0, maxx + x_padding),
        "maxy": min(90.0, maxy + y_padding),
    }
    return data_extent, display_extent


class MapPublicationService:
    """Resolve catalog assets into authenticated Martin MVT publications."""

    def __init__(self, engine=None) -> None:
        self.engine = engine or get_engine()
        if self.engine is None:
            raise MapPublicationUnavailable("Database is not configured")

    @staticmethod
    def _asset_version(operational: dict[str, Any]) -> int:
        version = _json_object(operational.get("version")).get("version", 1)
        try:
            return max(1, int(version))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _choose_feature_id(columns: list[dict[str, str]]) -> str:
        by_lower = {column["name"].lower(): column["name"] for column in columns}
        for candidate in _FEATURE_ID_CANDIDATES:
            if candidate in by_lower:
                return by_lower[candidate]
        raise MapPublicationInvalid(
            "Map publication requires a stable feature identifier column"
        )

    @staticmethod
    def _choose_properties(
        columns: list[dict[str, str]],
        feature_id: str,
        requested: Any,
    ) -> list[str]:
        supported = {
            column["name"]: column
            for column in columns
            if column["data_type"] in _SUPPORTED_PROPERTY_TYPES
            and column["name"] != feature_id
            and not _SENSITIVE_COLUMN_RE.search(column["name"])
        }
        if requested is not None:
            if not isinstance(requested, list) or len(requested) > 16:
                raise MapPublicationInvalid("property_allowlist must contain at most 16 fields")
            result = []
            for raw_name in requested:
                name = str(raw_name)
                if name not in supported:
                    raise MapPublicationInvalid(f"Field is not eligible for map tiles: {name}")
                if name not in result:
                    result.append(name)
            return result

        result = [name for name in _PROPERTY_PRIORITY if name in supported]
        for name in supported:
            if name not in result:
                result.append(name)
            if len(result) >= 8:
                break
        return result[:8]

    @staticmethod
    def _layer_payload(publication: dict[str, Any]) -> dict[str, Any]:
        display_extent = _json_object(publication.get("display_extent"))
        bounds = [
            display_extent.get("minx"),
            display_extent.get("miny"),
            display_extent.get("maxx"),
            display_extent.get("maxy"),
        ]
        valid_bounds = all(isinstance(value, (int, float)) for value in bounds)
        if valid_bounds:
            center = [
                (float(bounds[1]) + float(bounds[3])) / 2,
                (float(bounds[0]) + float(bounds[2])) / 2,
            ]
        else:
            bounds = None
            center = None
        publication_id = str(publication["publication_id"])
        properties = [str(value) for value in _json_array(publication["property_allowlist"])]
        return {
            "layer_id": f"map-publication-{publication_id}",
            "publication_id": publication_id,
            "name": publication.get("display_name") or publication.get("asset_name"),
            "type": "mvt",
            "tile_url": (
                f"/api/map-publications/{publication_id}/tiles/{{z}}/{{x}}/{{y}}.pbf"
            ),
            "metadata_url": f"/api/map-publications/{publication_id}",
            "feature_url_template": (
                f"/api/map-publications/{publication_id}/features/{{feature_id}}"
            ),
            "source_layer": "map_publication",
            "style": _json_object(publication["style_config"]),
            "tooltip_fields": ["feature_id", *properties[:5]],
            "visible": True,
            "min_zoom": int(publication["min_zoom"]),
            "max_zoom": int(publication["max_zoom"]),
            "bounds": bounds,
            "center": center,
            "zoom": int(publication["min_zoom"]),
        }

    @classmethod
    def _serialize(cls, row: Any) -> dict[str, Any]:
        publication = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        for field in ("publication_id", "publication_run_id"):
            if publication.get(field) is not None:
                publication[field] = str(publication[field])
        for field in ("created_at", "published_at", "updated_at", "retired_at"):
            value = publication.get(field)
            if isinstance(value, datetime):
                publication[field] = value.astimezone(UTC).isoformat()
        publication["property_allowlist"] = _json_array(
            publication.get("property_allowlist")
        )
        publication["data_extent"] = _json_object(publication.get("data_extent"))
        publication["display_extent"] = _json_object(publication.get("display_extent"))
        publication["style_config"] = _json_object(publication.get("style_config"))
        publication.pop("source_schema", None)
        publication.pop("source_table", None)
        publication.pop("geometry_column", None)
        result = dict(publication)
        result["layer"] = cls._layer_payload(publication)
        return result

    def _load_asset(self, connection, asset_id: int) -> dict[str, Any]:
        _inject_user_context(connection)
        row = connection.execute(
            text(
                """
                SELECT asset.id, asset.asset_name, asset.display_name,
                       asset.owner_username, asset.is_shared,
                       asset.technical_metadata, asset.business_metadata,
                       asset.operational_metadata,
                       ingestion.tenant_id AS ingestion_tenant_id
                FROM public.agent_data_assets asset
                LEFT JOIN LATERAL (
                    SELECT tenant_id
                    FROM public.agent_ingestion_runs
                    WHERE asset_id = asset.id
                    ORDER BY completed_at DESC NULLS LAST
                    LIMIT 1
                ) ingestion ON TRUE
                WHERE asset.id = :asset_id
                """
            ),
            {"asset_id": asset_id},
        ).mappings().one_or_none()
        if row is None:
            raise MapPublicationNotFound("Asset not found or access denied")
        return dict(row)

    @staticmethod
    def _source_metadata(connection, schema: str, table_name: str) -> dict[str, Any]:
        geometry = connection.execute(
            text(
                """
                SELECT f_geometry_column, type, srid
                FROM public.geometry_columns
                WHERE f_table_schema = :schema AND f_table_name = :table_name
                ORDER BY f_geometry_column
                LIMIT 1
                """
            ),
            {"schema": schema, "table_name": table_name},
        ).mappings().one_or_none()
        if geometry is None:
            raise MapPublicationInvalid("PostGIS serving projection has no geometry column")

        columns = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT column_name AS name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table_name
                    ORDER BY ordinal_position
                    """
                ),
                {"schema": schema, "table_name": table_name},
            ).mappings()
        ]
        return {"geometry": dict(geometry), "columns": columns}

    @staticmethod
    def _compute_extents(
        connection,
        schema: str,
        table_name: str,
        geometry_column: str,
        feature_count: int,
    ) -> tuple[dict[str, float], dict[str, float]]:
        qualified = f"{_quote_identifier(schema)}.{_quote_identifier(table_name)}"
        geometry = _quote_identifier(geometry_column)
        row = connection.execute(
            text(
                f"""
                WITH spatial_features AS MATERIALIZED (
                    SELECT {geometry} AS geom,
                           ST_PointOnSurface({geometry}) AS label_point
                    FROM {qualified}
                    WHERE {geometry} IS NOT NULL AND NOT ST_IsEmpty({geometry})
                )
                SELECT ST_XMin(ST_Extent(geom)) AS minx,
                       ST_YMin(ST_Extent(geom)) AS miny,
                       ST_XMax(ST_Extent(geom)) AS maxx,
                       ST_YMax(ST_Extent(geom)) AS maxy,
                       percentile_cont(0.001) WITHIN GROUP (
                           ORDER BY ST_X(label_point)
                       ) AS display_minx,
                       percentile_cont(0.001) WITHIN GROUP (
                           ORDER BY ST_Y(label_point)
                       ) AS display_miny,
                       percentile_cont(0.999) WITHIN GROUP (
                           ORDER BY ST_X(label_point)
                       ) AS display_maxx,
                       percentile_cont(0.999) WITHIN GROUP (
                           ORDER BY ST_Y(label_point)
                       ) AS display_maxy
                FROM spatial_features
                """
            )
        ).mappings().one()
        if row["minx"] is None:
            raise MapPublicationInvalid("PostGIS serving projection contains no geometry")
        return _extent_payload(row, feature_count)

    def publish(self, asset_id: int, config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = config or {}
        if not isinstance(config, dict):
            raise MapPublicationInvalid("Map publication config must be an object")
        actor = current_user_id.get()
        role = current_user_role.get()
        if not actor or actor == "anonymous":
            raise MapPublicationForbidden("Authenticated publisher is required")

        with self.engine.begin() as connection:
            asset = self._load_asset(connection, int(asset_id))
            if asset["owner_username"] != actor and role != "admin":
                raise MapPublicationForbidden("Only the asset owner or an admin can publish")

            technical = _json_object(asset["technical_metadata"])
            storage = _json_object(technical.get("storage"))
            postgis_table = str(storage.get("postgis_table") or "").strip()
            if not postgis_table:
                raise MapPublicationMaterializationRequired(
                    "Asset requires a scheduled PostGIS serving projection before map publication"
                )
            source_schema, source_table = _qualified_table(postgis_table)
            source = self._source_metadata(connection, source_schema, source_table)
            geometry = source["geometry"]
            feature_id = self._choose_feature_id(source["columns"])
            properties = self._choose_properties(
                source["columns"], feature_id, config.get("property_allowlist")
            )

            operational = _json_object(asset["operational_metadata"])
            asset_version = self._asset_version(operational)
            checksums = _json_object(technical.get("checksums"))
            source_sha = str(checksums.get("target_content_sha256") or "").lower()
            if not _SHA256_RE.fullmatch(source_sha):
                source_sha = _canonical_sha256(
                    {
                        "asset_id": asset_id,
                        "asset_version": asset_version,
                        "lakehouse_uri": storage.get("lakehouse_uri"),
                        "postgis_table": postgis_table,
                    }
                )
            try:
                feature_count = int(
                    _json_object(technical.get("structure")).get("feature_count") or 0
                )
            except (TypeError, ValueError):
                feature_count = 0

            min_zoom = int(config.get("min_zoom", 9 if feature_count >= 100_000 else 0))
            max_zoom = int(config.get("max_zoom", 20))
            max_features = int(config.get("max_features_per_tile", 50_000))
            if not 0 <= min_zoom <= max_zoom <= 30:
                raise MapPublicationInvalid("Invalid map publication zoom range")
            if not 100 <= max_features <= 100_000:
                raise MapPublicationInvalid("Invalid max_features_per_tile")
            style = config.get("style") or _default_style(str(geometry["type"]))
            if not isinstance(style, dict):
                raise MapPublicationInvalid("Map style must be an object")

            config_document = {
                "feature_id_column": feature_id,
                "property_allowlist": properties,
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "max_features_per_tile": max_features,
                "style": style,
            }
            config_sha = _canonical_sha256(config_document)
            existing = connection.execute(
                text(
                    """
                    SELECT publication.*, asset.asset_name, asset.display_name
                    FROM public.agent_map_publications publication
                    JOIN public.agent_data_assets asset ON asset.id = publication.asset_id
                    WHERE publication.tenant_id = :tenant_id
                      AND publication.asset_id = :asset_id
                      AND publication.asset_version = :asset_version
                      AND publication.config_sha256 = :config_sha
                      AND publication.status = 'ready'
                    """
                ),
                {
                    "tenant_id": current_tenant_id.get()
                    or asset.get("ingestion_tenant_id")
                    or "local-dev",
                    "asset_id": asset_id,
                    "asset_version": asset_version,
                    "config_sha": config_sha,
                },
            ).one_or_none()
            if existing is not None:
                existing_result = dict(existing._mapping)
                platform_lineage = self._publish_platform_lineage(existing_result)
                serialized = self._serialize(existing_result)
                serialized["platform_lineage"] = platform_lineage
                return serialized

            data_extent, display_extent = self._compute_extents(
                connection,
                source_schema,
                source_table,
                str(geometry["f_geometry_column"]),
                feature_count,
            )
            publication_id = uuid4()
            run_id = uuid4()
            tenant_id = (
                current_tenant_id.get()
                or asset.get("ingestion_tenant_id")
                or "local-dev"
            )
            row = connection.execute(
                text(
                    """
                    INSERT INTO public.agent_map_publications (
                        publication_id, tenant_id, asset_id, asset_version,
                        source_content_sha256, config_sha256, publication_run_id,
                        source_schema, source_table, geometry_column, geometry_type,
                        geometry_srid, feature_id_column, property_allowlist,
                        data_extent, display_extent, min_zoom, max_zoom,
                        max_features_per_tile, style_config, status, created_by,
                        published_at
                    ) VALUES (
                        :publication_id, :tenant_id, :asset_id, :asset_version,
                        :source_sha, :config_sha, :run_id,
                        :source_schema, :source_table, :geometry_column, :geometry_type,
                        :geometry_srid, :feature_id, CAST(:properties AS jsonb),
                        CAST(:data_extent AS jsonb), CAST(:display_extent AS jsonb),
                        :min_zoom, :max_zoom, :max_features, CAST(:style AS jsonb),
                        'ready', :actor, NOW()
                    )
                    ON CONFLICT (tenant_id, asset_id, asset_version, config_sha256)
                    DO UPDATE SET
                        status = 'ready', error_message = NULL,
                        publication_run_id = EXCLUDED.publication_run_id,
                        published_at = NOW(), updated_at = NOW()
                    RETURNING *
                    """
                ),
                {
                    "publication_id": publication_id,
                    "tenant_id": tenant_id,
                    "asset_id": asset_id,
                    "asset_version": asset_version,
                    "source_sha": source_sha,
                    "config_sha": config_sha,
                    "run_id": run_id,
                    "source_schema": source_schema,
                    "source_table": source_table,
                    "geometry_column": geometry["f_geometry_column"],
                    "geometry_type": geometry["type"],
                    "geometry_srid": int(geometry["srid"]),
                    "feature_id": feature_id,
                    "properties": json.dumps(properties),
                    "data_extent": json.dumps(data_extent),
                    "display_extent": json.dumps(display_extent),
                    "min_zoom": min_zoom,
                    "max_zoom": max_zoom,
                    "max_features": max_features,
                    "style": json.dumps(style),
                    "actor": actor,
                },
            ).one()
            publication_id = row._mapping["publication_id"]
            run_id = row._mapping["publication_run_id"]
            connection.execute(
                text(
                    """
                    INSERT INTO public.agent_map_publication_events (
                        publication_id, event_type, status, actor,
                        publication_run_id, details
                    ) VALUES (
                        :publication_id, 'published', 'ready', :actor,
                        :run_id, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "publication_id": publication_id,
                    "actor": actor,
                    "run_id": run_id,
                    "details": json.dumps(
                        {
                            "asset_id": asset_id,
                            "asset_version": asset_version,
                            "source_content_sha256": source_sha,
                            "config_sha256": config_sha,
                        }
                    ),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO public.agent_asset_lineage (
                        source_asset_id, target_external_system, target_external_id,
                        relationship, tool_name, pipeline_run_id, metadata, created_by
                    ) SELECT
                        :asset_id, 'map_publication', :publication_id,
                        'published_as', 'governed_map_publication', :run_id,
                        CAST(:metadata AS jsonb), :actor
                    WHERE NOT EXISTS (
                        SELECT 1 FROM public.agent_asset_lineage
                        WHERE source_asset_id = :asset_id
                          AND target_external_system = 'map_publication'
                          AND target_external_id = :publication_id
                    )
                    """
                ),
                {
                    "asset_id": asset_id,
                    "publication_id": str(publication_id),
                    "run_id": str(run_id),
                    "metadata": json.dumps(
                        {
                            "asset_version": asset_version,
                            "source_content_sha256": source_sha,
                            "config_sha256": config_sha,
                            "serving_kind": "mvt",
                        }
                    ),
                    "actor": actor,
                },
            )
            result = dict(row._mapping)
            result["asset_name"] = asset["asset_name"]
            result["display_name"] = asset["display_name"]

        platform_lineage = self._publish_platform_lineage(result)
        serialized = self._serialize(result)
        serialized["platform_lineage"] = platform_lineage
        return serialized

    def _publication_query(self, where_clause: str, parameters: dict[str, Any]):
        with self.engine.connect() as connection:
            _inject_user_context(connection)
            return connection.execute(
                text(
                    f"""
                    SELECT publication.*, asset.asset_name, asset.display_name
                    FROM public.agent_map_publications publication
                    JOIN public.agent_data_assets asset ON asset.id = publication.asset_id
                    WHERE {where_clause}
                    ORDER BY publication.asset_version DESC,
                             publication.published_at DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                parameters,
            ).one_or_none()

    def current(self, asset_id: int) -> dict[str, Any]:
        row = self._publication_query(
            "publication.asset_id = :asset_id AND publication.status = 'ready'",
            {"asset_id": int(asset_id)},
        )
        if row is None:
            raise MapPublicationNotFound("No ready map publication for this asset")
        return self._serialize(row)

    def get(self, publication_id: UUID | str) -> dict[str, Any]:
        try:
            normalized = UUID(str(publication_id))
        except (TypeError, ValueError) as exc:
            raise MapPublicationNotFound("Map publication not found") from exc
        row = self._publication_query(
            "publication.publication_id = :publication_id",
            {"publication_id": normalized},
        )
        if row is None:
            raise MapPublicationNotFound("Map publication not found or access denied")
        return self._serialize(row)

    def feature(self, publication_id: UUID | str, feature_id: str) -> dict[str, Any]:
        publication = self.get(publication_id)
        with self.engine.connect() as connection:
            _inject_user_context(connection)
            raw = connection.execute(
                text(
                    """
                    SELECT source_schema, source_table, geometry_column,
                           feature_id_column, property_allowlist
                    FROM public.agent_map_publications
                    WHERE publication_id = :publication_id AND status = 'ready'
                    """
                ),
                {"publication_id": UUID(str(publication_id))},
            ).mappings().one_or_none()
            if raw is None:
                raise MapPublicationNotFound("Map publication not found")
            fields = [
                str(value) for value in _json_array(raw["property_allowlist"])
            ]
            select_fields = ", ".join(_quote_identifier(field) for field in fields)
            if select_fields:
                select_fields = ", " + select_fields
            qualified = (
                f"{_quote_identifier(raw['source_schema'])}."
                f"{_quote_identifier(raw['source_table'])}"
            )
            id_column = _quote_identifier(raw["feature_id_column"])
            geometry = _quote_identifier(raw["geometry_column"])
            row = connection.execute(
                text(
                    f"""
                    SELECT {id_column}::text AS feature_id{select_fields},
                           ST_AsGeoJSON(ST_Envelope({geometry}))::jsonb AS geometry_extent
                    FROM {qualified}
                    WHERE {id_column}::text = :feature_id
                    LIMIT 1
                    """
                ),
                {"feature_id": str(feature_id)},
            ).mappings().one_or_none()
        if row is None:
            raise MapPublicationNotFound("Feature not found")
        return {
            "publication_id": str(publication_id),
            "asset_id": publication["asset_id"],
            "feature": dict(row),
        }

    @staticmethod
    def _publish_platform_lineage(publication: dict[str, Any]) -> dict[str, Any]:
        try:
            from .platform_contracts import (
                LineageEvent,
                LineageEventType,
                Resource,
                ResourceVersion,
                canonical_json_fingerprint,
            )
            from .platform_gateway import GatewayNotFoundError, PlatformGateway

            tenant_id = str(publication["tenant_id"])
            asset_id = int(publication["asset_id"])
            source_sha = str(publication["source_content_sha256"])
            config_sha = str(publication["config_sha256"])
            source_slug = _safe_resource_component(
                str(publication["asset_name"]), f"asset-{asset_id}"
            )
            source_urn = f"gda://{tenant_id}/dataset/{source_slug}"
            source_version_id = uuid5(NAMESPACE_URL, f"{source_urn}:{source_sha}")
            target_urn = f"gda://{tenant_id}/map_layer/asset-{asset_id}"
            target_sha = _canonical_sha256(
                {"source_content_sha256": source_sha, "config_sha256": config_sha}
            )
            target_version_id = uuid5(NAMESPACE_URL, f"{target_urn}:{target_sha}")
            publication_id = str(publication["publication_id"])
            gateway = PlatformGateway()
            gateway.get_resource_version(tenant_id, source_version_id)
            try:
                existing_target = gateway.get_resource_version(
                    tenant_id, target_version_id
                )
            except GatewayNotFoundError:
                existing_target = None
            publication_time = _publication_timestamp(publication)
            target_created_at = (
                existing_target.created_at if existing_target else publication_time
            )
            gateway.register_resource(
                Resource(
                    tenant_id=tenant_id,
                    resource_urn=target_urn,
                    resource_kind="map_layer",
                    authority_system="gis_data_agent",
                    authority_locator=f"asset:{asset_id}:map",
                    owner_ref=f"human:{publication['created_by']}",
                    governance_ref={"distribution_channel": "authenticated_mvt"},
                    technical_refs=({"tile_proxy": "/api/map-publications"},),
                )
            )
            gateway.register_resource_version(
                ResourceVersion(
                    tenant_id=tenant_id,
                    resource_urn=target_urn,
                    resource_version_id=target_version_id,
                    version_key=f"sha256-{target_sha[:12]}",
                    content_sha256=target_sha,
                    authority_version_ref={
                        "asset_id": asset_id,
                        "asset_version": int(publication["asset_version"]),
                        "publication_id": publication_id,
                        "source_content_sha256": source_sha,
                        "config_sha256": config_sha,
                    },
                    created_by="workload:gda-map-publication",
                    created_at=target_created_at,
                )
            )
            facets = {
                "schema": "gda.map_publication_lineage.v1",
                "asset_id": asset_id,
                "asset_version": int(publication["asset_version"]),
                "publication_id": publication_id,
                "source_content_sha256": source_sha,
                "config_sha256": config_sha,
                "serving_kind": "mvt",
            }
            lineage_id = uuid5(target_version_id, f"publish:{source_version_id}")
            gateway.record_lineage(
                LineageEvent(
                    tenant_id=tenant_id,
                    lineage_event_id=lineage_id,
                    event_type=LineageEventType.PUBLISH,
                    source_resource_version_id=source_version_id,
                    target_resource_version_id=target_version_id,
                    producer="workload:gda-map-publication",
                    event_sha256=canonical_json_fingerprint(facets),
                    facets=facets,
                    occurred_at=target_created_at,
                )
            )
            return {
                "status": "recorded",
                "target_resource_urn": target_urn,
                "target_resource_version_id": str(target_version_id),
                "lineage_event_id": str(lineage_id),
                "metadata_projection": "queued_by_lineage_outbox",
            }
        except Exception as exc:
            logger.warning("Map publication platform lineage bridge failed: %s", exc)
            return {"status": "unavailable", "message": str(exc)[:300]}
