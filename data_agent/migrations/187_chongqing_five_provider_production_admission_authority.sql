-- 187: Explicit append-only production admission for one five-Provider run.
--
-- Technical profile releases, rule bindings, deployments, and plans remain
-- non-authorizing inputs. Only a bounded, human-authorized lifecycle event can
-- admit callbacks, and the gateway has no direct table-write privilege.

CREATE TABLE IF NOT EXISTS
    gda_control.chongqing_five_provider_production_admission_history (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    current_event_version INTEGER NOT NULL,
    current_event_sha256 CHAR(64) NOT NULL,
    history_sha256 CHAR(64) NOT NULL,
    history_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, history_sha256),
    CONSTRAINT uq_gda_chongqing_production_admission_version
        UNIQUE (tenant_id, run_id, current_event_version),
    CONSTRAINT ck_gda_chongqing_production_admission_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_chongqing_production_admission_run
        CHECK (octet_length(btrim(run_id)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_chongqing_production_admission_version
        CHECK (current_event_version BETWEEN 1 AND 1024),
    CONSTRAINT ck_gda_chongqing_production_admission_hashes
        CHECK (
            current_event_sha256 ~ '^[0-9a-f]{64}$'
            AND history_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_gda_chongqing_production_admission_document
        CHECK (
            jsonb_typeof(history_document) = 'object'
            AND history_document ->> 'tenant_id' = tenant_id
            AND history_document ->> 'run_id' = run_id
            AND history_document ->> 'current_event_sha256'
                = current_event_sha256
            AND history_document ->> 'history_sha256' = history_sha256
            AND history_document -> 'technical_baseline_grants_production_authority'
                = 'false'::JSONB
            AND history_document -> 'provider_dispatch_performed' = 'false'::JSONB
            AND jsonb_typeof(history_document -> 'events') = 'array'
            AND jsonb_array_length(history_document -> 'events')
                = current_event_version
            AND (history_document -> 'events' -> (current_event_version - 1))
                    ->> 'event_version' = current_event_version::TEXT
            AND (history_document -> 'events' -> (current_event_version - 1))
                    ->> 'event_sha256' = current_event_sha256
            AND (history_document -> 'events' -> (current_event_version - 1))
                    ->> 'tenant_id' = tenant_id
            AND (history_document -> 'events' -> (current_event_version - 1))
                    ->> 'run_id' = run_id
            AND (history_document -> 'events' -> (current_event_version - 1))
                    ->> 'authorized_by' ~ '^human:[^[:space:]]{1,128}$'
            AND (history_document -> 'events' -> (current_event_version - 1))
                    ->> 'authorization_evidence_sha256' ~ '^[0-9a-f]{64}$'
            AND (history_document -> 'events' -> (current_event_version - 1))
                    ->> 'trust_anchor_sha256' ~ '^[0-9a-f]{64}$'
            AND (history_document -> 'events' -> (current_event_version - 1))
                    -> 'technical_baseline_grants_production_authority'
                    = 'false'::JSONB
            AND (history_document -> 'events' -> (current_event_version - 1))
                    -> 'provider_dispatch_performed' = 'false'::JSONB
            AND jsonb_typeof(
                    (history_document -> 'events' -> (current_event_version - 1))
                        -> 'target'
                ) = 'object'
            AND (history_document -> 'events' -> (current_event_version - 1))
                    -> 'target' ->> 'tenant_id' = tenant_id
            AND (history_document -> 'events' -> (current_event_version - 1))
                    -> 'target' ->> 'run_id' = run_id
            AND (history_document -> 'events' -> (current_event_version - 1))
                    -> 'target' ->> 'target_sha256' ~ '^[0-9a-f]{64}$'
            AND (history_document -> 'events' -> (current_event_version - 1))
                    -> 'target' -> 'technical_baseline_grants_production_authority'
                    = 'false'::JSONB
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_chongqing_production_admission_current
    ON gda_control.chongqing_five_provider_production_admission_history
        (tenant_id, run_id, current_event_version DESC);

CREATE OR REPLACE VIEW
    gda_control.chongqing_five_provider_production_admission_history_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, run_id)
       tenant_id, run_id, current_event_version, current_event_sha256,
       history_sha256, history_document, recorded_at
FROM gda_control.chongqing_five_provider_production_admission_history
ORDER BY tenant_id, run_id, current_event_version DESC;

CREATE OR REPLACE FUNCTION
    gda_control.guard_chongqing_five_provider_production_admission_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.chongqing_production_admission_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use record_chongqing_five_provider_production_admission_history()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'five-Provider production admission tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION
    gda_control.record_chongqing_five_provider_production_admission_history(
        p_tenant_id TEXT,
        p_run_id TEXT,
        p_current_event_version INTEGER,
        p_current_event_sha256 TEXT,
        p_history_sha256 TEXT,
        p_history_document JSONB
    )
RETURNS TABLE(history_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing
        gda_control.chongqing_five_provider_production_admission_history%ROWTYPE;
    v_current
        gda_control.chongqing_five_provider_production_admission_history%ROWTYPE;
    v_tail JSONB;
    v_current_tail JSONB;
    v_rollback_target JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'five-Provider production admission tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;

    IF p_run_id IS NULL
       OR octet_length(btrim(p_run_id)) NOT BETWEEN 1 AND 512
       OR p_current_event_version NOT BETWEEN 1 AND 1024
       OR p_current_event_sha256 IS NULL
       OR p_current_event_sha256 !~ '^[0-9a-f]{64}$'
       OR p_history_sha256 IS NULL
       OR p_history_sha256 !~ '^[0-9a-f]{64}$'
       OR p_history_document IS NULL
       OR jsonb_typeof(p_history_document) <> 'object'
       OR p_history_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_history_document ->> 'run_id' IS DISTINCT FROM btrim(p_run_id)
       OR p_history_document ->> 'current_event_sha256'
            IS DISTINCT FROM p_current_event_sha256
       OR p_history_document ->> 'history_sha256'
            IS DISTINCT FROM p_history_sha256
       OR p_history_document -> 'technical_baseline_grants_production_authority'
            IS DISTINCT FROM 'false'::JSONB
       OR p_history_document -> 'provider_dispatch_performed'
            IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(p_history_document -> 'events') <> 'array'
       OR jsonb_array_length(p_history_document -> 'events')
            IS DISTINCT FROM p_current_event_version THEN
        RAISE EXCEPTION 'five-Provider production admission history is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_tail := (p_history_document -> 'events') -> (p_current_event_version - 1);
    IF jsonb_typeof(v_tail) <> 'object'
       OR v_tail ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR v_tail ->> 'run_id' IS DISTINCT FROM btrim(p_run_id)
       OR v_tail ->> 'event_version'
            IS DISTINCT FROM p_current_event_version::TEXT
       OR v_tail ->> 'event_id' IS DISTINCT FROM
            btrim(p_run_id) || '-production-admission-' ||
            p_current_event_version::TEXT
       OR v_tail ->> 'event_sha256' IS DISTINCT FROM p_current_event_sha256
       OR v_tail ->> 'event_kind' NOT IN ('promotion', 'revocation', 'rollback')
       OR v_tail ->> 'authorized_by' !~ '^human:[^[:space:]]{1,128}$'
       OR v_tail ->> 'authorization_evidence_sha256' !~ '^[0-9a-f]{64}$'
       OR v_tail ->> 'trust_anchor_sha256' !~ '^[0-9a-f]{64}$'
       OR NULLIF(btrim(v_tail ->> 'authorization_reason'), '') IS NULL
       OR (v_tail ->> 'authorized_at')::TIMESTAMPTZ IS NULL
       OR (v_tail ->> 'expires_at')::TIMESTAMPTZ IS NULL
       OR v_tail ->> 'technical_review_state'
            IS DISTINCT FROM 'technical_baseline_unreviewed'
       OR v_tail ->> 'technical_intended_use'
            IS DISTINCT FROM 'assisted_precheck_not_for_production_decision'
       OR v_tail -> 'technical_baseline_grants_production_authority'
            IS DISTINCT FROM 'false'::JSONB
       OR v_tail -> 'provider_dispatch_performed' IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(v_tail -> 'target') <> 'object'
       OR v_tail -> 'target' ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR v_tail -> 'target' ->> 'run_id' IS DISTINCT FROM btrim(p_run_id)
       OR v_tail -> 'target' ->> 'target_sha256' !~ '^[0-9a-f]{64}$'
       OR v_tail -> 'target' ->> 'technical_review_state'
            IS DISTINCT FROM 'technical_baseline_unreviewed'
       OR v_tail -> 'target' ->> 'technical_intended_use'
            IS DISTINCT FROM 'assisted_precheck_not_for_production_decision'
       OR v_tail -> 'target' -> 'technical_baseline_grants_production_authority'
            IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(v_tail -> 'ancestor_event_sha256s') <> 'array'
       OR jsonb_array_length(v_tail -> 'ancestor_event_sha256s')
            IS DISTINCT FROM p_current_event_version - 1
       OR p_history_document ->> 'admission_state'
            IS DISTINCT FROM v_tail ->> 'admission_state'
       OR p_history_document -> 'production_execution_authorized'
            IS DISTINCT FROM v_tail -> 'production_execution_authorized' THEN
        RAISE EXCEPTION 'current five-Provider production admission event is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF v_tail ->> 'event_kind' = 'revocation' THEN
        IF v_tail ->> 'admission_state' IS DISTINCT FROM 'revoked'
           OR v_tail -> 'production_execution_authorized'
                IS DISTINCT FROM 'false'::JSONB
           OR jsonb_typeof(v_tail -> 'rollback_target_event_sha256')
                IS DISTINCT FROM 'null' THEN
            RAISE EXCEPTION 'five-Provider production admission revocation is invalid'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        IF v_tail ->> 'admission_state' IS DISTINCT FROM 'active'
           OR v_tail -> 'production_execution_authorized'
                IS DISTINCT FROM 'true'::JSONB
           OR (v_tail ->> 'expires_at')::TIMESTAMPTZ
                <= (v_tail ->> 'authorized_at')::TIMESTAMPTZ THEN
            RAISE EXCEPTION 'five-Provider production admission grant is invalid'
                USING ERRCODE = '22023';
        END IF;
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'chongqing-production-admission|' || p_tenant_id || '|' || btrim(p_run_id),
            0
        )
    );

    SELECT stored.* INTO v_existing
    FROM gda_control.chongqing_five_provider_production_admission_history AS stored
    WHERE stored.tenant_id = p_tenant_id
      AND stored.history_sha256 = p_history_sha256;
    IF FOUND THEN
        IF v_existing.run_id IS DISTINCT FROM btrim(p_run_id)
           OR v_existing.current_event_version
                IS DISTINCT FROM p_current_event_version
           OR v_existing.current_event_sha256
                IS DISTINCT FROM p_current_event_sha256
           OR v_existing.history_document IS DISTINCT FROM p_history_document THEN
            RAISE EXCEPTION 'five-Provider production admission idempotency differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.history_document, FALSE;
        RETURN;
    END IF;

    SELECT current.* INTO v_current
    FROM gda_control.chongqing_five_provider_production_admission_history AS current
    WHERE current.tenant_id = p_tenant_id
      AND current.run_id = btrim(p_run_id)
    ORDER BY current.current_event_version DESC
    LIMIT 1;

    IF NOT FOUND THEN
        IF p_current_event_version <> 1
           OR v_tail ->> 'event_kind' IS DISTINCT FROM 'promotion'
           OR jsonb_typeof(v_tail -> 'predecessor_event_sha256')
                IS DISTINCT FROM 'null'
           OR jsonb_typeof(v_tail -> 'rollback_target_event_sha256')
                IS DISTINCT FROM 'null'
           OR jsonb_array_length(v_tail -> 'ancestor_event_sha256s') <> 0 THEN
            RAISE EXCEPTION 'initial five-Provider production admission is invalid'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        IF p_current_event_version <> v_current.current_event_version + 1 THEN
            RAISE EXCEPTION
                'five-Provider production admission version is not contiguous'
                USING ERRCODE = '22023';
        END IF;
        IF (p_history_document -> 'events') - (p_current_event_version - 1)
                IS DISTINCT FROM v_current.history_document -> 'events' THEN
            RAISE EXCEPTION
                'five-Provider production admission rewrites prior events'
                USING ERRCODE = '22023';
        END IF;
        IF v_tail ->> 'predecessor_event_sha256'
                IS DISTINCT FROM v_current.current_event_sha256
           OR (v_tail -> 'ancestor_event_sha256s' ->>
                    (p_current_event_version - 2))
                IS DISTINCT FROM v_current.current_event_sha256 THEN
            RAISE EXCEPTION 'five-Provider production admission predecessor is stale'
                USING ERRCODE = '22023';
        END IF;

        v_current_tail := (v_current.history_document -> 'events') ->
            (v_current.current_event_version - 1);
        IF v_current_tail ->> 'admission_state' = 'active' THEN
            IF v_tail ->> 'event_kind' IS DISTINCT FROM 'revocation'
               OR v_tail -> 'target' ->> 'target_sha256'
                    IS DISTINCT FROM v_current_tail -> 'target' ->> 'target_sha256' THEN
                RAISE EXCEPTION 'active production admission must be revoked first'
                    USING ERRCODE = '22023';
            END IF;
        ELSIF v_tail ->> 'event_kind' NOT IN ('promotion', 'rollback') THEN
            RAISE EXCEPTION 'revoked production admission requires a new grant'
                USING ERRCODE = '22023';
        END IF;

        IF v_tail ->> 'event_kind' = 'rollback' THEN
            SELECT ancestor.value INTO v_rollback_target
            FROM jsonb_array_elements(v_current.history_document -> 'events')
                 AS ancestor(value)
            WHERE ancestor.value ->> 'event_sha256'
                    = v_tail ->> 'rollback_target_event_sha256'
              AND ancestor.value ->> 'admission_state' = 'active';
            IF v_rollback_target IS NULL
               OR v_rollback_target -> 'target' ->> 'target_sha256'
                    IS DISTINCT FROM v_tail -> 'target' ->> 'target_sha256' THEN
                RAISE EXCEPTION 'production admission rollback target is invalid'
                    USING ERRCODE = '22023';
            END IF;
        ELSIF jsonb_typeof(v_tail -> 'rollback_target_event_sha256')
                IS DISTINCT FROM 'null' THEN
            RAISE EXCEPTION 'only production rollback may name a rollback target'
                USING ERRCODE = '22023';
        END IF;
    END IF;

    PERFORM set_config(
        'gda.chongqing_production_admission_write_allowed',
        '1',
        true
    );
    INSERT INTO
        gda_control.chongqing_five_provider_production_admission_history (
        tenant_id, run_id, current_event_version, current_event_sha256,
        history_sha256, history_document
    ) VALUES (
        p_tenant_id, btrim(p_run_id), p_current_event_version,
        p_current_event_sha256, p_history_sha256, p_history_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.chongqing_production_admission_write_allowed',
        '0',
        true
    );

    RETURN QUERY SELECT v_existing.history_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.chongqing_production_admission_write_allowed',
        '0',
        true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_chongqing_production_admission_insert_guard
    ON gda_control.chongqing_five_provider_production_admission_history;
CREATE TRIGGER trg_gda_chongqing_production_admission_insert_guard
BEFORE INSERT ON gda_control.chongqing_five_provider_production_admission_history
FOR EACH ROW
EXECUTE FUNCTION
    gda_control.guard_chongqing_five_provider_production_admission_insert();

DROP TRIGGER IF EXISTS trg_gda_chongqing_production_admission_immutable
    ON gda_control.chongqing_five_provider_production_admission_history;
CREATE TRIGGER trg_gda_chongqing_production_admission_immutable
BEFORE UPDATE OR DELETE
ON gda_control.chongqing_five_provider_production_admission_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.chongqing_five_provider_production_admission_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.chongqing_five_provider_production_admission_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.chongqing_five_provider_production_admission_history;
CREATE POLICY tenant_isolation
    ON gda_control.chongqing_five_provider_production_admission_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
    gda_control.chongqing_five_provider_production_admission_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE
    gda_control.chongqing_five_provider_production_admission_history_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.chongqing_five_provider_production_admission_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.chongqing_five_provider_production_admission_history_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
    gda_control.record_chongqing_five_provider_production_admission_history(
        TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    gda_control.record_chongqing_five_provider_production_admission_history(
        TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB
    ) TO gda_control_gateway;
