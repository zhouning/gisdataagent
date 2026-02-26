-- Migration 007: Create audit_log table for system event tracking
-- Records high-value user actions for enterprise compliance and debugging

CREATE TABLE IF NOT EXISTS agent_audit_log (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    ip_address VARCHAR(45),
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_date ON agent_audit_log (username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON agent_audit_log (action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_date ON agent_audit_log (created_at DESC);
