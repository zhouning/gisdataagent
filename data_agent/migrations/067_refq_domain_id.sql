-- Migration 067: Add domain_id to reference_queries for domain-isolated few-shot
ALTER TABLE agent_reference_queries ADD COLUMN IF NOT EXISTS domain_id VARCHAR(256);
CREATE INDEX IF NOT EXISTS idx_refq_domain ON agent_reference_queries (domain_id);
