-- Quality Rules — user-defined governance rules with standard linkage (v14.5)
CREATE TABLE IF NOT EXISTS agent_quality_rules (
    id SERIAL PRIMARY KEY,
    rule_name VARCHAR(200) NOT NULL,
    standard_id VARCHAR(100),
    rule_type VARCHAR(30) NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    severity VARCHAR(20) DEFAULT 'HIGH',
    enabled BOOLEAN DEFAULT TRUE,
    owner_username VARCHAR(100) NOT NULL,
    is_shared BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_quality_rule UNIQUE (rule_name, owner_username)
);
CREATE INDEX IF NOT EXISTS idx_qrule_owner ON agent_quality_rules (owner_username);
