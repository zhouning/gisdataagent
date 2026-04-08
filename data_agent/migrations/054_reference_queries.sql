-- Migration 054: Reference query library for NL2SQL few-shot and context enrichment (v19.0)
-- Curated + auto-ingested verified queries with embedding search

CREATE TABLE IF NOT EXISTS agent_reference_queries (
    id BIGSERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    description TEXT DEFAULT '',
    response_summary TEXT,
    tags JSONB DEFAULT '[]'::jsonb,
    pipeline_type VARCHAR(50),
    task_type VARCHAR(50),
    source VARCHAR(30) DEFAULT 'manual',   -- auto (from upvote) / manual / seed
    feedback_id BIGINT REFERENCES agent_feedback(id) ON DELETE SET NULL,
    embedding REAL[],                       -- 768-dim text-embedding-004 (matches kb_chunks)
    use_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    verified_by VARCHAR(100),
    verified_at TIMESTAMP,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refq_pipeline
    ON agent_reference_queries (pipeline_type);
CREATE INDEX IF NOT EXISTS idx_refq_tags
    ON agent_reference_queries USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_refq_use_count
    ON agent_reference_queries (use_count DESC);
CREATE INDEX IF NOT EXISTS idx_refq_source
    ON agent_reference_queries (source);
