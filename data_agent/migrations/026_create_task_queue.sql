-- v11.0.1: Concurrent Task Queue
-- Background job management for parallel pipeline execution.

CREATE TABLE IF NOT EXISTS agent_task_queue (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(36) UNIQUE NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    prompt TEXT NOT NULL,
    pipeline_type VARCHAR(30) DEFAULT 'general',
    status VARCHAR(20) DEFAULT 'queued',
    priority INTEGER DEFAULT 5,
    result_summary TEXT,
    error_message TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    duration REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tq_user ON agent_task_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_tq_status ON agent_task_queue(status);
