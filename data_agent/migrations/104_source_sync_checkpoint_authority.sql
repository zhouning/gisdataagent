-- 104: Source sync definition, append-only commit, and CAS checkpoint authority.

CREATE TABLE IF NOT EXISTS gda_control.source_sync_definition (
    tenant_id TEXT NOT NULL,
    sync_definition_urn TEXT NOT NULL,
    sync_definition_version_id UUID PRIMARY KEY,
    platform_definition_version_id UUID NOT NULL,
    source_resource_urn TEXT NOT NULL,
    source_definition_fingerprint CHAR(64) NOT NULL,
    target_resource_urn TEXT NOT NULL,
    mode TEXT NOT NULL,
    write_disposition TEXT NOT NULL,
    cursor_kind TEXT NOT NULL,
    cursor_field TEXT,
    primary_keys TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    delete_mode TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    definition_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_source_sync_definition_tenant_id
        UNIQUE (tenant_id, sync_definition_version_id),
    CONSTRAINT uq_gda_source_sync_definition_urn_version
        UNIQUE (tenant_id, sync_definition_urn, sync_definition_version_id),
    CONSTRAINT fk_gda_source_sync_definition_resource_version
        FOREIGN KEY (
            tenant_id, sync_definition_urn,
            sync_definition_version_id, definition_sha256
        ) REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id, content_sha256
        ),
    CONSTRAINT fk_gda_source_sync_platform_definition
        FOREIGN KEY (tenant_id, platform_definition_version_id)
        REFERENCES gda_control.platform_definition_version(
            tenant_id, definition_version_id
        ),
    CONSTRAINT ck_gda_source_sync_definition_urn CHECK (
        sync_definition_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/sync_definition/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(sync_definition_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_source_sync_source_urn CHECK (
        source_resource_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_resource_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_source_sync_target_urn CHECK (
        target_resource_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(target_resource_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_source_sync_source_fingerprint
        CHECK (source_definition_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_sync_mode CHECK (mode IN ('full','incremental')),
    CONSTRAINT ck_gda_source_sync_disposition
        CHECK (write_disposition IN ('overwrite','append','merge')),
    CONSTRAINT ck_gda_source_sync_cursor_kind
        CHECK (cursor_kind IN ('none','field','provider_token','offset')),
    CONSTRAINT ck_gda_source_sync_cursor_field CHECK (
        (cursor_kind = 'field' AND cursor_field ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$')
        OR (cursor_kind <> 'field' AND cursor_field IS NULL)
    ),
    CONSTRAINT ck_gda_source_sync_delete_mode
        CHECK (delete_mode IN ('ignore','soft_delete','hard_delete')),
    CONSTRAINT ck_gda_source_sync_semantics CHECK (
        (
            mode = 'full'
            AND write_disposition = 'overwrite'
            AND cursor_kind = 'none'
            AND cursor_field IS NULL
        ) OR (
            mode = 'incremental'
            AND cursor_kind <> 'none'
        )
    ),
    CONSTRAINT ck_gda_source_sync_merge_keys CHECK (
        write_disposition <> 'merge' OR cardinality(primary_keys) > 0
    ),
    CONSTRAINT ck_gda_source_sync_delete_merge CHECK (
        delete_mode = 'ignore' OR write_disposition = 'merge'
    ),
    CONSTRAINT ck_gda_source_sync_config CHECK (jsonb_typeof(config) = 'object'),
    CONSTRAINT ck_gda_source_sync_definition_sha
        CHECK (definition_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_sync_definition_actor
        CHECK (created_by ~ '^(human|workload|agent):[^[:space:]]+$')
);

CREATE INDEX IF NOT EXISTS idx_gda_source_sync_definition_source
    ON gda_control.source_sync_definition(tenant_id, source_resource_urn);
CREATE INDEX IF NOT EXISTS idx_gda_source_sync_definition_target
    ON gda_control.source_sync_definition(tenant_id, target_resource_urn);

CREATE TABLE IF NOT EXISTS gda_control.source_sync_checkpoint (
    tenant_id TEXT NOT NULL,
    sync_definition_version_id UUID NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 0,
    cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
    cursor_sha256 CHAR(64) NOT NULL,
    last_sync_commit_id UUID,
    last_run_id UUID,
    target_commit_ref JSONB,
    target_content_sha256 CHAR(64),
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, sync_definition_version_id),
    CONSTRAINT fk_gda_source_sync_checkpoint_definition
        FOREIGN KEY (tenant_id, sync_definition_version_id)
        REFERENCES gda_control.source_sync_definition(
            tenant_id, sync_definition_version_id
        ),
    CONSTRAINT ck_gda_source_sync_checkpoint_version CHECK (state_version >= 0),
    CONSTRAINT ck_gda_source_sync_checkpoint_cursor
        CHECK (jsonb_typeof(cursor) = 'object'),
    CONSTRAINT ck_gda_source_sync_checkpoint_cursor_sha
        CHECK (cursor_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_sync_checkpoint_target_ref
        CHECK (target_commit_ref IS NULL OR jsonb_typeof(target_commit_ref) = 'object'),
    CONSTRAINT ck_gda_source_sync_checkpoint_target_sha
        CHECK (
            target_content_sha256 IS NULL
            OR target_content_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_gda_source_sync_checkpoint_actor
        CHECK (updated_by ~ '^(human|workload|agent):[^[:space:]]+$'),
    CONSTRAINT ck_gda_source_sync_checkpoint_state CHECK (
        (
            state_version = 0
            AND last_sync_commit_id IS NULL
            AND last_run_id IS NULL
            AND target_commit_ref IS NULL
            AND target_content_sha256 IS NULL
        ) OR (
            state_version > 0
            AND last_sync_commit_id IS NOT NULL
            AND last_run_id IS NOT NULL
            AND target_commit_ref IS NOT NULL
            AND target_content_sha256 IS NOT NULL
        )
    )
);

CREATE TABLE IF NOT EXISTS gda_control.source_sync_commit (
    tenant_id TEXT NOT NULL,
    sync_commit_id UUID PRIMARY KEY,
    sync_definition_version_id UUID NOT NULL,
    run_id UUID NOT NULL,
    from_state_version INTEGER NOT NULL,
    to_state_version INTEGER NOT NULL,
    previous_cursor JSONB NOT NULL,
    previous_cursor_sha256 CHAR(64) NOT NULL,
    next_cursor JSONB NOT NULL,
    next_cursor_sha256 CHAR(64) NOT NULL,
    source_slice_sha256 CHAR(64) NOT NULL,
    target_commit_ref JSONB NOT NULL,
    target_content_sha256 CHAR(64) NOT NULL,
    records_read BIGINT NOT NULL,
    records_inserted BIGINT NOT NULL,
    records_updated BIGINT NOT NULL,
    records_deleted BIGINT NOT NULL,
    records_output BIGINT NOT NULL,
    committed_by TEXT NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL,
    commit_sha256 CHAR(64) NOT NULL,
    CONSTRAINT uq_gda_source_sync_commit_tenant_id
        UNIQUE (tenant_id, sync_commit_id),
    CONSTRAINT uq_gda_source_sync_commit_state
        UNIQUE (tenant_id, sync_definition_version_id, to_state_version),
    CONSTRAINT uq_gda_source_sync_commit_dedupe
        UNIQUE (
            tenant_id, sync_definition_version_id,
            previous_cursor_sha256, next_cursor_sha256, source_slice_sha256
        ),
    CONSTRAINT fk_gda_source_sync_commit_definition
        FOREIGN KEY (tenant_id, sync_definition_version_id)
        REFERENCES gda_control.source_sync_definition(
            tenant_id, sync_definition_version_id
        ),
    CONSTRAINT fk_gda_source_sync_commit_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT ck_gda_source_sync_commit_version CHECK (
        from_state_version >= 0
        AND to_state_version = from_state_version + 1
    ),
    CONSTRAINT ck_gda_source_sync_commit_cursors CHECK (
        jsonb_typeof(previous_cursor) = 'object'
        AND jsonb_typeof(next_cursor) = 'object'
        AND previous_cursor_sha256 ~ '^[0-9a-f]{64}$'
        AND next_cursor_sha256 ~ '^[0-9a-f]{64}$'
        AND previous_cursor_sha256 <> next_cursor_sha256
    ),
    CONSTRAINT ck_gda_source_sync_commit_source_sha
        CHECK (source_slice_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_sync_commit_target CHECK (
        jsonb_typeof(target_commit_ref) = 'object'
        AND target_commit_ref <> '{}'::jsonb
        AND target_content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_source_sync_commit_counts CHECK (
        records_read >= 0
        AND records_inserted >= 0
        AND records_updated >= 0
        AND records_deleted >= 0
        AND records_output >= 0
        AND records_inserted + records_updated + records_deleted <= records_read
    ),
    CONSTRAINT ck_gda_source_sync_commit_actor
        CHECK (committed_by ~ '^workload:[^[:space:]]+$'),
    CONSTRAINT ck_gda_source_sync_commit_sha
        CHECK (commit_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_gda_source_sync_commit_run
    ON gda_control.source_sync_commit(tenant_id, run_id);

ALTER TABLE gda_control.source_sync_checkpoint
    ADD CONSTRAINT fk_gda_source_sync_checkpoint_last_commit
    FOREIGN KEY (tenant_id, last_sync_commit_id)
    REFERENCES gda_control.source_sync_commit(tenant_id, sync_commit_id);

CREATE OR REPLACE FUNCTION gda_control.guard_source_sync_definition_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_resource gda_control.resource%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_resource
    FROM gda_control.resource
    WHERE tenant_id = NEW.tenant_id
      AND resource_urn = NEW.sync_definition_urn;
    IF NOT FOUND
       OR v_resource.resource_kind <> 'sync_definition'
       OR v_resource.authority_system <> 'gda_control'
       OR v_resource.authority_locator <> NEW.sync_definition_urn THEN
        RAISE EXCEPTION 'source sync definition requires its canonical Resource'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_source_sync_checkpoint_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.state_version <> 0
       OR NEW.last_sync_commit_id IS NOT NULL
       OR NEW.last_run_id IS NOT NULL
       OR NEW.target_commit_ref IS NOT NULL
       OR NEW.target_content_sha256 IS NOT NULL THEN
        RAISE EXCEPTION 'source sync checkpoint has an invalid initial state'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_source_sync_checkpoint_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.source_sync_commit_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.commit_source_sync()'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.sync_definition_version_id IS DISTINCT FROM OLD.sync_definition_version_id
       OR NEW.state_version <> OLD.state_version + 1
       OR NEW.last_sync_commit_id IS NULL
       OR NEW.last_run_id IS NULL
       OR NEW.target_commit_ref IS NULL
       OR NEW.target_content_sha256 IS NULL THEN
        RAISE EXCEPTION 'source sync checkpoint must advance by one committed version'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_source_sync_commit_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.source_sync_commit_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.commit_source_sync()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.commit_source_sync(
    p_tenant_id TEXT,
    p_sync_commit_id UUID,
    p_sync_definition_version_id UUID,
    p_run_id UUID,
    p_from_state_version INTEGER,
    p_to_state_version INTEGER,
    p_previous_cursor JSONB,
    p_previous_cursor_sha256 TEXT,
    p_next_cursor JSONB,
    p_next_cursor_sha256 TEXT,
    p_source_slice_sha256 TEXT,
    p_target_commit_ref JSONB,
    p_target_content_sha256 TEXT,
    p_records_read BIGINT,
    p_records_inserted BIGINT,
    p_records_updated BIGINT,
    p_records_deleted BIGINT,
    p_records_output BIGINT,
    p_committed_by TEXT,
    p_committed_at TIMESTAMPTZ,
    p_commit_sha256 TEXT
)
RETURNS TABLE(result_sync_commit_id UUID, result_created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_definition gda_control.source_sync_definition%ROWTYPE;
    v_checkpoint gda_control.source_sync_checkpoint%ROWTYPE;
    v_existing gda_control.source_sync_commit%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
    v_run_actor TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_to_state_version <> p_from_state_version + 1
       OR p_previous_cursor IS NULL
       OR jsonb_typeof(p_previous_cursor) <> 'object'
       OR p_next_cursor IS NULL
       OR jsonb_typeof(p_next_cursor) <> 'object'
       OR p_previous_cursor_sha256 !~ '^[0-9a-f]{64}$'
       OR p_next_cursor_sha256 !~ '^[0-9a-f]{64}$'
       OR p_previous_cursor_sha256 = p_next_cursor_sha256
       OR p_source_slice_sha256 !~ '^[0-9a-f]{64}$'
       OR p_target_commit_ref IS NULL
       OR jsonb_typeof(p_target_commit_ref) <> 'object'
       OR p_target_commit_ref = '{}'::jsonb
       OR p_target_content_sha256 !~ '^[0-9a-f]{64}$'
       OR p_committed_by !~ '^workload:[^[:space:]]+$'
       OR p_commit_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'source sync commit identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.source_sync_commit AS c
    WHERE c.tenant_id = p_tenant_id
      AND c.sync_commit_id = p_sync_commit_id;
    IF FOUND THEN
        IF v_existing.sync_definition_version_id IS DISTINCT FROM p_sync_definition_version_id
           OR v_existing.run_id IS DISTINCT FROM p_run_id
           OR v_existing.from_state_version IS DISTINCT FROM p_from_state_version
           OR v_existing.to_state_version IS DISTINCT FROM p_to_state_version
           OR v_existing.previous_cursor IS DISTINCT FROM p_previous_cursor
           OR v_existing.previous_cursor_sha256 IS DISTINCT FROM p_previous_cursor_sha256
           OR v_existing.next_cursor IS DISTINCT FROM p_next_cursor
           OR v_existing.next_cursor_sha256 IS DISTINCT FROM p_next_cursor_sha256
           OR v_existing.source_slice_sha256 IS DISTINCT FROM p_source_slice_sha256
           OR v_existing.target_commit_ref IS DISTINCT FROM p_target_commit_ref
           OR v_existing.target_content_sha256 IS DISTINCT FROM p_target_content_sha256
           OR v_existing.records_read IS DISTINCT FROM p_records_read
           OR v_existing.records_inserted IS DISTINCT FROM p_records_inserted
           OR v_existing.records_updated IS DISTINCT FROM p_records_updated
           OR v_existing.records_deleted IS DISTINCT FROM p_records_deleted
           OR v_existing.records_output IS DISTINCT FROM p_records_output
           OR v_existing.committed_by IS DISTINCT FROM p_committed_by
           OR v_existing.committed_at IS DISTINCT FROM p_committed_at
           OR v_existing.commit_sha256 IS DISTINCT FROM p_commit_sha256 THEN
            RAISE EXCEPTION 'source sync commit identity has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.sync_commit_id, FALSE;
        RETURN;
    END IF;

    SELECT * INTO v_definition
    FROM gda_control.source_sync_definition AS d
    WHERE d.tenant_id = p_tenant_id
      AND d.sync_definition_version_id = p_sync_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source sync definition not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT * INTO v_run
    FROM gda_control.platform_run AS r
    WHERE r.tenant_id = p_tenant_id
      AND r.run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source sync PlatformRun not found'
            USING ERRCODE = 'P0002';
    END IF;
    v_run_actor := concat(
        v_run.subject_context->>'subject_type',
        ':',
        v_run.subject_context->>'subject_id'
    );
    IF v_run.definition_version_id <> v_definition.platform_definition_version_id
       OR v_run.orchestration_class <> 'dataops'
       OR v_run.status NOT IN ('dispatching','running','reconciling')
       OR v_run_actor <> p_committed_by
       OR p_committed_at < v_run.submitted_at THEN
        RAISE EXCEPTION 'source sync commit is not authorized by its PlatformRun'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_checkpoint
    FROM gda_control.source_sync_checkpoint AS cp
    WHERE cp.tenant_id = p_tenant_id
      AND cp.sync_definition_version_id = p_sync_definition_version_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source sync checkpoint not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.source_sync_commit AS c
    WHERE c.tenant_id = p_tenant_id
      AND c.sync_definition_version_id = p_sync_definition_version_id
      AND c.previous_cursor_sha256 = p_previous_cursor_sha256
      AND c.next_cursor_sha256 = p_next_cursor_sha256
      AND c.source_slice_sha256 = p_source_slice_sha256;
    IF FOUND THEN
        IF v_existing.previous_cursor IS DISTINCT FROM p_previous_cursor
           OR v_existing.next_cursor IS DISTINCT FROM p_next_cursor
           OR v_existing.target_commit_ref IS DISTINCT FROM p_target_commit_ref
           OR v_existing.target_content_sha256 IS DISTINCT FROM p_target_content_sha256
           OR v_existing.records_read IS DISTINCT FROM p_records_read
           OR v_existing.records_inserted IS DISTINCT FROM p_records_inserted
           OR v_existing.records_updated IS DISTINCT FROM p_records_updated
           OR v_existing.records_deleted IS DISTINCT FROM p_records_deleted
           OR v_existing.records_output IS DISTINCT FROM p_records_output THEN
            RAISE EXCEPTION 'duplicate source slice has different target evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.sync_commit_id, FALSE;
        RETURN;
    END IF;

    IF v_checkpoint.state_version <> p_from_state_version
       OR p_to_state_version <> v_checkpoint.state_version + 1
       OR v_checkpoint.cursor IS DISTINCT FROM p_previous_cursor
       OR v_checkpoint.cursor_sha256 IS DISTINCT FROM p_previous_cursor_sha256 THEN
        RAISE EXCEPTION 'source sync checkpoint version or cursor conflict'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config('gda.source_sync_commit_allowed', '1', true);
    INSERT INTO gda_control.source_sync_commit (
        tenant_id, sync_commit_id, sync_definition_version_id, run_id,
        from_state_version, to_state_version,
        previous_cursor, previous_cursor_sha256,
        next_cursor, next_cursor_sha256,
        source_slice_sha256, target_commit_ref, target_content_sha256,
        records_read, records_inserted, records_updated, records_deleted,
        records_output, committed_by, committed_at, commit_sha256
    ) VALUES (
        p_tenant_id, p_sync_commit_id, p_sync_definition_version_id, p_run_id,
        p_from_state_version, p_to_state_version,
        p_previous_cursor, p_previous_cursor_sha256,
        p_next_cursor, p_next_cursor_sha256,
        p_source_slice_sha256, p_target_commit_ref, p_target_content_sha256,
        p_records_read, p_records_inserted, p_records_updated, p_records_deleted,
        p_records_output, p_committed_by, p_committed_at, p_commit_sha256
    );
    UPDATE gda_control.source_sync_checkpoint
    SET state_version = p_to_state_version,
        cursor = p_next_cursor,
        cursor_sha256 = p_next_cursor_sha256,
        last_sync_commit_id = p_sync_commit_id,
        last_run_id = p_run_id,
        target_commit_ref = p_target_commit_ref,
        target_content_sha256 = p_target_content_sha256,
        updated_by = p_committed_by,
        updated_at = p_committed_at
    WHERE tenant_id = p_tenant_id
      AND sync_definition_version_id = p_sync_definition_version_id;
    PERFORM set_config('gda.source_sync_commit_allowed', '0', true);

    RETURN QUERY SELECT p_sync_commit_id, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.source_sync_commit_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_source_sync_definition_insert_guard
    ON gda_control.source_sync_definition;
CREATE TRIGGER trg_gda_source_sync_definition_insert_guard
BEFORE INSERT ON gda_control.source_sync_definition
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_source_sync_definition_insert();

DROP TRIGGER IF EXISTS trg_gda_source_sync_definition_immutable
    ON gda_control.source_sync_definition;
CREATE TRIGGER trg_gda_source_sync_definition_immutable
BEFORE UPDATE OR DELETE ON gda_control.source_sync_definition
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_source_sync_checkpoint_insert_guard
    ON gda_control.source_sync_checkpoint;
CREATE TRIGGER trg_gda_source_sync_checkpoint_insert_guard
BEFORE INSERT ON gda_control.source_sync_checkpoint
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_source_sync_checkpoint_insert();

DROP TRIGGER IF EXISTS trg_gda_source_sync_checkpoint_update_guard
    ON gda_control.source_sync_checkpoint;
CREATE TRIGGER trg_gda_source_sync_checkpoint_update_guard
BEFORE UPDATE ON gda_control.source_sync_checkpoint
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_source_sync_checkpoint_update();

DROP TRIGGER IF EXISTS trg_gda_source_sync_checkpoint_delete_guard
    ON gda_control.source_sync_checkpoint;
CREATE TRIGGER trg_gda_source_sync_checkpoint_delete_guard
BEFORE DELETE ON gda_control.source_sync_checkpoint
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_source_sync_commit_insert_guard
    ON gda_control.source_sync_commit;
CREATE TRIGGER trg_gda_source_sync_commit_insert_guard
BEFORE INSERT ON gda_control.source_sync_commit
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_source_sync_commit_insert();

DROP TRIGGER IF EXISTS trg_gda_source_sync_commit_immutable
    ON gda_control.source_sync_commit;
CREATE TRIGGER trg_gda_source_sync_commit_immutable
BEFORE UPDATE OR DELETE ON gda_control.source_sync_commit
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.source_sync_definition ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.source_sync_definition FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.source_sync_definition;
CREATE POLICY tenant_isolation ON gda_control.source_sync_definition
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.source_sync_checkpoint ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.source_sync_checkpoint FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.source_sync_checkpoint;
CREATE POLICY tenant_isolation ON gda_control.source_sync_checkpoint
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.source_sync_commit ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.source_sync_commit FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.source_sync_commit;
CREATE POLICY tenant_isolation ON gda_control.source_sync_commit
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.source_sync_definition
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.source_sync_checkpoint
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.source_sync_commit
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.source_sync_definition
    TO gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.source_sync_checkpoint
    TO gda_control_gateway;
GRANT SELECT ON gda_control.source_sync_commit
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_source_sync_definition_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_source_sync_checkpoint_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_source_sync_checkpoint_update()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_source_sync_commit_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.commit_source_sync(
    TEXT, UUID, UUID, UUID, INTEGER, INTEGER, JSONB, TEXT, JSONB, TEXT,
    TEXT, JSONB, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, TEXT,
    TIMESTAMPTZ, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.commit_source_sync(
    TEXT, UUID, UUID, UUID, INTEGER, INTEGER, JSONB, TEXT, JSONB, TEXT,
    TEXT, JSONB, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, TEXT,
    TIMESTAMPTZ, TEXT
) TO gda_control_gateway;
