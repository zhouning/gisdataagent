-- 092: Minimal GDA control/evidence ledger.
--
-- This schema owns cross-system identity, immutable version bindings, run
-- correlation and evidence. It is not a generic metadata catalog, scheduler,
-- queue, lease system, object store, or execution-provider state database.

CREATE SCHEMA IF NOT EXISTS gda_control;

CREATE TABLE IF NOT EXISTS gda_control.resource (
    tenant_id TEXT NOT NULL,
    resource_urn TEXT PRIMARY KEY,
    resource_kind TEXT NOT NULL,
    authority_system TEXT NOT NULL,
    authority_locator TEXT NOT NULL,
    owner_ref TEXT NOT NULL,
    governance_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    technical_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_resource_tenant_urn UNIQUE (tenant_id, resource_urn),
    CONSTRAINT ck_gda_resource_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_resource_urn
        CHECK (resource_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'),
    CONSTRAINT ck_gda_resource_urn_tenant
        CHECK (split_part(resource_urn, '/', 3) = tenant_id),
    CONSTRAINT ck_gda_resource_urn_kind
        CHECK (split_part(resource_urn, '/', 4) = resource_kind),
    CONSTRAINT ck_gda_resource_governance_ref
        CHECK (jsonb_typeof(governance_ref) = 'object'),
    CONSTRAINT ck_gda_resource_technical_refs
        CHECK (jsonb_typeof(technical_refs) = 'array')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_resource_authority
    ON gda_control.resource(tenant_id, authority_system, authority_locator);
CREATE INDEX IF NOT EXISTS idx_gda_resource_kind
    ON gda_control.resource(tenant_id, resource_kind);

CREATE TABLE IF NOT EXISTS gda_control.resource_version (
    tenant_id TEXT NOT NULL,
    resource_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_urn TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    content_sha256 CHAR(64) NOT NULL,
    authority_version_ref JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_resource_version_tenant_id
        UNIQUE (tenant_id, resource_version_id),
    CONSTRAINT uq_gda_resource_version_resource_id
        UNIQUE (tenant_id, resource_urn, resource_version_id),
    CONSTRAINT uq_gda_resource_version_identity
        UNIQUE (tenant_id, resource_urn, resource_version_id, content_sha256),
    CONSTRAINT uq_gda_resource_version_key
        UNIQUE (tenant_id, resource_urn, version_key),
    CONSTRAINT fk_gda_resource_version_resource
        FOREIGN KEY (tenant_id, resource_urn)
        REFERENCES gda_control.resource(tenant_id, resource_urn),
    CONSTRAINT fk_gda_resource_version_predecessor
        FOREIGN KEY (tenant_id, resource_urn, predecessor_version_id)
        REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id
        ),
    CONSTRAINT ck_gda_resource_version_sha256
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_resource_version_authority_ref
        CHECK (jsonb_typeof(authority_version_ref) = 'object'),
    CONSTRAINT ck_gda_resource_version_not_self_predecessor
        CHECK (predecessor_version_id IS NULL OR predecessor_version_id <> resource_version_id)
);

CREATE INDEX IF NOT EXISTS idx_gda_resource_version_resource
    ON gda_control.resource_version(tenant_id, resource_urn, created_at DESC);

CREATE TABLE IF NOT EXISTS gda_control.platform_definition_version (
    tenant_id TEXT NOT NULL,
    definition_version_id UUID PRIMARY KEY,
    definition_urn TEXT NOT NULL,
    orchestration_class TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    portability_class TEXT NOT NULL,
    definition_document JSONB NOT NULL,
    input_contract JSONB NOT NULL,
    output_contract JSONB NOT NULL,
    definition_sha256 CHAR(64) NOT NULL,
    CONSTRAINT uq_gda_definition_version_tenant_id
        UNIQUE (tenant_id, definition_version_id),
    CONSTRAINT uq_gda_definition_version_orchestration
        UNIQUE (tenant_id, definition_version_id, orchestration_class),
    CONSTRAINT fk_gda_definition_resource_version
        FOREIGN KEY (
            tenant_id, definition_urn, definition_version_id, definition_sha256
        )
        REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id, content_sha256
        ),
    CONSTRAINT ck_gda_definition_kind
        CHECK (split_part(definition_urn, '/', 4) = 'definition'),
    CONSTRAINT ck_gda_definition_orchestration
        CHECK (orchestration_class IN (
            'dataops','durable_agent','durable_gwm','action','synchronous'
        )),
    CONSTRAINT ck_gda_definition_portability
        CHECK (portability_class IN ('portable','engine_family','provider_native')),
    CONSTRAINT ck_gda_definition_document
        CHECK (jsonb_typeof(definition_document) = 'object'),
    CONSTRAINT ck_gda_definition_input
        CHECK (jsonb_typeof(input_contract) = 'object'),
    CONSTRAINT ck_gda_definition_output
        CHECK (jsonb_typeof(output_contract) = 'object'),
    CONSTRAINT ck_gda_definition_sha256
        CHECK (definition_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_gda_definition_capability
    ON gda_control.platform_definition_version(
        tenant_id, capability_id, orchestration_class
    );

CREATE TABLE IF NOT EXISTS gda_control.platform_run (
    tenant_id TEXT NOT NULL,
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    definition_version_id UUID NOT NULL,
    orchestration_class TEXT NOT NULL,
    subject_context JSONB NOT NULL,
    idempotency_key TEXT NOT NULL,
    policy_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    config_fingerprint CHAR(64),
    status TEXT NOT NULL DEFAULT 'accepted',
    state_version INTEGER NOT NULL DEFAULT 0,
    submitted_by TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_platform_run_tenant_id UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_platform_run_idempotency
        UNIQUE (tenant_id, definition_version_id, idempotency_key),
    CONSTRAINT fk_gda_platform_run_definition
        FOREIGN KEY (tenant_id, definition_version_id, orchestration_class)
        REFERENCES gda_control.platform_definition_version(
            tenant_id, definition_version_id, orchestration_class
        ),
    CONSTRAINT ck_gda_platform_run_orchestration
        CHECK (orchestration_class IN (
            'dataops','durable_agent','durable_gwm','action','synchronous'
        )),
    CONSTRAINT ck_gda_platform_run_subject
        CHECK (jsonb_typeof(subject_context) = 'object'),
    CONSTRAINT ck_gda_platform_run_subject_tenant
        CHECK (subject_context->>'tenant_id' = tenant_id),
    CONSTRAINT ck_gda_platform_run_subject_identity CHECK (
        NULLIF(btrim(subject_context->>'subject_id'), '') IS NOT NULL
        AND subject_context->>'subject_type' IN ('human','workload','agent')
        AND NULLIF(btrim(subject_context->>'purpose'), '') IS NOT NULL
        AND jsonb_typeof(subject_context->'roles') = 'array'
    ),
    CONSTRAINT ck_gda_platform_run_policy_refs
        CHECK (jsonb_typeof(policy_refs) = 'object'),
    CONSTRAINT ck_gda_platform_run_config_fingerprint
        CHECK (config_fingerprint IS NULL OR config_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_platform_run_status
        CHECK (status IN (
            'accepted','dispatching','running','cancelling','reconciling',
            'succeeded','failed','cancelled','timed_out'
        )),
    CONSTRAINT ck_gda_platform_run_state_version CHECK (state_version >= 0),
    CONSTRAINT ck_gda_platform_run_terminal_time CHECK (
        (status IN ('succeeded','failed','cancelled','timed_out') AND terminal_at IS NOT NULL)
        OR
        (status NOT IN ('succeeded','failed','cancelled','timed_out') AND terminal_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_platform_run_status
    ON gda_control.platform_run(tenant_id, status, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_gda_platform_run_definition
    ON gda_control.platform_run(tenant_id, definition_version_id, submitted_at DESC);

CREATE TABLE IF NOT EXISTS gda_control.platform_run_input_binding (
    tenant_id TEXT NOT NULL,
    run_id UUID NOT NULL,
    binding_name TEXT NOT NULL,
    resource_version_id UUID NOT NULL,
    semantic_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, binding_name),
    CONSTRAINT fk_gda_run_input_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_run_input_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_run_input_binding_name
        CHECK (binding_name ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_run_input_semantic_type
        CHECK (NULLIF(btrim(semantic_type), '') IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_gda_run_input_resource_version
    ON gda_control.platform_run_input_binding(tenant_id, resource_version_id);

CREATE TABLE IF NOT EXISTS gda_control.platform_run_event (
    tenant_id TEXT NOT NULL,
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    sequence_no INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_run_event_tenant_id UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_run_event_sequence UNIQUE (tenant_id, run_id, sequence_no),
    CONSTRAINT fk_gda_run_event_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT ck_gda_run_event_sequence CHECK (sequence_no >= 0),
    CONSTRAINT ck_gda_run_event_from_status CHECK (
        from_status IS NULL OR from_status IN (
            'accepted','dispatching','running','cancelling','reconciling',
            'succeeded','failed','cancelled','timed_out'
        )
    ),
    CONSTRAINT ck_gda_run_event_to_status CHECK (to_status IN (
        'accepted','dispatching','running','cancelling','reconciling',
        'succeeded','failed','cancelled','timed_out'
    )),
    CONSTRAINT ck_gda_run_event_initial CHECK (
        (sequence_no = 0 AND from_status IS NULL AND to_status = 'accepted')
        OR
        (sequence_no > 0 AND from_status IS NOT NULL)
    ),
    CONSTRAINT ck_gda_run_event_actor
        CHECK (NULLIF(btrim(actor_subject), '') IS NOT NULL),
    CONSTRAINT ck_gda_run_event_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_run_event_details CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_run_event_run
    ON gda_control.platform_run_event(tenant_id, run_id, sequence_no);

CREATE TABLE IF NOT EXISTS gda_control.framework_attempt_observation (
    tenant_id TEXT NOT NULL,
    observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    attempt_no INTEGER NOT NULL,
    framework_kind TEXT NOT NULL,
    external_namespace TEXT NOT NULL,
    external_run_id TEXT NOT NULL,
    external_attempt_id TEXT,
    observed_state TEXT NOT NULL,
    observation_sha256 CHAR(64) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_attempt_observation_tenant_id
        UNIQUE (tenant_id, observation_id),
    CONSTRAINT uq_gda_attempt_observation_fingerprint
        UNIQUE (tenant_id, run_id, observation_sha256),
    CONSTRAINT fk_gda_attempt_observation_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT ck_gda_attempt_observation_no CHECK (attempt_no >= 1),
    CONSTRAINT ck_gda_attempt_framework CHECK (framework_kind IN (
        'dolphinscheduler','temporal','spark','flink','kubernetes',
        'postgis','duckdb','arcpy','cloud','legacy'
    )),
    CONSTRAINT ck_gda_attempt_observation_sha256
        CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_attempt_observation_evidence
        CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_attempt_observation_external
    ON gda_control.framework_attempt_observation(
        tenant_id, framework_kind, external_namespace, external_run_id
    );

CREATE TABLE IF NOT EXISTS gda_control.artifact (
    tenant_id TEXT NOT NULL,
    artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_key TEXT NOT NULL,
    artifact_role TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    media_type TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    run_id UUID,
    resource_version_id UUID,
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_artifact_tenant_id UNIQUE (tenant_id, artifact_id),
    CONSTRAINT uq_gda_artifact_run_key UNIQUE (tenant_id, run_id, artifact_key),
    CONSTRAINT fk_gda_artifact_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_artifact_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_artifact_role CHECK (artifact_role IN (
        'input','output','checkpoint','log','evidence','execution_plan'
    )),
    CONSTRAINT ck_gda_artifact_storage_uri
        CHECK (storage_uri ~ '^[a-z][a-z0-9+.-]*://'),
    CONSTRAINT ck_gda_artifact_storage_scheme
        CHECK (split_part(storage_uri, ':', 1) IN (
            'file','gs','https','iceberg','obs','postgresql','s3','stac'
        )),
    CONSTRAINT ck_gda_artifact_file_uri
        CHECK (split_part(storage_uri, ':', 1) <> 'file'
            OR storage_uri ~ '^file:///[^?#]*$'),
    CONSTRAINT ck_gda_artifact_no_credentials
        CHECK (storage_uri !~ '^[a-z][a-z0-9+.-]*://[^/]*@'),
    CONSTRAINT ck_gda_artifact_stable_uri
        CHECK (position('?' IN storage_uri) = 0 AND position('#' IN storage_uri) = 0),
    CONSTRAINT ck_gda_artifact_sha256
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_artifact_size CHECK (size_bytes >= 0),
    CONSTRAINT ck_gda_artifact_manifest CHECK (jsonb_typeof(manifest) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_artifact_run
    ON gda_control.artifact(tenant_id, run_id, artifact_role);
CREATE INDEX IF NOT EXISTS idx_gda_artifact_resource_version
    ON gda_control.artifact(tenant_id, resource_version_id);

CREATE TABLE IF NOT EXISTS gda_control.lineage_event (
    tenant_id TEXT NOT NULL,
    lineage_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    source_resource_version_id UUID NOT NULL,
    target_resource_version_id UUID NOT NULL,
    run_id UUID,
    definition_version_id UUID,
    artifact_id UUID,
    producer TEXT NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    facets JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_lineage_event_tenant_id
        UNIQUE (tenant_id, lineage_event_id),
    CONSTRAINT uq_gda_lineage_event_fingerprint UNIQUE (tenant_id, event_sha256),
    CONSTRAINT fk_gda_lineage_source_version
        FOREIGN KEY (tenant_id, source_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_lineage_target_version
        FOREIGN KEY (tenant_id, target_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_lineage_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_lineage_definition
        FOREIGN KEY (tenant_id, definition_version_id)
        REFERENCES gda_control.platform_definition_version(
            tenant_id, definition_version_id
        ),
    CONSTRAINT fk_gda_lineage_artifact
        FOREIGN KEY (tenant_id, artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_lineage_type CHECK (
        event_type IN ('read','write','derive','copy','materialize','publish')
    ),
    CONSTRAINT ck_gda_lineage_not_self
        CHECK (source_resource_version_id <> target_resource_version_id),
    CONSTRAINT ck_gda_lineage_sha256 CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_lineage_facets CHECK (jsonb_typeof(facets) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_lineage_source
    ON gda_control.lineage_event(tenant_id, source_resource_version_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_gda_lineage_target
    ON gda_control.lineage_event(tenant_id, target_resource_version_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_gda_lineage_run
    ON gda_control.lineage_event(tenant_id, run_id, occurred_at);

CREATE OR REPLACE FUNCTION gda_control.reject_immutable_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_platform_run_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status <> 'accepted' OR NEW.state_version <> 0
       OR NEW.started_at IS NOT NULL OR NEW.terminal_at IS NOT NULL THEN
        RAISE EXCEPTION 'platform run must start at accepted state version 0'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.initialize_platform_run_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO gda_control.platform_run_event (
        tenant_id, run_id, sequence_no, from_status, to_status,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        NEW.tenant_id, NEW.run_id, 0, NULL, 'accepted',
        NEW.submitted_by, 'submitted', '{}'::jsonb, NEW.submitted_at
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_platform_run_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.transition_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.transition_platform_run()'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.definition_version_id IS DISTINCT FROM OLD.definition_version_id
       OR NEW.orchestration_class IS DISTINCT FROM OLD.orchestration_class
       OR NEW.subject_context IS DISTINCT FROM OLD.subject_context
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.policy_refs IS DISTINCT FROM OLD.policy_refs
       OR NEW.config_fingerprint IS DISTINCT FROM OLD.config_fingerprint
       OR NEW.submitted_by IS DISTINCT FROM OLD.submitted_by
       OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
        RAISE EXCEPTION 'immutable platform run binding cannot be changed'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state_version <> OLD.state_version + 1 OR NEW.status = OLD.status THEN
        RAISE EXCEPTION 'platform run transition must advance state_version once'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.current_tenant()
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant', true), '')
$$;

CREATE OR REPLACE FUNCTION gda_control.transition_platform_run(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_to_status TEXT,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_details JSONB DEFAULT '{}'::jsonb
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_allowed BOOLEAN := FALSE;
    v_new_version INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'platform run tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'transition actor and reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'transition details must be a JSON object'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'platform run % not found', p_run_id
            USING ERRCODE = 'P0002';
    END IF;
    IF v_run.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'platform run state version conflict: expected %, actual %',
            p_expected_state_version, v_run.state_version
            USING ERRCODE = '40001';
    END IF;

    v_allowed := CASE v_run.status
        WHEN 'accepted' THEN p_to_status = ANY (ARRAY[
            'dispatching','failed','cancelled'
        ])
        WHEN 'dispatching' THEN p_to_status = ANY (ARRAY[
            'running','cancelling','reconciling','failed','cancelled'
        ])
        WHEN 'running' THEN p_to_status = ANY (ARRAY[
            'cancelling','reconciling','succeeded','failed','cancelled','timed_out'
        ])
        WHEN 'cancelling' THEN p_to_status = ANY (ARRAY[
            'reconciling','cancelled','failed'
        ])
        WHEN 'reconciling' THEN p_to_status = ANY (ARRAY[
            'dispatching','running','cancelling','succeeded','failed',
            'cancelled','timed_out'
        ])
        ELSE FALSE
    END;

    IF NOT v_allowed THEN
        RAISE EXCEPTION 'invalid platform run transition % -> %',
            v_run.status, p_to_status
            USING ERRCODE = '23514';
    END IF;

    v_new_version := v_run.state_version + 1;
    PERFORM set_config('gda.transition_allowed', '1', true);
    UPDATE gda_control.platform_run
    SET status = p_to_status,
        state_version = v_new_version,
        started_at = CASE
            WHEN p_to_status = 'running' THEN COALESCE(started_at, now())
            ELSE started_at
        END,
        terminal_at = CASE
            WHEN p_to_status IN ('succeeded','failed','cancelled','timed_out')
                THEN now()
            ELSE NULL
        END,
        updated_at = now()
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    PERFORM set_config('gda.transition_allowed', '0', true);

    INSERT INTO gda_control.platform_run_event (
        tenant_id, run_id, sequence_no, from_status, to_status,
        actor_subject, reason, details
    ) VALUES (
        v_run.tenant_id, v_run.run_id, v_new_version, v_run.status, p_to_status,
        p_actor_subject, p_reason, p_details
    );
    RETURN v_new_version;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.transition_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_run_insert_guard
    ON gda_control.platform_run;
CREATE TRIGGER trg_gda_run_insert_guard
BEFORE INSERT ON gda_control.platform_run
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_platform_run_insert();

DROP TRIGGER IF EXISTS trg_gda_run_initialize_event
    ON gda_control.platform_run;
CREATE TRIGGER trg_gda_run_initialize_event
AFTER INSERT ON gda_control.platform_run
FOR EACH ROW EXECUTE FUNCTION gda_control.initialize_platform_run_event();

DROP TRIGGER IF EXISTS trg_gda_run_update_guard
    ON gda_control.platform_run;
CREATE TRIGGER trg_gda_run_update_guard
BEFORE UPDATE ON gda_control.platform_run
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_platform_run_update();

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'resource_version',
        'platform_definition_version',
        'platform_run_input_binding',
        'platform_run_event',
        'framework_attempt_observation',
        'artifact',
        'lineage_event'
    ]
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_gda_immutable ON gda_control.%I',
            relation_name
        );
        EXECUTE format(
            'CREATE TRIGGER trg_gda_immutable BEFORE UPDATE OR DELETE ON '
            'gda_control.%I FOR EACH ROW EXECUTE FUNCTION '
            'gda_control.reject_immutable_mutation()',
            relation_name
        );
    END LOOP;
END;
$$;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'resource',
        'resource_version',
        'platform_definition_version',
        'platform_run',
        'platform_run_input_binding',
        'platform_run_event',
        'framework_attempt_observation',
        'artifact',
        'lineage_event'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE gda_control.%I ENABLE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'ALTER TABLE gda_control.%I FORCE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS tenant_isolation ON gda_control.%I',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON gda_control.%I '
            'USING (tenant_id = gda_control.current_tenant()) '
            'WITH CHECK (tenant_id = gda_control.current_tenant())',
            relation_name
        );
    END LOOP;
END;
$$;

-- Access is fail-closed until AR-1 provisions a dedicated gateway role and
-- grants only the required table/function privileges.
REVOKE ALL ON SCHEMA gda_control FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA gda_control FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gda_control FROM PUBLIC;
