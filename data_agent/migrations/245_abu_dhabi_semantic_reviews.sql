-- 245: Auditable expert decisions for generated business-semantic tasks.
--
-- This is intentionally separate from the immutable semantic artifact and
-- versioned CRUD registry.  A decision records expert disposition only; it
-- never changes generated evidence, creates an executable binding, or
-- promotes a semantic entry into runtime without the existing publish gates.

CREATE TABLE IF NOT EXISTS agent_business_semantic_reviews (
    id BIGSERIAL PRIMARY KEY,
    scope VARCHAR(32) NOT NULL CHECK (scope ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'),
    queue_kind VARCHAR(32) NOT NULL CHECK (queue_kind IN ('table', 'field', 'relationship')),
    task_id VARCHAR(255) NOT NULL,
    decision VARCHAR(32) NOT NULL CHECK (
        decision IN ('approved_for_draft', 'needs_changes', 'rejected')
    ),
    review_notes TEXT NOT NULL DEFAULT '',
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewed_by VARCHAR(255) NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scope, queue_kind, task_id)
);

CREATE INDEX IF NOT EXISTS idx_business_semantic_reviews_scope_decision
    ON agent_business_semantic_reviews (scope, queue_kind, decision, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_business_semantic_reviews_scope_updated
    ON agent_business_semantic_reviews (scope, updated_at DESC);

GRANT SELECT ON agent_business_semantic_reviews TO agent_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_business_semantic_reviews TO agent_user;
GRANT USAGE, SELECT ON SEQUENCE agent_business_semantic_reviews_id_seq TO agent_user;
