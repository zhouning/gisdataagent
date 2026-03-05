-- 019: Knowledge graph snapshots
-- Stores serialized knowledge graph data for audit and persistence.

CREATE TABLE IF NOT EXISTS agent_knowledge_graphs (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    graph_name VARCHAR(200),
    node_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0,
    entity_types JSONB DEFAULT '{}',
    graph_data JSONB DEFAULT '{}',
    source_files JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kg_username ON agent_knowledge_graphs(username);
