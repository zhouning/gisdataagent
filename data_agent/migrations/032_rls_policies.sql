-- Row Level Security policies for multi-tenant isolation (v15.0)
-- Prerequisite: app.current_user and app.current_user_role GUCs set per transaction

-- Data Catalog
ALTER TABLE agent_data_catalog ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS catalog_isolation ON agent_data_catalog;
CREATE POLICY catalog_isolation ON agent_data_catalog
    USING (owner_username = current_setting('app.current_user', true)
           OR is_shared = true
           OR current_setting('app.current_user_role', true) = 'admin');

-- Custom Skills
ALTER TABLE agent_custom_skills ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS skills_isolation ON agent_custom_skills;
CREATE POLICY skills_isolation ON agent_custom_skills
    USING (owner_username = current_setting('app.current_user', true)
           OR is_shared = true
           OR current_setting('app.current_user_role', true) = 'admin');

-- User Tools
ALTER TABLE agent_user_tools ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS utools_isolation ON agent_user_tools;
CREATE POLICY utools_isolation ON agent_user_tools
    USING (owner_username = current_setting('app.current_user', true)
           OR is_shared = true
           OR current_setting('app.current_user_role', true) = 'admin');

-- Virtual Sources
ALTER TABLE agent_virtual_sources ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS vsource_isolation ON agent_virtual_sources;
CREATE POLICY vsource_isolation ON agent_virtual_sources
    USING (owner_username = current_setting('app.current_user', true)
           OR is_shared = true
           OR current_setting('app.current_user_role', true) = 'admin');

-- Workflows
ALTER TABLE agent_workflows ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS wf_isolation ON agent_workflows;
CREATE POLICY wf_isolation ON agent_workflows
    USING (owner_username = current_setting('app.current_user', true)
           OR is_shared = true
           OR current_setting('app.current_user_role', true) = 'admin');

-- Quality Rules
ALTER TABLE agent_quality_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS qrule_isolation ON agent_quality_rules;
CREATE POLICY qrule_isolation ON agent_quality_rules
    USING (owner_username = current_setting('app.current_user', true)
           OR is_shared = true
           OR current_setting('app.current_user_role', true) = 'admin');

-- User Memories
ALTER TABLE agent_user_memories ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_isolation ON agent_user_memories;
CREATE POLICY memory_isolation ON agent_user_memories
    USING (username = current_setting('app.current_user', true)
           OR current_setting('app.current_user_role', true) = 'admin');

-- Token Usage
ALTER TABLE agent_token_usage ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS token_isolation ON agent_token_usage;
CREATE POLICY token_isolation ON agent_token_usage
    USING (username = current_setting('app.current_user', true)
           OR current_setting('app.current_user_role', true) = 'admin');
