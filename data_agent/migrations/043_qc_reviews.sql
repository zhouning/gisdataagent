-- Migration 043: QC Review workflow (human review loop)
-- Supports: review → mark → fix → approve cycle

CREATE TABLE IF NOT EXISTS agent_qc_reviews (
    id SERIAL PRIMARY KEY,
    workflow_run_id INTEGER,
    file_path TEXT NOT NULL,
    defect_code VARCHAR(20),
    defect_description TEXT,
    severity VARCHAR(10) DEFAULT 'B',
    status VARCHAR(20) DEFAULT 'pending',
    assigned_to VARCHAR(100),
    reviewer VARCHAR(100),
    review_comment TEXT,
    fix_description TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qc_reviews_status
    ON agent_qc_reviews (status, assigned_to);
CREATE INDEX IF NOT EXISTS idx_qc_reviews_run
    ON agent_qc_reviews (workflow_run_id);
