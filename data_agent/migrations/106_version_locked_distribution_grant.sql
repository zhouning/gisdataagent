-- 106: Lock approved asset grants to an immutable DataProductVersion and
-- invalidate generated packages when a grant is revoked.
--
-- The Catalog remains the asset authority. An asset may declare its product
-- identity at operational_metadata.publication.data_product_urn. Approval
-- validates that reference through the governed registry and snapshots the
-- then-current immutable version here. Assets without that declaration keep
-- the migration-105 compatibility path and remain explicitly transitional.

ALTER TABLE gda_control.data_product_version
    ADD CONSTRAINT uq_gda_data_product_version_binding
    UNIQUE (tenant_id, product_urn, data_product_version_id, version_key);

ALTER TABLE agent_data_requests
    ADD COLUMN IF NOT EXISTS product_tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS product_urn TEXT,
    ADD COLUMN IF NOT EXISTS data_product_version_id UUID,
    ADD COLUMN IF NOT EXISTS data_product_version_key TEXT,
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS revoked_by VARCHAR(100),
    ADD COLUMN IF NOT EXISTS revocation_reason TEXT NOT NULL DEFAULT '';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_dreq_data_product_version'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT fk_dreq_data_product_version
            FOREIGN KEY (
                product_tenant_id, product_urn,
                data_product_version_id, data_product_version_key
            ) REFERENCES gda_control.data_product_version (
                tenant_id, product_urn, data_product_version_id, version_key
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_dreq_product_version_binding'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT ck_dreq_product_version_binding CHECK (
                (
                    product_tenant_id IS NULL
                    AND product_urn IS NULL
                    AND data_product_version_id IS NULL
                    AND data_product_version_key IS NULL
                )
                OR (
                    status = 'approved'
                    AND product_tenant_id IS NOT NULL
                    AND product_urn IS NOT NULL
                    AND data_product_version_id IS NOT NULL
                    AND data_product_version_key IS NOT NULL
                    AND product_urn LIKE
                        'gda://' || product_tenant_id || '/data_product/%'
                    AND data_product_version_key
                        ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_dreq_revocation'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT ck_dreq_revocation CHECK (
                (
                    revoked_at IS NULL
                    AND revoked_by IS NULL
                    AND revocation_reason = ''
                )
                OR (
                    status = 'approved'
                    AND revoked_at IS NOT NULL
                    AND NULLIF(btrim(revoked_by), '') IS NOT NULL
                    AND NULLIF(btrim(revocation_reason), '') IS NOT NULL
                    AND approved_at IS NOT NULL
                    AND revoked_at >= approved_at
                )
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_dreq_revocable_grant
    ON agent_data_requests(asset_id, requester, expires_at DESC)
    WHERE status = 'approved' AND revoked_at IS NULL;

CREATE TABLE agent_distribution_packages (
    package_id UUID PRIMARY KEY,
    requester VARCHAR(100) NOT NULL,
    zip_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    invalidated_at TIMESTAMP,
    invalidated_by VARCHAR(100),
    invalidation_reason TEXT NOT NULL DEFAULT '',
    download_count INTEGER NOT NULL DEFAULT 0,
    last_downloaded_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_distribution_package_name UNIQUE (requester, zip_name),
    CONSTRAINT ck_distribution_package_name CHECK (
        zip_name ~ '^data_package_[0-9a-f]{12}\.zip$'
    ),
    CONSTRAINT ck_distribution_package_expiry CHECK (expires_at > created_at),
    CONSTRAINT ck_distribution_package_invalidation CHECK (
        (
            invalidated_at IS NULL
            AND invalidated_by IS NULL
            AND invalidation_reason = ''
        )
        OR (
            invalidated_at IS NOT NULL
            AND NULLIF(btrim(invalidated_by), '') IS NOT NULL
            AND NULLIF(btrim(invalidation_reason), '') IS NOT NULL
            AND invalidated_at >= created_at
        )
    ),
    CONSTRAINT ck_distribution_package_download_count CHECK (download_count >= 0)
);

CREATE TABLE agent_distribution_package_items (
    package_id UUID NOT NULL,
    asset_id INTEGER NOT NULL,
    grant_request_id INTEGER,
    PRIMARY KEY (package_id, asset_id),
    CONSTRAINT fk_distribution_package
        FOREIGN KEY (package_id)
        REFERENCES agent_distribution_packages(package_id) ON DELETE CASCADE,
    CONSTRAINT fk_distribution_package_asset
        FOREIGN KEY (asset_id) REFERENCES agent_data_assets(id),
    CONSTRAINT fk_distribution_package_grant
        FOREIGN KEY (grant_request_id) REFERENCES agent_data_requests(id)
);

CREATE INDEX idx_distribution_package_grant
    ON agent_distribution_package_items(grant_request_id)
    WHERE grant_request_id IS NOT NULL;

ALTER TABLE agent_distribution_packages ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_distribution_packages FORCE ROW LEVEL SECURITY;
CREATE POLICY distribution_package_isolation ON agent_distribution_packages
    USING (
        requester = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    )
    WITH CHECK (
        requester = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

ALTER TABLE agent_distribution_package_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_distribution_package_items FORCE ROW LEVEL SECURITY;
CREATE POLICY distribution_package_item_isolation
    ON agent_distribution_package_items
    USING (
        EXISTS (
            SELECT 1
            FROM agent_distribution_packages package
            WHERE package.package_id = agent_distribution_package_items.package_id
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM agent_distribution_packages package
            WHERE package.package_id = agent_distribution_package_items.package_id
        )
    );

GRANT SELECT, INSERT, UPDATE ON agent_distribution_packages TO agent_user;
GRANT SELECT, INSERT ON agent_distribution_package_items TO agent_user;
