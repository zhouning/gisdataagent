-- Migration 109: enforce the data asset catalog authorization boundary.
--
-- Migration 032 predates agent_data_assets, so a normally ordered database may
-- never have applied RLS to the unified backing table. Its legacy ALL policy
-- also treated shared assets as writable. Replace it with operation-specific,
-- fail-closed policies and force table owners through the same checks.

ALTER TABLE public.agent_data_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_data_assets FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS assets_isolation ON public.agent_data_assets;
DROP POLICY IF EXISTS agent_data_assets_select ON public.agent_data_assets;
DROP POLICY IF EXISTS agent_data_assets_insert ON public.agent_data_assets;
DROP POLICY IF EXISTS agent_data_assets_update ON public.agent_data_assets;
DROP POLICY IF EXISTS agent_data_assets_delete ON public.agent_data_assets;

CREATE POLICY agent_data_assets_select ON public.agent_data_assets
    FOR SELECT
    USING (
        owner_username = current_setting('app.current_user', true)
        OR is_shared = TRUE
        OR current_setting('app.current_user_role', true) = 'admin'
    );

CREATE POLICY agent_data_assets_insert ON public.agent_data_assets
    FOR INSERT
    WITH CHECK (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

CREATE POLICY agent_data_assets_update ON public.agent_data_assets
    FOR UPDATE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    )
    WITH CHECK (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

CREATE POLICY agent_data_assets_delete ON public.agent_data_assets
    FOR DELETE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );
