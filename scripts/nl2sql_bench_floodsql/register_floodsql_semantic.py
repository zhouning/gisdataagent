"""Register FloodSQL-Bench tables to the semantic layer (Phase 0a step 1).

Mirror of `scripts/nl2sql_bench_cq/register_cq_semantic.py` for the
FloodSQL-Bench dataset. Writes to two existing tables in the
flights_dataset DB on the Huawei-cloud PG (119.3.175.198):

  - agent_semantic_sources    (one row per table: display name, geom_type,
                                srid, synonyms, suggested analyses)
  - agent_semantic_registry   (one row per column: aliases, unit, desc,
                                semantic_domain, is_geometry)

The dataset itself was loaded into ``floodsql.*`` schema by
``scripts/floodsql/load_floodsql.py``. This script registers ONLY the
metadata; it does not touch the data tables.

Usage:
    cd D:/adk
    .venv/Scripts/python.exe scripts/nl2sql_bench_floodsql/register_floodsql_semantic.py
       [--schema floodsql]   # PG schema where the data lives (remote=floodsql, local=floodsql_bench)
       [--owner floodsql_bench]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.db_engine import get_engine

OWNER = "floodsql_bench"

# ---------------------------------------------------------------------------
# 10 tables — display names, descriptions, synonyms, suggested analyses
# Source: arXiv 2512.12084 (FloodSQL-Bench paper) §3.1, A.3 + our local probe
# ---------------------------------------------------------------------------
TABLES = {
    "census_tracts": {
        "display_name": "U.S. Census Tracts (TX/FL/LA)",
        "description": (
            "U.S. Census tract polygon boundaries for the three target states. "
            "11-digit GEOID = 2-digit STATEFP + 3-digit COUNTYFP + 6-digit tract code; "
            "primary join key for claims/svi/nri/cre. Geometries simplified at 10m tolerance."
        ),
        "synonyms": ["tract", "census tract", "tract boundary", "tracts", "tract polygon"],
        "suggested_analyses": ["spatial_join", "polygon_overlay", "tract_aggregation"],
    },
    "county": {
        "display_name": "U.S. County Boundaries (TX/FL/LA)",
        "description": (
            "County-level polygon boundaries (385 counties across TX/FL/LA). "
            "5-digit GEOID = STATEFP + COUNTYFP. Joins to claims/hospitals via "
            "LEFT(claims.geoid, 5) and hospitals.countyfips."
        ),
        "synonyms": ["county", "counties", "county boundary", "county polygon", "administrative"],
        "suggested_analyses": ["county_aggregation", "spatial_join", "polygon_overlay"],
    },
    "floodplain": {
        "display_name": "FEMA Flood Hazard Zones (NFHL)",
        "description": (
            "FEMA National Flood Hazard Layer (NFHL) flood-risk polygons. ~916K geometries. "
            "fld_zone codes: A/AE/AH/AO/V/VE/X/D/OPEN_WATER. Spatial-only — no join key. "
            "Simplified at 100m tolerance to keep query latency tractable."
        ),
        "synonyms": ["floodplain", "flood plain", "flood zone", "flood hazard", "FEMA flood zone", "NFHL"],
        "suggested_analyses": ["spatial_join", "polygon_overlay", "flood_risk_assessment"],
    },
    "zcta": {
        "display_name": "ZIP Code Tabulation Areas (TX/FL/LA)",
        "description": (
            "Census-derived ZCTA polygons (NOT identical to USPS ZIP). Spatial-only — "
            "joins via geometry, not by ZIP key. Simplified at 50m tolerance."
        ),
        "synonyms": ["ZCTA", "ZIP code area", "ZIP boundary", "postal area", "ZIP polygon"],
        "suggested_analyses": ["spatial_join", "polygon_overlay"],
    },
    "claims": {
        "display_name": "NFIP Flood Insurance Claims",
        "description": (
            "National Flood Insurance Program (NFIP) historical claim records (~1.3M rows). "
            "11-digit GEOID is the primary key; geometry column is a Point but is treated as "
            "key-only by the benchmark — DO NOT spatial-join via claims.geometry. Three "
            "payout amount columns are stored as TEXT and require CAST(col AS DOUBLE PRECISION) "
            "before numeric aggregation."
        ),
        "synonyms": ["NFIP claim", "flood claim", "insurance claim", "claims", "payout", "policy claim"],
        "suggested_analyses": ["temporal_aggregation", "tract_aggregation", "amount_distribution"],
    },
    "hospitals": {
        "display_name": "Hospital Locations (HIFLD, TX/FL/LA)",
        "description": (
            "Hospital point locations (HIFLD dataset, ~1.5K rows). NO geometry column — "
            "use ST_SetSRID(ST_Point(lon, lat), 4326) on the fly. Categorical TYPE (10 classes "
            "incl. GENERAL ACUTE CARE, CRITICAL ACCESS, PSYCHIATRIC). countyfips is the 5-digit "
            "county FIPS for join to county.geoid."
        ),
        "synonyms": ["hospital", "healthcare facility", "medical center", "hospitals", "clinic"],
        "suggested_analyses": ["point_in_polygon", "knn", "facility_count_per_region"],
    },
    "schools": {
        "display_name": "School Locations (HIFLD, TX/FL/LA)",
        "description": (
            "School point locations (HIFLD dataset, ~20.5K rows). NO geometry column — use "
            "ST_SetSRID(ST_Point(lon, lat), 4326) on the fly. TYPE is one of "
            "{COLLEGE, PUBLIC_SCHOOL, PRIVATE_SCHOOL}. ZIP joins to hospitals.zip; no "
            "countyfips column (must be derived spatially)."
        ),
        "synonyms": ["school", "schools", "college", "public school", "private school", "education"],
        "suggested_analyses": ["point_in_polygon", "spatial_filter", "facility_count_per_region"],
    },
    "svi": {
        "display_name": "CDC Social Vulnerability Index (SVI)",
        "description": (
            "CDC/ATSDR Social Vulnerability Index, tract-level (159 columns). Themes: "
            "RPL_THEME1=Socioeconomic, RPL_THEME2=Household, RPL_THEME3=Minority/Language, "
            "RPL_THEME4=Housing/Transportation; RPL_THEMES=overall. **-999 marks missing values** "
            "(NOT NULL); filter via BETWEEN 0 AND 100 or != -999. EP_*/MP_* are percentages, "
            "EPL_* are 0-1 percentile ranks. E_* are estimates, M_* are margins of error."
        ),
        "synonyms": ["SVI", "social vulnerability", "vulnerability index", "socioeconomic vulnerability"],
        "suggested_analyses": ["tract_aggregation", "demographic_analysis", "vulnerability_ranking"],
    },
    "nri": {
        "display_name": "FEMA National Risk Index (NRI)",
        "description": (
            "FEMA National Risk Index, tract-level. Two flood hazard families: CFLD_* (Coastal Flood) "
            "and RFLD_* (Riverine Flood). Each has EVNTS (events), AFREQ (annual frequency), "
            "EXP* (exposure), HLR* (historical loss ratio), EAL* (Expected Annual Loss), "
            "RISK* (composite score). RISKR is a 7-class text rating "
            "{Very Low, Relatively Low, Relatively Moderate, Relatively High, Very High, "
            "No Rating, Insufficient Data}."
        ),
        "synonyms": ["NRI", "national risk index", "FEMA risk", "flood risk score", "expected annual loss"],
        "suggested_analyses": ["risk_ranking", "tract_aggregation", "hazard_comparison"],
    },
    "cre": {
        "display_name": "Census Community Resilience Estimates (CRE)",
        "description": (
            "U.S. Census CRE, tract-level (20 columns). Buckets households by number of risk "
            "factors faced: PRED0_* = 0 risk factors (most resilient), PRED12_* = 1-2 factors, "
            "PRED3_* = 3+ factors (least resilient). Each bucket has _E (estimate), _M (MOE), "
            "_PE (percentage of POPUNI), _PM (percentage MOE)."
        ),
        "synonyms": ["CRE", "community resilience", "resilience estimates", "risk factor distribution"],
        "suggested_analyses": ["resilience_ranking", "demographic_analysis", "tract_aggregation"],
    },
}


# ---------------------------------------------------------------------------
# Column annotations — semantic_domain / aliases / unit / description
# Mostly mirrors CQ patterns. is_geometry=True for the literal geometry col.
# ---------------------------------------------------------------------------
COLUMNS = {
    "census_tracts": {
        "geoid":     {"domain": "ID",          "aliases": ["GEOID", "tract id", "11-digit GEOID", "tract code"], "unit": "", "desc": "11-digit Census tract ID. STATEFP(2) + COUNTYFP(3) + tract(6). Primary join key to claims/svi/nri/cre."},
        "statefp":   {"domain": "ADMIN_CODE",  "aliases": ["state FIPS", "STATEFP"], "unit": "", "desc": "2-digit state FIPS code. '12'=Florida, '22'=Louisiana, '48'=Texas."},
        "countyfp":  {"domain": "ADMIN_CODE",  "aliases": ["county FIPS", "COUNTYFP"], "unit": "", "desc": "3-digit county FIPS within state."},
        "name":      {"domain": "NAME",        "aliases": ["tract name"], "unit": "", "desc": "Tract numeric name (e.g., '101.02')."},
        "geometry":  {"domain": None,          "aliases": [], "unit": "", "desc": "MultiPolygon, SRID=4326. Use directly with ST_Intersects/ST_Contains/ST_Within with floodplain/zcta/county. Use ST_IsValid() guard."},
    },
    "county": {
        "geoid":     {"domain": "ID",          "aliases": ["county GEOID", "5-digit GEOID", "county code", "COUNTYFIPS"], "unit": "", "desc": "5-digit county code = STATEFP + COUNTYFP. LEFT(claims.geoid, 5) joins here."},
        "statefp":   {"domain": "ADMIN_CODE",  "aliases": ["state FIPS", "STATEFP"], "unit": "", "desc": "2-digit state FIPS."},
        "countyfp":  {"domain": "ADMIN_CODE",  "aliases": ["county FIPS", "COUNTYFP"], "unit": "", "desc": "3-digit county FIPS within state."},
        "name":      {"domain": "NAME",        "aliases": ["county name"], "unit": "", "desc": "County name (e.g., 'Harris', 'Miami-Dade'). NOT including the word 'County'."},
        "geometry":  {"domain": None,          "aliases": [], "unit": "", "desc": "MultiPolygon, SRID=4326."},
    },
    "floodplain": {
        "gfid":      {"domain": "ID",          "aliases": ["FEMA ID"], "unit": "", "desc": "FEMA flood-zone polygon ID (not unique across rows)."},
        "statefp":   {"domain": "ADMIN_CODE",  "aliases": ["state FIPS"], "unit": "", "desc": "2-digit state FIPS."},
        "fld_zone":  {"domain": "CATEGORY",    "aliases": ["flood zone", "zone code", "FEMA zone"], "unit": "", "desc": "FEMA flood-risk classification: A, AE, AH, AO (1% annual chance), V, VE (coastal), X (minimal risk), D (undetermined), OPEN_WATER."},
        "geometry":  {"domain": None,          "aliases": [], "unit": "", "desc": "MultiPolygon, SRID=4326. ALWAYS guard with ST_IsValid(geometry) before ST_Intersects (~5% of polygons are invalid)."},
    },
    "zcta": {
        "geoid":     {"domain": "ID",          "aliases": ["ZIP", "ZCTA", "zip code"], "unit": "", "desc": "5-digit ZCTA code (NOT identical to USPS ZIP)."},
        "statefp":   {"domain": "ADMIN_CODE",  "aliases": ["state FIPS"], "unit": "", "desc": "2-digit state FIPS."},
        "geometry":  {"domain": None,          "aliases": [], "unit": "", "desc": "MultiPolygon, SRID=4326."},
    },
    "claims": {
        "id":          {"domain": "ID",        "aliases": ["claim id", "claim number"], "unit": "", "desc": "NFIP claim record ID."},
        "geoid":       {"domain": "ID",        "aliases": ["GEOID", "tract id"], "unit": "", "desc": "11-digit GEOID. Join key to census_tracts/svi/nri/cre. LEFT(geoid, 5) gives county GEOID."},
        "statefp":     {"domain": "ADMIN_CODE","aliases": ["state FIPS", "STATEFP"], "unit": "", "desc": "2-digit state FIPS."},
        "dateofloss":  {"domain": "DATE",      "aliases": ["loss date", "date of loss", "claim date"], "unit": "", "desc": "Date the loss event occurred. Type is DATE; use DATE 'YYYY-MM-DD' literal or EXTRACT(YEAR FROM ...) for year."},
        "amountpaidonbuildingclaim":             {"domain": "AMOUNT", "aliases": ["building payout", "structural payout"], "unit": "USD (text-encoded)", "desc": "Stored as TEXT. CAST(col AS DOUBLE PRECISION) before numeric ops. Range -201,667 .. 10,741,476."},
        "amountpaidoncontentsclaim":             {"domain": "AMOUNT", "aliases": ["contents payout"], "unit": "USD (text-encoded)", "desc": "Stored as TEXT. CAST(col AS DOUBLE PRECISION) before numeric ops."},
        "amountpaidonincreasedcostofcomplianceclaim": {"domain": "AMOUNT", "aliases": ["ICC payout", "increased cost of compliance"], "unit": "USD (text-encoded)", "desc": "Stored as TEXT. CAST(col AS DOUBLE PRECISION) before numeric ops."},
        "geometry":    {"domain": None,        "aliases": [], "unit": "", "desc": "Point geometry, SRID=4326. KEY-ONLY usage per benchmark — do NOT spatial-join via claims.geometry; use GEOID instead."},
    },
    "hospitals": {
        "hospital_id":  {"domain": "ID",       "aliases": ["hospital code"], "unit": "", "desc": "Hospital ID (HIFLD)."},
        "name":         {"domain": "NAME",     "aliases": ["hospital name"], "unit": "", "desc": "Hospital name."},
        "address":      {"domain": "ADDRESS",  "aliases": ["street address"], "unit": "", "desc": "Street address."},
        "city":         {"domain": "NAME",     "aliases": ["city name"], "unit": "", "desc": "City (UPPERCASE, e.g., 'HOUSTON', 'MIAMI')."},
        "state":        {"domain": "ADMIN_CODE","aliases": ["state abbr"], "unit": "", "desc": "Two-letter state abbreviation: 'TX', 'FL', 'LA' (NOT full name)."},
        "zip":          {"domain": "ID",       "aliases": ["ZIP code", "postal code"], "unit": "", "desc": "5-digit ZIP. Joins to schools.zip."},
        "county":       {"domain": "NAME",     "aliases": ["county name"], "unit": "", "desc": "County name (UPPERCASE, e.g., 'HARRIS', 'MIAMI-DADE')."},
        "countyfips":   {"domain": "ID",       "aliases": ["county FIPS", "5-digit county"], "unit": "", "desc": "5-digit county FIPS. Join key to county.geoid."},
        "lat":          {"domain": "LATITUDE", "aliases": ["latitude"], "unit": "degrees", "desc": "WGS84 latitude (use with lon to construct Point: ST_SetSRID(ST_Point(lon, lat), 4326))."},
        "lon":          {"domain": "LONGITUDE","aliases": ["longitude"], "unit": "degrees", "desc": "WGS84 longitude."},
        "type":         {"domain": "CATEGORY", "aliases": ["hospital type"], "unit": "", "desc": "Type: GENERAL ACUTE CARE, CRITICAL ACCESS, PSYCHIATRIC, REHABILITATION, LONG TERM CARE, MILITARY, CHILDREN, WOMEN, SPECIAL, CHRONIC DISEASE."},
        "statefp":      {"domain": "ADMIN_CODE","aliases": ["state FIPS"], "unit": "", "desc": "2-digit state FIPS (12, 22, 48)."},
        "unique_id":    {"domain": "ID",       "aliases": ["composite ID"], "unit": "", "desc": "Composite ID like '48_hospital_0005479830' — used as DISTINCT key in COUNT(DISTINCT ...)."},
    },
    "schools": {
        "school_id":    {"domain": "ID",       "aliases": ["school code"], "unit": "", "desc": "School ID (HIFLD)."},
        "name":         {"domain": "NAME",     "aliases": ["school name"], "unit": "", "desc": "School name."},
        "address":      {"domain": "ADDRESS",  "aliases": ["street address"], "unit": "", "desc": "Street address."},
        "city":         {"domain": "NAME",     "aliases": ["city name"], "unit": "", "desc": "City (UPPERCASE, e.g., 'SAN ANTONIO', 'DALLAS')."},
        "state":        {"domain": "ADMIN_CODE","aliases": ["state abbr"], "unit": "", "desc": "Two-letter state abbreviation: 'TX', 'FL', 'LA'."},
        "zip":          {"domain": "ID",       "aliases": ["ZIP code", "postal code"], "unit": "", "desc": "5-digit ZIP. Joins to hospitals.zip."},
        "lat":          {"domain": "LATITUDE", "aliases": ["latitude"], "unit": "degrees", "desc": "WGS84 latitude."},
        "lon":          {"domain": "LONGITUDE","aliases": ["longitude"], "unit": "degrees", "desc": "WGS84 longitude."},
        "type":         {"domain": "CATEGORY", "aliases": ["school type"], "unit": "", "desc": "Type: COLLEGE / PUBLIC_SCHOOL / PRIVATE_SCHOOL."},
        "statefp":      {"domain": "ADMIN_CODE","aliases": ["state FIPS"], "unit": "", "desc": "2-digit state FIPS."},
        "unique_id":    {"domain": "ID",       "aliases": ["composite ID"], "unit": "", "desc": "Composite ID like '48_COLLEGE_476540'."},
    },
    "svi": {
        "geoid":        {"domain": "ID",       "aliases": ["tract ID", "GEOID"], "unit": "", "desc": "11-digit Census tract GEOID. Join key to census_tracts/claims/nri/cre."},
        "st":           {"domain": "ADMIN_CODE","aliases": ["state numeric"], "unit": "", "desc": "Numeric state FIPS (12=FL, 22=LA, 48=TX)."},
        "state":        {"domain": "ADMIN_CODE","aliases": ["state name"], "unit": "", "desc": "FULL state name: 'Florida', 'Louisiana', 'Texas' (NOT abbreviation)."},
        "st_abbr":      {"domain": "ADMIN_CODE","aliases": ["state abbreviation"], "unit": "", "desc": "Two-letter state abbreviation: 'FL', 'LA', 'TX'."},
        "stcnty":       {"domain": "ID",       "aliases": ["state+county code"], "unit": "", "desc": "5-digit STATEFP+COUNTYFP."},
        "county":       {"domain": "NAME",     "aliases": ["county name"], "unit": "", "desc": "County name with 'County' suffix (e.g., 'Harris County')."},
        "fips":         {"domain": "ID",       "aliases": ["FIPS"], "unit": "", "desc": "Same as GEOID but stored as bigint."},
        "location":     {"domain": "NAME",     "aliases": ["location string"], "unit": "", "desc": "Composite location name."},
        "area_sqmi":    {"domain": "AREA",     "aliases": ["area"], "unit": "sq mi", "desc": "Tract area in square miles."},
        "e_totpop":     {"domain": "POPULATION","aliases": ["total population", "POPUNI"], "unit": "people", "desc": "Estimated total population."},
        "rpl_theme1":   {"domain": "PERCENTILE","aliases": ["socioeconomic vulnerability", "Theme 1"], "unit": "0-1 rank", "desc": "Relative percentile rank for Theme 1 (Socioeconomic Status). 0=least vulnerable, 1=most vulnerable. -999 = missing."},
        "rpl_theme2":   {"domain": "PERCENTILE","aliases": ["household composition", "Theme 2"], "unit": "0-1 rank", "desc": "Relative percentile rank for Theme 2 (Household Characteristics). -999 = missing."},
        "rpl_theme3":   {"domain": "PERCENTILE","aliases": ["minority", "Theme 3"], "unit": "0-1 rank", "desc": "Relative percentile rank for Theme 3 (Racial & Ethnic Minority Status). -999 = missing."},
        "rpl_theme4":   {"domain": "PERCENTILE","aliases": ["housing transportation", "Theme 4"], "unit": "0-1 rank", "desc": "Relative percentile rank for Theme 4 (Housing Type & Transportation). -999 = missing."},
        "rpl_themes":   {"domain": "PERCENTILE","aliases": ["overall vulnerability", "RPL_THEMES", "summary percentile"], "unit": "0-1 rank", "desc": "Overall SVI percentile rank (combination of all 4 themes). -999 = missing."},
        "ep_pov150":    {"domain": "PERCENT",  "aliases": ["pct in poverty", "poverty pct"], "unit": "%", "desc": "Estimated % below 150% poverty line."},
        "ep_unemp":     {"domain": "PERCENT",  "aliases": ["unemployment pct"], "unit": "%", "desc": "Estimated % unemployed."},
        "ep_noveh":     {"domain": "PERCENT",  "aliases": ["pct without vehicle", "no vehicle %"], "unit": "%", "desc": "Estimated % of households with no vehicle."},
        "ep_noint":     {"domain": "PERCENT",  "aliases": ["no internet pct", "without internet %"], "unit": "%", "desc": "Estimated % with no internet access."},
        "e_age65":      {"domain": "POPULATION","aliases": ["population 65+"], "unit": "people", "desc": "Estimated population aged 65+."},
        "e_age17":      {"domain": "POPULATION","aliases": ["population under 18"], "unit": "people", "desc": "Estimated population under 18."},
        "e_minrty":     {"domain": "POPULATION","aliases": ["minority population"], "unit": "people", "desc": "Estimated minority population (non-white)."},
    },
    "nri": {
        "geoid":        {"domain": "ID",       "aliases": ["tract GEOID"], "unit": "", "desc": "11-digit Census tract GEOID."},
        "state":        {"domain": "ADMIN_CODE","aliases": ["state abbr"], "unit": "", "desc": "Two-letter state abbreviation: 'FL', 'LA', 'TX' (note: differs from svi.state which is full name)."},
        "cfld_evnts":   {"domain": "COUNT",    "aliases": ["coastal flood events"], "unit": "events", "desc": "Number of coastal flood events recorded."},
        "cfld_afreq":   {"domain": "FREQUENCY","aliases": ["coastal flood annual frequency"], "unit": "events/year", "desc": "Coastal flood annual frequency."},
        "cfld_eals":    {"domain": "AMOUNT",   "aliases": ["coastal flood EAL score"], "unit": "0-100 score", "desc": "Coastal Flood Expected Annual Loss score (normalized 0-100)."},
        "cfld_ealb":    {"domain": "AMOUNT",   "aliases": ["coastal flood building EAL"], "unit": "USD/yr", "desc": "Coastal Flood Expected Annual Loss for buildings."},
        "cfld_riskr":   {"domain": "CATEGORY", "aliases": ["coastal flood risk rating"], "unit": "", "desc": "Coastal Flood risk rating: 'Very Low', 'Relatively Low', 'Relatively Moderate', 'Relatively High', 'Very High', 'No Rating', 'Insufficient Data'."},
        "rfld_evnts":   {"domain": "COUNT",    "aliases": ["riverine flood events"], "unit": "events", "desc": "Number of riverine flood events recorded."},
        "rfld_afreq":   {"domain": "FREQUENCY","aliases": ["riverine flood annual frequency"], "unit": "events/year", "desc": "Riverine flood annual frequency."},
        "rfld_eals":    {"domain": "AMOUNT",   "aliases": ["riverine flood EAL score"], "unit": "0-100 score", "desc": "Riverine Flood Expected Annual Loss score."},
        "rfld_ealb":    {"domain": "AMOUNT",   "aliases": ["riverine flood building EAL"], "unit": "USD/yr", "desc": "Riverine Flood Expected Annual Loss for buildings."},
        "rfld_riskr":   {"domain": "CATEGORY", "aliases": ["riverine flood risk rating"], "unit": "", "desc": "Riverine Flood risk rating (same 7 classes as cfld_riskr)."},
        "rfld_hlrb":    {"domain": "RATIO",    "aliases": ["riverine flood historical loss ratio buildings"], "unit": "ratio", "desc": "Historical loss ratio for riverine flood, buildings."},
    },
    "cre": {
        "geoid":     {"domain": "ID",          "aliases": ["tract GEOID"], "unit": "", "desc": "11-digit Census tract GEOID."},
        "geo_id":    {"domain": "ID",          "aliases": ["full GEOID"], "unit": "", "desc": "Full-length GEOID (e.g., '1400000US12001000201')."},
        "state":     {"domain": "ADMIN_CODE",  "aliases": ["state numeric"], "unit": "", "desc": "Numeric state FIPS (bigint: 12, 22, 48)."},
        "county":    {"domain": "ADMIN_CODE",  "aliases": ["county FIPS"], "unit": "", "desc": "Numeric county FIPS (bigint)."},
        "name":      {"domain": "NAME",        "aliases": ["tract description"], "unit": "", "desc": "Composite tract description (e.g., 'Census Tract 3.01, Alachua County, Florida')."},
        "popuni":    {"domain": "POPULATION",  "aliases": ["population universe"], "unit": "people", "desc": "Tract population universe."},
        "pred0_e":   {"domain": "POPULATION",  "aliases": ["pop with 0 risk factors"], "unit": "people", "desc": "Estimated population with 0 risk factors (most resilient)."},
        "pred0_pe":  {"domain": "PERCENT",     "aliases": ["pct with 0 risk factors"], "unit": "%", "desc": "Estimated percentage of population with 0 risk factors."},
        "pred12_e":  {"domain": "POPULATION",  "aliases": ["pop with 1-2 risk factors"], "unit": "people", "desc": "Estimated population with 1-2 risk factors."},
        "pred12_pe": {"domain": "PERCENT",     "aliases": ["pct with 1-2 risk factors"], "unit": "%", "desc": "Estimated percentage of population with 1-2 risk factors."},
        "pred3_e":   {"domain": "POPULATION",  "aliases": ["pop with 3+ risk factors"], "unit": "people", "desc": "Estimated population with 3+ risk factors (least resilient)."},
        "pred3_pe":  {"domain": "PERCENT",     "aliases": ["pct with 3+ risk factors"], "unit": "%", "desc": "Estimated percentage of population with 3+ risk factors."},
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default="floodsql",
                    help="PG schema where the FloodSQL data lives (remote=floodsql, local=floodsql_bench)")
    ap.add_argument("--owner", default=OWNER)
    args = ap.parse_args()

    engine = get_engine()
    if engine is None:
        print("ERROR: get_engine() returned None — check .env DB config", file=sys.stderr)
        return 2

    n_tables = 0
    n_columns = 0
    with engine.begin() as conn:
        for table, meta in TABLES.items():
            # Detect actual geometry type + SRID from the loaded data
            geom = conn.execute(text(
                "SELECT type, srid FROM geometry_columns "
                "WHERE f_table_schema=:s AND f_table_name=:t LIMIT 1"
            ), {"s": args.schema, "t": table}).fetchone()

            conn.execute(text("""
                INSERT INTO agent_semantic_sources
                    (table_name, display_name, description, geometry_type, srid,
                     synonyms, suggested_analyses, owner_username)
                VALUES (:t, :dn, :desc, :gt, :srid,
                        CAST(:syn AS jsonb), CAST(:sa AS jsonb), :owner)
                ON CONFLICT (table_name) DO UPDATE SET
                    display_name       = EXCLUDED.display_name,
                    description        = EXCLUDED.description,
                    geometry_type      = EXCLUDED.geometry_type,
                    srid               = EXCLUDED.srid,
                    synonyms           = EXCLUDED.synonyms,
                    suggested_analyses = EXCLUDED.suggested_analyses,
                    updated_at         = NOW()
            """), {
                "t": table,
                "dn": meta["display_name"],
                "desc": meta["description"],
                "gt": geom[0] if geom else None,
                "srid": geom[1] if geom else None,
                "syn": json.dumps(meta["synonyms"]),
                "sa": json.dumps(meta["suggested_analyses"]),
                "owner": args.owner,
            })
            n_tables += 1

            col_meta = COLUMNS.get(table, {})
            for col_name, ann in col_meta.items():
                is_geom = (col_name == "geometry")
                conn.execute(text("""
                    INSERT INTO agent_semantic_registry
                        (table_name, column_name, semantic_domain, aliases,
                         unit, description, is_geometry, owner_username)
                    VALUES (:t, :col, :domain, CAST(:aliases AS jsonb),
                            :unit, :desc, :is_geom, :owner)
                    ON CONFLICT (table_name, column_name) DO UPDATE SET
                        semantic_domain = EXCLUDED.semantic_domain,
                        aliases         = EXCLUDED.aliases,
                        unit            = EXCLUDED.unit,
                        description     = EXCLUDED.description,
                        is_geometry     = EXCLUDED.is_geometry,
                        updated_at      = NOW()
                """), {
                    "t": table,
                    "col": col_name,
                    "domain": ann.get("domain"),
                    "aliases": json.dumps(ann.get("aliases", [])),
                    "unit": ann.get("unit", ""),
                    "desc": ann.get("desc", ""),
                    "is_geom": is_geom,
                    "owner": args.owner,
                })
                n_columns += 1
            print(f"  {table:20s} → {len(col_meta)} columns annotated")

    try:
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache()
    except Exception:
        pass

    print(f"\nRegistered {n_tables} tables / {n_columns} columns to "
          f"agent_semantic_sources / agent_semantic_registry. owner='{args.owner}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
