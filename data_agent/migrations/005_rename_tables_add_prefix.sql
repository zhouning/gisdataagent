-- Migration 005: Rename system tables to add 'agent_' prefix
-- Avoids name collisions in shared development databases.
-- Safe to run: IF EXISTS prevents errors if tables don't exist yet.
-- PostgreSQL RENAME automatically carries over indexes, RLS policies, constraints, and triggers.

ALTER TABLE IF EXISTS app_users RENAME TO agent_app_users;
ALTER TABLE IF EXISTS user_memories RENAME TO agent_user_memories;
ALTER TABLE IF EXISTS token_usage RENAME TO agent_token_usage;
ALTER TABLE IF EXISTS table_ownership RENAME TO agent_table_ownership;

-- Verification
DO $$
DECLARE
    r RECORD;
BEGIN
    RAISE NOTICE '--- Renamed Tables ---';
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename LIKE 'agent_%'
        ORDER BY tablename
    LOOP
        RAISE NOTICE '  %', r.tablename;
    END LOOP;
END $$;
