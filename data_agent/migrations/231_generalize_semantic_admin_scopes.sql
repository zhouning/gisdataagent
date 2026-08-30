-- 231: Allow the versioned semantic registry to serve any registered source.
-- Existing installations were created with a two-source check constraint;
-- scope remains bounded to a safe 32-character registration identifier.

ALTER TABLE IF EXISTS agent_semantic_admin_versions
    DROP CONSTRAINT IF EXISTS agent_semantic_admin_versions_scope_check;
ALTER TABLE IF EXISTS agent_semantic_admin_versions
    ADD CONSTRAINT agent_semantic_admin_versions_scope_check
    CHECK (scope ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$');

ALTER TABLE IF EXISTS agent_semantic_admin_entries
    DROP CONSTRAINT IF EXISTS agent_semantic_admin_entries_scope_check;
ALTER TABLE IF EXISTS agent_semantic_admin_entries
    ADD CONSTRAINT agent_semantic_admin_entries_scope_check
    CHECK (scope ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$');
