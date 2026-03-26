-- Migration 041: Alert Rules for QC monitoring
-- Configurable threshold-based alerts with push channels

CREATE TABLE IF NOT EXISTS agent_alert_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    metric_name VARCHAR(100) NOT NULL,
    condition VARCHAR(20) NOT NULL DEFAULT 'gt',
    threshold FLOAT NOT NULL,
    severity VARCHAR(20) DEFAULT 'warning',
    channel VARCHAR(30) DEFAULT 'webhook',
    channel_config JSONB DEFAULT '{}'::jsonb,
    enabled BOOLEAN DEFAULT TRUE,
    cooldown_seconds INTEGER DEFAULT 300,
    owner_username VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_alert_history (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER REFERENCES agent_alert_rules(id) ON DELETE CASCADE,
    metric_name VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    threshold FLOAT NOT NULL,
    severity VARCHAR(20),
    message TEXT,
    notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_metric
    ON agent_alert_rules (metric_name, enabled);
CREATE INDEX IF NOT EXISTS idx_alert_history_rule
    ON agent_alert_history (rule_id, created_at DESC);
