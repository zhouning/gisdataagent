-- 018: Fusion operations tracking table
-- Records multi-modal data fusion operations for audit and lineage.

CREATE TABLE IF NOT EXISTS agent_fusion_operations (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    source_files JSONB NOT NULL DEFAULT '[]',
    strategy VARCHAR(50) NOT NULL,
    parameters JSONB DEFAULT '{}',
    output_file TEXT,
    quality_score FLOAT,
    quality_report JSONB DEFAULT '{}',
    duration_s FLOAT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fusion_ops_user ON agent_fusion_operations(username);
CREATE INDEX IF NOT EXISTS idx_fusion_ops_created ON agent_fusion_operations(created_at DESC);
