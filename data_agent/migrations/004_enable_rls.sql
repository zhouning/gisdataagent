-- Migration 004: Enable Row-Level Security and Table Ownership Registry
-- Run by DB admin (not agent_user): psql -h <host> -U <admin> -d <db> -f 004_enable_rls.sql
-- Idempotent: safe to re-run.

-- ================================================================
-- PART 1: Ensure agent_user cannot bypass RLS
-- ================================================================
-- agent_user is already NOSUPERUSER (confirmed). Just ensure NOBYPASSRLS.
DO $$
BEGIN
    BEGIN
        EXECUTE 'ALTER ROLE agent_user NOBYPASSRLS';
        RAISE NOTICE '[RLS] agent_user set to NOBYPASSRLS';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE WARNING '[RLS] Cannot alter agent_user. Check: SELECT rolbypassrls FROM pg_roles WHERE rolname = ''agent_user''';
    END;
END $$;

-- ================================================================
-- PART 2: RLS on agent_user_memories
-- ================================================================
ALTER TABLE agent_user_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_user_memories FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_user_memories_isolation ON agent_user_memories;
CREATE POLICY agent_user_memories_isolation ON agent_user_memories
    USING (
        username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

DROP POLICY IF EXISTS agent_user_memories_insert ON agent_user_memories;
CREATE POLICY agent_user_memories_insert ON agent_user_memories
    FOR INSERT
    WITH CHECK (
        username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- ================================================================
-- PART 3: RLS on agent_token_usage
-- ================================================================
ALTER TABLE agent_token_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_token_usage FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_token_usage_isolation ON agent_token_usage;
CREATE POLICY agent_token_usage_isolation ON agent_token_usage
    USING (
        username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

DROP POLICY IF EXISTS agent_token_usage_insert ON agent_token_usage;
CREATE POLICY agent_token_usage_insert ON agent_token_usage
    FOR INSERT
    WITH CHECK (
        username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- ================================================================
-- PART 4: Table Ownership Registry — create + pre-seed BEFORE RLS
-- ================================================================
CREATE TABLE IF NOT EXISTS agent_table_ownership (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(200) UNIQUE NOT NULL,
    owner_username VARCHAR(100) NOT NULL,
    is_shared BOOLEAN DEFAULT FALSE,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_table_ownership_owner ON agent_table_ownership (owner_username);
CREATE INDEX IF NOT EXISTS idx_agent_table_ownership_shared ON agent_table_ownership (is_shared);

-- Pre-seed existing spatial tables as admin-shared (BEFORE enabling RLS)
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT f_table_name FROM geometry_columns
        WHERE f_table_schema = 'public'
    LOOP
        INSERT INTO agent_table_ownership (table_name, owner_username, is_shared, description)
        VALUES (tbl, 'admin', TRUE, 'Pre-existing shared table (auto-registered by migration)')
        ON CONFLICT (table_name) DO NOTHING;
    END LOOP;
END $$;

-- ================================================================
-- PART 5: Enable RLS on agent_table_ownership (after pre-seed)
-- ================================================================
ALTER TABLE agent_table_ownership ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_table_ownership FORCE ROW LEVEL SECURITY;

-- SELECT: own tables + shared + admin sees all
DROP POLICY IF EXISTS agent_table_ownership_select ON agent_table_ownership;
CREATE POLICY agent_table_ownership_select ON agent_table_ownership
    FOR SELECT
    USING (
        owner_username = current_setting('app.current_user', true)
        OR is_shared = TRUE
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- INSERT: own tables + admin
DROP POLICY IF EXISTS agent_table_ownership_insert ON agent_table_ownership;
CREATE POLICY agent_table_ownership_insert ON agent_table_ownership
    FOR INSERT
    WITH CHECK (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- UPDATE: own tables + admin (needed for share_table() and UPSERT)
DROP POLICY IF EXISTS agent_table_ownership_update ON agent_table_ownership;
CREATE POLICY agent_table_ownership_update ON agent_table_ownership
    FOR UPDATE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- DELETE: own tables + admin
DROP POLICY IF EXISTS agent_table_ownership_delete ON agent_table_ownership;
CREATE POLICY agent_table_ownership_delete ON agent_table_ownership
    FOR DELETE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- ================================================================
-- Verification
-- ================================================================
DO $$
DECLARE
    r RECORD;
BEGIN
    RAISE NOTICE '--- RLS Status ---';
    FOR r IN
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE relname IN ('agent_user_memories', 'agent_token_usage', 'agent_table_ownership')
    LOOP
        RAISE NOTICE '  % : rls=%, force=%', r.relname, r.relrowsecurity, r.relforcerowsecurity;
    END LOOP;

    RAISE NOTICE '--- Policies ---';
    FOR r IN
        SELECT tablename, policyname, cmd
        FROM pg_policies
        WHERE tablename IN ('agent_user_memories', 'agent_token_usage', 'agent_table_ownership')
        ORDER BY tablename, policyname
    LOOP
        RAISE NOTICE '  %.% (%)', r.tablename, r.policyname, r.cmd;
    END LOOP;

    RAISE NOTICE '--- Pre-seeded tables ---';
    FOR r IN
        SELECT count(*) AS cnt FROM agent_table_ownership
    LOOP
        RAISE NOTICE '  agent_table_ownership rows: %', r.cnt;
    END LOOP;
END $$;
