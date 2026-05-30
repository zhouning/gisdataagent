-- 083: Wave 7 — agent_quality_rules derived metadata columns + FK.
--      The QcRuleStrategy (to_qc_rule) writes into this table; we add the
--      same derived-row scaffolding that agent_semantic_hints already has:
--        std_derived_link_id  UUID  -> std_derived_link(id) ON DELETE SET NULL
--        std_version_id       UUID
--        source_tag           TEXT
--        derived_status       TEXT  CHECK ('active' | 'stale')
--
-- Why this didn't ride 075's auto-FK loop: 075 only wired tables that existed
-- AND were named in the spec; agent_quality_rules existed since v14.5 (mig 029)
-- but the spec called the target "qc_rules" so the loop never matched.
--
-- Idempotent — safe to re-run on partial deployments.

ALTER TABLE agent_quality_rules
    ADD COLUMN IF NOT EXISTS std_derived_link_id UUID,
    ADD COLUMN IF NOT EXISTS std_version_id      UUID,
    ADD COLUMN IF NOT EXISTS source_tag          TEXT,
    ADD COLUMN IF NOT EXISTS derived_status      TEXT;

-- FK to std_derived_link with ON DELETE SET NULL: a deleted link should not
-- cascade-delete the derived rule (history preservation), only orphan it.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_quality_rules_derived_link_fk'
    ) THEN
        ALTER TABLE agent_quality_rules
            ADD CONSTRAINT agent_quality_rules_derived_link_fk
                FOREIGN KEY (std_derived_link_id)
                REFERENCES std_derived_link(id)
                ON DELETE SET NULL;
    END IF;
END $$;

ALTER TABLE agent_quality_rules
    DROP CONSTRAINT IF EXISTS agent_quality_rules_derived_status_check;
ALTER TABLE agent_quality_rules
    ADD CONSTRAINT agent_quality_rules_derived_status_check
        CHECK (derived_status IS NULL OR derived_status IN ('active','stale'));

CREATE INDEX IF NOT EXISTS idx_agent_quality_rules_derived
    ON agent_quality_rules(std_version_id, derived_status)
    WHERE std_derived_link_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_quality_rules_link
    ON agent_quality_rules(std_derived_link_id);
