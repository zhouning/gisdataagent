-- 131: Versioned, auditable platform branding settings.

CREATE TABLE IF NOT EXISTS app_platform_settings (
    namespace TEXT NOT NULL,
    setting_key TEXT NOT NULL,
    setting_value TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (namespace, setting_key),
    CONSTRAINT ck_app_platform_settings_namespace CHECK (
        namespace ~ '^[a-z][a-z0-9_.-]{1,63}$'
    ),
    CONSTRAINT ck_app_platform_settings_key CHECK (
        setting_key ~ '^[a-z][a-z0-9_.-]{1,63}$'
    ),
    CONSTRAINT ck_app_platform_settings_value_size CHECK (
        octet_length(setting_value) BETWEEN 1 AND 1024
    )
);

CREATE INDEX IF NOT EXISTS idx_app_platform_settings_updated_at
    ON app_platform_settings (updated_at DESC);

REVOKE ALL ON app_platform_settings FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') THEN
        GRANT SELECT, INSERT, UPDATE ON app_platform_settings TO agent_user;
    END IF;
END;
$$;
