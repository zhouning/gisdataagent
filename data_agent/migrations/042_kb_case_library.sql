-- Migration 042: Knowledge Base case library extension
-- Adds case-specific fields for QC experience library

ALTER TABLE agent_kb_documents ADD COLUMN IF NOT EXISTS doc_type VARCHAR(30) DEFAULT 'document';
ALTER TABLE agent_kb_documents ADD COLUMN IF NOT EXISTS defect_category VARCHAR(50);
ALTER TABLE agent_kb_documents ADD COLUMN IF NOT EXISTS product_type VARCHAR(50);
ALTER TABLE agent_kb_documents ADD COLUMN IF NOT EXISTS resolution TEXT;
ALTER TABLE agent_kb_documents ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_kb_docs_type
    ON agent_kb_documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_kb_docs_defect
    ON agent_kb_documents (defect_category) WHERE defect_category IS NOT NULL;
