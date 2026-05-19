"""Load FloodSQL-Bench parquet files into PostgreSQL/PostGIS.

Creates a `floodsql` schema in the existing flights_dataset database to
keep tables isolated from the v7 CQ benchmark. Uses geopandas.to_postgis
for tables with geometry and pandas.to_sql for the rest.

Usage:
    .venv/Scripts/python.exe scripts/floodsql/load_floodsql.py
       [--dry-run]  # only print DDL plan, don't touch DB
       [--drop]     # drop existing floodsql schema first
       [--only TABLE]  # load just one table (debug)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkb
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATA_DIR = Path("D:/adk/data/floodsql_bench/data")
SCHEMA = os.environ.get("FLOODSQL_SCHEMA", "floodsql")

# (table_name, parquet_filename, has_geometry, geom_type)
# Note: hospitals' geometry column is empty BLOBs (论文 A.1: "opaque point
# BLOBs are discarded"); gold SQL uses ST_Point(LON, LAT) on the fly.
TABLES = [
    ("census_tracts", "census_tracts_tx_fl_la.parquet", True, "MULTIPOLYGON"),
    ("county",        "county_tx_fl_la.parquet",        True, "MULTIPOLYGON"),
    ("floodplain",    "floodplain_tx_fl_la.parquet",    True, "MULTIPOLYGON"),
    ("zcta",          "zcta_tx_fl_la.parquet",          True, "MULTIPOLYGON"),
    ("claims",        "claims_tx_fl_la.parquet",        True, "POINT"),
    ("hospitals",     "hospitals_tx_fl_la.parquet",     False, None),
    ("schools",       "schools_tx_fl_la.parquet",       False, None),
    ("svi",           "svi_tx_fl_la.parquet",           False, None),
    ("nri",           "nri_tx_fl_la.parquet",           False, None),
    ("cre",           "cre_tx_fl_la.parquet",           False, None),
]

# Per-table indexes to create AFTER load. GIST on geometry, BTREE on join keys.
# All column names are lowercase to match the lowercased load (see load_table).
INDEXES = {
    "census_tracts": ["GIST(geometry)", "geoid", "statefp"],
    "county":        ["GIST(geometry)", "geoid", "statefp"],
    "floodplain":    ["GIST(geometry)", "statefp"],
    "zcta":          ["GIST(geometry)", "geoid", "statefp"],
    "claims":        ["geoid", "statefp", "dateofloss"],
    "hospitals":     ["zip", "statefp", "countyfips", "lat", "lon"],
    "schools":       ["zip", "statefp"],
    "svi":           ["geoid", "state"],
    "nri":           ["geoid", "state"],
    "cre":           ["geoid"],
}


def get_engine() -> Engine:
    from urllib.parse import quote_plus
    host = os.environ.get("POSTGRES_HOST", "119.3.175.198")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db   = os.environ.get("POSTGRES_DATABASE", "flights_dataset")
    user = os.environ.get("POSTGRES_USER", "agent_user")
    pwd  = os.environ.get("POSTGRES_PASSWORD", "SuperMap@123")
    # URL-encode user/password — '@' in 'SuperMap@123' would otherwise be
    # parsed as the host delimiter.
    url = f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(pwd)}@{host}:{port}/{db}"
    return create_engine(url, pool_pre_ping=True)


def setup_schema(engine: Engine, drop: bool = False):
    with engine.begin() as conn:
        if drop:
            print(f"  [drop] DROP SCHEMA {SCHEMA} CASCADE")
            conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        # PostGIS extension lives in the database, not in schema; ensure it's there
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    print(f"  [ok] schema {SCHEMA} ready")


def load_table(engine: Engine, name: str, fname: str, has_geom: bool, geom_type: str | None):
    p = DATA_DIR / fname
    print(f"\n=== {name} ({p.name}) ===", flush=True)
    t0 = time.time()
    if has_geom:
        try:
            gdf = gpd.read_parquet(p)
        except (ValueError, Exception) as e:
            # Some parquets (e.g. hospitals) were written with pandas, not
            # geopandas, so they lack geo metadata. Fall back to pandas +
            # manual WKB → shapely conversion.
            if "geo metadata" in str(e).lower() or "missing geo" in str(e).lower():
                print(f"  [fallback] no geo metadata, using pandas + WKB decode", flush=True)
                df = pd.read_parquet(p)
                from shapely import wkb as _wkb
                df["geometry"] = df["geometry"].apply(
                    lambda b: _wkb.loads(b) if b is not None else None)
                gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
            else:
                raise
        # Force CRS to EPSG:4326 if not already (OGC:CRS84 is equivalent but be explicit)
        if gdf.crs is None or "4326" not in str(gdf.crs):
            print(f"  [crs] {gdf.crs} → setting EPSG:4326", flush=True)
            gdf = gdf.set_crs(4326, allow_override=True)
        # CRITICAL: lowercase column names (except geometry) so DuckDB-style
        # unquoted mixed-case references (e.g. dateOfLoss, RPL_THEME1) work
        # in PostgreSQL — PG folds unquoted identifiers to lowercase.
        gdf.columns = [c if c == "geometry" else c.lower() for c in gdf.columns]
        print(f"  [read] {len(gdf):,} rows, geom_type={gdf.geom_type.value_counts().to_dict()}", flush=True)
        gdf.to_postgis(name, engine, schema=SCHEMA, if_exists="replace",
                       index=False, chunksize=20_000)
    else:
        df = pd.read_parquet(p)
        # Drop the empty BLOB `geometry` column on hospitals — see TABLES note.
        if "geometry" in df.columns:
            df = df.drop(columns=["geometry"])
        df.columns = [c.lower() for c in df.columns]
        print(f"  [read] {len(df):,} rows, {len(df.columns)} cols", flush=True)
        df.to_sql(name, engine, schema=SCHEMA, if_exists="replace",
                  index=False, chunksize=20_000, method="multi")
    print(f"  [load] done in {time.time()-t0:.1f}s", flush=True)


def create_indexes(engine: Engine, name: str, idxs: list[str]):
    if not idxs:
        return
    print(f"\n=== indexes on {name} ===")
    with engine.begin() as conn:
        for i, idx in enumerate(idxs):
            t0 = time.time()
            if idx.upper().startswith("GIST"):
                col = idx[5:-1]  # GIST(geometry) → geometry
                stmt = (f'CREATE INDEX IF NOT EXISTS idx_{name}_geom '
                        f'ON {SCHEMA}.{name} USING GIST({col})')
            else:
                col_name = idx.replace('"', '').lower()
                stmt = (f'CREATE INDEX IF NOT EXISTS idx_{name}_{col_name} '
                        f'ON {SCHEMA}.{name} ({idx})')
            print(f"  [idx] {stmt}")
            conn.execute(text(stmt))
            print(f"        done in {time.time()-t0:.1f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--drop", action="store_true",
                    help="DROP SCHEMA floodsql CASCADE before loading")
    ap.add_argument("--only", default=None,
                    help="comma-separated table names to load (debug)")
    ap.add_argument("--skip-load", action="store_true",
                    help="only create indexes, skip parquet load")
    ap.add_argument("--skip-index", action="store_true",
                    help="only load data, skip index creation")
    args = ap.parse_args()

    if args.dry_run:
        print("=== DRY RUN — DDL plan ===")
        print(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE  -- only if --drop")
        print(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        for name, fname, has_geom, gt in TABLES:
            print(f"\n-- {name} from {fname}")
            print(f"  -> read {DATA_DIR / fname}")
            if has_geom:
                print(f"  -> geopandas.to_postgis({SCHEMA}.{name}, geom_type={gt})")
            else:
                print(f"  -> pandas.to_sql({SCHEMA}.{name})")
            for idx in INDEXES.get(name, []):
                print(f"  -> CREATE INDEX ... ON {SCHEMA}.{name} {idx}")
        return

    only = set(args.only.split(",")) if args.only else None
    engine = get_engine()
    setup_schema(engine, drop=args.drop)

    if not args.skip_load:
        for name, fname, has_geom, gt in TABLES:
            if only and name not in only:
                continue
            try:
                load_table(engine, name, fname, has_geom, gt)
            except Exception as e:
                print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
                continue

    if not args.skip_index:
        for name, fname, has_geom, gt in TABLES:
            if only and name not in only:
                continue
            create_indexes(engine, name, INDEXES.get(name, []))

    # Final verification: count rows per table
    print("\n=== Verification ===")
    with engine.connect() as conn:
        for name, _, _, _ in TABLES:
            if only and name not in only:
                continue
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{name}")).scalar()
                print(f"  {SCHEMA}.{name:<20s}: {n:>10,} rows")
            except Exception as e:
                print(f"  {SCHEMA}.{name:<20s}: ERROR {e}")


if __name__ == "__main__":
    main()
