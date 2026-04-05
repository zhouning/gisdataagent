-- Migration 052: Database performance optimization (v18.0)
-- Materialized view for pipeline analytics + read-only role + pool monitoring

-- 1. Create read-only role for analytics queries
-- (Idempotent: skip if role already exists on managed RDS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_reader') THEN
        CREATE ROLE agent_reader WITH LOGIN PASSWORD 'reader_password_change_me';
    END IF;
END
$$;

-- Grant permissions (idempotent, uses dynamic SQL for current database)
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO agent_reader', current_database());
EXCEPTION WHEN OTHERS THEN
    NULL;
END
$$;

GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_reader;

-- 2. Materialized view: pipeline run analytics (hourly aggregation)
-- pipeline_type lives on agent_workflows, not on agent_workflow_runs → JOIN required
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_pipeline_analytics AS
SELECT
    DATE_TRUNC('hour', r.started_at) AS hour,
    w.pipeline_type,
    r.status,
    COUNT(*) AS run_count,
    AVG(EXTRACT(EPOCH FROM (r.completed_at - r.started_at))) AS avg_duration_seconds,
    MAX(EXTRACT(EPOCH FROM (r.completed_at - r.started_at))) AS max_duration_seconds
FROM agent_workflow_runs r
JOIN agent_workflows w ON w.id = r.workflow_id
WHERE r.started_at IS NOT NULL
GROUP BY 1, 2, 3;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_pipeline_analytics_pk
    ON mv_pipeline_analytics (hour, pipeline_type, status);

-- 3. Materialized view: token usage daily summary
-- agent_token_usage uses username (not user_id)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_token_usage_daily AS
SELECT
    DATE_TRUNC('day', created_at) AS day,
    username,
    model_name AS model,
    COUNT(*) AS request_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(input_tokens + output_tokens) AS total_tokens
FROM agent_token_usage
WHERE created_at IS NOT NULL
GROUP BY 1, 2, 3;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_token_usage_daily_pk
    ON mv_token_usage_daily (day, username, model);

-- 4. Helper function to refresh materialized views
CREATE OR REPLACE FUNCTION refresh_analytics_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_pipeline_analytics;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_token_usage_daily;
END;
$$ LANGUAGE plpgsql;

-- 5. Connection pool monitoring view (live query)
CREATE OR REPLACE VIEW v_connection_stats AS
SELECT
    datname,
    state,
    COUNT(*) AS connection_count,
    MAX(NOW() - state_change) AS max_idle_time
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY datname, state;
