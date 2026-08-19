-- 185: Append-only durable authority for Chongqing source-selection releases.
--
-- Stored histories remain unreviewed technical publications. This migration
-- does not provide customer approval, production promotion, or execution
-- authorization.

CREATE TABLE IF NOT EXISTS
    gda_control.chongqing_source_selection_profile_release_history (
    tenant_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    active_release_version INTEGER NOT NULL,
    active_release_sha256 CHAR(64) NOT NULL,
    history_sha256 CHAR(64) NOT NULL,
    history_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, history_sha256),
    CONSTRAINT uq_gda_chongqing_profile_release_version
        UNIQUE (tenant_id, profile_id, scenario_id, active_release_version),
    CONSTRAINT ck_gda_chongqing_profile_release_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_chongqing_profile_release_profile
        CHECK (profile_id ~ '^[a-z0-9][a-z0-9._-]{0,127}$'),
    CONSTRAINT ck_gda_chongqing_profile_release_scenario
        CHECK (scenario_id IN ('heping_review', 'banzhu_adjustment')),
    CONSTRAINT ck_gda_chongqing_profile_release_version
        CHECK (active_release_version BETWEEN 1 AND 1024),
    CONSTRAINT ck_gda_chongqing_profile_release_hashes
        CHECK (
            active_release_sha256 ~ '^[0-9a-f]{64}$'
            AND history_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_gda_chongqing_profile_release_document
        CHECK (
            jsonb_typeof(history_document) = 'object'
            AND history_document ->> 'tenant_id' = tenant_id
            AND history_document ->> 'profile_id' = profile_id
            AND history_document ->> 'scenario_id' = scenario_id
            AND history_document ->> 'active_release_sha256'
                = active_release_sha256
            AND history_document ->> 'history_sha256' = history_sha256
            AND history_document ->> 'history_state'
                = 'technical_history_active_unreviewed'
            AND history_document -> 'customer_approval_present'
                = 'false'::JSONB
            AND history_document -> 'production_execution_authorized'
                = 'false'::JSONB
            AND history_document -> 'authority_write_performed'
                = 'false'::JSONB
            AND jsonb_typeof(history_document -> 'releases') = 'array'
            AND jsonb_array_length(history_document -> 'releases')
                = active_release_version
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'tenant_id' = tenant_id
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'profile_id' = profile_id
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'scenario_id' = scenario_id
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'release_version' = active_release_version::TEXT
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'release_id'
                    = profile_id || '-release-' || active_release_version::TEXT
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'release_sha256' = active_release_sha256
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'source_selection_profile_sha256' ~ '^[0-9a-f]{64}$'
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'source_catalog_sha256' ~ '^[0-9a-f]{64}$'
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'scenario_evidence_sha256' ~ '^[0-9a-f]{64}$'
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'publication_state'
                    = 'technical_candidate_published_unreviewed'
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'review_state' = 'technical_baseline_unreviewed'
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    ->> 'intended_use'
                    = 'assisted_precheck_not_for_production_decision'
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    -> 'customer_approval_present' = 'false'::JSONB
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    -> 'production_execution_authorized' = 'false'::JSONB
            AND (history_document -> 'releases' -> (active_release_version - 1))
                    -> 'authority_write_performed' = 'false'::JSONB
            AND jsonb_typeof(
                    (history_document -> 'releases' -> (active_release_version - 1))
                        -> 'ancestor_release_sha256s'
                ) = 'array'
            AND jsonb_array_length(
                    (history_document -> 'releases' -> (active_release_version - 1))
                        -> 'ancestor_release_sha256s'
                ) = active_release_version - 1
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_chongqing_profile_release_current
    ON gda_control.chongqing_source_selection_profile_release_history
        (tenant_id, profile_id, scenario_id, active_release_version DESC);

CREATE OR REPLACE VIEW
    gda_control.chongqing_source_selection_profile_release_history_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, profile_id, scenario_id)
       tenant_id, profile_id, scenario_id, active_release_version,
       active_release_sha256, history_sha256, history_document, recorded_at
FROM gda_control.chongqing_source_selection_profile_release_history
ORDER BY tenant_id, profile_id, scenario_id, active_release_version DESC;

CREATE OR REPLACE FUNCTION
    gda_control.guard_chongqing_source_selection_profile_release_history_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.chongqing_profile_release_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use record_chongqing_source_selection_profile_release_history()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source-selection profile release tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION
    gda_control.record_chongqing_source_selection_profile_release_history(
        p_tenant_id TEXT,
        p_profile_id TEXT,
        p_scenario_id TEXT,
        p_active_release_version INTEGER,
        p_active_release_sha256 TEXT,
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
    v_existing gda_control.chongqing_source_selection_profile_release_history%ROWTYPE;
    v_current gda_control.chongqing_source_selection_profile_release_history%ROWTYPE;
    v_tail JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source-selection profile release tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;

    IF p_profile_id IS NULL
       OR p_profile_id !~ '^[a-z0-9][a-z0-9._-]{0,127}$'
       OR p_scenario_id NOT IN ('heping_review', 'banzhu_adjustment')
       OR p_active_release_version NOT BETWEEN 1 AND 1024
       OR p_active_release_sha256 IS NULL
       OR p_active_release_sha256 !~ '^[0-9a-f]{64}$'
       OR p_history_sha256 IS NULL
       OR p_history_sha256 !~ '^[0-9a-f]{64}$'
       OR p_history_document IS NULL
       OR jsonb_typeof(p_history_document) <> 'object'
       OR p_history_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_history_document ->> 'profile_id' IS DISTINCT FROM p_profile_id
       OR p_history_document ->> 'scenario_id' IS DISTINCT FROM p_scenario_id
       OR p_history_document ->> 'active_release_sha256'
            IS DISTINCT FROM p_active_release_sha256
       OR p_history_document ->> 'history_sha256'
            IS DISTINCT FROM p_history_sha256
       OR p_history_document ->> 'history_state'
            IS DISTINCT FROM 'technical_history_active_unreviewed'
       OR p_history_document -> 'customer_approval_present'
            IS DISTINCT FROM 'false'::JSONB
       OR p_history_document -> 'production_execution_authorized'
            IS DISTINCT FROM 'false'::JSONB
       OR p_history_document -> 'authority_write_performed'
            IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(p_history_document -> 'releases') <> 'array'
       OR jsonb_array_length(p_history_document -> 'releases')
            IS DISTINCT FROM p_active_release_version THEN
        RAISE EXCEPTION 'source-selection profile release history is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_tail := (p_history_document -> 'releases') -> (p_active_release_version - 1);
    IF jsonb_typeof(v_tail) <> 'object'
       OR v_tail ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR v_tail ->> 'profile_id' IS DISTINCT FROM p_profile_id
       OR v_tail ->> 'scenario_id' IS DISTINCT FROM p_scenario_id
       OR v_tail ->> 'release_version'
            IS DISTINCT FROM p_active_release_version::TEXT
       OR v_tail ->> 'release_id' IS DISTINCT FROM
            p_profile_id || '-release-' || p_active_release_version::TEXT
       OR v_tail ->> 'release_sha256' IS DISTINCT FROM p_active_release_sha256
       OR v_tail ->> 'source_selection_profile_sha256' !~ '^[0-9a-f]{64}$'
       OR v_tail ->> 'source_catalog_sha256' !~ '^[0-9a-f]{64}$'
       OR v_tail ->> 'scenario_evidence_sha256' !~ '^[0-9a-f]{64}$'
       OR v_tail ->> 'publication_state'
            IS DISTINCT FROM 'technical_candidate_published_unreviewed'
       OR v_tail ->> 'review_state'
            IS DISTINCT FROM 'technical_baseline_unreviewed'
       OR v_tail ->> 'intended_use'
            IS DISTINCT FROM 'assisted_precheck_not_for_production_decision'
       OR v_tail -> 'customer_approval_present' IS DISTINCT FROM 'false'::JSONB
       OR v_tail -> 'production_execution_authorized'
            IS DISTINCT FROM 'false'::JSONB
       OR v_tail -> 'authority_write_performed' IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(v_tail -> 'ancestor_release_sha256s') <> 'array'
       OR jsonb_array_length(v_tail -> 'ancestor_release_sha256s')
            IS DISTINCT FROM p_active_release_version - 1 THEN
        RAISE EXCEPTION 'active source-selection profile release is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'chongqing-profile-release|' || p_tenant_id || '|' ||
            p_profile_id || '|' || p_scenario_id,
            0
        )
    );

    SELECT stored.* INTO v_existing
    FROM gda_control.chongqing_source_selection_profile_release_history AS stored
    WHERE stored.tenant_id = p_tenant_id
      AND stored.history_sha256 = p_history_sha256;
    IF FOUND THEN
        IF v_existing.profile_id IS DISTINCT FROM p_profile_id
           OR v_existing.scenario_id IS DISTINCT FROM p_scenario_id
           OR v_existing.active_release_version
                IS DISTINCT FROM p_active_release_version
           OR v_existing.active_release_sha256
                IS DISTINCT FROM p_active_release_sha256
           OR v_existing.history_document IS DISTINCT FROM p_history_document THEN
            RAISE EXCEPTION 'source-selection profile release idempotency differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.history_document, FALSE;
        RETURN;
    END IF;

    SELECT current.* INTO v_current
    FROM gda_control.chongqing_source_selection_profile_release_history AS current
    WHERE current.tenant_id = p_tenant_id
      AND current.profile_id = p_profile_id
      AND current.scenario_id = p_scenario_id
    ORDER BY current.active_release_version DESC
    LIMIT 1;

    IF NOT FOUND THEN
        IF p_active_release_version <> 1
           OR v_tail ->> 'event_kind' IS DISTINCT FROM 'initial_publication'
           OR jsonb_typeof(v_tail -> 'ancestor_release_sha256s') <> 'array'
           OR jsonb_array_length(v_tail -> 'ancestor_release_sha256s') <> 0
           OR jsonb_typeof(v_tail -> 'predecessor_release_sha256')
                IS DISTINCT FROM 'null' THEN
            RAISE EXCEPTION 'initial source-selection profile release is invalid'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        IF p_active_release_version <> v_current.active_release_version + 1 THEN
            RAISE EXCEPTION 'source-selection profile release version is not contiguous'
                USING ERRCODE = '22023';
        END IF;
        IF (p_history_document -> 'releases') - (p_active_release_version - 1)
                IS DISTINCT FROM v_current.history_document -> 'releases' THEN
            RAISE EXCEPTION 'source-selection profile release history rewrites prior releases'
                USING ERRCODE = '22023';
        END IF;
        IF v_tail ->> 'predecessor_release_sha256'
                IS DISTINCT FROM v_current.active_release_sha256 THEN
            RAISE EXCEPTION 'source-selection profile release predecessor is stale'
                USING ERRCODE = '22023';
        END IF;
        IF v_tail ->> 'event_kind' NOT IN ('profile_change', 'rollback')
           OR (v_tail -> 'ancestor_release_sha256s' ->>
                    (p_active_release_version - 2))
                IS DISTINCT FROM v_current.active_release_sha256 THEN
            RAISE EXCEPTION 'source-selection profile release ancestry is invalid'
                USING ERRCODE = '22023';
        END IF;
        IF v_tail ->> 'event_kind' = 'profile_change'
           AND jsonb_typeof(v_tail -> 'rollback_target_release_sha256')
                IS DISTINCT FROM 'null' THEN
            RAISE EXCEPTION 'profile-change release cannot name a rollback target'
                USING ERRCODE = '22023';
        END IF;
        IF v_tail ->> 'event_kind' = 'rollback'
           AND (
                v_tail ->> 'rollback_target_release_sha256' IS NULL
                OR NOT (
                    (v_tail -> 'ancestor_release_sha256s')
                        ? (v_tail ->> 'rollback_target_release_sha256')
                )
           ) THEN
            RAISE EXCEPTION 'rollback target is not an ancestor release'
                USING ERRCODE = '22023';
        END IF;
    END IF;

    PERFORM set_config('gda.chongqing_profile_release_write_allowed', '1', true);
    INSERT INTO gda_control.chongqing_source_selection_profile_release_history (
        tenant_id, profile_id, scenario_id, active_release_version,
        active_release_sha256, history_sha256, history_document
    ) VALUES (
        p_tenant_id, p_profile_id, p_scenario_id, p_active_release_version,
        p_active_release_sha256, p_history_sha256, p_history_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config('gda.chongqing_profile_release_write_allowed', '0', true);

    RETURN QUERY SELECT v_existing.history_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.chongqing_profile_release_write_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_chongqing_profile_release_insert_guard
    ON gda_control.chongqing_source_selection_profile_release_history;
CREATE TRIGGER trg_gda_chongqing_profile_release_insert_guard
BEFORE INSERT ON gda_control.chongqing_source_selection_profile_release_history
FOR EACH ROW
EXECUTE FUNCTION
    gda_control.guard_chongqing_source_selection_profile_release_history_insert();

DROP TRIGGER IF EXISTS trg_gda_chongqing_profile_release_immutable
    ON gda_control.chongqing_source_selection_profile_release_history;
CREATE TRIGGER trg_gda_chongqing_profile_release_immutable
BEFORE UPDATE OR DELETE
ON gda_control.chongqing_source_selection_profile_release_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.chongqing_source_selection_profile_release_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.chongqing_source_selection_profile_release_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.chongqing_source_selection_profile_release_history;
CREATE POLICY tenant_isolation
    ON gda_control.chongqing_source_selection_profile_release_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
    gda_control.chongqing_source_selection_profile_release_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE
    gda_control.chongqing_source_selection_profile_release_history_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.chongqing_source_selection_profile_release_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.chongqing_source_selection_profile_release_history_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
    gda_control.guard_chongqing_source_selection_profile_release_history_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION
    gda_control.record_chongqing_source_selection_profile_release_history(
        TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    gda_control.record_chongqing_source_selection_profile_release_history(
        TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB
    ) TO gda_control_gateway;
