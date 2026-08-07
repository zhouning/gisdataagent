-- 122: Versioned SLO definition authority with ApprovalCase-gated activation.
--
-- Observations and candidate objectives are not production commitments. Only
-- an immutable definition version bound to an exact approved ApprovalCase may
-- become active and therefore eligible for rule compilation.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS gda_control.slo_definition_version (
    tenant_id TEXT NOT NULL,
    slo_definition_ref TEXT NOT NULL,
    slo_version_ref TEXT NOT NULL,
    definition_version INTEGER NOT NULL,
    service_resource_urn TEXT NOT NULL,
    indicator_config JSONB NOT NULL,
    objective_basis_points INTEGER NOT NULL,
    objective_window_seconds INTEGER NOT NULL,
    owner_subject TEXT NOT NULL,
    oncall_ref TEXT NOT NULL,
    burn_rate_policy JSONB NOT NULL,
    definition_fingerprint CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    creation_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, slo_version_ref),
    CONSTRAINT uq_gda_slo_definition_version_number
        UNIQUE (tenant_id, slo_definition_ref, definition_version),
    CONSTRAINT uq_gda_slo_definition_version_fingerprint
        UNIQUE (tenant_id, slo_version_ref, definition_fingerprint),
    CONSTRAINT ck_gda_slo_definition_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_slo_definition_ref CHECK (
        slo_definition_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(slo_definition_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_slo_version_ref CHECK (
        slo_version_ref = slo_definition_ref || '.v' || definition_version::text
    ),
    CONSTRAINT ck_gda_slo_definition_version
        CHECK (definition_version BETWEEN 1 AND 1000000),
    CONSTRAINT ck_gda_slo_service_ref CHECK (
        service_resource_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(service_resource_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_slo_indicator_object
        CHECK (jsonb_typeof(indicator_config) = 'object'),
    CONSTRAINT ck_gda_slo_objective
        CHECK (objective_basis_points BETWEEN 1 AND 9999),
    CONSTRAINT ck_gda_slo_objective_window
        CHECK (objective_window_seconds BETWEEN 3600 AND 31622400),
    CONSTRAINT ck_gda_slo_owner
        CHECK (owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_slo_oncall
        CHECK (oncall_ref ~ '^oncall:[a-z0-9][a-z0-9._-]{0,127}$'),
    CONSTRAINT ck_gda_slo_burn_policy
        CHECK (
            jsonb_typeof(burn_rate_policy) = 'array'
            AND jsonb_array_length(burn_rate_policy) BETWEEN 1 AND 4
        ),
    CONSTRAINT ck_gda_slo_fingerprint
        CHECK (definition_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_slo_creator
        CHECK (created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_slo_creation_reason
        CHECK (NULLIF(btrim(creation_reason), '') IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_gda_slo_definition_service
    ON gda_control.slo_definition_version(
        tenant_id, service_resource_urn, slo_definition_ref, definition_version
    );

CREATE TABLE IF NOT EXISTS gda_control.slo_definition_activation (
    tenant_id TEXT NOT NULL,
    slo_definition_ref TEXT NOT NULL,
    active_version_ref TEXT NOT NULL,
    active_fingerprint CHAR(64) NOT NULL,
    approval_case_ref TEXT NOT NULL,
    activation_version INTEGER NOT NULL,
    activated_by TEXT NOT NULL,
    activation_reason TEXT NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, slo_definition_ref),
    CONSTRAINT fk_gda_slo_activation_version
        FOREIGN KEY (tenant_id, active_version_ref, active_fingerprint)
        REFERENCES gda_control.slo_definition_version(
            tenant_id, slo_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_slo_activation_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_slo_activation_version
        CHECK (activation_version >= 1),
    CONSTRAINT ck_gda_slo_activator
        CHECK (activated_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_slo_activation_reason
        CHECK (NULLIF(btrim(activation_reason), '') IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS gda_control.slo_definition_event (
    tenant_id TEXT NOT NULL,
    slo_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slo_definition_ref TEXT NOT NULL,
    slo_version_ref TEXT NOT NULL,
    definition_fingerprint CHAR(64) NOT NULL,
    event_type TEXT NOT NULL,
    approval_case_ref TEXT,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_slo_event_tenant_id
        UNIQUE (tenant_id, slo_event_id),
    CONSTRAINT fk_gda_slo_event_version
        FOREIGN KEY (tenant_id, slo_version_ref, definition_fingerprint)
        REFERENCES gda_control.slo_definition_version(
            tenant_id, slo_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_slo_event_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_slo_event_type
        CHECK (event_type IN ('staged', 'activated')),
    CONSTRAINT ck_gda_slo_event_approval_binding CHECK (
        (event_type = 'staged' AND approval_case_ref IS NULL)
        OR (event_type = 'activated' AND approval_case_ref IS NOT NULL)
    ),
    CONSTRAINT ck_gda_slo_event_actor
        CHECK (actor_subject ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_slo_event_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_slo_event_details
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_slo_definition_event
    ON gda_control.slo_definition_event(
        tenant_id, slo_definition_ref, occurred_at, slo_event_id
    );

CREATE OR REPLACE FUNCTION gda_control.guard_slo_activation_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.slo_activation_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.activate_slo_definition_version()'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.slo_definition_ref IS DISTINCT FROM OLD.slo_definition_ref
        OR NEW.activation_version <> OLD.activation_version + 1
    ) THEN
        RAISE EXCEPTION 'SLO activation identity or CAS sequence is invalid'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.stage_slo_definition_version(
    p_tenant_id TEXT,
    p_slo_definition_ref TEXT,
    p_slo_version_ref TEXT,
    p_definition_version INTEGER,
    p_service_resource_urn TEXT,
    p_indicator_config JSONB,
    p_objective_basis_points INTEGER,
    p_objective_window_seconds INTEGER,
    p_owner_subject TEXT,
    p_oncall_ref TEXT,
    p_burn_rate_policy JSONB,
    p_created_by TEXT,
    p_creation_reason TEXT,
    p_created_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_document JSONB;
    v_fingerprint TEXT;
    v_stored gda_control.slo_definition_version%ROWTYPE;
    v_inserted BOOLEAN := FALSE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'SLO tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_slo_definition_ref IS NULL
       OR p_slo_definition_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_slo_definition_ref, '/', 3) <> p_tenant_id
       OR p_definition_version NOT BETWEEN 1 AND 1000000
       OR p_slo_version_ref <> p_slo_definition_ref || '.v' || p_definition_version::text
       OR p_service_resource_urn !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_service_resource_urn, '/', 3) <> p_tenant_id
       OR p_objective_basis_points NOT BETWEEN 1 AND 9999
       OR p_objective_window_seconds NOT BETWEEN 3600 AND 31622400
       OR p_owner_subject !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_oncall_ref !~ '^oncall:[a-z0-9][a-z0-9._-]{0,127}$'
       OR p_created_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_creation_reason), '') IS NULL
       OR p_created_at IS NULL THEN
        RAISE EXCEPTION 'SLO identity, objective, ownership or provenance is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_indicator_config) <> 'object'
       OR (
            SELECT array_agg(key ORDER BY key) IS DISTINCT FROM ARRAY[
                'bad_outcomes', 'good_outcomes', 'kind',
                'match_labels', 'metric_name'
            ]::text[]
            FROM jsonb_object_keys(p_indicator_config) AS keys(key)
       )
       OR p_indicator_config->>'kind' <> 'event_success_ratio'
       OR COALESCE(p_indicator_config->>'metric_name', '')
            !~ '^[a-zA-Z_:][a-zA-Z0-9_:]*$'
       OR jsonb_typeof(p_indicator_config->'good_outcomes') <> 'array'
       OR jsonb_array_length(p_indicator_config->'good_outcomes') = 0
       OR jsonb_typeof(p_indicator_config->'bad_outcomes') <> 'array'
       OR jsonb_array_length(p_indicator_config->'bad_outcomes') = 0
       OR jsonb_typeof(p_indicator_config->'match_labels') <> 'object'
       OR p_indicator_config->'match_labels' ? 'outcome' THEN
        RAISE EXCEPTION 'SLO event-ratio indicator is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(
            (p_indicator_config->'good_outcomes')
            || (p_indicator_config->'bad_outcomes')
        ) AS outcome(value)
        WHERE value !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,63}$'
    ) OR (
        SELECT COUNT(*) <> COUNT(DISTINCT value)
            OR array_agg(value) IS DISTINCT FROM array_agg(value ORDER BY value)
        FROM jsonb_array_elements_text(
            p_indicator_config->'good_outcomes'
        ) outcome(value)
    ) OR (
        SELECT COUNT(*) <> COUNT(DISTINCT value)
            OR array_agg(value) IS DISTINCT FROM array_agg(value ORDER BY value)
        FROM jsonb_array_elements_text(
            p_indicator_config->'bad_outcomes'
        ) outcome(value)
    ) OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(p_indicator_config->'good_outcomes') good(value)
        JOIN jsonb_array_elements_text(p_indicator_config->'bad_outcomes') bad(value)
          USING (value)
    ) OR EXISTS (
        SELECT 1
        FROM jsonb_each_text(p_indicator_config->'match_labels') label(name, value)
        WHERE name !~ '^[a-zA-Z_][a-zA-Z0-9_]*$'
           OR value !~ '^[a-zA-Z0-9._:-]{1,128}$'
    ) THEN
        RAISE EXCEPTION 'SLO outcomes or match labels are invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_burn_rate_policy) <> 'array'
       OR jsonb_array_length(p_burn_rate_policy) NOT BETWEEN 1 AND 4
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_burn_rate_policy) policy(value)
            WHERE jsonb_typeof(value) <> 'object'
               OR (
                    SELECT COUNT(*)
                    FROM jsonb_object_keys(value)
               ) <> 7
               OR COALESCE(value->>'name', '') !~ '^[a-z][a-z0-9_-]{0,63}$'
               OR COALESCE(value->>'short_window_seconds', '') !~ '^[0-9]+$'
               OR (value->>'short_window_seconds')::bigint < 300
               OR COALESCE(value->>'long_window_seconds', '') !~ '^[0-9]+$'
               OR (value->>'long_window_seconds')::bigint <=
                    (value->>'short_window_seconds')::bigint
               OR (value->>'long_window_seconds')::bigint >
                    p_objective_window_seconds
               OR COALESCE(value->>'burn_rate_milli', '') !~ '^[0-9]+$'
               OR (value->>'burn_rate_milli')::bigint NOT BETWEEN 1 AND 1000000
               OR COALESCE(value->>'minimum_events', '') !~ '^[0-9]+$'
               OR (value->>'minimum_events')::bigint NOT BETWEEN 1 AND 1000000000
               OR COALESCE(value->>'for_seconds', '') !~ '^[0-9]+$'
               OR (value->>'for_seconds')::bigint NOT BETWEEN 0 AND 86400
               OR COALESCE(value->>'severity', '') NOT IN ('warning', 'critical')
       ) OR (
            SELECT COUNT(*) <> COUNT(DISTINCT value->>'name')
            FROM jsonb_array_elements(p_burn_rate_policy) policy(value)
       ) THEN
        RAISE EXCEPTION 'SLO burn-rate policy is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_document := jsonb_build_object(
        'schema', 'gda.slo_definition_version.v1',
        'tenant_id', p_tenant_id,
        'slo_definition_ref', p_slo_definition_ref,
        'slo_version_ref', p_slo_version_ref,
        'version', p_definition_version,
        'service_resource_urn', p_service_resource_urn,
        'indicator', p_indicator_config,
        'objective_basis_points', p_objective_basis_points,
        'objective_window_seconds', p_objective_window_seconds,
        'owner_subject', p_owner_subject,
        'oncall_ref', p_oncall_ref,
        'burn_rate_windows', p_burn_rate_policy,
        'created_by', p_created_by,
        'creation_reason', p_creation_reason,
        'created_at', p_created_at
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'),
        'hex'
    );

    INSERT INTO gda_control.slo_definition_version (
        tenant_id, slo_definition_ref, slo_version_ref, definition_version,
        service_resource_urn, indicator_config, objective_basis_points,
        objective_window_seconds, owner_subject, oncall_ref, burn_rate_policy,
        definition_fingerprint, created_by, creation_reason, created_at
    ) VALUES (
        p_tenant_id, p_slo_definition_ref, p_slo_version_ref,
        p_definition_version, p_service_resource_urn, p_indicator_config,
        p_objective_basis_points, p_objective_window_seconds, p_owner_subject,
        p_oncall_ref, p_burn_rate_policy, v_fingerprint, p_created_by,
        p_creation_reason, p_created_at
    )
    ON CONFLICT (tenant_id, slo_version_ref) DO NOTHING
    RETURNING TRUE INTO v_inserted;

    IF NOT COALESCE(v_inserted, FALSE) THEN
        SELECT * INTO v_stored
        FROM gda_control.slo_definition_version
        WHERE tenant_id = p_tenant_id
          AND slo_version_ref = p_slo_version_ref;
        IF NOT FOUND
           OR v_stored.slo_definition_ref IS DISTINCT FROM p_slo_definition_ref
           OR v_stored.definition_version IS DISTINCT FROM p_definition_version
           OR v_stored.service_resource_urn IS DISTINCT FROM p_service_resource_urn
           OR v_stored.indicator_config IS DISTINCT FROM p_indicator_config
           OR v_stored.objective_basis_points IS DISTINCT FROM p_objective_basis_points
           OR v_stored.objective_window_seconds IS DISTINCT FROM p_objective_window_seconds
           OR v_stored.owner_subject IS DISTINCT FROM p_owner_subject
           OR v_stored.oncall_ref IS DISTINCT FROM p_oncall_ref
           OR v_stored.burn_rate_policy IS DISTINCT FROM p_burn_rate_policy
           OR v_stored.created_by IS DISTINCT FROM p_created_by
           OR v_stored.creation_reason IS DISTINCT FROM p_creation_reason THEN
            RAISE EXCEPTION 'SLO version identity already has different evidence'
                USING ERRCODE = '40001';
        END IF;
        -- Preserve the first server timestamp and its fingerprint across HTTP retries.
        RETURN v_stored.definition_fingerprint;
    END IF;

    INSERT INTO gda_control.slo_definition_event (
        tenant_id, slo_definition_ref, slo_version_ref,
        definition_fingerprint, event_type, approval_case_ref,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        p_tenant_id, p_slo_definition_ref, p_slo_version_ref,
        v_fingerprint, 'staged', NULL, p_created_by, p_creation_reason,
        jsonb_build_object(
            'definition_version', p_definition_version,
            'service_resource_urn', p_service_resource_urn,
            'objective_basis_points', p_objective_basis_points,
            'objective_window_seconds', p_objective_window_seconds,
            'owner_subject', p_owner_subject,
            'oncall_ref', p_oncall_ref
        ),
        p_created_at
    );
    RETURN v_fingerprint;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.activate_slo_definition_version(
    p_tenant_id TEXT,
    p_slo_version_ref TEXT,
    p_definition_fingerprint TEXT,
    p_approval_case_ref TEXT,
    p_expected_activation_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_definition gda_control.slo_definition_version%ROWTYPE;
    v_activation gda_control.slo_definition_activation%ROWTYPE;
    v_approval gda_control.approval_case%ROWTYPE;
    v_new_version INTEGER;
    v_now TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'SLO tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_slo_version_ref IS NULL
       OR p_slo_version_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
       OR split_part(p_slo_version_ref, '/', 3) <> p_tenant_id
       OR p_definition_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_approval_case_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_approval_case_ref, '/', 3) <> p_tenant_id
       OR p_expected_activation_version < 0
       OR p_actor_subject !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'SLO activation identity, CAS, actor or reason is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_definition
    FROM gda_control.slo_definition_version
    WHERE tenant_id = p_tenant_id
      AND slo_version_ref = p_slo_version_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SLO definition version % not found', p_slo_version_ref
            USING ERRCODE = 'P0002';
    END IF;
    IF v_definition.definition_fingerprint <> p_definition_fingerprint THEN
        RAISE EXCEPTION 'SLO definition fingerprint mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_activation
    FROM gda_control.slo_definition_activation
    WHERE tenant_id = p_tenant_id
      AND slo_definition_ref = v_definition.slo_definition_ref
    FOR UPDATE;
    IF FOUND
       AND v_activation.active_version_ref = p_slo_version_ref
       AND v_activation.active_fingerprint = p_definition_fingerprint
       AND v_activation.approval_case_ref = p_approval_case_ref THEN
        RETURN v_activation.activation_version;
    END IF;
    IF (NOT FOUND AND p_expected_activation_version <> 0)
       OR (FOUND AND v_activation.activation_version <> p_expected_activation_version) THEN
        RAISE EXCEPTION 'SLO activation version conflict'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_approval
    FROM gda_control.approval_case
    WHERE tenant_id = p_tenant_id
      AND approval_case_ref = p_approval_case_ref;
    v_now := clock_timestamp();
    IF NOT FOUND
       OR v_approval.status <> 'approved'
       OR v_approval.action <> 'slo_definition.activate'
       OR v_approval.target_resource_urn <> p_slo_version_ref
       OR v_approval.target_fingerprint <> p_definition_fingerprint
       OR v_approval.decided_by !~ '^human:[^[:space:]]+$'
       OR v_approval.decided_at IS NULL
       OR v_now >= v_approval.expires_at THEN
        RAISE EXCEPTION 'ApprovalCase does not authorize this SLO activation'
            USING ERRCODE = '23514';
    END IF;

    v_new_version := COALESCE(v_activation.activation_version, 0) + 1;
    PERFORM set_config('gda.slo_activation_allowed', '1', true);
    INSERT INTO gda_control.slo_definition_activation (
        tenant_id, slo_definition_ref, active_version_ref,
        active_fingerprint, approval_case_ref, activation_version,
        activated_by, activation_reason, activated_at
    ) VALUES (
        p_tenant_id, v_definition.slo_definition_ref, p_slo_version_ref,
        p_definition_fingerprint, p_approval_case_ref, v_new_version,
        p_actor_subject, p_reason, v_now
    )
    ON CONFLICT (tenant_id, slo_definition_ref) DO UPDATE
    SET active_version_ref = EXCLUDED.active_version_ref,
        active_fingerprint = EXCLUDED.active_fingerprint,
        approval_case_ref = EXCLUDED.approval_case_ref,
        activation_version = EXCLUDED.activation_version,
        activated_by = EXCLUDED.activated_by,
        activation_reason = EXCLUDED.activation_reason,
        activated_at = EXCLUDED.activated_at;
    PERFORM set_config('gda.slo_activation_allowed', '0', true);

    INSERT INTO gda_control.slo_definition_event (
        tenant_id, slo_definition_ref, slo_version_ref,
        definition_fingerprint, event_type, approval_case_ref,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        p_tenant_id, v_definition.slo_definition_ref, p_slo_version_ref,
        p_definition_fingerprint, 'activated', p_approval_case_ref,
        p_actor_subject, p_reason,
        jsonb_build_object(
            'activation_version', v_new_version,
            'approval_decided_by', v_approval.decided_by,
            'approval_decided_at', v_approval.decided_at,
            'owner_subject', v_definition.owner_subject,
            'oncall_ref', v_definition.oncall_ref
        ),
        v_now
    );
    RETURN v_new_version;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.slo_activation_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_slo_definition_immutable
    ON gda_control.slo_definition_version;
CREATE TRIGGER trg_gda_slo_definition_immutable
BEFORE UPDATE OR DELETE ON gda_control.slo_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_slo_activation_guard
    ON gda_control.slo_definition_activation;
CREATE TRIGGER trg_gda_slo_activation_guard
BEFORE INSERT OR UPDATE ON gda_control.slo_definition_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_slo_activation_mutation();

DROP TRIGGER IF EXISTS trg_gda_slo_activation_delete_guard
    ON gda_control.slo_definition_activation;
CREATE TRIGGER trg_gda_slo_activation_delete_guard
BEFORE DELETE ON gda_control.slo_definition_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_slo_event_immutable
    ON gda_control.slo_definition_event;
CREATE TRIGGER trg_gda_slo_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.slo_definition_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.slo_definition_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.slo_definition_version FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.slo_definition_version;
CREATE POLICY tenant_isolation ON gda_control.slo_definition_version
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.slo_definition_activation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.slo_definition_activation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.slo_definition_activation;
CREATE POLICY tenant_isolation ON gda_control.slo_definition_activation
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.slo_definition_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.slo_definition_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.slo_definition_event;
CREATE POLICY tenant_isolation ON gda_control.slo_definition_event
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.slo_definition_version
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.slo_definition_activation
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.slo_definition_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.slo_definition_version TO gda_control_gateway;
GRANT SELECT ON gda_control.slo_definition_activation TO gda_control_gateway;
GRANT SELECT ON gda_control.slo_definition_event TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_slo_activation_mutation()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.stage_slo_definition_version(
    TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB, INTEGER, INTEGER,
    TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.activate_slo_definition_version(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.stage_slo_definition_version(
    TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB, INTEGER, INTEGER,
    TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.activate_slo_definition_version(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) TO gda_control_gateway;
