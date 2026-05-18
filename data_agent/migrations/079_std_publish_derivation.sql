-- 079: Wave 5 — std_data_element binding columns + std_publish_event table
--      + tighten std_derived_link with PARTIAL UNIQUE (active per target).
--
-- Design note (deviates from spec §3.1):
--   The spec assumed `sources(id)` UUID FK, but no such table exists.
--   The actual semantic layer (agent_semantic_sources / agent_semantic_hints)
--   keys natively by `table_name` TEXT and uses `scope_ref` like 'tbl.col'.
--   We therefore bind by (bound_table, bound_column) only — no source UUID.

-- (a) std_data_element binding columns ----------------------------------
ALTER TABLE std_data_element
    ADD COLUMN IF NOT EXISTS bound_table   TEXT,
    ADD COLUMN IF NOT EXISTS bound_column  TEXT;

ALTER TABLE std_data_element
    DROP CONSTRAINT IF EXISTS std_data_element_binding_consistency_check;
ALTER TABLE std_data_element
    ADD CONSTRAINT std_data_element_binding_consistency_check
        CHECK ((bound_table IS NULL AND bound_column IS NULL)
            OR (bound_table IS NOT NULL AND bound_column IS NOT NULL));

CREATE INDEX IF NOT EXISTS idx_std_data_element_bound_target
    ON std_data_element(bound_table, bound_column)
    WHERE bound_table IS NOT NULL;

-- (b) std_publish_event table -------------------------------------------
CREATE TABLE IF NOT EXISTS std_publish_event (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    event_type          TEXT NOT NULL,
    actor_user_id       TEXT NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes               TEXT,
    CONSTRAINT std_publish_event_type_check
        CHECK (event_type IN ('published','forked'))
);

CREATE INDEX IF NOT EXISTS idx_std_publish_event_version
    ON std_publish_event(document_version_id, occurred_at DESC);

-- (c) std_derived_link PARTIAL UNIQUE on active rows --------------------
-- Per spec §7 invariant 1: same (strategy, target) only one active row.
CREATE UNIQUE INDEX IF NOT EXISTS idx_std_derived_link_unique_active
    ON std_derived_link(derivation_strategy, target_kind, target_id)
    WHERE status = 'active';
