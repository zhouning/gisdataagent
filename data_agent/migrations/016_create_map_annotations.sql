-- Migration 016: Create map annotations table for collaborative spatial comments.
CREATE TABLE IF NOT EXISTS agent_map_annotations (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    team_id INT DEFAULT NULL,
    title VARCHAR(200) DEFAULT '',
    comment TEXT DEFAULT '',
    lng DOUBLE PRECISION NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    color VARCHAR(20) DEFAULT '#e63946',
    is_resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_map_annotations_user ON agent_map_annotations (username);
CREATE INDEX IF NOT EXISTS idx_agent_map_annotations_team ON agent_map_annotations (team_id) WHERE team_id IS NOT NULL;
