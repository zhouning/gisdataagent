-- Migration 075: std_derived_link table + FK columns on downstream tables.
-- Derivation engine lives in P2; only schema is added here.
-- The ALTER statements are guarded with IF NOT EXISTS / DO blocks so re-runs
-- and partial deployments are safe.
--
-- Step 2 discovery findings (2026-05-14):
--   agent_semantic_hints  — exists as standalone table → FK added
--   sources_synonyms      — does NOT exist (synonyms is a column in agent_semantic_sources)
--   value_semantics       — does NOT exist (value_semantics is a column in agent_semantic_registry)
--   qc_rules              — does NOT exist in this deployment
-- The DO block's ARRAY contains only the tables that actually exist.
-- Tests for the missing tables will pytest.skip via to_regclass() check.

CREATE TABLE IF NOT EXISTS std_derived_link (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_kind           TEXT NOT NULL
                              CHECK (source_kind IN ('clause','data_element','value_domain','term')),
    source_id             UUID NOT NULL,
    source_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    target_kind           TEXT NOT NULL
                              CHECK (target_kind IN (
                                  'semantic_hint','value_semantic','synonym',
                                  'qc_rule','defect_code','data_model_attribute',
                                  'table_column')),
    target_table          TEXT NOT NULL,
    target_id             TEXT NOT NULL,
    derivation_strategy   TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','active','stale','overridden','superseded')),
    stale_reason          TEXT,
    generated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_std_derived_link_active
    ON std_derived_link(target_kind, target_table, target_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_std_derived_link_source
    ON std_derived_link(source_kind, source_id);

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'agent_semantic_hints'
    ]
    LOOP
        IF to_regclass(tbl) IS NOT NULL THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN IF NOT EXISTS std_derived_link_id UUID REFERENCES std_derived_link(id) ON DELETE SET NULL',
                tbl
            );
            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_derived_link ON %I(std_derived_link_id)', tbl, tbl);
        END IF;
    END LOOP;
END $$;
