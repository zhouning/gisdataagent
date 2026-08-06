-- 146: Governed DataPanel navigation visibility and ordering overrides.
-- Built-in navigation metadata remains code-owned; this table stores only
-- administrator-managed overrides so the default registry stays deployable.

CREATE TABLE IF NOT EXISTS app_navigation_policies (
    scope_type VARCHAR(20) NOT NULL,
    scope_key VARCHAR(100) NOT NULL,
    tab_key VARCHAR(100) NOT NULL,
    visible BOOLEAN,
    group_key VARCHAR(60),
    section_key VARCHAR(80),
    sort_order INTEGER,
    updated_by VARCHAR(100) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scope_type, scope_key, tab_key),
    CONSTRAINT ck_app_navigation_scope_type
        CHECK (scope_type IN ('global', 'tenant', 'role')),
    CONSTRAINT ck_app_navigation_scope_key
        CHECK (btrim(scope_key) <> ''),
    CONSTRAINT ck_app_navigation_sort_order
        CHECK (sort_order IS NULL OR sort_order >= 0)
);

CREATE INDEX IF NOT EXISTS idx_app_navigation_policies_scope
    ON app_navigation_policies (scope_type, scope_key, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_app_navigation_policies_tab
    ON app_navigation_policies (tab_key);
