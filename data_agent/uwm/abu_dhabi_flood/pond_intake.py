"""Operator-run, read-only intake from registered databases and audited GDBs.

Customer rows remain in a private snapshot outside the repository. The web API
never accepts a database URL, local path, SQL, or a credential from a request.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .pond_planning import freeze_snapshot, sha256

GDB_SPECS = (
    ("DMT_StormWater_AbuDhabi_Processed.gdb.zip", "PIPELINE", "stormwater", "pipeline"),
    ("DMT_StormWater_AbuDhabi_Processed.gdb.zip", "INLET", "stormwater", "inlet"),
    ("DMT_StormWater_AbuDhabi_Processed.gdb.zip", "CATCHBASIN", "stormwater", "catchbasin"),
    ("DMT_StormWater_AbuDhabi_Processed.gdb.zip", "OUTFALL", "stormwater", "outfall"),
    ("DMT_StormWater_AbuDhabi_Processed.gdb.zip", "PS_PUMP", "stormwater", "pump"),
    ("AbuDhabi_AlDhafra_ElectricDistribution_Processed.gdb.zip", "SecUGElectricLineSegment", "utilities", "electric_distribution"),
    ("AbuDhabi_AlDhafra_ElectricDistribution_Processed.gdb.zip", "PriUGElectricLineSegment", "utilities", "electric_distribution"),
    ("ElectricTransmission_Processed.gdb.zip", "T_BuriedElectricLineSegment", "utilities", "electric_transmission"),
    ("AbuDhabi_AlDhafra_RecycledWater_Processed.gdb.zip", "PressurizedMain_RW", "utilities", "recycled_water"),
    ("Sewerage_ADSSC_Processed.gdb.zip", "ADSSC_S_SGravityPipe_proj", "utilities", "sewer_gravity"),
    ("Sewerage_ADSSC_Processed.gdb.zip", "ADSSC_S_SPressMain_proj", "utilities", "sewer_pressure"),
    ("WaterTransmission_Processed.gdb.zip", "Trans_SupplyMainPipe", "utilities", "water_transmission"),
    ("WaterTransmission_Processed.gdb.zip", "Trans_GravityPipe", "utilities", "water_transmission"),
    ("WaterTransmission_Processed.gdb.zip", "Trans_TrunkMainPipe", "utilities", "water_transmission"),
    ("AbuDhabi_AlDhafra_WaterDistribution_Processed.gdb.7z", "SectorMainPipe", "utilities", "water_distribution"),
    ("AbuDhabi_AlDhafra_WaterDistribution_Processed.gdb.7z", "MainPipe", "utilities", "water_distribution"),
    ("AbuDhabi_AlDhafra_WaterDistribution_Processed.gdb.7z", "ServiceLine", "utilities", "water_distribution"),
    ("TelecomData_Processed.gdb.7z", "L_DU_Span_proj", "utilities", "telecom"),
    ("TelecomData_Processed.gdb.7z", "L_ETISALAT_SPAN_proj", "utilities", "telecom"),
    ("DMT_IrrigationStormWater_AbuDhabi_Processed.gdb.zip", "IRRPRESSUREMAIN", "utilities", "irrigation"),
)
ENGINEERING_FIELDS = (
    "UID", "UNITID", "DATA_SOURCE", "INVERT_LEVEL_UPSTREAM", "INVERT_LEVEL_DOWNSTREAM", "PIPE_DIAMETER",
    "INVERT_LEVEL", "COVER_LEVEL", "FLOW_RATE", "HEAD", "StartCode", "EndCode", "PointCode",
    "StartElev", "EndElev", "StartElevSource", "EndElevSource", "GroundElev", "WellBottomElev", "ElevSource",
)


def open_registered_database(source: dict, database: str):
    import psycopg2
    if database not in {"flood", "makani_sync_full"} or not source.get("enabled") or source.get("credential_status") == "unavailable":
        raise ValueError("pond_source_binding_unavailable")
    endpoint = urlparse(source["endpoint_url"])
    if endpoint.scheme.split("+")[0] not in {"postgres", "postgresql"}:
        raise ValueError("pond_postgresql_source_required")
    auth = source.get("auth_config") or {}
    connection = psycopg2.connect(host=endpoint.hostname, port=endpoint.port or 5432, dbname=database,
        user=auth.get("username"), password=auth.get("password"), connect_timeout=10,
        application_name="pond_planning_readonly_intake",
        options="-c default_transaction_read_only=on -c statement_timeout=90000 -c lock_timeout=2000")
    connection.set_session(readonly=True, isolation_level="REPEATABLE READ", autocommit=False)
    return connection


def _query(connection, statement, params=()):
    from psycopg2.extras import RealDictCursor
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(statement, params)
        return [dict(row) for row in cursor.fetchall()]


def _collection(rows: list[dict], source: str) -> dict:
    features = []
    for row in rows:
        geometry = row.pop("geometry")
        if isinstance(geometry, str):
            geometry = json.loads(geometry)
        row["source_key"] = f"{source}:{row['source_fid']}"
        row["geometry_evidence"] = "source_asset_geometry_engineering_use_unverified"
        features.append({"type": "Feature", "properties": row, "geometry": geometry})
    # PostgreSQL numerics/timestamps are converted before entering the public contract.
    return json.loads(json.dumps({"type": "FeatureCollection", "features": features}, default=str))


def read_database_layers(connect: Callable, catchment_fids: list[int], *, context_buffer_m: float = 2000) -> tuple[dict, dict]:
    """Separate repeatable-read snapshots per database; no cross-DB atomicity claim."""
    from shapely.geometry import shape, mapping
    from shapely.ops import transform, unary_union
    from pyproj import Transformer
    if not catchment_fids or len(catchment_fids) > 8 or any(type(n) is not int or not 1 <= n <= 100000 for n in catchment_fids):
        raise ValueError("pond_intake_catchment_ids_invalid")
    if not 100 <= context_buffer_m <= 6000:
        raise ValueError("pond_intake_context_buffer_invalid")
    layers = {}
    evidence = {"selected_catchment_fids": [str(n) for n in sorted(set(catchment_fids))], "context_buffer_m": context_buffer_m,
                "database_read_only": True, "cross_database_atomic_snapshot": False, "database_snapshots": []}
    with closing(connect("flood")) as connection, connection:
        try:
            identity = _query(connection, "SELECT current_database() AS database, current_setting('transaction_read_only') AS read_only, txid_current_snapshot()::text AS transaction_snapshot, transaction_timestamp()::text AS transaction_time")[0]
            if identity["read_only"] != "on":
                raise ValueError("pond_readonly_transaction_required")
            evidence["database_snapshots"].append(identity)
            catchments = _query(connection, """SELECT ogc_fid::text AS source_fid, label, tbl_ha::float8 AS reported_area_ha,
                ST_Area(wkb_geometry) AS geometric_area_m2, ST_AsGeoJSON(ST_Transform(ST_Force2D(wkb_geometry),4326),8)::json AS geometry
                FROM catchment.catchment ORDER BY ogc_fid""")
            layers["catchments"] = _collection(catchments, "flood.catchment.catchment")
            selected = [f for f in layers["catchments"]["features"] if f["properties"]["source_fid"] in evidence["selected_catchment_fids"]]
            if len(selected) != len(evidence["selected_catchment_fids"]):
                raise ValueError("pond_intake_catchment_missing")
            to_m = Transformer.from_crs(4326, 32640, always_xy=True).transform
            to_ll = Transformer.from_crs(32640, 4326, always_xy=True).transform
            geometry = unary_union([transform(to_m, shape(f["geometry"])) for f in selected])
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError("pond_intake_catchment_invalid")
            context = geometry.buffer(context_buffer_m)
            context_ll = json.dumps(mapping(transform(to_ll, context)))
            evidence["context_bbox_epsg32640"] = list(context.bounds)
            evidence["context_geometry_wgs84"] = json.loads(context_ll)
            layers["hotspots"] = _collection(_query(connection, """SELECT record_id::text AS source_fid, hotspot_code, municipality, priority,
                pumps_qty::float8 AS pump_demand_count, detention_ponds_aed::float8 AS reported_pond_budget_aed,
                ST_AsGeoJSON(ST_Transform(ST_Force2D(geom),4326),8)::json AS geometry
                FROM hotspot.hotspot WHERE ST_Intersects(geom,ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),32640)) ORDER BY record_id""", (context_ll,)), "flood.hotspot.hotspot")
            layers["ponds"] = _collection(_query(connection, """SELECT gid::text AS source_fid, unitid, depth, volume, asset_area, data_source,
                projectid, status AS asset_status, condition AS asset_condition, cover_level, bottom_floor_level,
                no_of_connected_pipes, side_slope, floor_slope,
                ST_AsGeoJSON(ST_Transform(ST_Force2D(geom),4326),8)::json AS geometry
                FROM stormwater_drainage.pond WHERE ST_Intersects(geom,ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),32640)) ORDER BY gid""", (context_ll,)), "flood.stormwater_drainage.pond")
        finally:
            # Context-manager transaction completion is not a connection close.
            pass
    with closing(connect("makani_sync_full")) as connection, connection:
        identity = _query(connection, "SELECT current_database() AS database, current_setting('transaction_read_only') AS read_only, txid_current_snapshot()::text AS transaction_snapshot, transaction_timestamp()::text AS transaction_time")[0]
        if identity["read_only"] != "on":
            raise ValueError("pond_readonly_transaction_required")
        evidence["database_snapshots"].append(identity)
        layers["parcels"] = _collection(_query(connection, """SELECT objectid::text AS source_fid, objectid::text AS object_id,
            plotid::text AS plot_id, gisid::text AS gis_id, construction_status,
            ownershiptype AS ownership_type, planningstatus AS planning_status, elms_allocationstatus AS allocation_status,
            primaryuseeng, primaryuseengdesc, secuseeng, elms_landusename_e, elms_parentlanduse_e,
            elms_landuse_const, elms_parentlanduse_const, zonetpss,
            ST_AsGeoJSON(ST_Force2D(shape),8)::json AS geometry FROM public.udm_plot
            WHERE shape && ST_SetSRID(ST_GeomFromGeoJSON(%s),4326) AND ST_Intersects(shape,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))
            ORDER BY objectid""", (context_ll, context_ll)), "makani_sync_full.public.udm_plot")
        layers["corridors"] = _collection(_query(connection, """SELECT objectid::text AS source_fid, reservationtype AS reservation_type,
            ST_AsGeoJSON(ST_Force2D(shape),8)::json AS geometry FROM public.servicecorridor
            WHERE shape && ST_SetSRID(ST_GeomFromGeoJSON(%s),4326) AND ST_Intersects(shape,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))
            ORDER BY objectid""", (context_ll, context_ll)), "makani_sync_full.public.servicecorridor")
        layers["buildings"] = _collection(_query(connection, """SELECT objectid::text AS source_fid,
            buildingid, primaryuseengdesc, plot_primarylanduse, plot_seclanduse,
            ST_AsGeoJSON(ST_Force2D(shape),8)::json AS geometry FROM public.udm_building
            WHERE shape && ST_SetSRID(ST_GeomFromGeoJSON(%s),4326) AND ST_Intersects(shape,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))
            ORDER BY objectid""", (context_ll, context_ll)), "makani_sync_full.public.udm_building")
        layers["roads"] = _collection(_query(connection, """SELECT objectid::text AS source_fid,
            roadid, roadtype, roadtype_en, roadname_en, dmt_roadclass,
            ST_AsGeoJSON(ST_Force2D(shape),8)::json AS geometry FROM public.udm_adr_roadcentreline
            WHERE shape && ST_SetSRID(ST_GeomFromGeoJSON(%s),4326) AND ST_Intersects(shape,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))
            ORDER BY objectid""", (context_ll, context_ll)), "makani_sync_full.public.udm_adr_roadcentreline")
    return layers, evidence


def read_audited_gdb_layers(source_root: Path, audit_root: Path, context_geometry: dict, *, progress=print) -> tuple[dict, dict]:
    import pyogrio
    from shapely.geometry import shape
    from shapely.ops import transform
    from pyproj import Transformer
    inventory_path = audit_root / "submission_inventory.json"
    inventory = json.loads(inventory_path.read_text())
    archives = {a["archive"]: a for a in inventory["archives"]}
    for name, entry in archives.items():
        if Path(name).name != name or sha256(source_root / name) != entry["sha256"]:
            raise ValueError("pond_source_archive_checksum_mismatch")
    context = shape(context_geometry)
    output = {"stormwater": {"type": "FeatureCollection", "features": []}, "utilities": {"type": "FeatureCollection", "features": []}}
    source_receipts = []
    extracted = {}
    temporary_directories = []
    for archive, layer, target, role in GDB_SPECS:
        entry = archives[archive]
        matches = [g for g in entry["gdbs"] if any(l["layer_name"] == layer for l in g["layers"])]
        if len(matches) != 1:
            raise ValueError("pond_required_gdb_layer_missing_or_ambiguous")
        gdb = matches[0]
        if archive.endswith('.zip'):
            uri = f"/vsizip/{source_root / archive}/{gdb['gdb']}"
        else:
            if archive not in extracted:
                from pathlib import PurePosixPath
                names = subprocess.check_output(['/usr/bin/bsdtar', '-tf', str(source_root / archive)], text=True).splitlines()
                if any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts for n in names):
                    raise ValueError('pond_archive_member_path_invalid')
                temporary = tempfile.TemporaryDirectory(prefix='pond-intake-')
                temporary_directories.append(temporary)
                cache = Path(temporary.name)
                subprocess.run(['/usr/bin/bsdtar', '-xf', str(source_root / archive), '-C', str(cache)], check=True, capture_output=True)
                extracted[archive] = cache
            uri = str(extracted[archive] / gdb['gdb'])
        info = pyogrio.read_info(uri, layer=layer)
        if info["crs"] is None:
            raise ValueError("pond_gdb_crs_required")
        project = Transformer.from_crs(4326, info["crs"], always_xy=True).transform
        mask = transform(project, context)
        columns = [c for c in ENGINEERING_FIELDS if c in info["fields"]] if target == "stormwater" else []
        frame = pyogrio.read_dataframe(uri, layer=layer, columns=columns, bbox=mask.bounds, fid_as_index=True)
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
        frame = frame[frame.geometry.intersects(mask)].copy()
        source_fids = [str(n) for n in frame.index]
        frame = frame.to_crs(4326)
        frame["source_fid"] = source_fids
        frame["source_key"] = [f"gdb:{entry['sha256'][:16]}:{layer}:{n}" for n in source_fids]
        frame["asset_role"] = role
        frame["utility_type"] = role if target == "utilities" else None
        frame["engineering_admitted"] = False
        frame["geometry_evidence"] = "customer_processed_geometry"
        # Retain original and processed fields side by side; never fill engineering
        # inverts from StartElev or WellBottomElev merely because they are complete.
        geojson = json.loads(frame.to_json(drop_id=True, na="null"))
        output[target]["features"].extend(geojson["features"])
        source_receipts.append({"archive": archive, "archive_sha256": entry["sha256"], "gdb": gdb["gdb"], "layer": layer,
                                "source_crs": info["crs"], "source_count": int(info["features"]), "selected_count": len(frame)})
        progress(json.dumps({"layer": layer, "selected_count": len(frame)}))
    evidence = {"archives": [{"archive": name, "sha256": entry["sha256"]} for name, entry in sorted(archives.items())],
                "audit_inventory_sha256": sha256(inventory_path), "gdb_layers": source_receipts,
                "utility_coverage": "selected_submitted_line_classes_only; field_clearance_and_other_unmapped_assets_unverified",
                "source_summary": {"archives_verified": len(archives), "catalogued_gdbs": sum(len(a["gdbs"]) for a in archives.values()),
                                   "catalogued_layers": sum(len(g["layers"]) for a in archives.values() for g in a["gdbs"]), "ingested_gdb_layers": len(source_receipts)}}
    for temporary in temporary_directories:
        temporary.cleanup()
    return output, evidence


def build_intake(connect: Callable, source_root: Path, audit_root: Path, catchment_fids: list[int], *, root: Path | None = None, progress=print) -> dict:
    layers, provenance = read_database_layers(connect, catchment_fids)
    progress(json.dumps({"database_layer_counts": {k: len(v["features"]) for k, v in layers.items()}}))
    gdb_layers, gdb_evidence = read_audited_gdb_layers(source_root, audit_root, provenance["context_geometry_wgs84"], progress=progress)
    layers.update(gdb_layers)
    provenance.update(gdb_evidence)
    provenance.update({"evidence_class": "customer_source_unverified", "intake_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "quality_findings": [
            {"code": "processed_elevations_not_surveyed", "detail": "StartElev/EndElev are DEM-derived; full submission audit found uniform 1.2 ground-to-well offset.", "blocks": "engineering_hydraulics"},
            {"code": "procedural_pond_models", "detail": "3D pond models are not surveyed storage curves.", "blocks": "storage_capacity"},
            {"code": "land_permission_unverified", "detail": "Parcel or corridor presence does not establish excavation or discharge permission.", "blocks": "construction_recommendation"},
            {"code": "utility_coverage_partial", "detail": gdb_evidence["utility_coverage"], "blocks": "excavation_clearance"},
            {"code": "catchment_parts_not_merged", "detail": "Selection uses source FID, not potentially repeated labels; hydraulic boundary remains to be verified.", "blocks": "model_domain_admission"},
        ]})
    return freeze_snapshot(layers, provenance, root=root)
