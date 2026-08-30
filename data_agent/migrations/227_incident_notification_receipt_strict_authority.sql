-- 227: New notification completions must carry an external acceptance receipt.
-- Legacy receipts remain readable for rows migrated by 226, but cannot settle
-- a newly claimed notification.

CREATE OR REPLACE FUNCTION gda_control.complete_data_incident_notification(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_worker_id TEXT,
    p_provider_receipt JSONB
)
RETURNS SETOF gda_control.data_incident_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_destination_ref TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_provider_receipt) IS DISTINCT FROM 'object'
       OR p_provider_receipt->>'schema' IS DISTINCT FROM 'gda.alertmanager_provider_receipt.v1'
       OR p_provider_receipt->>'provider' IS DISTINCT FROM 'alertmanager'
       OR p_provider_receipt->>'accepted' IS DISTINCT FROM 'true'
       OR COALESCE(p_provider_receipt->>'http_status', '') !~ '^[0-9]{3}$'
       OR (p_provider_receipt->>'http_status')::INTEGER NOT BETWEEN 200 AND 299
       OR COALESCE(p_provider_receipt->>'accepted_at', '') = ''
       OR COALESCE(p_provider_receipt->>'destination_ref', '') = '' THEN
        RAISE EXCEPTION 'provider receipt is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT destination_ref INTO v_destination_ref
      FROM gda_control.data_incident_notification_outbox
     WHERE tenant_id = p_tenant_id AND notification_id = p_notification_id;
    IF NOT FOUND OR p_provider_receipt->>'destination_ref' IS DISTINCT FROM v_destination_ref THEN
        RAISE EXCEPTION 'provider receipt destination is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '1', true);
    RETURN QUERY
    WITH target AS (
        SELECT notification.*, clock_timestamp() AS terminal_at
          FROM gda_control.data_incident_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.notification_id = p_notification_id
           AND notification.status = 'in_flight'
           AND notification.claimed_by = p_worker_id
           AND notification.claimed_until > clock_timestamp()
         FOR UPDATE
    )
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = 'done', claimed_by = NULL, claimed_until = NULL,
           last_error = NULL, provider_receipt = p_provider_receipt,
           terminal_worker_id = p_worker_id, completed_at = target.terminal_at,
           receipt_sha256 = gda_control.data_incident_notification_receipt_fingerprint(
               target.tenant_id, target.notification_id, target.incident_id,
               target.incident_event_id, target.incident_sequence_no,
               target.channel, target.destination_ref, 'done',
               target.attempt_count, target.max_attempts, p_provider_receipt,
               NULL, p_worker_id, target.terminal_at
           )
      FROM target
     WHERE notification.tenant_id = target.tenant_id
       AND notification.notification_id = target.notification_id
    RETURNING notification.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'notification claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '0', true);
END;
$$;

REVOKE ALL ON FUNCTION gda_control.complete_data_incident_notification(
    TEXT, UUID, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.complete_data_incident_notification(
    TEXT, UUID, TEXT, JSONB
) TO gda_control_gateway;
