-- 107: Bound each transitional distribution grant by a package quota.
--
-- Quota is consumed when a package is registered against the grant. Historical
-- or later-invalidated packages continue to count so the audit trail cannot be
-- rewritten by deleting delivery artifacts.

ALTER TABLE agent_data_requests
    ADD COLUMN IF NOT EXISTS requested_package_quota INTEGER NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS granted_package_quota INTEGER;

UPDATE agent_data_requests
SET granted_package_quota = requested_package_quota
WHERE status = 'approved'
  AND granted_package_quota IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_dreq_requested_package_quota'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT ck_dreq_requested_package_quota CHECK (
                requested_package_quota BETWEEN 1 AND 100
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_dreq_granted_package_quota'
          AND conrelid = 'agent_data_requests'::regclass
    ) THEN
        ALTER TABLE agent_data_requests
            ADD CONSTRAINT ck_dreq_granted_package_quota CHECK (
                status <> 'approved'
                OR granted_package_quota BETWEEN 1 AND 100
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_distribution_package_item_quota_usage
    ON agent_distribution_package_items(grant_request_id, package_id)
    WHERE grant_request_id IS NOT NULL;
