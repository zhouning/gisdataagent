-- Migration 005: Rename system tables to add 'agent_' prefix
-- Avoids name collisions in shared development databases.
-- Safe to run: checks source exists and target doesn't before renaming.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='app_users')
       AND NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='agent_app_users') THEN
        ALTER TABLE app_users RENAME TO agent_app_users;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='user_memories')
       AND NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='agent_user_memories') THEN
        ALTER TABLE user_memories RENAME TO agent_user_memories;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='token_usage')
       AND NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='agent_token_usage') THEN
        ALTER TABLE token_usage RENAME TO agent_token_usage;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='table_ownership')
       AND NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='agent_table_ownership') THEN
        ALTER TABLE table_ownership RENAME TO agent_table_ownership;
    END IF;
END $$;
