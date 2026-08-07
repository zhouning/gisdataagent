-- AR-0 forward repair: these tables previously existed only through runtime
-- ensure_* helpers, while historical SQL migrations depend on them.

CREATE TABLE IF NOT EXISTS agent_user_tools (
    id SERIAL PRIMARY KEY,
    owner_username VARCHAR(100) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT '',
    parameters JSONB DEFAULT '[]',
    template_type VARCHAR(30) NOT NULL,
    template_config JSONB DEFAULT '{}',
    python_code TEXT,
    is_shared BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    timeout_seconds INTEGER DEFAULT 30,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(owner_username, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_ut_owner ON agent_user_tools(owner_username);
CREATE INDEX IF NOT EXISTS idx_ut_shared
    ON agent_user_tools(is_shared) WHERE is_shared = TRUE;
CREATE INDEX IF NOT EXISTS idx_ut_enabled
    ON agent_user_tools(enabled) WHERE enabled = TRUE;

CREATE TABLE IF NOT EXISTS agent_mcp_servers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    transport VARCHAR(30) DEFAULT 'stdio',
    enabled BOOLEAN DEFAULT FALSE,
    category VARCHAR(50) DEFAULT '',
    pipelines JSONB DEFAULT '["general","planner"]',
    command VARCHAR(500) DEFAULT '',
    args JSONB DEFAULT '[]',
    env JSONB DEFAULT '{}',
    cwd VARCHAR(500),
    url VARCHAR(500) DEFAULT '',
    headers JSONB DEFAULT '{}',
    timeout REAL DEFAULT 5.0,
    bearer_token_env_var VARCHAR(255) DEFAULT '',
    bearer_token_file_env_var VARCHAR(255) DEFAULT '',
    ca_bundle_env_var VARCHAR(255) DEFAULT '',
    system_managed BOOLEAN DEFAULT FALSE,
    expose_raw_tools BOOLEAN DEFAULT TRUE,
    owner_username VARCHAR(100),
    is_shared BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_knowledge_bases (
    id SERIAL PRIMARY KEY,
    owner_username VARCHAR(100) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    is_shared BOOLEAN DEFAULT FALSE,
    document_count INTEGER DEFAULT 0,
    total_chunks INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(owner_username, name)
);

CREATE TABLE IF NOT EXISTS agent_kb_documents (
    id SERIAL PRIMARY KEY,
    kb_id INTEGER NOT NULL REFERENCES agent_knowledge_bases(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(50) NOT NULL,
    raw_text TEXT,
    char_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_kb_chunks (
    id SERIAL PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES agent_kb_documents(id) ON DELETE CASCADE,
    kb_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding REAL[],
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_owner ON agent_knowledge_bases(owner_username);
CREATE INDEX IF NOT EXISTS idx_kb_shared
    ON agent_knowledge_bases(is_shared) WHERE is_shared = TRUE;
CREATE INDEX IF NOT EXISTS idx_kbdoc_kb ON agent_kb_documents(kb_id);
CREATE INDEX IF NOT EXISTS idx_kbc_doc ON agent_kb_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_kbc_kb ON agent_kb_chunks(kb_id);
