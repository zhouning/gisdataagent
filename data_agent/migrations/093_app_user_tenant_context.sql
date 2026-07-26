-- 093: Bind authenticated application users to an explicit platform tenant.
--
-- Existing users remain unbound and therefore cannot call the AR-1 platform
-- gateway until an administrator assigns a tenant. No compatibility default is
-- guessed because tenant identity is an authorization boundary.

ALTER TABLE agent_app_users
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_app_users_tenant_id'
          AND conrelid = 'agent_app_users'::regclass
    ) THEN
        ALTER TABLE agent_app_users
            ADD CONSTRAINT ck_agent_app_users_tenant_id CHECK (
                tenant_id IS NULL
                OR tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_app_users_tenant
    ON agent_app_users(tenant_id)
    WHERE tenant_id IS NOT NULL;
