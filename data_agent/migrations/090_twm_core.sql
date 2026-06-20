-- 090: Territorial World Model core tables.
-- Stores projects, layer bindings, state versions, objects, relations,
-- policy rules, rule hits, evidence, review tasks, scenarios and metrics.

CREATE TABLE IF NOT EXISTS twm_project (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    region_code TEXT NOT NULL DEFAULT '',
    business_scenario TEXT NOT NULL DEFAULT 'planning_supervision',
    owner_username TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_layer_binding (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    canonical_role TEXT NOT NULL DEFAULT '',
    object_type TEXT NOT NULL DEFAULT '',
    layer_alias TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    semantic_product_path TEXT NOT NULL DEFAULT '',
    asset_id INTEGER,
    time_label TEXT NOT NULL DEFAULT '',
    valid_from TEXT,
    valid_to TEXT,
    field_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    not_for_production BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_state_version (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    state_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    label TEXT NOT NULL DEFAULT '',
    source_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    rule_set_id TEXT,
    object_count INTEGER NOT NULL DEFAULT 0,
    relation_count INTEGER NOT NULL DEFAULT 0,
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    build_status TEXT NOT NULL DEFAULT 'building',
    build_log JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_state_object (
    id TEXT PRIMARY KEY,
    state_version_id TEXT NOT NULL,
    object_type TEXT NOT NULL DEFAULT '',
    object_code TEXT NOT NULL DEFAULT '',
    source_role TEXT NOT NULL DEFAULT '',
    source_asset_id INTEGER,
    source_feature_id TEXT,
    source_path TEXT NOT NULL DEFAULT '',
    canonical_role TEXT NOT NULL DEFAULT '',
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    semantic_tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    quality_score NUMERIC,
    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    not_for_production BOOLEAN NOT NULL DEFAULT FALSE,
    qa_use_for_rules BOOLEAN NOT NULL DEFAULT TRUE,
    geometry_crs TEXT NOT NULL DEFAULT 'EPSG:4326',
    geom_wkt TEXT NOT NULL DEFAULT '',
    bbox_json JSONB
);

CREATE TABLE IF NOT EXISTS twm_state_relation (
    id TEXT PRIMARY KEY,
    state_version_id TEXT NOT NULL,
    subject_object_id TEXT NOT NULL,
    predicate TEXT NOT NULL DEFAULT '',
    object_object_id TEXT NOT NULL DEFAULT '',
    relation_type TEXT NOT NULL DEFAULT '',
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC NOT NULL DEFAULT 0,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    geom_wkt TEXT NOT NULL DEFAULT '',
    source_subject_role TEXT NOT NULL DEFAULT '',
    source_target_role TEXT NOT NULL DEFAULT '',
    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    not_for_production BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS twm_rule_set (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    version_label TEXT NOT NULL DEFAULT '',
    source_std_version_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_policy_rule (
    id TEXT PRIMARY KEY,
    rule_set_id TEXT NOT NULL,
    rule_code TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'medium',
    rule_body JSONB NOT NULL DEFAULT '{}'::jsonb,
    legal_basis JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_policy TEXT NOT NULL DEFAULT 'review_required',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    std_derived_link_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_rule_hit (
    id TEXT PRIMARY KEY,
    state_version_id TEXT NOT NULL,
    rule_id TEXT NOT NULL DEFAULT '',
    subject_object_id TEXT NOT NULL DEFAULT '',
    target_object_id TEXT,
    hit_status TEXT NOT NULL DEFAULT 'open',
    severity TEXT NOT NULL DEFAULT 'medium',
    risk_score NUMERIC NOT NULL DEFAULT 0,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    explanation TEXT NOT NULL DEFAULT '',
    geom_wkt TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    review_task_id TEXT
);

CREATE TABLE IF NOT EXISTS twm_evidence_item (
    id TEXT PRIMARY KEY,
    rule_hit_id TEXT NOT NULL DEFAULT '',
    evidence_type TEXT NOT NULL DEFAULT '',
    source_system TEXT NOT NULL DEFAULT 'twm',
    source_ref TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    checksum TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_review_task (
    id TEXT PRIMARY KEY,
    rule_hit_id TEXT NOT NULL DEFAULT '',
    assignee TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    decision TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_scenario (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    base_state_version_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    scenario_type TEXT NOT NULL DEFAULT 'baseline',
    input_changes JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_model TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twm_scenario_metric (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL DEFAULT '',
    metric_code TEXT NOT NULL DEFAULT '',
    metric_name TEXT NOT NULL DEFAULT '',
    value NUMERIC NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT '',
    benchmark_value NUMERIC,
    direction TEXT NOT NULL DEFAULT 'lower_better',
    explanation TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_twm_project_owner
    ON twm_project(owner_username);

CREATE INDEX IF NOT EXISTS idx_twm_layer_binding_project
    ON twm_layer_binding(project_id);

CREATE INDEX IF NOT EXISTS idx_twm_state_version_project
    ON twm_state_version(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_twm_state_object_state
    ON twm_state_object(state_version_id);

CREATE INDEX IF NOT EXISTS idx_twm_state_relation_state
    ON twm_state_relation(state_version_id);

CREATE INDEX IF NOT EXISTS idx_twm_policy_rule_rule_set
    ON twm_policy_rule(rule_set_id, enabled);

CREATE INDEX IF NOT EXISTS idx_twm_rule_hit_state
    ON twm_rule_hit(state_version_id, severity, hit_status);

CREATE INDEX IF NOT EXISTS idx_twm_evidence_rule_hit
    ON twm_evidence_item(rule_hit_id, evidence_type);

CREATE INDEX IF NOT EXISTS idx_twm_review_task_rule_hit
    ON twm_review_task(rule_hit_id, status);

CREATE INDEX IF NOT EXISTS idx_twm_scenario_project
    ON twm_scenario(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_twm_scenario_metric_scenario
    ON twm_scenario_metric(scenario_id, metric_code);

