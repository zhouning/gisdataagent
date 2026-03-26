-- Agent message bus persistence (v15.4)
CREATE TABLE IF NOT EXISTS agent_messages (
    id BIGSERIAL PRIMARY KEY,
    message_id VARCHAR(36) NOT NULL,
    from_agent VARCHAR(100) NOT NULL DEFAULT '',
    to_agent VARCHAR(100) NOT NULL DEFAULT '',
    message_type VARCHAR(30) NOT NULL DEFAULT 'notification',
    payload JSONB NOT NULL DEFAULT '{}',
    correlation_id VARCHAR(100) NOT NULL DEFAULT '',
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_msg_undelivered
    ON agent_messages (to_agent, created_at) WHERE delivered = FALSE;
CREATE INDEX IF NOT EXISTS idx_agent_msg_correlation
    ON agent_messages (correlation_id) WHERE correlation_id != '';
