-- =============================================================================
-- PostGIS initialization script
-- Runs once on first container creation via /docker-entrypoint-initdb.d/
-- =============================================================================

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Create application user (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'agent_user') THEN
        CREATE ROLE agent_user WITH LOGIN PASSWORD 'change_me_strong_password' NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$$;

-- Grant privileges
GRANT CONNECT ON DATABASE gis_agent TO agent_user;
GRANT USAGE ON SCHEMA public TO agent_user;
GRANT CREATE ON SCHEMA public TO agent_user;

-- Default privileges for future tables/sequences created by postgres
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agent_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO agent_user;
