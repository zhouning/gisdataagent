-- 101: Evidence-bound promotion of inert Active Metadata activation requests.
--
-- The authorization ledger is append-only. For the metadata projection
-- capability, a dispatch command can exist only when the exact request,
-- ResourceVersion, DefinitionVersion, accepted Run, execution plan,
-- PolicyDecision and independent Approval are bound in the same transaction.

CREATE TABLE IF NOT EXISTS gda_control.metadata_activation_authorization (
    tenant_id TEXT NOT NULL,
    authorization_id UUID PRIMARY KEY,
    request_id UUID NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    resource_urn TEXT NOT NULL,
    resource_version_id UUID NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    definition_version_id UUID NOT NULL,
    definition_sha256 CHAR(64) NOT NULL,
    run_id UUID NOT NULL,
    execution_plan_artifact_id UUID NOT NULL,
    execution_plan_sha256 CHAR(64) NOT NULL,
    policy_decision_artifact_id UUID NOT NULL,
    policy_decision_sha256 CHAR(64) NOT NULL,
    approval_artifact_id UUID NOT NULL,
    approval_sha256 CHAR(64) NOT NULL,
    command_id UUID NOT NULL,
    route TEXT NOT NULL,
    status TEXT NOT NULL,
    authorized_by TEXT NOT NULL,
    authorized_at TIMESTAMPTZ NOT NULL,
    authorization_document JSONB NOT NULL,
    authorization_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_gda_activation_authorization_tenant_id
        UNIQUE (tenant_id, authorization_id),
    CONSTRAINT uq_gda_activation_authorization_request
        UNIQUE (tenant_id, request_id),
    CONSTRAINT uq_gda_activation_authorization_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_activation_authorization_command
        UNIQUE (tenant_id, command_id),
    CONSTRAINT fk_gda_activation_authorization_request
        FOREIGN KEY (tenant_id, request_id)
        REFERENCES gda_control.metadata_activation_request(tenant_id, request_id),
    CONSTRAINT fk_gda_activation_authorization_version
        FOREIGN KEY (
            tenant_id, resource_urn, resource_version_id, content_sha256
        ) REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id, content_sha256
        ),
    CONSTRAINT fk_gda_activation_authorization_definition
        FOREIGN KEY (tenant_id, definition_version_id)
        REFERENCES gda_control.platform_definition_version(
            tenant_id, definition_version_id
        ),
    CONSTRAINT fk_gda_activation_authorization_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_activation_authorization_plan
        FOREIGN KEY (tenant_id, execution_plan_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_activation_authorization_policy
        FOREIGN KEY (tenant_id, policy_decision_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_activation_authorization_approval
        FOREIGN KEY (tenant_id, approval_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_activation_authorization_command
        FOREIGN KEY (tenant_id, command_id)
        REFERENCES gda_control.platform_command_outbox(tenant_id, command_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_gda_activation_authorization_hashes CHECK (
        request_sha256 ~ '^[0-9a-f]{64}$'
        AND content_sha256 ~ '^[0-9a-f]{64}$'
        AND definition_sha256 ~ '^[0-9a-f]{64}$'
        AND execution_plan_sha256 ~ '^[0-9a-f]{64}$'
        AND policy_decision_sha256 ~ '^[0-9a-f]{64}$'
        AND approval_sha256 ~ '^[0-9a-f]{64}$'
        AND authorization_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_activation_authorization_route CHECK (
        route = 'metadata_fabric.projection_plan'
    ),
    CONSTRAINT ck_gda_activation_authorization_status CHECK (
        status = 'authorized_for_dispatch'
    ),
    CONSTRAINT ck_gda_activation_authorizer CHECK (
        authorized_by ~ '^workload:.+'
    ),
    CONSTRAINT ck_gda_activation_authorization_document CHECK (
        jsonb_typeof(authorization_document) = 'object'
        AND authorization_document ?& ARRAY[
            'schema', 'authorization_id', 'tenant_id', 'request_id',
            'request_sha256', 'resource_urn', 'resource_version_id',
            'content_sha256', 'definition_version_id', 'definition_sha256',
            'run_id', 'execution_plan_artifact_id', 'execution_plan_sha256',
            'policy_decision_artifact_id', 'policy_decision_sha256',
            'approval_artifact_id', 'approval_sha256', 'command_id', 'route',
            'status', 'authorized_by', 'authorized_at',
            'scheduler_command_enqueued', 'provider_apply_authorized',
            'provider_mutations_executed',
            'production_scheduler_submission_verified',
            'production_ingestion_verified', 'production_ready',
            'authorization_sha256'
        ]
        AND authorization_document - ARRAY[
            'schema', 'authorization_id', 'tenant_id', 'request_id',
            'request_sha256', 'resource_urn', 'resource_version_id',
            'content_sha256', 'definition_version_id', 'definition_sha256',
            'run_id', 'execution_plan_artifact_id', 'execution_plan_sha256',
            'policy_decision_artifact_id', 'policy_decision_sha256',
            'approval_artifact_id', 'approval_sha256', 'command_id', 'route',
            'status', 'authorized_by', 'authorized_at',
            'scheduler_command_enqueued', 'provider_apply_authorized',
            'provider_mutations_executed',
            'production_scheduler_submission_verified',
            'production_ingestion_verified', 'production_ready',
            'authorization_sha256'
        ] = '{}'::jsonb
        AND authorization_document->>'schema' = 'gda.metadata_activation_authorization.v1'
        AND authorization_document->>'authorization_id' = authorization_id::text
        AND authorization_document->>'tenant_id' = tenant_id
        AND authorization_document->>'request_id' = request_id::text
        AND authorization_document->>'request_sha256' = request_sha256
        AND authorization_document->>'resource_urn' = resource_urn
        AND authorization_document->>'resource_version_id' = resource_version_id::text
        AND authorization_document->>'content_sha256' = content_sha256
        AND authorization_document->>'definition_version_id' = definition_version_id::text
        AND authorization_document->>'definition_sha256' = definition_sha256
        AND authorization_document->>'run_id' = run_id::text
        AND authorization_document->>'execution_plan_artifact_id' =
            execution_plan_artifact_id::text
        AND authorization_document->>'execution_plan_sha256' = execution_plan_sha256
        AND authorization_document->>'policy_decision_artifact_id' =
            policy_decision_artifact_id::text
        AND authorization_document->>'policy_decision_sha256' = policy_decision_sha256
        AND authorization_document->>'approval_artifact_id' = approval_artifact_id::text
        AND authorization_document->>'approval_sha256' = approval_sha256
        AND authorization_document->>'command_id' = command_id::text
        AND authorization_document->>'route' = route
        AND authorization_document->>'status' = status
        AND authorization_document->>'authorized_by' = authorized_by
        AND (authorization_document->>'authorized_at')::timestamptz = authorized_at
        AND (authorization_document->>'scheduler_command_enqueued')::boolean = true
        AND (authorization_document->>'provider_apply_authorized')::boolean = false
        AND (authorization_document->>'provider_mutations_executed')::boolean = false
        AND (
            authorization_document->>'production_scheduler_submission_verified'
        )::boolean = false
        AND (authorization_document->>'production_ingestion_verified')::boolean = false
        AND (authorization_document->>'production_ready')::boolean = false
        AND authorization_document->>'authorization_sha256' = authorization_sha256
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_activation_authorization_resource
    ON gda_control.metadata_activation_authorization(
        tenant_id, resource_version_id, authorized_at DESC
    );

ALTER TABLE gda_control.metadata_activation_authorization
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metadata_activation_authorization
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gda_activation_authorization_tenant_isolation
    ON gda_control.metadata_activation_authorization;
CREATE POLICY gda_activation_authorization_tenant_isolation
    ON gda_control.metadata_activation_authorization
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.authorize_metadata_activation(
    p_tenant_id TEXT,
    p_authorization JSONB
)
RETURNS TABLE(activation_authorization JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    request_row gda_control.metadata_activation_request%ROWTYPE;
    version_row gda_control.resource_version%ROWTYPE;
    definition_row gda_control.platform_definition_version%ROWTYPE;
    run_row gda_control.platform_run%ROWTYPE;
    plan_row gda_control.artifact%ROWTYPE;
    policy_row gda_control.artifact%ROWTYPE;
    approval_row gda_control.artifact%ROWTYPE;
    stored gda_control.metadata_activation_authorization%ROWTYPE;
    decision JSONB;
    approval JSONB;
    expected_resources TEXT[];
    decision_resources TEXT[];
    decision_resource_count INTEGER;
    decision_distinct_count INTEGER;
    inserted_rows INTEGER := 0;
    p_authorized_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_authorization) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'activation authorization must be an object'
            USING ERRCODE = '22023';
    END IF;
    IF p_authorization->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_authorization->>'schema' IS DISTINCT FROM
            'gda.metadata_activation_authorization.v1'
       OR p_authorization->>'route' IS DISTINCT FROM
            'metadata_fabric.projection_plan'
       OR p_authorization->>'status' IS DISTINCT FROM
            'authorized_for_dispatch'
       OR COALESCE((p_authorization->>'scheduler_command_enqueued')::boolean, false)
            IS DISTINCT FROM true
       OR COALESCE((p_authorization->>'provider_apply_authorized')::boolean, true)
            IS DISTINCT FROM false
       OR COALESCE((p_authorization->>'provider_mutations_executed')::boolean, true)
            IS DISTINCT FROM false
       OR COALESCE(
            (p_authorization->>'production_scheduler_submission_verified')::boolean,
            true
          ) IS DISTINCT FROM false
       OR COALESCE((p_authorization->>'production_ingestion_verified')::boolean, true)
            IS DISTINCT FROM false
       OR COALESCE((p_authorization->>'production_ready')::boolean, true)
            IS DISTINCT FROM false THEN
        RAISE EXCEPTION 'activation authorization safety claims are invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_authorization->>'authorized_by' !~ '^workload:.+' THEN
        RAISE EXCEPTION 'activation authorizer must use workload identity'
            USING ERRCODE = '22023';
    END IF;
    p_authorized_at := (p_authorization->>'authorized_at')::timestamptz;
    IF p_authorized_at > clock_timestamp() + interval '5 minutes' THEN
        RAISE EXCEPTION 'activation authorization time is in the future'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO request_row
      FROM gda_control.metadata_activation_request
     WHERE tenant_id = p_tenant_id
       AND request_id = (p_authorization->>'request_id')::uuid
     FOR UPDATE;
    IF NOT FOUND
       OR request_row.status <> 'awaiting_authorization'
       OR request_row.request_sha256 IS DISTINCT FROM
            p_authorization->>'request_sha256'
       OR request_row.resource_urn IS DISTINCT FROM
            p_authorization->>'resource_urn'
       OR request_row.resource_version_id IS DISTINCT FROM
            (p_authorization->>'resource_version_id')::uuid
       OR request_row.content_sha256 IS DISTINCT FROM
            p_authorization->>'content_sha256'
       OR request_row.route IS DISTINCT FROM p_authorization->>'route' THEN
        RAISE EXCEPTION 'activation authorization does not match the durable request'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO version_row
      FROM gda_control.resource_version
     WHERE tenant_id = p_tenant_id
       AND resource_version_id = request_row.resource_version_id;
    IF NOT FOUND
       OR version_row.resource_urn IS DISTINCT FROM request_row.resource_urn
       OR version_row.content_sha256 IS DISTINCT FROM request_row.content_sha256 THEN
        RAISE EXCEPTION 'activation ResourceVersion binding is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO definition_row
      FROM gda_control.platform_definition_version
     WHERE tenant_id = p_tenant_id
       AND definition_version_id =
            (p_authorization->>'definition_version_id')::uuid;
    IF NOT FOUND
       OR definition_row.definition_sha256 IS DISTINCT FROM
            p_authorization->>'definition_sha256'
       OR definition_row.orchestration_class <> 'dataops'
       OR definition_row.capability_id <> 'metadata_fabric.projection_plan' THEN
        RAISE EXCEPTION 'activation DefinitionVersion binding is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO run_row
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id
       AND run_id = (p_authorization->>'run_id')::uuid
     FOR UPDATE;
    IF NOT FOUND
       OR run_row.definition_version_id IS DISTINCT FROM
            definition_row.definition_version_id
       OR run_row.orchestration_class <> 'dataops'
       OR run_row.status <> 'accepted'
       OR run_row.subject_context->>'subject_type' <> 'workload'
       OR run_row.submitted_at > p_authorized_at
       OR run_row.policy_refs->>'policy_decision_artifact_id' IS DISTINCT FROM
            p_authorization->>'policy_decision_artifact_id'
       OR run_row.policy_refs->>'approval_artifact_id' IS DISTINCT FROM
            p_authorization->>'approval_artifact_id'
       OR NOT EXISTS (
            SELECT 1 FROM gda_control.platform_run_input_binding binding
             WHERE binding.tenant_id = p_tenant_id
               AND binding.run_id = run_row.run_id
               AND binding.resource_version_id = request_row.resource_version_id
       ) THEN
        RAISE EXCEPTION 'activation Run binding is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO plan_row
      FROM gda_control.artifact
     WHERE tenant_id = p_tenant_id
       AND artifact_id =
            (p_authorization->>'execution_plan_artifact_id')::uuid;
    IF NOT FOUND
       OR plan_row.artifact_role <> 'execution_plan'
       OR plan_row.run_id IS NOT NULL
       OR plan_row.resource_version_id IS DISTINCT FROM
            definition_row.definition_version_id
       OR plan_row.content_sha256 IS DISTINCT FROM
            p_authorization->>'execution_plan_sha256'
       OR plan_row.created_at > p_authorized_at THEN
        RAISE EXCEPTION 'activation execution plan binding is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO policy_row
      FROM gda_control.artifact
     WHERE tenant_id = p_tenant_id
       AND artifact_id =
            (p_authorization->>'policy_decision_artifact_id')::uuid;
    decision := policy_row.manifest->'decision';
    IF NOT FOUND
       OR policy_row.artifact_role <> 'evidence'
       OR policy_row.run_id IS NOT NULL
       OR policy_row.resource_version_id IS DISTINCT FROM
            definition_row.definition_version_id
       OR policy_row.content_sha256 IS DISTINCT FROM
            p_authorization->>'policy_decision_sha256'
       OR policy_row.manifest->>'schema' <>
            'gda.policy_decision_artifact.v1'
       OR jsonb_typeof(decision) IS DISTINCT FROM 'object'
       OR decision->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR decision->>'run_id' IS DISTINCT FROM run_row.run_id::text
       OR decision->'subject_context' IS DISTINCT FROM run_row.subject_context
       OR decision->>'definition_version_id' IS DISTINCT FROM
            definition_row.definition_version_id::text
       OR decision->>'execution_plan_artifact_id' IS DISTINCT FROM
            plan_row.artifact_id::text
       OR decision->>'action' <> 'dolphinscheduler.dispatch'
       OR decision->>'effect' <> 'allow'
       OR decision->'obligations' <> '[]'::jsonb
       OR jsonb_typeof(decision->'resource_version_ids') IS DISTINCT FROM 'array'
       OR COALESCE((decision->>'requires_approval')::boolean, false) <> true
       OR decision->>'evaluator_subject' !~ '^workload:.+'
       OR decision->>'evaluator_subject' = run_row.submitted_by
       OR (decision->>'decided_at')::timestamptz > p_authorized_at
       OR p_authorized_at >= (decision->>'expires_at')::timestamptz
       OR clock_timestamp() >= (decision->>'expires_at')::timestamptz THEN
        RAISE EXCEPTION 'activation PolicyDecision binding is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT array_agg(resource_id ORDER BY resource_id)
      INTO expected_resources
      FROM (
        SELECT definition_row.definition_version_id::text AS resource_id
        UNION
        SELECT binding.resource_version_id::text
          FROM gda_control.platform_run_input_binding binding
         WHERE binding.tenant_id = p_tenant_id
           AND binding.run_id = run_row.run_id
      ) resources;
    SELECT array_agg(value ORDER BY value), count(*), count(DISTINCT value)
      INTO decision_resources, decision_resource_count, decision_distinct_count
      FROM jsonb_array_elements_text(decision->'resource_version_ids') items(value);
    IF decision_resources IS DISTINCT FROM expected_resources
       OR decision_resource_count IS DISTINCT FROM decision_distinct_count THEN
        RAISE EXCEPTION 'activation PolicyDecision resource scope is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO approval_row
      FROM gda_control.artifact
     WHERE tenant_id = p_tenant_id
       AND artifact_id = (p_authorization->>'approval_artifact_id')::uuid;
    approval := approval_row.manifest->'approval';
    IF NOT FOUND
       OR approval_row.artifact_role <> 'evidence'
       OR approval_row.run_id IS NOT NULL
       OR approval_row.resource_version_id IS DISTINCT FROM
            definition_row.definition_version_id
       OR approval_row.content_sha256 IS DISTINCT FROM
            p_authorization->>'approval_sha256'
       OR approval_row.manifest->>'schema' <> 'gda.approval_artifact.v1'
       OR jsonb_typeof(approval) IS DISTINCT FROM 'object'
       OR approval->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR approval->>'run_id' IS DISTINCT FROM run_row.run_id::text
       OR approval->>'definition_version_id' IS DISTINCT FROM
            definition_row.definition_version_id::text
       OR approval->>'policy_decision_artifact_id' IS DISTINCT FROM
            policy_row.artifact_id::text
       OR approval->>'policy_decision_sha256' IS DISTINCT FROM
            policy_row.content_sha256
       OR approval->>'verdict' <> 'approved'
       OR approval->>'approver_subject' !~ '^human:.+'
       OR approval->>'approver_subject' IN (
            run_row.submitted_by, decision->>'evaluator_subject'
       )
       OR (approval->>'decided_at')::timestamptz <
            (decision->>'decided_at')::timestamptz
       OR (approval->>'expires_at')::timestamptz >
            (decision->>'expires_at')::timestamptz
       OR (approval->>'decided_at')::timestamptz > p_authorized_at
       OR p_authorized_at >= (approval->>'expires_at')::timestamptz
       OR clock_timestamp() >= (approval->>'expires_at')::timestamptz THEN
        RAISE EXCEPTION 'activation Approval binding is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF p_authorization->>'authorized_by' IN (
        run_row.submitted_by,
        decision->>'evaluator_subject',
        approval->>'approver_subject'
    ) THEN
        RAISE EXCEPTION 'activation authorizer is not independent'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO gda_control.metadata_activation_authorization (
        tenant_id, authorization_id, request_id, request_sha256,
        resource_urn, resource_version_id, content_sha256,
        definition_version_id, definition_sha256, run_id,
        execution_plan_artifact_id, execution_plan_sha256,
        policy_decision_artifact_id, policy_decision_sha256,
        approval_artifact_id, approval_sha256, command_id, route, status,
        authorized_by, authorized_at, authorization_document,
        authorization_sha256
    ) VALUES (
        p_tenant_id,
        (p_authorization->>'authorization_id')::uuid,
        request_row.request_id,
        request_row.request_sha256,
        request_row.resource_urn,
        request_row.resource_version_id,
        request_row.content_sha256,
        definition_row.definition_version_id,
        definition_row.definition_sha256,
        run_row.run_id,
        plan_row.artifact_id,
        plan_row.content_sha256,
        policy_row.artifact_id,
        policy_row.content_sha256,
        approval_row.artifact_id,
        approval_row.content_sha256,
        (p_authorization->>'command_id')::uuid,
        p_authorization->>'route',
        p_authorization->>'status',
        p_authorization->>'authorized_by',
        p_authorized_at,
        p_authorization,
        p_authorization->>'authorization_sha256'
    )
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS inserted_rows = ROW_COUNT;

    SELECT * INTO stored
      FROM gda_control.metadata_activation_authorization
     WHERE tenant_id = p_tenant_id
       AND request_id = request_row.request_id;
    IF NOT FOUND OR stored.authorization_document IS DISTINCT FROM p_authorization THEN
        RAISE EXCEPTION 'activation authorization identity has different content'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT stored.authorization_document, inserted_rows = 1;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_active_metadata_dispatch()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
DECLARE
    capability TEXT;
    executor_subject TEXT;
    authorization_row gda_control.metadata_activation_authorization%ROWTYPE;
BEGIN
    IF NEW.command_type <> 'dolphinscheduler.dispatch' THEN
        RETURN NEW;
    END IF;
    SELECT definition.capability_id, run.submitted_by
      INTO capability, executor_subject
      FROM gda_control.platform_run run
      JOIN gda_control.platform_definition_version definition
        ON definition.tenant_id = run.tenant_id
       AND definition.definition_version_id = run.definition_version_id
     WHERE run.tenant_id = NEW.tenant_id AND run.run_id = NEW.run_id;
    IF capability IS DISTINCT FROM 'metadata_fabric.projection_plan' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO authorization_row
      FROM gda_control.metadata_activation_authorization
     WHERE tenant_id = NEW.tenant_id AND command_id = NEW.command_id;
    IF NOT FOUND
       OR authorization_row.run_id IS DISTINCT FROM NEW.run_id
       OR authorization_row.execution_plan_artifact_id IS DISTINCT FROM
            NEW.execution_plan_artifact_id
       OR executor_subject IS DISTINCT FROM NEW.actor_subject
       OR NEW.payload->>'schema' <>
            'gda.dolphinscheduler_dispatch_command.v1'
       OR NEW.payload->>'policy_decision_artifact_id' IS DISTINCT FROM
            authorization_row.policy_decision_artifact_id::text
       OR NEW.payload->>'metadata_activation_authorization_id' IS DISTINCT FROM
            authorization_row.authorization_id::text
       OR NEW.payload->>'metadata_activation_request_id' IS DISTINCT FROM
            authorization_row.request_id::text THEN
        RAISE EXCEPTION 'Active Metadata dispatch requires exact authorization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_active_metadata_dispatch
    ON gda_control.platform_command_outbox;
CREATE TRIGGER trg_guard_active_metadata_dispatch
BEFORE INSERT ON gda_control.platform_command_outbox
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_active_metadata_dispatch();

REVOKE ALL ON TABLE gda_control.metadata_activation_authorization FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.metadata_activation_authorization
    FROM gda_control_gateway;
GRANT SELECT ON gda_control.metadata_activation_authorization
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.authorize_metadata_activation(text, jsonb)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.authorize_metadata_activation(text, jsonb)
    TO gda_control_gateway;
