-- 123: Generalize DataIncident from Run-only to exactly one governed subject.
--
-- Existing Run incidents retain their original fingerprint material. Resource
-- incidents bind a canonical ResourceURN and cannot manufacture a PlatformRun.

ALTER TABLE gda_control.data_incident
    ADD COLUMN IF NOT EXISTS subject_resource_urn TEXT;

ALTER TABLE gda_control.data_incident
    ALTER COLUMN run_id DROP NOT NULL;

ALTER TABLE gda_control.data_incident
    DROP CONSTRAINT IF EXISTS ck_gda_data_incident_subject;
ALTER TABLE gda_control.data_incident
    ADD CONSTRAINT ck_gda_data_incident_subject CHECK (
        num_nonnulls(run_id, subject_resource_urn) = 1
        AND (
            subject_resource_urn IS NULL
            OR (
                subject_resource_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
                AND split_part(subject_resource_urn, '/', 3) = tenant_id
            )
        )
        AND (trigger_observation_id IS NULL OR run_id IS NOT NULL)
    );

CREATE INDEX IF NOT EXISTS idx_gda_data_incident_subject
    ON gda_control.data_incident(
        tenant_id, subject_resource_urn, status, opened_at DESC
    )
    WHERE subject_resource_urn IS NOT NULL;

CREATE OR REPLACE FUNCTION gda_control.guard_data_incident_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.incident_transition_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.transition_data_incident()'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.incident_id IS DISTINCT FROM OLD.incident_id
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.subject_resource_urn IS DISTINCT FROM OLD.subject_resource_urn
       OR NEW.dedupe_key IS DISTINCT FROM OLD.dedupe_key
       OR NEW.incident_type IS DISTINCT FROM OLD.incident_type
       OR NEW.severity IS DISTINCT FROM OLD.severity
       OR NEW.summary IS DISTINCT FROM OLD.summary
       OR NEW.trigger_observation_id IS DISTINCT FROM OLD.trigger_observation_id
       OR NEW.details IS DISTINCT FROM OLD.details
       OR NEW.incident_sha256 IS DISTINCT FROM OLD.incident_sha256
       OR NEW.detected_by IS DISTINCT FROM OLD.detected_by
       OR NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN
        RAISE EXCEPTION 'immutable data incident binding cannot be changed'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state_version <> OLD.state_version + 1 OR NEW.status = OLD.status THEN
        RAISE EXCEPTION 'data incident transition must advance state_version once'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.guard_data_incident_update() FROM PUBLIC;
