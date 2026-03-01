-- Migration 012: Team Collaboration Tables
-- Creates agent_teams and agent_team_members for F4 Team Collaboration

-- Table 1: Teams
CREATE TABLE IF NOT EXISTS agent_teams (
    id SERIAL PRIMARY KEY,
    team_name VARCHAR(100) NOT NULL UNIQUE,
    owner_username VARCHAR(100) NOT NULL,
    description TEXT DEFAULT '',
    max_members INT DEFAULT 10,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_teams_owner ON agent_teams (owner_username);

-- Table 2: Team Membership
CREATE TABLE IF NOT EXISTS agent_team_members (
    id SERIAL PRIMARY KEY,
    team_id INT NOT NULL REFERENCES agent_teams(id) ON DELETE CASCADE,
    username VARCHAR(100) NOT NULL,
    team_role VARCHAR(30) NOT NULL DEFAULT 'member',
    joined_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(team_id, username)
);
CREATE INDEX IF NOT EXISTS idx_agent_team_members_user ON agent_team_members (username);
CREATE INDEX IF NOT EXISTS idx_agent_team_members_team ON agent_team_members (team_id);

-- RLS on agent_teams: see teams you own or belong to
ALTER TABLE agent_teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_teams FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_teams_select ON agent_teams;
CREATE POLICY agent_teams_select ON agent_teams
    FOR SELECT
    USING (
        owner_username = current_setting('app.current_user', true)
        OR id IN (
            SELECT team_id FROM agent_team_members
            WHERE username = current_setting('app.current_user', true)
        )
        OR current_setting('app.current_user_role', true) = 'admin'
    );

DROP POLICY IF EXISTS agent_teams_insert ON agent_teams;
CREATE POLICY agent_teams_insert ON agent_teams
    FOR INSERT
    WITH CHECK (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

DROP POLICY IF EXISTS agent_teams_update ON agent_teams;
CREATE POLICY agent_teams_update ON agent_teams
    FOR UPDATE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

DROP POLICY IF EXISTS agent_teams_delete ON agent_teams;
CREATE POLICY agent_teams_delete ON agent_teams
    FOR DELETE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- RLS on agent_team_members: see members of teams you belong to
ALTER TABLE agent_team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_team_members FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_team_members_select ON agent_team_members;
CREATE POLICY agent_team_members_select ON agent_team_members
    FOR SELECT
    USING (
        team_id IN (
            SELECT team_id FROM agent_team_members
            WHERE username = current_setting('app.current_user', true)
        )
        OR team_id IN (
            SELECT id FROM agent_teams
            WHERE owner_username = current_setting('app.current_user', true)
        )
        OR current_setting('app.current_user_role', true) = 'admin'
    );

DROP POLICY IF EXISTS agent_team_members_insert ON agent_team_members;
CREATE POLICY agent_team_members_insert ON agent_team_members
    FOR INSERT
    WITH CHECK (
        team_id IN (
            SELECT id FROM agent_teams
            WHERE owner_username = current_setting('app.current_user', true)
        )
        OR current_setting('app.current_user_role', true) = 'admin'
    );

DROP POLICY IF EXISTS agent_team_members_delete ON agent_team_members;
CREATE POLICY agent_team_members_delete ON agent_team_members
    FOR DELETE
    USING (
        team_id IN (
            SELECT id FROM agent_teams
            WHERE owner_username = current_setting('app.current_user', true)
        )
        OR current_setting('app.current_user_role', true) = 'admin'
    );
