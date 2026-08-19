-- 175: PostGIS-local, transaction-bound projection repair receipts.
--
-- The target mutation and this receipt are committed by the same PostgreSQL
-- transaction. Recovery may therefore use a matching receipt as provider
-- commit evidence without replaying the sealed repair plan.

CREATE SCHEMA IF NOT EXISTS gda_provider;

CREATE TABLE IF NOT EXISTS gda_provider.postgis_projection_repair_receipt (
    tenant_id TEXT NOT NULL,
    projection_id TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    checkpoint_version INTEGER NOT NULL,
    plan_sha256 CHAR(64) NOT NULL,
    plan_idempotency_key CHAR(64) NOT NULL,
    provider_transaction_id TEXT NOT NULL,
    provider_commit_ref JSONB NOT NULL,
    target_exists BOOLEAN NOT NULL,
    target_content_sha256 CHAR(64),
    target_row_count BIGINT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    receipt_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, plan_idempotency_key),
    CONSTRAINT uq_gda_postgis_projection_receipt_plan
        UNIQUE (tenant_id, plan_sha256),
    CONSTRAINT uq_gda_postgis_projection_receipt_target_version
        UNIQUE (tenant_id, projection_id, target_ref, checkpoint_version),
    CONSTRAINT ck_gda_postgis_projection_receipt_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_postgis_projection_receipt_projection CHECK (
        projection_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_postgis_projection_receipt_target CHECK (
        NULLIF(btrim(target_ref), '') IS NOT NULL
        AND octet_length(target_ref) <= 512
    ),
    CONSTRAINT ck_gda_postgis_projection_receipt_action
        CHECK (action IN ('checkpoint', 'rebuild', 'delete')),
    CONSTRAINT ck_gda_postgis_projection_receipt_status CHECK (
        status IN ('completed', 'replayed', 'checkpointed', 'deleted')
    ),
    CONSTRAINT ck_gda_postgis_projection_receipt_action_status CHECK (
        (action = 'checkpoint' AND status IN ('checkpointed', 'replayed'))
        OR (action = 'rebuild' AND status IN ('completed', 'replayed'))
        OR (action = 'delete' AND status IN ('deleted', 'replayed'))
    ),
    CONSTRAINT ck_gda_postgis_projection_receipt_version
        CHECK (checkpoint_version >= 1),
    CONSTRAINT ck_gda_postgis_projection_receipt_plan_sha CHECK (
        plan_sha256 ~ '^[0-9a-f]{64}$'
        AND plan_idempotency_key ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_postgis_projection_receipt_transaction
        CHECK (provider_transaction_id ~ '^[0-9]+$'),
    CONSTRAINT ck_gda_postgis_projection_receipt_commit_ref CHECK (
        jsonb_typeof(provider_commit_ref) = 'object'
        AND provider_commit_ref ->> 'provider' = 'postgis'
        AND provider_commit_ref ->> 'provider_transaction_id'
            = provider_transaction_id
        AND provider_commit_ref ->> 'plan_sha256' = plan_sha256
        AND provider_commit_ref ->> 'idempotency_key' = plan_idempotency_key
        AND provider_commit_ref ->> 'receipt_sha256' = receipt_sha256
    ),
    CONSTRAINT ck_gda_postgis_projection_receipt_target_state CHECK (
        target_row_count >= 0
        AND (
            target_exists
            AND target_content_sha256 ~ '^[0-9a-f]{64}$'
            OR NOT target_exists
            AND target_content_sha256 IS NULL
            AND target_row_count = 0
        )
    ),
    CONSTRAINT ck_gda_postgis_projection_receipt_sha
        CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_gda_postgis_projection_receipt_target
    ON gda_provider.postgis_projection_repair_receipt (
        tenant_id, projection_id, target_ref, checkpoint_version DESC
    );

CREATE OR REPLACE FUNCTION gda_provider.reject_postgis_projection_receipt_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'PostGIS projection provider receipts are immutable'
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_postgis_projection_receipt_immutable
    ON gda_provider.postgis_projection_repair_receipt;
CREATE TRIGGER trg_gda_postgis_projection_receipt_immutable
BEFORE UPDATE OR DELETE ON gda_provider.postgis_projection_repair_receipt
FOR EACH ROW
EXECUTE FUNCTION gda_provider.reject_postgis_projection_receipt_mutation();

ALTER TABLE gda_provider.postgis_projection_repair_receipt
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_provider.postgis_projection_repair_receipt
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_provider.postgis_projection_repair_receipt;
CREATE POLICY tenant_isolation
    ON gda_provider.postgis_projection_repair_receipt
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant', true), '')
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant', true), '')
    );

REVOKE ALL ON SCHEMA gda_provider FROM PUBLIC;
REVOKE ALL ON TABLE gda_provider.postgis_projection_repair_receipt FROM PUBLIC;
REVOKE ALL ON FUNCTION
    gda_provider.reject_postgis_projection_receipt_mutation() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') THEN
        GRANT USAGE ON SCHEMA gda_provider TO agent_user;
        GRANT SELECT, INSERT ON TABLE
            gda_provider.postgis_projection_repair_receipt TO agent_user;
    END IF;
END
$$;
