-- 244: Auditable expert decisions for generated business-question candidates.
--
-- Queue artifacts are immutable evidence and never become Gold by editing the
-- JSON file.  This registry records the human decision separately.  An
-- approved row only authorizes a later, independent Gold-contract generation
-- step; it does not expose Gold SQL and it is not a runtime routing input.

CREATE TABLE IF NOT EXISTS agent_business_benchmark_reviews (
    id BIGSERIAL PRIMARY KEY,
    scope VARCHAR(32) NOT NULL CHECK (scope ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'),
    task_id VARCHAR(255) NOT NULL,
    decision VARCHAR(32) NOT NULL CHECK (
        decision IN ('approved_for_gold', 'rejected', 'needs_changes')
    ),
    review_notes TEXT NOT NULL DEFAULT '',
    question_templates JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewed_by VARCHAR(255) NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scope, task_id)
);

CREATE INDEX IF NOT EXISTS idx_business_benchmark_reviews_scope_decision
    ON agent_business_benchmark_reviews (scope, decision, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_business_benchmark_reviews_scope_updated
    ON agent_business_benchmark_reviews (scope, updated_at DESC);

GRANT SELECT ON agent_business_benchmark_reviews TO agent_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_business_benchmark_reviews TO agent_user;
GRANT USAGE, SELECT ON SEQUENCE agent_business_benchmark_reviews_id_seq TO agent_user;
