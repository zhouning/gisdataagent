-- Logical BIRD source names map to separate, read-only PostgreSQL databases.
CREATE TABLE IF NOT EXISTS agent_bird_databases (
    db_id TEXT PRIMARY KEY,
    database_name TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL UNIQUE,
    table_count INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (db_id ~ '^[a-z0-9_]+$'),
    CHECK (database_name = 'bird_' || db_id),
    CHECK (source_name = database_name)
);

CREATE TABLE IF NOT EXISTS agent_bird_tables (
    db_id TEXT NOT NULL REFERENCES agent_bird_databases(db_id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    columns_json JSONB NOT NULL,
    foreign_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    primary_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    estimated_rows BIGINT NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (db_id, table_name)
);
