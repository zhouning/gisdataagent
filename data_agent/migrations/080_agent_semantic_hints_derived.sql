-- 080: Wave 5 — agent_semantic_hints derived metadata columns.
--      std_derived_link_id already exists (from P0); add std_version_id +
--      derived_status only.

ALTER TABLE agent_semantic_hints
    ADD COLUMN IF NOT EXISTS std_version_id   UUID,
    ADD COLUMN IF NOT EXISTS derived_status   TEXT;

ALTER TABLE agent_semantic_hints
    DROP CONSTRAINT IF EXISTS agent_semantic_hints_derived_status_check;
ALTER TABLE agent_semantic_hints
    ADD CONSTRAINT agent_semantic_hints_derived_status_check
        CHECK (derived_status IS NULL OR derived_status IN ('active','stale'));

CREATE INDEX IF NOT EXISTS idx_agent_semantic_hints_derived
    ON agent_semantic_hints(std_version_id, derived_status)
    WHERE std_derived_link_id IS NOT NULL;
