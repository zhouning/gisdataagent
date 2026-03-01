-- Migration 013: Extend RLS for Team Collaboration
-- Team members can see data tables and templates owned by fellow team members.

-- Extend agent_table_ownership SELECT: add team member visibility
DROP POLICY IF EXISTS agent_table_ownership_select ON agent_table_ownership;
CREATE POLICY agent_table_ownership_select ON agent_table_ownership
    FOR SELECT
    USING (
        owner_username = current_setting('app.current_user', true)
        OR is_shared = TRUE
        OR current_setting('app.current_user_role', true) = 'admin'
        -- Team members see tables owned by any fellow team member
        OR owner_username IN (
            SELECT tm2.username FROM agent_team_members tm1
            JOIN agent_team_members tm2 ON tm1.team_id = tm2.team_id
            WHERE tm1.username = current_setting('app.current_user', true)
        )
    );

-- Extend agent_analysis_templates SELECT: add team member visibility
DROP POLICY IF EXISTS agent_templates_select ON agent_analysis_templates;
CREATE POLICY agent_templates_select ON agent_analysis_templates
    FOR SELECT
    USING (
        owner_username = current_setting('app.current_user', true)
        OR is_shared = TRUE
        OR current_setting('app.current_user_role', true) = 'admin'
        -- Team members see templates owned by any fellow team member
        OR owner_username IN (
            SELECT tm2.username FROM agent_team_members tm1
            JOIN agent_team_members tm2 ON tm1.team_id = tm2.team_id
            WHERE tm1.username = current_setting('app.current_user', true)
        )
    );
