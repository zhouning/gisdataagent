-- 181: Append-only completion authority for federated compensation checkpoints.
--
-- A completion record is admitted only when every referenced checkpoint is
-- still the live authority current. Partial or uncertain writer results never
-- reach this function. This is not a cross-target or cross-store transaction.

CREATE TABLE IF NOT EXISTS
gda_control.federated_projection_compensation_checkpoint_completion (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    write_request_set_sha256 CHAR(64) NOT NULL,
    authority_record_set_sha256 CHAR(64) NOT NULL,
    checkpoint_targets JSONB NOT NULL,
    completion_idempotency_key CHAR(64) NOT NULL,
    completion_request_sha256 CHAR(64) NOT NULL,
    completed_by TEXT NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id),
    CONSTRAINT uq_gda_federated_projection_compensation_completion_key
        UNIQUE (tenant_id, completion_idempotency_key),
    CONSTRAINT uq_gda_federated_projection_compensation_completion_request
        UNIQUE (tenant_id, completion_request_sha256),
    CONSTRAINT ck_gda_federated_projection_compensation_completion_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_federated_projection_compensation_completion_run CHECK (
        NULLIF(btrim(run_id), '') IS NOT NULL
        AND octet_length(run_id) <= 512
    ),
    CONSTRAINT ck_gda_federated_projection_compensation_completion_hashes CHECK (
        write_request_set_sha256 ~ '^[0-9a-f]{64}$'
        AND authority_record_set_sha256 ~ '^[0-9a-f]{64}$'
        AND completion_idempotency_key ~ '^[0-9a-f]{64}$'
        AND completion_request_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_federated_projection_compensation_completion_targets CHECK (
        jsonb_typeof(checkpoint_targets) = 'array'
        AND jsonb_array_length(checkpoint_targets) BETWEEN 1 AND 32
    ),
    CONSTRAINT ck_gda_federated_projection_compensation_completion_actor CHECK (
        completed_by ~ '^(human|agent|workload):[^[:space:]]{1,128}$'
    )
);

DROP TRIGGER IF EXISTS
trg_gda_federated_projection_compensation_checkpoint_completion_immutable
ON gda_control.federated_projection_compensation_checkpoint_completion;
CREATE TRIGGER
trg_gda_federated_projection_compensation_checkpoint_completion_immutable
BEFORE UPDATE OR DELETE ON
gda_control.federated_projection_compensation_checkpoint_completion
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE
gda_control.federated_projection_compensation_checkpoint_completion
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE
gda_control.federated_projection_compensation_checkpoint_completion
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON
gda_control.federated_projection_compensation_checkpoint_completion;
CREATE POLICY tenant_isolation ON
gda_control.federated_projection_compensation_checkpoint_completion
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
gda_control.federated_projection_compensation_checkpoint_completion
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
gda_control.federated_projection_compensation_checkpoint_completion
    TO gda_control_gateway;

CREATE OR REPLACE FUNCTION
gda_control.record_federated_projection_compensation_checkpoint_completion(
    p_tenant_id TEXT,
    p_run_id TEXT,
    p_write_request_set_sha256 TEXT,
    p_authority_record_set_sha256 TEXT,
    p_checkpoint_targets JSONB,
    p_completion_idempotency_key TEXT,
    p_completion_request_sha256 TEXT,
    p_completed_by TEXT
)
RETURNS TABLE(completion_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing
        gda_control.federated_projection_compensation_checkpoint_completion%ROWTYPE;
    v_inserted
        gda_control.federated_projection_compensation_checkpoint_completion%ROWTYPE;
    v_target JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'compensation completion tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_run_id), '') IS NULL
       OR octet_length(p_run_id) > 512
       OR p_write_request_set_sha256 !~ '^[0-9a-f]{64}$'
       OR p_authority_record_set_sha256 !~ '^[0-9a-f]{64}$'
       OR p_completion_idempotency_key !~ '^[0-9a-f]{64}$'
       OR p_completion_request_sha256 !~ '^[0-9a-f]{64}$'
       OR p_completed_by !~ '^(human|agent|workload):[^[:space:]]{1,128}$'
       OR jsonb_typeof(p_checkpoint_targets) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_checkpoint_targets) NOT BETWEEN 1 AND 32 THEN
        RAISE EXCEPTION 'compensation completion identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_checkpoint_targets)
             WITH ORDINALITY AS target(value, ordinal)
        WHERE jsonb_typeof(target.value) IS DISTINCT FROM 'object'
           OR NOT target.value ?& ARRAY[
                'tenant_id', 'run_id', 'position', 'write_request_sha256',
                'authority_record_item_sha256', 'projection_id',
                'target_engine', 'target_ref', 'checkpoint_sha256',
                'checkpoint_version', 'target_sha256'
           ]
           OR target.value ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
           OR target.value ->> 'run_id' IS DISTINCT FROM p_run_id
           OR target.value ->> 'position' !~ '^[0-9]+$'
           OR (target.value ->> 'position')::INTEGER
                IS DISTINCT FROM (target.ordinal - 1)::INTEGER
           OR target.value ->> 'write_request_sha256' !~ '^[0-9a-f]{64}$'
           OR target.value ->> 'authority_record_item_sha256'
                !~ '^[0-9a-f]{64}$'
           OR target.value ->> 'projection_id'
                !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
           OR target.value ->> 'target_engine' NOT IN (
                'postgis', 'rdf', 'vector', 'object_store', 'lakehouse'
           )
           OR NULLIF(btrim(target.value ->> 'target_ref'), '') IS NULL
           OR octet_length(target.value ->> 'target_ref') > 512
           OR target.value ->> 'checkpoint_sha256' !~ '^[0-9a-f]{64}$'
           OR target.value ->> 'checkpoint_version' !~ '^[1-9][0-9]*$'
           OR target.value ->> 'target_sha256' !~ '^[0-9a-f]{64}$'
           OR (
                SELECT count(*)
                FROM jsonb_object_keys(target.value)
              ) <> 11
    ) THEN
        RAISE EXCEPTION 'compensation completion target evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF (
        SELECT count(*) <> count(DISTINCT (
            target.value ->> 'projection_id',
            target.value ->> 'target_engine',
            target.value ->> 'target_ref'
        ))
        FROM jsonb_array_elements(p_checkpoint_targets) AS target(value)
    ) THEN
        RAISE EXCEPTION 'compensation completion targets must be unique'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'federated-compensation-completion|'
            || p_tenant_id || '|' || p_run_id,
            0
        )
    );
    SELECT completion.* INTO v_existing
    FROM gda_control.federated_projection_compensation_checkpoint_completion
         AS completion
    WHERE completion.tenant_id = p_tenant_id
      AND (
          completion.run_id = p_run_id
          OR completion.completion_idempotency_key
                = p_completion_idempotency_key
          OR completion.completion_request_sha256
                = p_completion_request_sha256
      )
    ORDER BY (
        completion.run_id = p_run_id
        AND completion.completion_idempotency_key
                = p_completion_idempotency_key
        AND completion.completion_request_sha256
                = p_completion_request_sha256
    ) DESC
    LIMIT 1;
    IF FOUND THEN
        IF v_existing.run_id IS DISTINCT FROM p_run_id
           OR v_existing.write_request_set_sha256::TEXT
                IS DISTINCT FROM p_write_request_set_sha256
           OR v_existing.authority_record_set_sha256::TEXT
                IS DISTINCT FROM p_authority_record_set_sha256
           OR v_existing.checkpoint_targets IS DISTINCT FROM p_checkpoint_targets
           OR v_existing.completion_idempotency_key::TEXT
                IS DISTINCT FROM p_completion_idempotency_key
           OR v_existing.completion_request_sha256::TEXT
                IS DISTINCT FROM p_completion_request_sha256
           OR v_existing.completed_by IS DISTINCT FROM p_completed_by THEN
            RAISE EXCEPTION 'compensation completion idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT to_jsonb(v_existing), FALSE;
        RETURN;
    END IF;

    -- Hold every checkpoint target lock until completion is inserted. The
    -- order is canonical so concurrent completion attempts cannot deadlock.
    FOR v_target IN
        SELECT target.value
        FROM jsonb_array_elements(p_checkpoint_targets) AS target(value)
        ORDER BY target.value ->> 'projection_id',
                 target.value ->> 'target_engine',
                 target.value ->> 'target_ref'
    LOOP
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                'projection-checkpoint-target|' || p_tenant_id || '|'
                || (v_target ->> 'projection_id') || '|'
                || (v_target ->> 'target_engine') || '|'
                || (v_target ->> 'target_ref'),
                0
            )
        );
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_checkpoint_targets) AS target(value)
        LEFT JOIN gda_control.cross_store_projection_checkpoint_current AS current
          ON current.tenant_id = p_tenant_id
         AND current.projection_id = target.value ->> 'projection_id'
         AND current.target_engine = target.value ->> 'target_engine'
         AND current.target_ref = target.value ->> 'target_ref'
        WHERE current.checkpoint_sha256::TEXT
                IS DISTINCT FROM target.value ->> 'checkpoint_sha256'
           OR current.checkpoint_version
                IS DISTINCT FROM (target.value ->> 'checkpoint_version')::INTEGER
    ) THEN
        RAISE EXCEPTION 'checkpoint authority current drifted before completion'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO
        gda_control.federated_projection_compensation_checkpoint_completion (
            tenant_id, run_id, write_request_set_sha256,
            authority_record_set_sha256, checkpoint_targets,
            completion_idempotency_key, completion_request_sha256,
            completed_by
        )
    VALUES (
        p_tenant_id, p_run_id, p_write_request_set_sha256,
        p_authority_record_set_sha256, p_checkpoint_targets,
        p_completion_idempotency_key, p_completion_request_sha256,
        p_completed_by
    )
    RETURNING * INTO v_inserted;
    RETURN QUERY SELECT to_jsonb(v_inserted), TRUE;
END;
$$;

REVOKE ALL ON FUNCTION
gda_control.record_federated_projection_compensation_checkpoint_completion(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
gda_control.record_federated_projection_compensation_checkpoint_completion(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT
) TO gda_control_gateway;
