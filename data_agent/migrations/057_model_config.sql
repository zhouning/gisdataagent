-- Migration 057: Admin model configuration (v23.0)
-- Persistent model tier assignments and custom model registrations.

CREATE TABLE IF NOT EXISTS agent_model_config (
    config_key   VARCHAR(50) PRIMARY KEY,
    config_value VARCHAR(200) NOT NULL,
    updated_by   VARCHAR(100),
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed defaults (only if empty)
INSERT INTO agent_model_config (config_key, config_value, updated_by)
SELECT 'tier_fast', 'gemini-2.0-flash', 'system'
WHERE NOT EXISTS (SELECT 1 FROM agent_model_config WHERE config_key = 'tier_fast');

INSERT INTO agent_model_config (config_key, config_value, updated_by)
SELECT 'tier_standard', 'gemini-2.5-flash', 'system'
WHERE NOT EXISTS (SELECT 1 FROM agent_model_config WHERE config_key = 'tier_standard');

INSERT INTO agent_model_config (config_key, config_value, updated_by)
SELECT 'tier_premium', 'gemini-2.5-pro', 'system'
WHERE NOT EXISTS (SELECT 1 FROM agent_model_config WHERE config_key = 'tier_premium');

INSERT INTO agent_model_config (config_key, config_value, updated_by)
SELECT 'router_model', 'gemini-2.0-flash', 'system'
WHERE NOT EXISTS (SELECT 1 FROM agent_model_config WHERE config_key = 'router_model');
