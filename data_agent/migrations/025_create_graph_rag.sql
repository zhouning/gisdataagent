-- v10.0.5: GraphRAG — Entity extraction + graph-augmented retrieval
-- Entities extracted from KB chunks, linked in a relation graph.

CREATE TABLE IF NOT EXISTS agent_kb_entities (
    id SERIAL PRIMARY KEY,
    chunk_id INTEGER NOT NULL REFERENCES agent_kb_chunks(id) ON DELETE CASCADE,
    kb_id INTEGER NOT NULL,
    entity_name VARCHAR(300) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    confidence REAL DEFAULT 1.0,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kbe_chunk ON agent_kb_entities(chunk_id);
CREATE INDEX IF NOT EXISTS idx_kbe_kb ON agent_kb_entities(kb_id);
CREATE INDEX IF NOT EXISTS idx_kbe_name ON agent_kb_entities(entity_name);

CREATE TABLE IF NOT EXISTS agent_kb_relations (
    id SERIAL PRIMARY KEY,
    kb_id INTEGER NOT NULL,
    source_entity_id INTEGER NOT NULL REFERENCES agent_kb_entities(id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES agent_kb_entities(id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,
    confidence REAL DEFAULT 1.0,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kbr_kb ON agent_kb_relations(kb_id);
CREATE INDEX IF NOT EXISTS idx_kbr_source ON agent_kb_relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_kbr_target ON agent_kb_relations(target_entity_id);
