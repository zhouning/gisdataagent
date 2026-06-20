-- 089: Self-evolution cycle audit records
-- Persists observe -> analyze -> propose cycle reports for human review,
-- approval UI, prompt diff review, and eval candidate promotion.

CREATE TABLE IF NOT EXISTS agent_self_evolution_cycles (
    id BIGSERIAL PRIMARY KEY,
    triggered_by VARCHAR(100) DEFAULT '',
    trigger_source VARCHAR(50) DEFAULT 'tool',
    mode VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'proposed',
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
    proposals JSONB NOT NULL DEFAULT '{}'::jsonb,
    safeguards JSONB NOT NULL DEFAULT '{}'::jsonb,
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_self_evolution_cycles_created
    ON agent_self_evolution_cycles (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_self_evolution_cycles_status
    ON agent_self_evolution_cycles (status, created_at DESC);
