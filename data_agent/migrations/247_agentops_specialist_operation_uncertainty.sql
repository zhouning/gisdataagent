-- 247: Durable reason codes for non-terminal specialist provider observations.
--
-- Migration 246 already keeps the complete receipt document as the immutable
-- source of truth.  This migration exposes the optional reason as a generated
-- column so operators can query permission, transport, and provider-state
-- uncertainty without parsing JSON.  Existing receipts intentionally remain
-- valid with a NULL reason.

ALTER TABLE gda_control.agentops_specialist_operation_receipt_history
    ADD COLUMN IF NOT EXISTS uncertainty_type TEXT GENERATED ALWAYS AS (
        NULLIF(receipt_document ->> 'uncertainty_type', '')
    ) STORED;

ALTER TABLE gda_control.agentops_specialist_operation_receipt_history
    DROP CONSTRAINT IF EXISTS ck_gda_agentops_specialist_operation_uncertainty;
ALTER TABLE gda_control.agentops_specialist_operation_receipt_history
    ADD CONSTRAINT ck_gda_agentops_specialist_operation_uncertainty CHECK (
        uncertainty_type IS NULL
        OR (
            status = 'unknown'
            AND uncertainty_type IN (
                'FlinkCancellationPermissionDenied',
                'FlinkCancellationTransportUnavailable',
                'FlinkJobNotFound',
                'FlinkCancellationRejected',
                'FlinkResponseInvalid',
                'FlinkJobNotCancelled',
                'ProviderCancellationAccepted',
                'ProviderCancellationObservationTimeout',
                'ProviderCancellationUnsupported'
            )
        )
    );

CREATE INDEX IF NOT EXISTS idx_gda_agentops_specialist_operation_uncertainty
    ON gda_control.agentops_specialist_operation_receipt_history (
        tenant_id, uncertainty_type, recorded_at DESC
    )
    WHERE uncertainty_type IS NOT NULL;

CREATE OR REPLACE VIEW gda_control.agentops_specialist_operation_receipt_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, operation_ref)
       tenant_id, operation_ref, receipt_sequence, receipt_sha256,
       workflow_id, run_id, step_id, tool_call_id, activity_id, attempt_no,
       request_sha256, provider_ref, provider_receipt_ref, status,
       output_artifact_id, failure_type, cancellation_requested,
       receipt_document, recorded_by, recorded_at, uncertainty_type
FROM gda_control.agentops_specialist_operation_receipt_history
ORDER BY tenant_id, operation_ref, receipt_sequence DESC;

REVOKE ALL ON gda_control.agentops_specialist_operation_receipt_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.agentops_specialist_operation_receipt_current
    TO gda_control_gateway;
