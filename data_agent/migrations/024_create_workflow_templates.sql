-- v10.0.4: Workflow Templates and Marketplace
-- Pre-built workflow definitions for cloning and reuse.

CREATE TABLE IF NOT EXISTS agent_workflow_templates (
    id SERIAL PRIMARY KEY,
    template_name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    category VARCHAR(50) DEFAULT 'general',
    author_username VARCHAR(100) NOT NULL,
    pipeline_type VARCHAR(30) DEFAULT 'general',
    steps JSONB NOT NULL,
    default_parameters JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT '{}'::text[],
    is_published BOOLEAN DEFAULT FALSE,
    clone_count INTEGER DEFAULT 0,
    rating_sum INTEGER DEFAULT 0,
    rating_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wft_published ON agent_workflow_templates(is_published) WHERE is_published = TRUE;
CREATE INDEX IF NOT EXISTS idx_wft_category ON agent_workflow_templates(category);
CREATE INDEX IF NOT EXISTS idx_wft_author ON agent_workflow_templates(author_username);
