-- 163: Durable irrigation world-model runs, proposals and audit evidence.
--
-- This domain projection deliberately reuses gda_control.ApprovalCase for the
-- human verdict.  It stores the model input/output as immutable JSON evidence
-- and never exposes a device execution command.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE SEQUENCE IF NOT EXISTS gda_control.irrigation_world_model_run_version_seq;

CREATE TABLE IF NOT EXISTS gda_control.irrigation_world_model_run (
    tenant_id TEXT NOT NULL,
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_external_id TEXT NOT NULL,
    run_resource_urn TEXT NOT NULL,
    proposal_external_id TEXT NOT NULL,
    approval_case_ref TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    run_version BIGINT NOT NULL DEFAULT nextval(
        'gda_control.irrigation_world_model_run_version_seq'
    ),
    parameters JSONB NOT NULL,
    ontology_snapshot JSONB NOT NULL,
    state_snapshot JSONB NOT NULL,
    model_contract JSONB NOT NULL,
    pipeline JSONB NOT NULL,
    results JSONB NOT NULL,
    proposal JSONB NOT NULL,
    claim_boundary JSONB NOT NULL,
    run_fingerprint CHAR(64) NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_review',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_irrigation_run_tenant_external
        UNIQUE (tenant_id, run_external_id),
    CONSTRAINT uq_gda_irrigation_run_tenant_id
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_irrigation_run_tenant_proposal
        UNIQUE (tenant_id, proposal_external_id),
    CONSTRAINT uq_gda_irrigation_run_tenant_resource
        UNIQUE (tenant_id, run_resource_urn),
    CONSTRAINT uq_gda_irrigation_run_tenant_approval
        UNIQUE (tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_irrigation_run_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_irrigation_run_external
        CHECK (run_external_id ~ '^irr-run-[0-9a-f-]{36}$'),
    CONSTRAINT ck_gda_irrigation_run_proposal
        CHECK (proposal_external_id ~ '^irr-proposal-[0-9a-f-]{36}$'),
    CONSTRAINT ck_gda_irrigation_run_resource
        CHECK (
            run_resource_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/irrigation_run/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(run_resource_urn, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_irrigation_run_approval
        CHECK (
            approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(approval_case_ref, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_irrigation_run_owner
        CHECK (owner_subject ~ '^human:[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_irrigation_run_json
        CHECK (
            jsonb_typeof(parameters) = 'object'
            AND jsonb_typeof(ontology_snapshot) = 'object'
            AND jsonb_typeof(state_snapshot) = 'object'
            AND jsonb_typeof(model_contract) = 'object'
            AND jsonb_typeof(pipeline) = 'array'
            AND jsonb_typeof(results) = 'array'
            AND jsonb_typeof(proposal) = 'object'
            AND jsonb_typeof(claim_boundary) = 'object'
        ),
    CONSTRAINT ck_gda_irrigation_run_fingerprint
        CHECK (run_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_irrigation_run_status
        CHECK (status IN ('awaiting_review', 'reviewed')),
    CONSTRAINT ck_gda_irrigation_run_time
        CHECK (updated_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_gda_irrigation_run_owner_time
    ON gda_control.irrigation_world_model_run(
        tenant_id, owner_subject, created_at DESC
    );

CREATE TABLE IF NOT EXISTS gda_control.irrigation_world_model_audit_event (
    tenant_id TEXT NOT NULL,
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    sequence_no INTEGER NOT NULL,
    step TEXT NOT NULL,
    event_status TEXT NOT NULL,
    detail TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_subject TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_irrigation_audit_tenant_event
        UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_irrigation_audit_sequence
        UNIQUE (tenant_id, run_id, sequence_no),
    CONSTRAINT fk_gda_irrigation_audit_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.irrigation_world_model_run(tenant_id, run_id),
    CONSTRAINT ck_gda_irrigation_audit_sequence
        CHECK (sequence_no BETWEEN 0 AND 100),
    CONSTRAINT ck_gda_irrigation_audit_text
        CHECK (
            NULLIF(btrim(step), '') IS NOT NULL
            AND NULLIF(btrim(event_status), '') IS NOT NULL
            AND NULLIF(btrim(detail), '') IS NOT NULL
        ),
    CONSTRAINT ck_gda_irrigation_audit_evidence
        CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT ck_gda_irrigation_audit_actor
        CHECK (actor_subject ~ '^(human|workload|agent):[^[:space:]]{1,128}$')
);

CREATE INDEX IF NOT EXISTS idx_gda_irrigation_audit_run
    ON gda_control.irrigation_world_model_audit_event(
        tenant_id, run_id, sequence_no
    );

ALTER TABLE gda_control.irrigation_world_model_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.irrigation_world_model_run FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.irrigation_world_model_run;
CREATE POLICY tenant_isolation ON gda_control.irrigation_world_model_run
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.irrigation_world_model_audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.irrigation_world_model_audit_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.irrigation_world_model_audit_event;
CREATE POLICY tenant_isolation ON gda_control.irrigation_world_model_audit_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.reject_irrigation_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'irrigation world-model audit events are append-only'
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_irrigation_audit_immutable
    ON gda_control.irrigation_world_model_audit_event;
CREATE TRIGGER trg_gda_irrigation_audit_immutable
BEFORE UPDATE OR DELETE ON gda_control.irrigation_world_model_audit_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_irrigation_audit_mutation();

REVOKE ALL ON TABLE gda_control.irrigation_world_model_run
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.irrigation_world_model_audit_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON
    gda_control.irrigation_world_model_run,
    gda_control.irrigation_world_model_audit_event
    TO gda_control_gateway;
GRANT USAGE, SELECT ON SEQUENCE
    gda_control.irrigation_world_model_run_version_seq
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.reject_irrigation_audit_mutation()
    FROM PUBLIC;
