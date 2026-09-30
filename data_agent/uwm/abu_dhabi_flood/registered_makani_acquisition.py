"""Governed, field-minimized snapshots from registered Makani source 13."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from .makani_probe import EXPECTED_SOURCE_BINDING
from .smartmakani_acquisition import TARGET_BBOX_WGS84, TARGET_CRS, canonical_json_bytes

REGISTERED_SNAPSHOT_SCHEMA = "gwm.abu_dhabi_flood.registered_makani_snapshot.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_FIELDS = frozenset(
    {
        "addressnumber",
        "addrkey",
        "asset_image",
        "comments",
        "created_user",
        "createdby",
        "inspected_by",
        "last_edited_user",
        "modifiedby",
        "roadname_ar",
        "roadname_en",
        "uploadeddirectory",
    }
)


@dataclass(frozen=True)
class RegisteredMakaniLayerSpec:
    table_name: str
    role: str
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.table_name):
            raise ValueError("registered_makani_table_name_invalid")
        if not _IDENTIFIER.fullmatch(self.role):
            raise ValueError("registered_makani_role_invalid")
        if not self.fields or self.fields[0] != "fid" or self.fields[-1] != "geom":
            raise ValueError("registered_makani_fields_require_fid_and_geom")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("registered_makani_fields_must_be_unique")
        if any(not _IDENTIFIER.fullmatch(field) for field in self.fields):
            raise ValueError("registered_makani_field_name_invalid")
        if _SENSITIVE_FIELDS.intersection(self.fields):
            raise ValueError("registered_makani_sensitive_field_selected")

    @property
    def resource_name(self) -> str:
        return f"layer.{self.table_name}"


LAYER_SPECS = (
    RegisteredMakaniLayerSpec(
        "st_pipeline",
        "pipeline",
        (
            "fid",
            "unitid",
            "uid",
            "asset_before",
            "asset_after",
            "outfallid",
            "pipe_diameter",
            "pipe_length",
            "pipe_material",
            "pipe_type",
            "gradient",
            "invert_level_upstream",
            "invert_level_downstream",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_inlet",
        "inlet",
        (
            "fid",
            "unitid",
            "asset_before",
            "asset_after",
            "outfallid",
            "invert_level",
            "ground_level",
            "cover_level",
            "outlet_diameter",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_catchbasin",
        "catchbasin",
        (
            "fid",
            "unitid",
            "asset_before",
            "asset_after",
            "outfallid",
            "invert_level",
            "cover_level",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_sw_node",
        "sw_node_virtual_topology",
        ("fid", "unitid", "asset_before", "asset_after", "geom"),
    ),
    RegisteredMakaniLayerSpec(
        "st_sw_junction",
        "sw_junction",
        (
            "fid",
            "unitid",
            "asset_before",
            "asset_after",
            "outfallid",
            "invert_level",
            "cover_level",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_outfall",
        "outfall",
        ("fid", "unitid", "invert_level", "base_level", "geom"),
    ),
    RegisteredMakaniLayerSpec(
        "st_ps_pump",
        "pump",
        (
            "fid",
            "unitid",
            "pump_station_id",
            "flow_rate",
            "head",
            "total_capacity",
            "power_kw",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_sw_pumpingstationstructure",
        "pumping_station_structure",
        (
            "fid",
            "unitid",
            "discharge",
            "ave_daily_capacity",
            "no_of_pumps",
            "head_m",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_sw_reservoirstructure",
        "reservoir_structure",
        (
            "fid",
            "unitid",
            "bed_level",
            "ground_level",
            "max_water_level",
            "reservoir_area",
            "reservoir_height",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_soakaway",
        "soakaway",
        (
            "fid",
            "unitid",
            "asset_before",
            "bottom_level",
            "ground_level",
            "invert_level",
            "soakaway_diameter",
            "soakaway_length",
            "soakaway_width",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_sw_cappedend",
        "capped_end",
        (
            "fid",
            "unitid",
            "asset_before",
            "invert_level",
            "cover_level",
            "asset_diameter",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_dischargechamber",
        "discharge_chamber",
        (
            "fid",
            "unitid",
            "asset_before",
            "asset_after",
            "outfallid",
            "invert_level",
            "bottom_level",
            "cover_level",
            "geom",
        ),
    ),
    RegisteredMakaniLayerSpec(
        "st_petrolinterceptor",
        "petrol_interceptor",
        (
            "fid",
            "unitid",
            "asset_before",
            "asset_after",
            "invert_level",
            "bottom_level",
            "cover_level",
            "inletpipe_lvl",
            "outletpipe_lvl",
            "geom",
        ),
    ),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def validate_registered_source(source: dict[str, Any]) -> dict[str, Any]:
    """Validate source identity and scope without returning credentials."""

    query_config = source.get("query_config") or {}
    observed = {
        "source_id": source.get("id"),
        "source_name": source.get("source_name"),
        "database_name": make_url(str(source.get("endpoint_url") or "")).database,
        "authorized_schemas": query_config.get("allowed_schemas"),
        "discovery_fingerprint": source.get("discovery_fingerprint"),
        "profile_fingerprint": source.get("profile_fingerprint"),
    }
    if observed != EXPECTED_SOURCE_BINDING:
        raise ValueError("registered_makani_source_binding_drift")
    if source.get("source_type") != "database" or source.get("enabled") is not True:
        raise ValueError("registered_makani_source_unavailable")
    if query_config.get("discovery_mode") != "metadata_only":
        raise ValueError("registered_makani_discovery_mode_changed")
    return observed


def _select_sql(spec: RegisteredMakaniLayerSpec) -> str:
    xmin, ymin, xmax, ymax = TARGET_BBOX_WGS84
    columns = ", ".join(f't."{field}"' for field in spec.fields)
    return (
        "WITH bounds AS (SELECT ST_Transform("
        f"ST_MakeEnvelope({xmin},{ymin},{xmax},{ymax},4326),32640) AS geom) "
        f"SELECT {columns} FROM \"layer\".\"{spec.table_name}\" t "
        "CROSS JOIN bounds b WHERE t.\"geom\" IS NOT NULL "
        "AND t.\"geom\" && b.geom AND ST_Intersects(t.\"geom\",b.geom) "
        "ORDER BY t.\"fid\""
    )


def _count_sql(spec: RegisteredMakaniLayerSpec) -> str:
    xmin, ymin, xmax, ymax = TARGET_BBOX_WGS84
    return (
        "WITH bounds AS (SELECT ST_Transform("
        f"ST_MakeEnvelope({xmin},{ymin},{xmax},{ymax},4326),32640) AS geom) "
        f"SELECT COUNT(*) FROM \"layer\".\"{spec.table_name}\" t "
        "CROSS JOIN bounds b WHERE t.\"geom\" IS NOT NULL "
        "AND t.\"geom\" && b.geom AND ST_Intersects(t.\"geom\",b.geom)"
    )


def _write_page(path: Path, frame: Any) -> dict[str, Any]:
    expected_columns = [column for column in frame.columns]
    if "fid" not in expected_columns or "geom" not in expected_columns:
        raise ValueError("registered_makani_page_shape_invalid")
    if frame["fid"].isna().any() or frame["fid"].duplicated().any():
        raise ValueError("registered_makani_page_fid_invalid")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("registered_makani_page_geometry_invalid")
    if frame.crs is None or frame.crs.to_epsg() != 32640:
        raise ValueError("registered_makani_page_crs_changed")
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    return {
        "path": path.name,
        "record_count": len(frame),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def download_registered_makani_snapshot(
    dataset_root: Path,
    *,
    owner: str = "abu-dhabi-site-operator",
    page_size: int = 5000,
    layer_specs: tuple[RegisteredMakaniLayerSpec, ...] = LAYER_SPECS,
) -> dict[str, Any]:
    """Download one transactionally consistent, field-minimized spatial snapshot."""

    if page_size < 100 or page_size > 10_000:
        raise ValueError("registered_makani_page_size_out_of_range")
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from data_agent.connectors.database import (
        _connect_args,
        _connection_url,
        _runtime_limits,
        _set_transaction_read_only,
    )
    from data_agent.virtual_sources import get_virtual_source

    source = get_virtual_source(int(EXPECTED_SOURCE_BINDING["source_id"]), owner)
    if source is None:
        raise ValueError("registered_makani_source_not_found")
    binding = validate_registered_source(source)
    query_config = source.get("query_config") or {}
    statement_timeout_ms, lock_timeout_ms, _ = _runtime_limits(query_config)
    engine = create_engine(
        _connection_url(source["endpoint_url"], source.get("auth_config") or {}),
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args=_connect_args(
            source["endpoint_url"],
            connect_timeout=10,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        ),
    )

    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    snapshot_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    snapshots_root = dataset_root / "online/makani_registered/snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    final_root = snapshots_root / snapshot_id
    layers: list[dict[str, Any]] = []

    try:
        with tempfile.TemporaryDirectory(
            dir=snapshots_root,
            prefix=f".{snapshot_id}.partial_",
        ) as temporary_name:
            temporary_root = Path(temporary_name)
            with engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                transaction = connection.begin()
                _set_transaction_read_only(
                    connection,
                    statement_timeout_ms=statement_timeout_ms,
                    lock_timeout_ms=lock_timeout_ms,
                )
                import geopandas as gpd

                for spec in layer_specs:
                    layer_root = temporary_root / spec.table_name
                    layer_root.mkdir(parents=True, exist_ok=True)
                    expected_count = int(
                        connection.execute(text(_count_sql(spec))).scalar_one()
                    )
                    pages: list[dict[str, Any]] = []
                    observed_fids: set[int] = set()
                    chunks = gpd.read_postgis(
                        text(_select_sql(spec)),
                        connection,
                        geom_col="geom",
                        chunksize=page_size,
                    )
                    for page_index, frame in enumerate(chunks):
                        expected_columns = list(spec.fields)
                        if list(frame.columns) != expected_columns:
                            raise ValueError(
                                f"registered_makani_columns_changed:{spec.table_name}"
                            )
                        page_fids = {int(value) for value in frame["fid"]}
                        if observed_fids.intersection(page_fids):
                            raise ValueError(
                                f"registered_makani_duplicate_fid:{spec.table_name}"
                            )
                        observed_fids.update(page_fids)
                        page_path = layer_root / f"page_{page_index:06d}.parquet"
                        pages.append(_write_page(page_path, frame))
                    if len(observed_fids) != expected_count:
                        raise ValueError(
                            f"registered_makani_count_mismatch:{spec.table_name}"
                        )
                    layer_manifest = {
                        "resource_name": spec.resource_name,
                        "role": spec.role,
                        "fields": list(spec.fields),
                        "record_count": expected_count,
                        "page_count": len(pages),
                        "pages": pages,
                        "crs": TARGET_CRS,
                        "contains_source_feature_rows": True,
                        "contains_raw_asset_identifiers": True,
                        "contains_personal_fields": False,
                        "admitted": False,
                    }
                    _atomic_write_json(layer_root / "manifest.json", layer_manifest)
                    layers.append(layer_manifest)
                transaction.commit()

            snapshot = {
                "schema": REGISTERED_SNAPSHOT_SCHEMA,
                "snapshot_id": snapshot_id,
                "created_at": created_at,
                "source_binding": binding,
                "authorization": {
                    "owner": owner,
                    "download_authorized_by_user": True,
                    "scope_expansion_allowed": False,
                },
                "query_policy": {
                    "read_only": True,
                    "transaction_isolation": "REPEATABLE READ",
                    "authorized_schema": "layer",
                    "target_bbox_wgs84": list(TARGET_BBOX_WGS84),
                    "target_crs": TARGET_CRS,
                    "page_size": page_size,
                    "field_minimized": True,
                },
                "layers": [
                    {
                        key: value
                        for key, value in layer.items()
                        if key != "pages"
                    }
                    for layer in layers
                ],
                "record_count": sum(layer["record_count"] for layer in layers),
                "page_count": sum(layer["page_count"] for layer in layers),
                "privacy": {
                    "contains_source_feature_rows": True,
                    "contains_raw_asset_identifiers": True,
                    "contains_personal_fields": False,
                    "credentials_persisted": False,
                },
                "admission": {
                    "admitted": False,
                    "operator_admitted": False,
                    "calibration_admitted": False,
                },
                "specification": [asdict(spec) for spec in layer_specs],
            }
            _atomic_write_json(temporary_root / "snapshot.json", snapshot)
            temporary_root.replace(final_root)
        pointer = {
            "schema": "gwm.abu_dhabi_flood.registered_makani_latest.v1",
            "snapshot_id": snapshot_id,
            "path": str(final_root.relative_to(dataset_root)),
            "snapshot_sha256": _sha256_file(final_root / "snapshot.json"),
        }
        _atomic_write_json(
            dataset_root / "online/makani_registered/latest_snapshot.json",
            pointer,
        )
        return snapshot
    finally:
        engine.dispose()


def layer_specs_as_json() -> str:
    return json.dumps([asdict(spec) for spec in LAYER_SPECS], sort_keys=True)
