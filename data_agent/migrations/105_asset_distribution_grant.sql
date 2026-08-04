-- 105: Turn legacy asset distribution approvals into bounded download grants.
--
-- This remains an asset-level compatibility contract. It does not replace the
-- future DataProductVersion-bound ConsumerBinding authority.

ALTER TABLE agent_data_requests
    ADD COLUMN IF NOT EXISTS requested_operations JSONB NOT NULL
        DEFAULT '["download"]'::jsonb,
    ADD COLUMN IF NOT EXISTS requested_duration_days INTEGER NOT NULL DEFAULT 30,
    ADD COLUMN IF NOT EXISTS granted_operations JSONB,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;

UPDATE agent_data_requests
SET approved_at = COALESCE(approved_at, created_at, NOW()),
    granted_operations = COALESCE(granted_operations, requested_operations),
    expires_at = COALESCE(
        expires_at,
        COALESCE(approved_at, created_at, NOW())
            + (requested_duration_days::text || ' days')::interval
    )
WHERE status = 'approved';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_dreq_requested_operations'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT ck_dreq_requested_operations CHECK (
                jsonb_typeof(requested_operations) = 'array'
                AND jsonb_array_length(requested_operations) > 0
                AND requested_operations <@ '["download"]'::jsonb
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_dreq_requested_duration'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT ck_dreq_requested_duration CHECK (
                requested_duration_days BETWEEN 1 AND 365
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_dreq_approved_grant'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT ck_dreq_approved_grant CHECK (
                status <> 'approved'
                OR (
                    jsonb_typeof(granted_operations) = 'array'
                    AND jsonb_array_length(granted_operations) > 0
                    AND granted_operations <@ '["download"]'::jsonb
                    AND expires_at IS NOT NULL
                    AND approved_at IS NOT NULL
                    AND expires_at > approved_at
                )
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_dreq_active_download_grant
    ON agent_data_requests(asset_id, requester, expires_at DESC)
    WHERE status = 'approved';
