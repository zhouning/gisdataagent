"""Step 2 — Import FloodSQL-Bench Parquet tables into PostGIS.

Creates schema `floodsql_bench`, loads spatial tables via geopandas
(`floodplain, census_tracts, zcta, county, schools, hospitals`) and
non-spatial tables via pandas (`claims, svi, cre, nri`).

Idempotent: drops & recreates each table on every run (`if_exists="replace"`).
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data_agent.db_engine import get_engine  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "floodsql"
SCHEMA = "floodsql_bench"

# Map filename stem → (is_spatial, geom_col_name_if_any, srid)
TABLE_SPEC = {
    "floodplain":    (True,  "geometry", 4326),
    "census_tracts": (True,  "geometry", 4326),
    "zcta":          (True,  "geometry", 4326),
    "county":        (True,  "geometry", 4326),
    "schools":       (True,  "geometry", 4326),
    "hospitals":     (True,  "geometry", 4326),
    "claims":        (False, None,       None),
    "svi":           (False, None,       None),
    "cre":           (False, None,       None),
    "nri":           (False, None,       None),
}

# JOIN-key columns to index for performance
INDEX_HINTS = {
    "claims":        ["censusBlockGroupFips", "countyCode", "state", "reportedZipCode"],
    "svi":           ["FIPS", "ST_ABBR", "COUNTY"],
    "cre":           ["GEOID", "STATE"],
    "nri":           ["STCOFIPS", "STATE", "TRACTFIPS"],
    "census_tracts": ["GEOID", "STATEFP", "COUNTYFP"],
    "zcta":          ["GEOID20", "ZCTA5CE20"],
    "county":        ["GEOID", "STATEFP", "COUNTYFP"],
    "floodplain":    ["DFIRM_ID", "FLD_ZONE"],
    "schools":       ["NAICS_CODE", "STATE"],
    "hospitals":     ["NAICS_CODE", "STATE"],
}


def find_parquet(stem: str) -> Path | None:
    """Locate the parquet file for `stem` anywhere under DATA_DIR."""
    matches = list(DATA_DIR.rglob(f"{stem}.parquet"))
    if matches:
        return matches[0]
    matches = list(DATA_DIR.rglob(f"{stem}*.parquet"))
    return matches[0] if matches else None


def main() -> int:
    import pandas as pd
    try:
        import geopandas as gpd  # noqa: F401
    except ImportError:
        print("ERROR: geopandas required.", file=sys.stderr)
        return 2

    engine = get_engine()
    if not engine:
        print("ERROR: get_engine() returned None — check .env DB credentials.", file=sys.stderr)
        return 2

    if not DATA_DIR.exists():
        print(f"ERROR: data dir not found: {DATA_DIR}. Run 01_download.py first.", file=sys.stderr)
        return 2

    # Ensure schema + PostGIS extension
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    print(f"[import] schema `{SCHEMA}` ready")

    summary: list[tuple[str, str, int]] = []

    for stem, (is_spatial, geom_col, srid) in TABLE_SPEC.items():
        pq = find_parquet(stem)
        if pq is None:
            print(f"  SKIP {stem}: parquet not found under {DATA_DIR}")
            summary.append((stem, "missing", 0))
            continue

        print(f"[import] {stem} ← {pq.relative_to(DATA_DIR)} ({pq.stat().st_size / 1e6:.1f} MB)")
        try:
            if is_spatial:
                import geopandas as gpd
                gdf = gpd.read_parquet(pq)
                if gdf.crs is None:
                    gdf = gdf.set_crs(epsg=srid)
                elif gdf.crs.to_epsg() != srid:
                    gdf = gdf.to_crs(epsg=srid)
                # Standardize geometry column name
                if gdf.geometry.name != geom_col:
                    gdf = gdf.rename_geometry(geom_col)
                gdf.to_postgis(stem, engine, schema=SCHEMA, if_exists="replace", index=False)
                rows = len(gdf)
            else:
                df = pd.read_parquet(pq)
                df.to_sql(stem, engine, schema=SCHEMA, if_exists="replace", index=False, chunksize=5000)
                rows = len(df)

            summary.append((stem, "ok", rows))

            # Build indexes on JOIN keys + GIST on geometry
            with engine.begin() as conn:
                for col in INDEX_HINTS.get(stem, []):
                    # Defensive: column may not exist; check first.
                    found = conn.execute(text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema=:s AND table_name=:t AND column_name=:c"
                    ), {"s": SCHEMA, "t": stem, "c": col}).first()
                    if not found:
                        continue
                    idx_name = f"idx_{stem}_{col.lower()}"
                    conn.execute(text(
                        f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                        f'ON {SCHEMA}.{stem} ("{col}")'
                    ))
                if is_spatial:
                    conn.execute(text(
                        f'CREATE INDEX IF NOT EXISTS "idx_{stem}_geom" '
                        f'ON {SCHEMA}.{stem} USING GIST ({geom_col})'
                    ))
            print(f"  → {rows} rows + indexes")

        except Exception as e:
            print(f"  ERROR loading {stem}: {e}", file=sys.stderr)
            summary.append((stem, f"error: {e}", 0))

    print("\n[import] Summary:")
    for stem, status, rows in summary:
        print(f"  {stem:20s} {status:10s} {rows:>10,} rows")

    failures = [s for s in summary if s[1] not in ("ok", "missing")]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
