-- 085: Wave 8 — std_data_model_snapshot: persisted product of the
--      to_data_model derivation strategy (CDM/LDM/PDM JSON + PostgreSQL DDL).
--      Plus: widen std_derived_link CHECK constraints to admit the new
--      source_kind 'document_version' and target_kind 'data_model'.
--
-- Why a snapshot row instead of entity/attribute tables:
--   The model is a one-shot projection of std_data_element rows; attributes
--   are 1:1 with elements and storing them again adds zero new information.
--   The deliverable users actually consume is the DDL .sql file plus the
--   three-layer JSON; both fit naturally as JSONB / TEXT blobs.
--   Future manual overrides will be JSON patches on top — single column
--   addition, no schema churn.
--
-- Idempotency / re-derive semantics:
--   Each derivation run inserts a NEW row (immutable history). The previous
--   active row's derived_status is flipped to 'stale' and its companion
--   std_derived_link is mark_stale()'d. This matches the QcRule /
--   DefectTaxonomy strategies' upsert-managed pattern but goes one step
--   further on auditability — every snapshot's DDL is preserved verbatim.

-- (a) Widen std_derived_link CHECK constraints --------------------------
-- We need to admit the new source_kind 'document_version' (the to_data_model
-- strategy operates at version granularity, not element granularity) and
-- the new target_kind 'data_model' (target of the new strategy). Tightening
-- here would break Wave 7 strategies, so this is a strict superset.
ALTER TABLE std_derived_link
    DROP CONSTRAINT IF EXISTS std_derived_link_source_kind_check;
ALTER TABLE std_derived_link
    ADD CONSTRAINT std_derived_link_source_kind_check
        CHECK (source_kind IN (
            'clause','data_element','value_domain','term',
            'document_version'
        ));

ALTER TABLE std_derived_link
    DROP CONSTRAINT IF EXISTS std_derived_link_target_kind_check;
ALTER TABLE std_derived_link
    ADD CONSTRAINT std_derived_link_target_kind_check
        CHECK (target_kind IN (
            'semantic_hint','value_semantic','synonym',
            'qc_rule','defect_code','data_model_attribute',
            'table_column',
            'data_model'
        ));

-- (b) std_data_model_snapshot table -------------------------------------
CREATE TABLE IF NOT EXISTS std_data_model_snapshot (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    generated_by            TEXT NOT NULL DEFAULT 'system',

    -- Derived artefacts. cdm/ldm/pdm are structurally similar JSONB blobs;
    -- ddl_postgresql is the rendered, copy-pasteable .sql text.
    cdm_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    ldm_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    pdm_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    ddl_postgresql          TEXT  NOT NULL DEFAULT '',

    -- Headline counts so the UI doesn't have to GROUP BY to display them.
    entity_count            INT NOT NULL DEFAULT 0,
    attribute_count         INT NOT NULL DEFAULT 0,
    constraint_count        INT NOT NULL DEFAULT 0,

    -- Companion to the std_derived_link row for this snapshot. Same
    -- stale-tracking convention as agent_quality_rules /
    -- agent_defect_code_bindings.
    std_derived_link_id     UUID REFERENCES std_derived_link(id) ON DELETE SET NULL,
    derived_status          TEXT NOT NULL DEFAULT 'active'
                                CHECK (derived_status IN ('active','stale','manual')),
    source_tag              TEXT,
    -- Mirrors agent_quality_rules / agent_defect_code_bindings so
    -- link_repo.rollback_version()'s generic UPDATE ... SET updated_at=now()
    -- doesn't need a special-case for this table.
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_std_dm_snapshot_version
    ON std_data_model_snapshot(document_version_id);

CREATE INDEX IF NOT EXISTS idx_std_dm_snapshot_active
    ON std_data_model_snapshot(document_version_id, generated_at DESC)
    WHERE derived_status = 'active';

CREATE INDEX IF NOT EXISTS idx_std_dm_snapshot_link
    ON std_data_model_snapshot(std_derived_link_id);
