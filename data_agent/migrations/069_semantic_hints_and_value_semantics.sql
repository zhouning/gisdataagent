-- =============================================================================
-- Migration 069: agent_semantic_hints + value_semantics column
-- =============================================================================
--
-- v7 P0-pre: enable de-hardcoding of CQ business rules from system_instruction.md
-- into the semantic layer DB, so new customers can configure equivalent
-- grounding via app-level semantic layer configuration rather than editing
-- the prompt source.
--
-- DDL only. Content seed goes via data_agent/seed_semantic_hints_cq.py.
--
-- Adds:
--  1. agent_semantic_hints — generic carrier for free-text business rules
--     scoped to a table, column, or dataset. Read by resolve_semantic_context
--     and rendered under `## [业务规则]` in the grounding prompt.
--  2. agent_semantic_registry.value_semantics JSONB — carries per-column
--     value enums, sentinel-value semantics, and unit caveats.
-- =============================================================================

CREATE TABLE IF NOT EXISTS agent_semantic_hints (
    id                BIGSERIAL PRIMARY KEY,
    scope_type        TEXT NOT NULL
                          CHECK (scope_type IN ('table', 'column', 'dataset')),
    scope_ref         TEXT NOT NULL,
        -- 'cq_district_population' (table) or
        -- 'cq_district_population.行政区划代码' (column)
    hint_kind         TEXT NOT NULL
                          CHECK (hint_kind IN (
                              'filter_default', 'value_enum', 'join_note',
                              'unit_note', 'exclusion', 'category_choice',
                              'quoting', 'size_class', 'srid_note', 'other')),
    hint_text_zh      TEXT NOT NULL,
    hint_text_en      TEXT,
    severity          TEXT NOT NULL DEFAULT 'info'
                          CHECK (severity IN ('info', 'warn', 'critical')),
    trigger_keywords  JSONB NOT NULL DEFAULT '[]'::jsonb,
        -- if non-empty AND severity != 'critical', only emit when user_text
        -- contains at least one of these keywords (case-insensitive).
    sample_sql        TEXT,
    source_tag        TEXT DEFAULT 'cq_migration_069',
    owner_username    TEXT DEFAULT 'audit',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT agent_semantic_hints_dedup
        UNIQUE (scope_ref, hint_kind, hint_text_zh)
);

CREATE INDEX IF NOT EXISTS ix_semhints_scope_ref
    ON agent_semantic_hints (scope_ref);
CREATE INDEX IF NOT EXISTS ix_semhints_scope_ref_prefix
    ON agent_semantic_hints (scope_ref text_pattern_ops);
CREATE INDEX IF NOT EXISTS ix_semhints_scope_type
    ON agent_semantic_hints (scope_type);

ALTER TABLE agent_semantic_registry
    ADD COLUMN IF NOT EXISTS value_semantics JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Free-form shape (not constrained — DB is content-agnostic):
-- {
--   "enum":        [{"value": "T", "meaning": "one-way forward"}, ...],
--   "sentinels":   [{"value": 0,   "meaning": "unset"}],
--   "unit_caveat": "stored in square DEGREES, NOT m²"
-- }
