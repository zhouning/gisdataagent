"""Step 3 — Register the 10 FloodSQL-Bench tables into the semantic layer.

Schema-aware (writes annotations for tables in `floodsql_bench` schema).
We bypass `auto_register_table()` because it hardcodes `public` schema lookups.

Records concise, English-aware aliases per FloodSQL metadata.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data_agent.db_engine import get_engine  # noqa: E402

SCHEMA = "floodsql_bench"
OWNER = "benchmark"

# Curated table-level metadata (display_name, description, synonyms, suggested_analyses)
TABLES = {
    "claims": {
        "display_name": "NFIP Flood Insurance Claims",
        "description": "FEMA National Flood Insurance Program redacted claims (TX/FL/LA).",
        "synonyms": ["claims", "insurance claims", "flood claims", "nfip claims"],
        "suggested_analyses": ["aggregate_by_county", "trend_by_year", "loss_distribution"],
    },
    "svi": {
        "display_name": "CDC Social Vulnerability Index",
        "description": "Census-tract level social vulnerability indicators.",
        "synonyms": ["svi", "social vulnerability"],
        "suggested_analyses": ["join_with_claims", "rank_by_vulnerability"],
    },
    "cre": {
        "display_name": "FEMA Community Resilience Estimates",
        "description": "Community resilience metrics by tract.",
        "synonyms": ["cre", "community resilience"],
        "suggested_analyses": ["join_with_svi"],
    },
    "nri": {
        "display_name": "FEMA National Risk Index",
        "description": "County/tract risk index for natural hazards.",
        "synonyms": ["nri", "risk index", "national risk index"],
        "suggested_analyses": ["rank_by_risk", "compare_states"],
    },
    "floodplain": {
        "display_name": "FEMA Floodplain (FIRM)",
        "description": "Polygon layer of FEMA flood hazard zones.",
        "synonyms": ["floodplain", "flood zone", "fema firm", "100-year floodplain"],
        "suggested_analyses": ["intersect_with_buildings", "intersect_with_tracts"],
    },
    "census_tracts": {
        "display_name": "US Census Tracts",
        "description": "Census tract polygons (state/county/tract).",
        "synonyms": ["census tracts", "tracts"],
        "suggested_analyses": ["join_by_geoid", "spatial_join"],
    },
    "zcta": {
        "display_name": "ZIP Code Tabulation Areas",
        "description": "ZCTA polygon layer.",
        "synonyms": ["zcta", "zip", "zip code", "postal area"],
        "suggested_analyses": ["aggregate_by_zip"],
    },
    "county": {
        "display_name": "US County Boundaries",
        "description": "County polygon layer (state/county FIPS).",
        "synonyms": ["county", "counties"],
        "suggested_analyses": ["aggregate_by_county"],
    },
    "schools": {
        "display_name": "HIFLD Schools",
        "description": "Point layer of public/private schools.",
        "synonyms": ["schools", "school", "education facility"],
        "suggested_analyses": ["count_in_floodplain", "spatial_join"],
    },
    "hospitals": {
        "display_name": "HIFLD Hospitals",
        "description": "Point layer of hospital facilities.",
        "synonyms": ["hospitals", "hospital", "medical facility"],
        "suggested_analyses": ["count_in_floodplain", "nearest_to"],
    },
}

# Column-level annotations per table (column → {domain, aliases, unit, description})
COLUMNS = {
    "claims": {
        "censusBlockGroupFips": {"aliases": ["census block group fips", "block group", "GEOID"], "desc": "12-digit Census block group FIPS"},
        "countyCode":           {"aliases": ["county fips", "county code"], "desc": "5-digit county FIPS"},
        "state":                {"aliases": ["state", "state abbreviation"], "desc": "USPS state code"},
        "reportedZipCode":      {"aliases": ["zip", "zipcode", "postal"], "desc": "5-digit ZIP code"},
        "amountPaidOnBuildingClaim":  {"unit": "USD", "aliases": ["building loss", "building claim amount"], "desc": "Paid building claim"},
        "amountPaidOnContentsClaim":  {"unit": "USD", "aliases": ["contents loss"], "desc": "Paid contents claim"},
        "totalBuildingInsuranceCoverage": {"unit": "USD", "aliases": ["building coverage"], "desc": "Building coverage"},
        "yearOfLoss":           {"aliases": ["year", "loss year"], "desc": "Year of loss"},
        "dateOfLoss":           {"aliases": ["loss date"], "desc": "Date of loss"},
    },
    "svi": {
        "FIPS":     {"aliases": ["GEOID", "tract fips"], "desc": "11-digit tract FIPS"},
        "ST_ABBR":  {"aliases": ["state", "state abbreviation"], "desc": "State USPS code"},
        "COUNTY":   {"aliases": ["county name"], "desc": "County name"},
        "RPL_THEMES": {"aliases": ["overall vulnerability", "svi score"], "desc": "Overall percentile rank"},
    },
    "cre": {
        "GEOID":  {"aliases": ["geoid", "tract id"], "desc": "Census GEOID"},
        "STATE":  {"aliases": ["state"], "desc": "State"},
    },
    "nri": {
        "STCOFIPS":  {"aliases": ["county fips"], "desc": "5-digit county FIPS"},
        "TRACTFIPS": {"aliases": ["tract fips", "geoid"], "desc": "11-digit tract FIPS"},
        "STATE":     {"aliases": ["state"], "desc": "State"},
        "RISK_SCORE":{"aliases": ["risk score"], "desc": "Composite risk score"},
    },
    "floodplain": {
        "DFIRM_ID":   {"aliases": ["firm id"], "desc": "DFIRM identifier"},
        "FLD_ZONE":   {"aliases": ["flood zone", "zone"], "desc": "FEMA flood zone designation"},
        "ZONE_SUBTY": {"aliases": ["zone subtype"], "desc": "Zone subtype"},
    },
    "census_tracts": {
        "GEOID":    {"aliases": ["geoid", "tract id"], "desc": "11-digit tract identifier"},
        "STATEFP":  {"aliases": ["state fips"], "desc": "State FIPS"},
        "COUNTYFP": {"aliases": ["county fips"], "desc": "County FIPS"},
        "ALAND":    {"unit": "m²", "aliases": ["land area"], "desc": "Land area"},
        "AWATER":   {"unit": "m²", "aliases": ["water area"], "desc": "Water area"},
    },
    "zcta": {
        "GEOID20":   {"aliases": ["zip", "zcta"], "desc": "ZCTA identifier"},
        "ZCTA5CE20": {"aliases": ["zip code"], "desc": "5-digit ZIP"},
    },
    "county": {
        "GEOID":    {"aliases": ["county geoid", "county fips"], "desc": "5-digit county FIPS"},
        "NAME":     {"aliases": ["county name"], "desc": "County name"},
        "STATEFP":  {"aliases": ["state fips"], "desc": "State FIPS"},
    },
    "schools": {
        "NAME":   {"aliases": ["school name"], "desc": "School name"},
        "STATE":  {"aliases": ["state"], "desc": "State"},
        "CITY":   {"aliases": ["city"], "desc": "City"},
        "ENROLLMENT": {"aliases": ["students", "enrollment"], "desc": "Student enrollment"},
    },
    "hospitals": {
        "NAME":  {"aliases": ["hospital name"], "desc": "Hospital name"},
        "STATE": {"aliases": ["state"], "desc": "State"},
        "CITY":  {"aliases": ["city"], "desc": "City"},
        "BEDS":  {"aliases": ["beds", "bed count"], "desc": "Bed count"},
    },
}


def get_columns(conn, table: str) -> list[tuple[str, str]]:
    rows = conn.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema=:s AND table_name=:t ORDER BY ordinal_position"
    ), {"s": SCHEMA, "t": table}).fetchall()
    return [(r[0], r[1]) for r in rows]


def get_geom_info(conn, table: str) -> tuple[str | None, int | None]:
    row = conn.execute(text(
        "SELECT type, srid FROM geometry_columns "
        "WHERE f_table_schema=:s AND f_table_name=:t LIMIT 1"
    ), {"s": SCHEMA, "t": table}).fetchone()
    return (row[0], row[1]) if row else (None, None)


def main() -> int:
    engine = get_engine()
    if not engine:
        print("ERROR: get_engine() returned None.", file=sys.stderr)
        return 2

    summary: list[tuple[str, int]] = []

    with engine.begin() as conn:
        for table, meta in TABLES.items():
            cols = get_columns(conn, table)
            if not cols:
                print(f"  SKIP {table}: not present in schema {SCHEMA}")
                summary.append((table, 0))
                continue

            geom_type, srid = get_geom_info(conn, table)

            # Upsert sources row
            conn.execute(text("""
                INSERT INTO agent_semantic_sources
                    (table_name, display_name, description, geometry_type, srid,
                     synonyms, suggested_analyses, owner_username)
                VALUES (:t, :dn, :desc, :gt, :srid,
                        CAST(:syn AS jsonb), CAST(:sa AS jsonb), :owner)
                ON CONFLICT (table_name) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    geometry_type = EXCLUDED.geometry_type,
                    srid = EXCLUDED.srid,
                    synonyms = EXCLUDED.synonyms,
                    suggested_analyses = EXCLUDED.suggested_analyses,
                    updated_at = NOW()
            """), {
                "t": table,
                "dn": meta["display_name"],
                "desc": meta["description"],
                "gt": geom_type,
                "srid": srid,
                "syn": json.dumps(meta["synonyms"]),
                "sa": json.dumps(meta["suggested_analyses"]),
                "owner": OWNER,
            })

            # Per-column annotations
            col_meta = COLUMNS.get(table, {})
            n = 0
            for col_name, data_type in cols:
                ann = col_meta.get(col_name)
                is_geom = data_type in ("USER-DEFINED", "geometry")
                if not (ann or is_geom):
                    continue
                conn.execute(text("""
                    INSERT INTO agent_semantic_registry
                        (table_name, column_name, semantic_domain, aliases,
                         unit, description, is_geometry, owner_username)
                    VALUES (:t, :col, :domain, CAST(:aliases AS jsonb),
                            :unit, :desc, :is_geom, :owner)
                    ON CONFLICT (table_name, column_name) DO UPDATE SET
                        aliases = EXCLUDED.aliases,
                        unit = EXCLUDED.unit,
                        description = EXCLUDED.description,
                        is_geometry = EXCLUDED.is_geometry,
                        updated_at = NOW()
                """), {
                    "t": table,
                    "col": col_name,
                    "domain": (ann or {}).get("domain"),
                    "aliases": json.dumps((ann or {}).get("aliases", [])),
                    "unit": (ann or {}).get("unit", ""),
                    "desc": (ann or {}).get("desc", ""),
                    "is_geom": is_geom,
                    "owner": OWNER,
                })
                n += 1
            summary.append((table, n))
            print(f"  {table:20s} → {n} column annotations (geom={geom_type}, srid={srid})")

    # Invalidate cache (best-effort)
    try:
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache()
    except Exception as e:
        print(f"  (cache invalidate skipped: {e})")

    print(f"\n[register] Done. Tables registered: {sum(1 for _, n in summary if n)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
