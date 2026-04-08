-- Migration 053: Agent feedback table for structured feedback loop (v19.0)
-- Stores user thumbs-up/down on agent responses for learning flywheel

CREATE TABLE IF NOT EXISTS agent_feedback (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    session_id VARCHAR(100),
    message_id VARCHAR(100),
    pipeline_type VARCHAR(50),
    query_text TEXT NOT NULL,
    response_text TEXT,
    vote SMALLINT NOT NULL,                -- +1 upvote, -1 downvote
    issue_description TEXT,
    issue_tags JSONB DEFAULT '[]'::jsonb,
    context_snapshot JSONB,                -- ContextEngine output at request time
    resolved_at TIMESTAMP,
    resolution_action VARCHAR(50),         -- ingested_as_reference / prompt_optimized / dismissed
    resolution_ref VARCHAR(200),           -- e.g. reference_query_id or prompt_version_id
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_user_created
    ON agent_feedback (username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_vote
    ON agent_feedback (vote, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_pipeline
    ON agent_feedback (pipeline_type, vote);
CREATE INDEX IF NOT EXISTS idx_feedback_unresolved
    ON agent_feedback (resolved_at) WHERE resolved_at IS NULL;
