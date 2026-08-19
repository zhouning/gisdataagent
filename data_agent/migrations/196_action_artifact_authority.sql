-- 196: Tenant-scoped immutable Proposal/ChangeSet/ActionResult artifacts.
-- PlatformRun remains the execution authority; this table stores only sealed
-- action artifacts and does not create a second scheduler or run state.

CREATE TABLE IF NOT EXISTS gda_control.action_artifact (
    tenant_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    artifact_sha256 CHAR(64) NOT NULL,
    identity_key TEXT NOT NULL,
    run_id UUID,
    artifact_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, artifact_kind, artifact_sha256),
    CONSTRAINT uq_gda_action_artifact_identity
        UNIQUE (tenant_id, artifact_kind, identity_key),
    CONSTRAINT ck_gda_action_artifact_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_action_artifact_kind
        CHECK (artifact_kind IN ('proposal', 'change_set', 'action_result')),
    CONSTRAINT ck_gda_action_artifact_hash
        CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_action_artifact_identity
        CHECK (NULLIF(btrim(identity_key), '') IS NOT NULL AND octet_length(identity_key) <= 1024),
    CONSTRAINT ck_gda_action_artifact_document
        CHECK (
            jsonb_typeof(artifact_document) = 'object'
            AND artifact_document ->> 'tenant_id' = tenant_id
            AND (
                (artifact_kind = 'proposal'
                    AND artifact_document ->> 'proposal_sha256' = artifact_sha256
                    AND artifact_document -> 'execution_authorized' = 'false'::JSONB)
                OR (artifact_kind = 'change_set'
                    AND artifact_document ->> 'change_set_sha256' = artifact_sha256)
                OR (artifact_kind = 'action_result'
                    AND artifact_document ->> 'result_sha256' = artifact_sha256)
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_action_artifact_run
    ON gda_control.action_artifact (tenant_id, run_id, recorded_at DESC);

CREATE TRIGGER trg_gda_action_artifact_immutable
BEFORE UPDATE OR DELETE ON gda_control.action_artifact
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.action_artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.action_artifact FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.action_artifact
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.action_artifact FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.action_artifact TO gda_control_gateway;

CREATE OR REPLACE FUNCTION gda_control.guard_action_artifact_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.action_artifact_write_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.record_action_artifact()' USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'action artifact tenant is mismatched' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_action_artifact_guard_insert
    ON gda_control.action_artifact;
CREATE TRIGGER trg_gda_action_artifact_guard_insert
BEFORE INSERT ON gda_control.action_artifact
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_action_artifact_insert();

CREATE OR REPLACE FUNCTION gda_control.record_action_artifact(
    p_tenant_id TEXT,
    p_artifact_kind TEXT,
    p_artifact_sha256 TEXT,
    p_identity_key TEXT,
    p_run_id UUID,
    p_artifact_document JSONB
)
RETURNS TABLE(artifact_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.action_artifact%ROWTYPE;
    v_created BOOLEAN := false;
    v_row_count INTEGER := 0;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'action artifact tenant is mismatched' USING ERRCODE = '42501';
    END IF;
    IF p_artifact_kind NOT IN ('proposal', 'change_set', 'action_result')
       OR p_artifact_sha256 !~ '^[0-9a-f]{64}$'
       OR NULLIF(btrim(p_identity_key), '') IS NULL
       OR octet_length(p_identity_key) > 1024
       OR p_artifact_document IS NULL
       OR jsonb_typeof(p_artifact_document) <> 'object'
       OR p_artifact_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR (
            p_artifact_kind = 'proposal'
            AND (
                p_artifact_document ->> 'proposal_sha256'
                    IS DISTINCT FROM p_artifact_sha256
                OR p_artifact_document -> 'execution_authorized'
                    IS DISTINCT FROM 'false'::JSONB
            )
       )
       OR (
            p_artifact_kind = 'change_set'
            AND p_artifact_document ->> 'change_set_sha256'
                IS DISTINCT FROM p_artifact_sha256
       )
       OR (
            p_artifact_kind = 'action_result'
            AND p_artifact_document ->> 'result_sha256'
                IS DISTINCT FROM p_artifact_sha256
       )
    THEN
        RAISE EXCEPTION 'action artifact evidence is invalid' USING ERRCODE = '22023';
    END IF;

    PERFORM set_config('gda.action_artifact_write_allowed', '1', true);
    INSERT INTO gda_control.action_artifact (
        tenant_id, artifact_kind, artifact_sha256, identity_key,
        run_id, artifact_document
    ) VALUES (
        p_tenant_id, p_artifact_kind, p_artifact_sha256, p_identity_key,
        p_run_id, p_artifact_document
    ) ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    v_created := v_row_count > 0;

    SELECT * INTO v_existing
    FROM gda_control.action_artifact
    WHERE tenant_id = p_tenant_id
      AND artifact_kind = p_artifact_kind
      AND (artifact_sha256 = p_artifact_sha256 OR identity_key = p_identity_key)
    ORDER BY recorded_at
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'action artifact was not recorded' USING ERRCODE = '55000';
    END IF;
    IF v_existing.artifact_sha256 <> p_artifact_sha256
       OR v_existing.identity_key <> p_identity_key
       OR v_existing.artifact_document IS DISTINCT FROM p_artifact_document THEN
        RAISE EXCEPTION 'action artifact identity is already bound to different content'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT v_existing.artifact_document, v_created;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.record_action_artifact(
    TEXT, TEXT, TEXT, TEXT, UUID, JSONB
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_action_artifact(
    TEXT, TEXT, TEXT, TEXT, UUID, JSONB
) TO gda_control_gateway;
