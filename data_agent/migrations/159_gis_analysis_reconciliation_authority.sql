-- 159: Durable reconciliation and human resolution for uncertain GIS cancellation.
-- Opening the shared DataIncident also feeds the existing Alertmanager outbox.

ALTER TABLE gda_control.platform_command_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_command_type;
ALTER TABLE gda_control.platform_command_outbox
    ADD CONSTRAINT ck_gda_command_type CHECK (
        command_type IN (
            'dolphinscheduler.dispatch',
            'dolphinscheduler.reconcile',
            'dolphinscheduler.cancel',
            'metric_query.execute',
            'gis_analysis.execute',
            'gis_analysis.cancel',
            'gis_analysis.reconcile'
        )
    );

CREATE TABLE IF NOT EXISTS gda_control.gis_analysis_reconciliation_observation (
    tenant_id TEXT NOT NULL,
    reconciliation_observation_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    reconcile_command_id UUID NOT NULL,
    reconcile_attempt_no INTEGER NOT NULL,
    cancel_command_id UUID NOT NULL,
    cancel_observation_id UUID NOT NULL,
    outcome TEXT NOT NULL,
    backend_binding_fingerprint CHAR(64) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_gis_reconciliation_observation_tenant
        UNIQUE (tenant_id, reconciliation_observation_id),
    CONSTRAINT uq_gda_gis_reconciliation_command_attempt
        UNIQUE (tenant_id, reconcile_command_id, reconcile_attempt_no),
    CONSTRAINT fk_gda_gis_reconciliation_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.gis_analysis_execution_admission(tenant_id, run_id),
    CONSTRAINT fk_gda_gis_reconciliation_command
        FOREIGN KEY (tenant_id, reconcile_command_id)
        REFERENCES gda_control.platform_command_outbox(tenant_id, command_id),
    CONSTRAINT fk_gda_gis_reconciliation_cancel
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.gis_analysis_cancel_receipt(tenant_id, run_id),
    CONSTRAINT ck_gda_gis_reconciliation_attempt CHECK (
        reconcile_attempt_no BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_gis_reconciliation_outcome CHECK (
        outcome IN ('signalled', 'not_found', 'unknown')
    ),
    CONSTRAINT ck_gda_gis_reconciliation_hash CHECK (
        backend_binding_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_gis_reconciliation_actor CHECK (
        recorded_by = 'workload:gis-analysis-postgis-reconciler'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_gis_reconciliation_run_time
    ON gda_control.gis_analysis_reconciliation_observation(
        tenant_id, run_id, observed_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.enqueue_gis_analysis_reconciliation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_cancel gda_control.gis_analysis_cancel_admission%ROWTYPE;
    v_analysis gda_control.gis_analysis_execution_admission%ROWTYPE;
    v_dedupe_key TEXT;
    v_command_id UUID;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'GIS reconciliation tenant context is mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO STRICT v_cancel
    FROM gda_control.gis_analysis_cancel_admission
    WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id;
    SELECT * INTO STRICT v_analysis
    FROM gda_control.gis_analysis_execution_admission
    WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id;
    v_dedupe_key := concat(
        'gis_analysis.reconcile:', NEW.tenant_id, ':', NEW.run_id::text, ':',
        NEW.cancel_observation_id::text
    );
    v_command_id := gda_control.gis_analysis_command_uuid(v_dedupe_key);
    INSERT INTO gda_control.platform_command_outbox (
        tenant_id, command_id, run_id, command_type,
        execution_plan_artifact_id, trigger_observation_id,
        dedupe_key, actor_subject, payload, status, attempt_count,
        max_attempts, available_at, created_at
    ) VALUES (
        NEW.tenant_id, v_command_id, NEW.run_id, 'gis_analysis.reconcile',
        v_analysis.plan_artifact_id, v_cancel.start_observation_id,
        v_dedupe_key, 'workload:gis-analysis-postgis-reconciler',
        jsonb_build_object(
            'schema', 'gda.gis_analysis_reconcile_command.v1',
            'run_id', NEW.run_id,
            'plan_artifact_id', v_analysis.plan_artifact_id,
            'cancel_command_id', NEW.cancel_command_id,
            'cancel_observation_id', NEW.cancel_observation_id,
            'initial_cancel_outcome', NEW.outcome,
            'backend_pid', v_cancel.backend_pid,
            'backend_start', v_cancel.backend_start,
            'database_oid', v_cancel.database_oid::bigint,
            'user_oid', v_cancel.user_oid::bigint,
            'application_name', v_cancel.application_name,
            'backend_binding_fingerprint',
                v_cancel.backend_binding_fingerprint,
            'reconciliation_deadline', NEW.observed_at + interval '10 minutes',
            'max_reconciliation_attempts', 5
        ),
        'pending', 0, 100, NEW.observed_at, NEW.observed_at
    ) ON CONFLICT (tenant_id, dedupe_key) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_gis_cancel_enqueue_reconciliation
    ON gda_control.gis_analysis_cancel_receipt;
CREATE TRIGGER trg_gda_gis_cancel_enqueue_reconciliation
AFTER INSERT ON gda_control.gis_analysis_cancel_receipt
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_gis_analysis_reconciliation();

INSERT INTO gda_control.platform_command_outbox (
    tenant_id, command_id, run_id, command_type,
    execution_plan_artifact_id, trigger_observation_id,
    dedupe_key, actor_subject, payload, status, attempt_count,
    max_attempts, available_at, created_at
)
SELECT
    receipt.tenant_id,
    gda_control.gis_analysis_command_uuid(concat(
        'gis_analysis.reconcile:', receipt.tenant_id, ':',
        receipt.run_id::text, ':', receipt.cancel_observation_id::text
    )),
    receipt.run_id,
    'gis_analysis.reconcile',
    analysis.plan_artifact_id,
    cancel.start_observation_id,
    concat(
        'gis_analysis.reconcile:', receipt.tenant_id, ':',
        receipt.run_id::text, ':', receipt.cancel_observation_id::text
    ),
    'workload:gis-analysis-postgis-reconciler',
    jsonb_build_object(
        'schema', 'gda.gis_analysis_reconcile_command.v1',
        'run_id', receipt.run_id,
        'plan_artifact_id', analysis.plan_artifact_id,
        'cancel_command_id', receipt.cancel_command_id,
        'cancel_observation_id', receipt.cancel_observation_id,
        'initial_cancel_outcome', receipt.outcome,
        'backend_pid', cancel.backend_pid,
        'backend_start', cancel.backend_start,
        'database_oid', cancel.database_oid::bigint,
        'user_oid', cancel.user_oid::bigint,
        'application_name', cancel.application_name,
        'backend_binding_fingerprint', cancel.backend_binding_fingerprint,
        'reconciliation_deadline', receipt.observed_at + interval '10 minutes',
        'max_reconciliation_attempts', 5
    ),
    'pending', 0, 100, receipt.observed_at, receipt.observed_at
FROM gda_control.gis_analysis_cancel_receipt AS receipt
JOIN gda_control.gis_analysis_cancel_admission AS cancel
  ON cancel.tenant_id = receipt.tenant_id
 AND cancel.run_id = receipt.run_id
JOIN gda_control.gis_analysis_execution_admission AS analysis
  ON analysis.tenant_id = receipt.tenant_id
 AND analysis.run_id = receipt.run_id
JOIN gda_control.platform_run AS run
  ON run.tenant_id = receipt.tenant_id
 AND run.run_id = receipt.run_id
WHERE run.status IN ('cancelling', 'reconciling')
ON CONFLICT (tenant_id, dedupe_key) DO NOTHING;

CREATE OR REPLACE FUNCTION gda_control.settle_gis_analysis_reconciliation(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_reconcile_command_id UUID,
    p_worker_id TEXT,
    p_outcome TEXT,
    p_backend_binding_fingerprint TEXT,
    p_actor_subject TEXT,
    p_observed_at TIMESTAMPTZ,
    p_retry_delay_seconds INTEGER,
    p_incident_id UUID DEFAULT NULL,
    p_incident_dedupe_key TEXT DEFAULT NULL,
    p_incident_details JSONB DEFAULT NULL,
    p_incident_sha256 TEXT DEFAULT NULL
)
RETURNS SETOF gda_control.platform_command_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_cancel gda_control.gis_analysis_cancel_admission%ROWTYPE;
    v_receipt gda_control.gis_analysis_cancel_receipt%ROWTYPE;
    v_command gda_control.platform_command_outbox%ROWTYPE;
    v_observation_id UUID;
    v_deadline TIMESTAMPTZ;
    v_business_max INTEGER;
    v_escalate BOOLEAN;
    v_details JSONB;
    v_existing_incident gda_control.data_incident%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS reconciliation tenant context is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject IS DISTINCT FROM
            'workload:gis-analysis-postgis-reconciler'
       OR NULLIF(btrim(p_worker_id), '') IS NULL
       OR p_outcome IS NULL
       OR p_outcome NOT IN ('signalled', 'not_found', 'unknown')
       OR COALESCE(
            p_backend_binding_fingerprint !~ '^[0-9a-f]{64}$', TRUE
       )
       OR p_observed_at IS NULL
       OR p_retry_delay_seconds IS NULL
       OR p_retry_delay_seconds NOT BETWEEN 0 AND 86400 THEN
        RAISE EXCEPTION 'GIS reconciliation evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_command
    FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id AND command_id = p_reconcile_command_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_command.run_id <> p_run_id
       OR v_command.command_type <> 'gis_analysis.reconcile'
       OR v_command.actor_subject <> p_actor_subject
       OR v_command.status <> 'in_flight'
       OR v_command.claimed_by <> p_worker_id
       OR v_command.claimed_until <= clock_timestamp()
       OR v_command.payload->>'schema' IS DISTINCT FROM
            'gda.gis_analysis_reconcile_command.v1'
       OR v_command.payload->>'backend_binding_fingerprint' IS DISTINCT FROM
            p_backend_binding_fingerprint THEN
        RAISE EXCEPTION 'GIS reconciliation command claim is invalid'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO STRICT v_cancel
    FROM gda_control.gis_analysis_cancel_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    SELECT * INTO STRICT v_receipt
    FROM gda_control.gis_analysis_cancel_receipt
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF v_cancel.cancel_command_id <> v_receipt.cancel_command_id
       OR v_receipt.cancel_command_id::text IS DISTINCT FROM
            v_command.payload->>'cancel_command_id'
       OR v_receipt.cancel_observation_id::text IS DISTINCT FROM
            v_command.payload->>'cancel_observation_id'
       OR v_cancel.backend_binding_fingerprint
            <> p_backend_binding_fingerprint
       OR v_receipt.backend_binding_fingerprint
            <> p_backend_binding_fingerprint
       OR p_observed_at < v_receipt.observed_at THEN
        RAISE EXCEPTION 'GIS reconciliation lacks exact cancellation evidence'
            USING ERRCODE = '23514';
    END IF;
    BEGIN
        v_deadline := (v_command.payload->>'reconciliation_deadline')::timestamptz;
        v_business_max := (v_command.payload->>'max_reconciliation_attempts')::integer;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'GIS reconciliation policy is invalid'
            USING ERRCODE = '23514';
    END;
    IF v_business_max IS NULL
       OR v_deadline IS NULL
       OR v_business_max NOT BETWEEN 1 AND 100
       OR v_deadline < v_receipt.observed_at THEN
        RAISE EXCEPTION 'GIS reconciliation policy is invalid'
            USING ERRCODE = '23514';
    END IF;

    v_observation_id := gda_control.gis_analysis_command_uuid(concat(
        'gis-analysis-reconciliation:', p_reconcile_command_id::text, ':',
        v_command.attempt_count::text
    ));
    INSERT INTO gda_control.gis_analysis_reconciliation_observation (
        tenant_id, reconciliation_observation_id, run_id,
        reconcile_command_id, reconcile_attempt_no, cancel_command_id,
        cancel_observation_id, outcome, backend_binding_fingerprint,
        observed_at, recorded_by
    ) VALUES (
        p_tenant_id, v_observation_id, p_run_id,
        p_reconcile_command_id, v_command.attempt_count,
        v_receipt.cancel_command_id, v_receipt.cancel_observation_id,
        p_outcome, p_backend_binding_fingerprint, p_observed_at, p_actor_subject
    );

    SELECT * INTO STRICT v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    IF v_run.status IN ('succeeded', 'failed', 'cancelled', 'timed_out') THEN
        UPDATE gda_control.platform_command_outbox
        SET status = 'done', claimed_by = NULL, claimed_until = NULL,
            last_error = NULL, completed_at = clock_timestamp()
        WHERE tenant_id = p_tenant_id AND command_id = p_reconcile_command_id;
        RETURN QUERY SELECT * FROM gda_control.platform_command_outbox
        WHERE tenant_id = p_tenant_id AND command_id = p_reconcile_command_id;
        RETURN;
    END IF;
    IF v_run.status = 'cancelling' THEN
        PERFORM gda_control.apply_platform_run_transition(
            p_tenant_id, p_run_id, v_run.state_version,
            'reconciling', p_actor_subject,
            'PostGIS cancellation is awaiting terminal evidence',
            jsonb_build_object(
                'schema', 'gda.gis_analysis_reconciliation_started.v1',
                'reconcile_command_id', p_reconcile_command_id,
                'cancel_observation_id', v_receipt.cancel_observation_id,
                'backend_binding_fingerprint', p_backend_binding_fingerprint
            )
        );
    ELSIF v_run.status <> 'reconciling' THEN
        RAISE EXCEPTION 'GIS reconciliation found a conflicting Run state'
            USING ERRCODE = '40001';
    END IF;

    v_escalate := v_command.attempt_count >= v_business_max
        OR p_observed_at >= v_deadline;
    IF NOT v_escalate THEN
        UPDATE gda_control.platform_command_outbox
        SET status = 'pending', claimed_by = NULL, claimed_until = NULL,
            last_error = left(concat('backend reconciliation outcome: ', p_outcome), 2000),
            available_at = clock_timestamp()
                + make_interval(secs => p_retry_delay_seconds),
            completed_at = NULL
        WHERE tenant_id = p_tenant_id AND command_id = p_reconcile_command_id;
        RETURN QUERY SELECT * FROM gda_control.platform_command_outbox
        WHERE tenant_id = p_tenant_id AND command_id = p_reconcile_command_id;
        RETURN;
    END IF;

    IF p_incident_id IS NULL
       OR COALESCE(
            p_incident_dedupe_key
                !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$',
            TRUE
       )
       OR COALESCE(p_incident_sha256 !~ '^[0-9a-f]{64}$', TRUE)
       OR p_incident_id <> gda_control.gis_analysis_command_uuid(
            concat('gis-analysis-reconciliation-incident:', p_run_id::text, ':',
                   v_receipt.cancel_observation_id::text)
       ) THEN
        RAISE EXCEPTION 'GIS reconciliation escalation evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    v_details := p_incident_details;
    IF jsonb_typeof(v_details) IS DISTINCT FROM 'object'
       OR v_details->>'schema' IS DISTINCT FROM
            'gda.gis_analysis_reconciliation_timeout.v1'
       OR v_details->>'reconcile_command_id' IS DISTINCT FROM
            p_reconcile_command_id::text
       OR (v_details->>'reconcile_attempt_count')::integer IS DISTINCT FROM
            v_command.attempt_count
       OR v_details->>'cancel_command_id' IS DISTINCT FROM
            v_receipt.cancel_command_id::text
       OR v_details->>'cancel_observation_id' IS DISTINCT FROM
            v_receipt.cancel_observation_id::text
       OR v_details->>'initial_cancel_outcome' IS DISTINCT FROM
            v_receipt.outcome
       OR v_details->>'last_reconciliation_outcome' IS DISTINCT FROM p_outcome
       OR v_details->>'backend_binding_fingerprint' IS DISTINCT FROM
            p_backend_binding_fingerprint
       OR (v_details->>'reconciliation_deadline')::timestamptz IS DISTINCT FROM
            v_deadline THEN
        RAISE EXCEPTION 'GIS reconciliation incident details are invalid'
            USING ERRCODE = '22023';
    END IF;
    INSERT INTO gda_control.data_incident (
        tenant_id, incident_id, run_id, subject_resource_urn, dedupe_key,
        incident_type, severity, summary, trigger_observation_id,
        details, incident_sha256, detected_by, status, state_version,
        opened_at, updated_at
    ) VALUES (
        p_tenant_id, p_incident_id, p_run_id, NULL, p_incident_dedupe_key,
        'gis_analysis_reconciliation_timeout', 'high',
        'GIS analysis cancellation requires human resolution',
        v_cancel.start_observation_id, v_details, p_incident_sha256,
        p_actor_subject, 'open', 0, p_observed_at, p_observed_at
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO STRICT v_existing_incident
    FROM gda_control.data_incident
    WHERE tenant_id = p_tenant_id AND incident_id = p_incident_id;
    IF v_existing_incident.run_id <> p_run_id
       OR v_existing_incident.dedupe_key <> p_incident_dedupe_key
       OR v_existing_incident.incident_type <> 'gis_analysis_reconciliation_timeout'
       OR v_existing_incident.incident_sha256 <> p_incident_sha256 THEN
        RAISE EXCEPTION 'GIS reconciliation incident identity conflicts'
            USING ERRCODE = '40001';
    END IF;
    UPDATE gda_control.platform_command_outbox
    SET status = 'failed', claimed_by = NULL, claimed_until = NULL,
        last_error = 'GIS cancellation reconciliation deadline exhausted',
        completed_at = clock_timestamp()
    WHERE tenant_id = p_tenant_id AND command_id = p_reconcile_command_id;
    RETURN QUERY SELECT * FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id AND command_id = p_reconcile_command_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.resolve_gis_analysis_reconciliation(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_incident_id UUID,
    p_expected_run_state_version INTEGER,
    p_expected_incident_state_version INTEGER,
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
    v_run gda_control.platform_run%ROWTYPE;
    v_incident gda_control.data_incident%ROWTYPE;
    v_state INTEGER;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS reconciliation resolution tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject !~ '^human:[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR length(p_reason) > 512 THEN
        RAISE EXCEPTION 'GIS reconciliation resolution evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT v_run FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id FOR UPDATE;
    SELECT * INTO STRICT v_incident FROM gda_control.data_incident
    WHERE tenant_id = p_tenant_id AND incident_id = p_incident_id FOR UPDATE;
    IF v_run.status <> 'reconciling'
       OR v_run.state_version <> p_expected_run_state_version
       OR v_incident.run_id <> p_run_id
       OR v_incident.incident_type <> 'gis_analysis_reconciliation_timeout'
       OR v_incident.status NOT IN ('open', 'acknowledged')
       OR v_incident.state_version <> p_expected_incident_state_version THEN
        RAISE EXCEPTION 'GIS reconciliation resolution state conflicts'
            USING ERRCODE = '40001';
    END IF;
    v_state := gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, v_run.state_version, 'failed',
        p_actor_subject, p_reason,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_human_resolution.v1',
            'incident_id', p_incident_id,
            'decision', 'failed',
            'basis', 'terminal cancellation evidence remained unavailable'
        )
    );
    PERFORM gda_control.transition_data_incident(
        p_tenant_id, p_incident_id, v_incident.state_version,
        'resolved', p_actor_subject, p_reason,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_human_resolution.v1',
            'run_id', p_run_id,
            'run_terminal_status', 'failed'
        )
    );
    RETURN v_state;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_gis_reconciliation_incident_resolution()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF OLD.incident_type = 'gis_analysis_reconciliation_timeout'
       AND NEW.status = 'resolved'
       AND COALESCE(
            current_setting(
                'gda.gis_reconciliation_terminal_resolution_allowed', true
            ),
            ''
       ) <> '1'
       AND EXISTS (
            SELECT 1 FROM gda_control.platform_run
            WHERE tenant_id = OLD.tenant_id AND run_id = OLD.run_id
              AND status NOT IN ('succeeded', 'failed', 'cancelled', 'timed_out')
       ) THEN
        RAISE EXCEPTION 'resolve the GIS Run before closing its reconciliation incident'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_gis_reconciliation_incident_resolution
    ON gda_control.data_incident;
CREATE TRIGGER trg_gda_gis_reconciliation_incident_resolution
BEFORE UPDATE ON gda_control.data_incident
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_gis_reconciliation_incident_resolution();

CREATE OR REPLACE FUNCTION gda_control.resolve_gis_reconciliation_incident_on_terminal()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_incident gda_control.data_incident%ROWTYPE;
BEGIN
    IF NEW.to_status NOT IN ('succeeded', 'failed', 'cancelled', 'timed_out')
       OR NEW.actor_subject <> 'workload:gis-analysis-postgis' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_incident
    FROM gda_control.data_incident
    WHERE tenant_id = NEW.tenant_id
      AND run_id = NEW.run_id
      AND incident_type = 'gis_analysis_reconciliation_timeout'
      AND status IN ('open', 'acknowledged')
    ORDER BY opened_at DESC
    LIMIT 1;
    IF FOUND THEN
        PERFORM set_config(
            'gda.gis_reconciliation_terminal_resolution_allowed', '1', true
        );
        PERFORM gda_control.transition_data_incident(
            NEW.tenant_id, v_incident.incident_id, v_incident.state_version,
            'resolved', NEW.actor_subject,
            'trusted GIS provider terminal evidence converged',
            jsonb_build_object(
                'schema', 'gda.gis_analysis_terminal_convergence.v1',
                'run_id', NEW.run_id,
                'run_event_id', NEW.event_id,
                'run_terminal_status', NEW.to_status
            )
        );
        PERFORM set_config(
            'gda.gis_reconciliation_terminal_resolution_allowed', '0', true
        );
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.gis_reconciliation_terminal_resolution_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_gis_reconciliation_terminal_resolution
    ON gda_control.platform_run_event;
CREATE TRIGGER trg_gda_gis_reconciliation_terminal_resolution
AFTER INSERT ON gda_control.platform_run_event
FOR EACH ROW EXECUTE FUNCTION
    gda_control.resolve_gis_reconciliation_incident_on_terminal();

DROP TRIGGER IF EXISTS trg_gda_gis_reconciliation_observation_immutable
    ON gda_control.gis_analysis_reconciliation_observation;
CREATE TRIGGER trg_gda_gis_reconciliation_observation_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_analysis_reconciliation_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.gis_analysis_reconciliation_observation
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_analysis_reconciliation_observation
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gis_analysis_reconciliation_tenant_isolation
    ON gda_control.gis_analysis_reconciliation_observation;
CREATE POLICY gis_analysis_reconciliation_tenant_isolation
    ON gda_control.gis_analysis_reconciliation_observation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_analysis_reconciliation_observation
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.gis_analysis_reconciliation_observation
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.enqueue_gis_analysis_reconciliation()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.settle_gis_analysis_reconciliation(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, INTEGER,
    UUID, TEXT, JSONB, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.resolve_gis_analysis_reconciliation(
    TEXT, UUID, UUID, INTEGER, INTEGER, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_gis_reconciliation_incident_resolution()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.resolve_gis_reconciliation_incident_on_terminal()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.settle_gis_analysis_reconciliation(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, INTEGER,
    UUID, TEXT, JSONB, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.resolve_gis_analysis_reconciliation(
    TEXT, UUID, UUID, INTEGER, INTEGER, TEXT, TEXT
) TO gda_control_gateway;
