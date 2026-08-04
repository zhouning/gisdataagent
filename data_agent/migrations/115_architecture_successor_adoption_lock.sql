-- 115: Serialize provider observations with architecture successor adoption.
--
-- The successor transaction locks the same tenant/ResourceVersion key before
-- it checks the latest observation. This trigger makes every observation
-- insert, including a direct gateway-role insert, participate in that lock.

CREATE OR REPLACE FUNCTION gda_control.lock_architecture_resource_version(
    p_tenant_id TEXT,
    p_resource_version_id UUID
)
RETURNS VOID
LANGUAGE sql
VOLATILE
SET search_path TO pg_catalog, gda_control
AS $function$
    SELECT pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            p_tenant_id || ':' || p_resource_version_id::text,
            0
        )
    )
$function$;

CREATE OR REPLACE FUNCTION gda_control.lock_architecture_observation_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO pg_catalog, gda_control
SET row_security TO on
AS $function$
BEGIN
    PERFORM gda_control.lock_architecture_resource_version(
        NEW.tenant_id,
        NEW.resource_version_id
    );
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION gda_control.lock_architecture_successor_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO pg_catalog, gda_control
SET row_security TO on
AS $function$
DECLARE
    v_architecture_successor BOOLEAN;
BEGIN
    IF NEW.predecessor_version_id IS NOT NULL THEN
        PERFORM gda_control.lock_architecture_resource_version(
            NEW.tenant_id,
            NEW.predecessor_version_id
        );
        v_architecture_successor := NEW.authority_version_ref ?& ARRAY[
            'provider_observation_id',
            'schema_evidence_artifact_id',
            'snapshot_ref',
            'content_sha256'
        ]::TEXT[];
        IF EXISTS (
            SELECT 1
            FROM gda_control.resource_version AS existing
            WHERE existing.tenant_id = NEW.tenant_id
              AND existing.resource_urn = NEW.resource_urn
              AND existing.predecessor_version_id = NEW.predecessor_version_id
              AND existing.resource_version_id <> NEW.resource_version_id
              AND (
                  v_architecture_successor
                  OR existing.authority_version_ref ?& ARRAY[
                      'provider_observation_id',
                      'schema_evidence_artifact_id',
                      'snapshot_ref',
                      'content_sha256'
                  ]::TEXT[]
              )
        ) THEN
            RAISE EXCEPTION
                'architecture predecessor % already has a successor',
                NEW.predecessor_version_id
                USING ERRCODE = '23505';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS trg_gda_architecture_observation_adoption_lock
    ON gda_control.architecture_provider_observation;
CREATE TRIGGER trg_gda_architecture_observation_adoption_lock
BEFORE INSERT ON gda_control.architecture_provider_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.lock_architecture_observation_insert();

DROP TRIGGER IF EXISTS trg_gda_architecture_successor_adoption_lock
    ON gda_control.resource_version;
CREATE TRIGGER trg_gda_architecture_successor_adoption_lock
BEFORE INSERT ON gda_control.resource_version
FOR EACH ROW EXECUTE FUNCTION gda_control.lock_architecture_successor_insert();

REVOKE ALL ON FUNCTION gda_control.lock_architecture_resource_version(TEXT, UUID)
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.lock_architecture_observation_insert()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.lock_architecture_successor_insert()
    FROM PUBLIC, gda_control_gateway;
