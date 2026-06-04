-- Synthetic major-project PostGIS schema

-- Synthetic-only demonstration structure; contains no production records.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS mp_project_list (
    project_id TEXT PRIMARY KEY,
    zdxmbh TEXT NOT NULL,
    zdxm_sec TEXT NOT NULL,
    project_name TEXT NOT NULL,
    project_type TEXT,
    province TEXT,
    city TEXT,
    county TEXT,
    construction_unit TEXT,
    total_investment_million NUMERIC,
    planned_land_area_mu NUMERIC,
    list_year INTEGER,
    status TEXT,
    geom geometry(Polygon, 4326),
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mp_land_plan (
    plan_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_pre_review (
    pre_review_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,xs_dzjgh TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_site_selection (
    site_selection_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_conversion_expropriation (
    conversion_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_approval_project (
    approval_project_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,bp_guid TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_approval_supply (
    approval_supply_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,bp_guid TEXT
    ,gd_guid TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_land_supply (
    land_supply_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,gd_guid TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_land_use_permit (
    land_use_permit_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,ygdzjgh TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_construction_permit (
    construction_permit_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,ggdzjgh TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_verification (
    verification_id TEXT PRIMARY KEY
    ,project_id TEXT
    ,zdxmbh TEXT
    ,zdxm_sec TEXT
    ,project_name TEXT
    ,stage TEXT
    ,stage_name TEXT
    ,flowsn TEXT
    ,dzjgh TEXT
    ,approval_date DATE
    ,status TEXT
    ,area_mu NUMERIC
    ,synthetic_seed INTEGER NOT NULL
    ,profile TEXT
    ,generator_version TEXT
    ,verification_no TEXT
    ,FOREIGN KEY (project_id) REFERENCES mp_project_list(project_id)
);

CREATE TABLE IF NOT EXISTS mp_parcel (
    parcel_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES mp_project_list(project_id),
    land_use_type TEXT,
    area_mu NUMERIC,
    geom geometry(Polygon, 4326),
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mp_spatial_overlap (
    overlap_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES mp_project_list(project_id),
    parcel_id TEXT NOT NULL REFERENCES mp_parcel(parcel_id),
    overlap_ratio NUMERIC,
    overlap_area_mu NUMERIC,
    geometry_source TEXT,
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mp_relation_confidence (
    relation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES mp_project_list(project_id),
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    match_method TEXT NOT NULL,
    confidence NUMERIC NOT NULL,
    evidence JSONB,
    synthetic_seed INTEGER NOT NULL,
    profile TEXT NOT NULL,
    generator_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kg_nodes (
    node_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    biz_id TEXT NOT NULL,
    name TEXT,
    properties JSONB
);

CREATE TABLE IF NOT EXISTS kg_edges (
    edge_id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL REFERENCES kg_nodes(node_id),
    target_node_id TEXT NOT NULL REFERENCES kg_nodes(node_id),
    edge_type TEXT NOT NULL,
    confidence NUMERIC,
    match_method TEXT,
    evidence JSONB
);

CREATE TABLE IF NOT EXISTS kg_query_result (
    result_id BIGSERIAL PRIMARY KEY,
    benchmark_id TEXT,
    question TEXT NOT NULL,
    route_class TEXT,
    sql_text TEXT,
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mp_project_list_geom ON mp_project_list USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_mp_parcel_geom ON mp_parcel USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_mp_relation_confidence_type ON mp_relation_confidence (relation_type);

CREATE INDEX IF NOT EXISTS idx_kg_edges_edge_type ON kg_edges (edge_type);
