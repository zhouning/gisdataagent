-- 207: Bind terminal GIS deployment evidence to its immutable release and placement.
--
-- The generic framework_attempt_observation ledger remains the single provider
-- evidence store. This migration narrows the GIS terminal-evidence profile and
-- never creates a parallel health, deployment, or scheduler authority.

CREATE OR REPLACE FUNCTION gda_control.guard_gis_service_deployment_observation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.evidence ->> 'schema' <> 'gda.gis_service_deployment_observation.v2' THEN
        RETURN NEW;
    END IF;
    IF COALESCE(
        current_setting('gda.gis_service_deployment_observation_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the governed GIS deployment observation recorder'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.observed_state NOT IN (
        'success', 'succeeded', 'ready', 'completed',
        'failed', 'error', 'cancelled', 'timed_out'
    )
       OR NEW.evidence ->> 'deployment_revision_id' IS NULL
       OR NEW.evidence ->> 'service_definition_version_id' IS NULL
       OR NEW.evidence ->> 'service_release_binding_id' IS NULL
       OR NEW.evidence ->> 'provider_system' IS NULL
       OR NEW.evidence ->> 'provider_namespace' IS NULL
       OR NEW.evidence ->> 'provider_deployment_id' IS NULL
       OR NEW.evidence ->> 'provider_revision_ref' IS NULL
       OR COALESCE(NEW.evidence ->> 'config_sha256', '') !~ '^[0-9a-f]{64}$'
       OR NULLIF(btrim(COALESCE(NEW.evidence ->> 'provider_version', '')), '') IS NULL
       OR COALESCE(NEW.evidence ->> 'health_evidence_sha256', '') !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(NEW.evidence -> 'provider_receipt') <> 'object'
       OR NEW.evidence -> 'provider_receipt' = '{}'::jsonb
       OR COALESCE(NEW.evidence ->> 'endpoint_uri', '') !~ '^https://[^/@?#]+[^?#]*$'
       OR NEW.evidence ->> 'endpoint_uri' LIKE '%@%'
       OR position('?' IN COALESCE(NEW.evidence ->> 'endpoint_uri', '')) > 0
       OR position('#' IN COALESCE(NEW.evidence ->> 'endpoint_uri', '')) > 0 THEN
        RAISE EXCEPTION 'GIS deployment observation does not satisfy the terminal evidence contract'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_gis_service_deployment_observation_guard
    ON gda_control.framework_attempt_observation;
CREATE TRIGGER trg_gda_gis_service_deployment_observation_guard
BEFORE INSERT ON gda_control.framework_attempt_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_deployment_observation();

CREATE OR REPLACE FUNCTION gda_control.transition_service_deployment_revision(
    p_tenant_id TEXT,
    p_deployment_revision_id UUID,
    p_expected_state_version INTEGER,
    p_to_state TEXT,
    p_provider_observation_id UUID,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_idempotency_key TEXT,
    p_occurred_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_deployment gda_control.service_deployment_revision%ROWTYPE;
    v_event gda_control.service_deployment_event%ROWTYPE;
    v_run_status TEXT;
    v_observed_state TEXT;
    v_observation_namespace TEXT;
    v_observation_external_run_id TEXT;
    v_observation_external_attempt_id TEXT;
    v_observation_evidence JSONB;
    v_new_state_version INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service deployment tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'deployment transition actor, reason and idempotency are required'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_deployment
      FROM gda_control.service_deployment_revision
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ServiceDeploymentRevision was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_event
      FROM gda_control.service_deployment_event
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id
       AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_event.to_state = p_to_state
           AND v_event.provider_observation_id IS NOT DISTINCT FROM p_provider_observation_id
           AND v_event.actor_subject = p_actor_subject
           AND v_event.reason = p_reason
           AND v_event.occurred_at = p_occurred_at THEN
            RETURN v_event.sequence_no;
        END IF;
        RAISE EXCEPTION 'deployment transition idempotency has different content'
            USING ERRCODE = '40001';
    END IF;
    IF v_deployment.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'deployment state version conflict'
            USING ERRCODE = '40001';
    END IF;
    IF NOT (
        (v_deployment.state = 'planned' AND p_to_state = 'deploying')
        OR (v_deployment.state = 'deploying' AND p_to_state IN ('ready', 'failed'))
    ) THEN
        RAISE EXCEPTION 'invalid service deployment state transition'
            USING ERRCODE = '23514';
    END IF;
    SELECT status INTO v_run_status
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id AND run_id = v_deployment.run_id;

    IF p_to_state = 'deploying' THEN
        IF p_provider_observation_id IS NOT NULL
           OR v_run_status NOT IN ('dispatching', 'running', 'reconciling', 'succeeded') THEN
            RAISE EXCEPTION 'deploying requires an active deployment PlatformRun'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT observed_state, external_namespace, external_run_id,
               external_attempt_id, evidence
          INTO v_observed_state, v_observation_namespace,
               v_observation_external_run_id, v_observation_external_attempt_id,
               v_observation_evidence
          FROM gda_control.framework_attempt_observation
         WHERE tenant_id = p_tenant_id
           AND observation_id = p_provider_observation_id
           AND run_id = v_deployment.run_id;
        IF NOT FOUND
           OR v_observation_evidence ->> 'schema'
                IS DISTINCT FROM 'gda.gis_service_deployment_observation.v2'
           OR v_observation_evidence ->> 'deployment_revision_id'
                IS DISTINCT FROM p_deployment_revision_id::text
           OR v_observation_evidence ->> 'service_definition_version_id'
                IS DISTINCT FROM v_deployment.service_definition_version_id::text
           OR v_observation_evidence ->> 'service_release_binding_id'
                IS DISTINCT FROM v_deployment.service_release_binding_id::text
           OR v_observation_evidence ->> 'provider_system'
                IS DISTINCT FROM v_deployment.provider_system
           OR v_observation_evidence ->> 'provider_namespace'
                IS DISTINCT FROM v_deployment.provider_namespace
           OR v_observation_evidence ->> 'provider_deployment_id'
                IS DISTINCT FROM v_deployment.provider_deployment_id
           OR v_observation_evidence ->> 'provider_revision_ref'
                IS DISTINCT FROM v_deployment.provider_revision_ref
           OR v_observation_evidence ->> 'config_sha256'
                IS DISTINCT FROM v_deployment.config_sha256
           OR v_observation_namespace IS DISTINCT FROM v_deployment.provider_namespace
           OR v_observation_external_run_id IS DISTINCT FROM v_deployment.provider_deployment_id
           OR v_observation_external_attempt_id IS DISTINCT FROM v_deployment.provider_revision_ref THEN
            RAISE EXCEPTION 'terminal provider observation does not bind this release deployment'
                USING ERRCODE = '23514';
        END IF;
        IF p_to_state = 'ready'
           AND (
               v_run_status <> 'succeeded'
               OR lower(v_observed_state) NOT IN ('success', 'succeeded', 'ready', 'completed')
           ) THEN
            RAISE EXCEPTION 'ready requires succeeded Run and success observation'
                USING ERRCODE = '23514';
        ELSIF p_to_state = 'failed'
              AND (
                  v_run_status NOT IN ('failed', 'cancelled', 'timed_out')
                  OR lower(v_observed_state) NOT IN ('failed', 'error', 'cancelled', 'timed_out')
              ) THEN
            RAISE EXCEPTION 'failed requires terminal failed Run and observation'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    v_new_state_version := v_deployment.state_version + 1;
    PERFORM set_config('gda.service_deployment_transition_allowed', '1', true);
    UPDATE gda_control.service_deployment_revision
       SET state = p_to_state,
           state_version = v_new_state_version,
           terminal_observation_id = CASE
               WHEN p_to_state IN ('ready', 'failed') THEN p_provider_observation_id
               ELSE NULL
           END,
           updated_at = p_occurred_at,
           terminal_at = CASE
               WHEN p_to_state IN ('ready', 'failed') THEN p_occurred_at
               ELSE NULL
           END
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_deployment_event (
        tenant_id, deployment_revision_id, sequence_no, from_state, to_state,
        provider_observation_id, actor_subject, reason, idempotency_key,
        event_sha256, occurred_at
    ) VALUES (
        p_tenant_id, p_deployment_revision_id, v_new_state_version,
        v_deployment.state, p_to_state, p_provider_observation_id,
        p_actor_subject, p_reason, p_idempotency_key,
        encode(sha256(convert_to(jsonb_build_object(
            'tenant_id', p_tenant_id,
            'deployment_revision_id', p_deployment_revision_id::text,
            'sequence_no', v_new_state_version,
            'from_state', v_deployment.state,
            'to_state', p_to_state,
            'provider_observation_id', p_provider_observation_id::text,
            'actor_subject', p_actor_subject,
            'reason', p_reason,
            'occurred_at', p_occurred_at
        )::text, 'UTF8')), 'hex'),
        p_occurred_at
    );
    RETURN v_new_state_version;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.guard_gis_service_deployment_observation() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.guard_gis_service_deployment_observation()
    TO gda_control_gateway;
